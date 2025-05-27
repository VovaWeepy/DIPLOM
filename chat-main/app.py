from flask import Flask, render_template, request, jsonify
import requests
import xml.etree.ElementTree as ET
import logging
import uuid
import base64
import re

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

# GigaChat API настройки
GIGACHAT_CLIENT_ID = "1045c01b-12ae-4f79-b425-a6d713d5a157"
GIGACHAT_CLIENT_SECRET = "744f0a56-912d-4ab5-bef3-b1ebdff79ad4"
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# Хранение истории сообщений для текущей сессии
message_history = []

# Загрузка данных о товарах из XML
def load_products():
    try:
        tree = ET.parse('products.xml')
        root = tree.getroot()
        products = []
        for product in root.findall('product'):
            products.append({
                'id': product.find('id').text,
                'name': product.find('name').text,
                'category': product.find('category').text,
                'price': float(product.find('price').text),
                'description': product.find('description').text
            })
        logging.info(f"Успешно загружено {len(products)} товаров")
        return products
    except ET.ParseError as e:
        logging.error(f"Ошибка парсинга XML в products.xml: {e}")
        return []
    except FileNotFoundError:
        logging.warning("Файл products.xml не найден, возвращается пустой список товаров")
        return []
    except Exception as e:
        logging.error(f"Неизвестная ошибка при загрузке товаров: {e}")
        return []

# Фильтрация товаров по категории
def filter_products_by_category(products, category):
    return [p for p in products if p['category'] == category]

# Определение категории из сообщения пользователя
def detect_category_from_message(message):
    categories = ["Смартфоны", "Ноутбуки", "Телевизоры", "Наушники", "Планшеты"]
    message_lower = message.lower()
    for category in categories:
        if category.lower() in message_lower or any(keyword in message_lower for keyword in ["телефон", "смартфон"]) and category == "Смартфоны":
            return category
    return None

# Получение токена GigaChat
def get_gigachat_token():
    auth_string = f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}"
    logging.debug(f"Исходная строка для кодирования: {auth_string}")
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')
    logging.debug(f"Сформирован Base64 для Authorization: {auth_base64}")

    headers = {
        'Authorization': f'Basic {auth_base64}',
        'Content-Type': 'application/x-www-form-urlencoded',
        'RqUID': str(uuid.uuid4()),
        'Accept': 'application/json'
    }
    logging.debug(f"Заголовки запроса: {headers}")

    data = 'scope=GIGACHAT_API_PERS'
    try:
        response = requests.post(GIGACHAT_AUTH_URL, headers=headers, data=data, verify=False)
        response.raise_for_status()
        token = response.json()['access_token']
        logging.debug(f"Получен токен GigaChat: {token[:10]}...")
        return token
    except requests.exceptions.HTTPError as e:
        logging.error(f"Ошибка HTTP при получении токена GigaChat: {e}")
        logging.error(f"Ответ сервера: {response.text}")
        return None
    except Exception as e:
        logging.error(f"Ошибка получения токена GigaChat: {e}")
        return None

@app.route('/')
def index():
    products = load_products()
    return render_template('index.html', products=products)

@app.route('/category/<category>')
def category(category):
    products = load_products()
    category_products = filter_products_by_category(products, category)
    return render_template('category.html', products=category_products, category=category)

@app.route('/chat', methods=['POST'])
def chat():
    global message_history
    try:
        user_message = request.form.get('message')
        logging.debug(f"Получено сообщение: '{user_message}'")
        if not user_message or not user_message.strip():
            logging.warning("Пустое или некорректное сообщение от пользователя")
            return jsonify({"error": "Сообщение не может быть пустым"}), 400

        # Загрузка всех товаров
        products = load_products()

        # Определение категории из сообщения пользователя или истории
        detected_category = detect_category_from_message(user_message)
        if not detected_category and message_history:
            for msg in reversed(message_history):
                detected_category = detect_category_from_message(msg['content'])
                if detected_category:
                    break

        # Фильтрация товаров по категории, если категория определена
        if detected_category:
            relevant_products = filter_products_by_category(products, detected_category)
            logging.debug(f"Определена категория: {detected_category}, найдено {len(relevant_products)} товаров")
        else:
            relevant_products = products
            logging.debug("Категория не определена, используются все товары")

        # Формирование контекста товаров
        product_context = "\n".join([
            f"ID: {p['id']}, Name: {p['name']}, Category: {p['category']}, Price: {p['price']} руб., Description: {p['description']}"
            for p in relevant_products
        ])

        # Системный промпт с улучшенной инструкцией
        system_prompt = {
            "role": "system",
            "content": f"Вы — помощник интернет-магазина. Ваша задача — консультировать пользователей по выбору товаров, основываясь на данных из каталога:\n{product_context}\nОтвечайте в разговорном стиле, четко и дружелюбно. Учитывайте предыдущий контекст диалога и категорию товаров, о которой спрашивает пользователь. Не перечисляйте товары списком, а предлагайте их естественно, в рамках диалога. Если пользователь уточняет товар, используйте предыдущие сообщения для логичного ответа. Если категория не указана, уточните у пользователя, о чем идет речь. Если пользователь попросил показать ему товар до какой-то определенной суммы то проанализируй каталог и предложи товары из выбранной категории не больше написанной суммы. Если пользователь попросил показать ему товар за какую-то определенную сумму денег то проанализируй каталог и предложи товары в выбранной категории именно за данную сумму."
        }

        # Добавление нового сообщения пользователя в историю
        message_history.append({"role": "user", "content": user_message.strip()})

        # Подготовка полного списка сообщений для API
        messages = [system_prompt] + message_history

        token = get_gigachat_token()
        if not token:
            logging.error("Не удалось получить токен GigaChat")
            return jsonify({"error": "Не удалось аутентифицироваться в GigaChat"}), 500

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.7
        }
        logging.debug(f"Отправка запроса к GigaChat: {payload}")
        response = requests.post(GIGACHAT_API_URL, headers=headers, json=payload, verify=False, timeout=30)
        response.raise_for_status()
        response_content = response.json()['choices'][0]['message']['content']
        logging.debug(f"Ответ от GigaChat: {response_content}")

        # Добавление ответа ассистента в историю
        message_history.append({"role": "assistant", "content": response_content})

        # Форматирование ответа
        formatted_response = format_response(response_content)
        return jsonify({"response": formatted_response})

    except Exception as e:
        logging.error(f"Ошибка в чате: {e}")
        return jsonify({"error": str(e)}), 500

def format_response(text):
    """
    Преобразует текст в читаемый вид, заменяя Markdown-синтаксис и убирая лишние списки.
    """
    if not text:
        return "Пустой ответ от GigaChat"

    # Удаление Markdown-форматирования
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Удаление жирного текста
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # Удаление курсива
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)  # Удаление списков

    # Замена множественных переносов строк на одиночные
    text = re.sub(r'\n\s*\n', '\n', text)

    # Удаление лишних пробелов
    text = text.strip()

    return text

if __name__ == '__main__':
    app.run(debug=True)