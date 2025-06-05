from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import xml.etree.ElementTree as ET
import requests
import subprocess
import os
from DB import get_db_connection, create_users_table
import logging
import json
import base64
import uuid
from urllib.parse import urlparse
from datetime import datetime

app = Flask(__name__)
CORS(app, supports_credentials=True)  # Включаем поддержку CORS с credentials
app.secret_key = '744f0a56-912d-4ab5-bef3-b1ebdff79ad4'  # Замените на реальный секретный ключ

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

# Настройка сессии для работы в iframe
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

# Хранение настроек пользователей
user_settings = {}

# Хранение истории сообщений для каждого пользователя
chat_histories = {}

# GigaChat API настройки
GIGACHAT_CLIENT_ID = "1045c01b-12ae-4f79-b425-a6d713d5a157"
GIGACHAT_CLIENT_SECRET = "744f0a56-912d-4ab5-bef3-b1ebdff79ad4"
GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

# Добавим глобальную переменную для хранения данных о товарах
products_data = {}


def get_gigachat_token():
    auth_string = f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {
        'Authorization': f'Basic {auth_base64}',
        'Content-Type': 'application/x-www-form-urlencoded',
        'RqUID': str(uuid.uuid4()),
        'Accept': 'application/json'
    }

    data = 'scope=GIGACHAT_API_PERS'
    try:
        response = requests.post(GIGACHAT_AUTH_URL, headers=headers, data=data, verify=False)
        response.raise_for_status()
        token = response.json()['access_token']
        return token
    except Exception as e:
        logging.error(f"Ошибка получения токена GigaChat: {e}")
        return None


def create_chat_history_table():
    """Создание таблицы для хранения истории чата"""
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) NOT NULL,
                    message TEXT NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        except Exception as e:
            logging.error(f"Ошибка создания таблицы chat_history: {e}")
        finally:
            cur.close()
            conn.close()


def save_message_to_db(username, message, role):
    """Сохранение сообщения в базу данных"""
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chat_history (username, message, role) VALUES (%s, %s, %s)",
                (username, message, role)
            )
            conn.commit()
        except Exception as e:
            logging.error(f"Ошибка сохранения сообщения: {e}")
        finally:
            cur.close()
            conn.close()


def load_chat_history(username):
    """Загрузка истории чата из базы данных"""
    conn = get_db_connection()
    messages = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT message, role FROM chat_history WHERE username = %s ORDER BY timestamp ASC",
                (username,)
            )
            messages = [{"role": role, "content": message} for message, role in cur.fetchall()]
        except Exception as e:
            logging.error(f"Ошибка загрузки истории чата: {e}")
        finally:
            cur.close()
            conn.close()
    return messages


def init_db():
    create_users_table()
    create_chat_history_table()


@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Хеширование пароля
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                # Проверка существования пользователя
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                if cur.fetchone() is not None:
                    flash('Пользователь с таким именем уже существует')
                    return redirect(url_for('register'))

                # Добавление нового пользователя
                cur.execute(
                    "INSERT INTO users (username, password) VALUES (%s, %s)",
                    (username, hashed_password)
                )
                conn.commit()
                flash('Регистрация успешна!')
                return redirect(url_for('login'))
            except Exception as e:
                flash(f'Ошибка при регистрации: {str(e)}')
            finally:
                cur.close()
                conn.close()
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cur.fetchone()

                if user and check_password_hash(user[2], password):  # user[2] - это поле password
                    session['username'] = username
                    flash('Вход выполнен успешно!')
                    return redirect(url_for('dashboard'))
                else:
                    flash('Неверное имя пользователя или пароль')
            finally:
                cur.close()
                conn.close()
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=session['username'],
                         prompt_description="Введите дополнительные инструкции для чат-бота (например, особенности общения с клиентами, специальные предложения или акции)")


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


def load_products_from_xml(xml_url):
    """Загрузка товаров из XML файла"""
    try:
        logging.info(f'Начало загрузки XML из: {xml_url}')
        
        if not xml_url:
            logging.error('XML URL не указан')
            return []
            
        if xml_url.startswith(('http://', 'https://')):
            # Загрузка по URL
            logging.info('Загрузка XML по URL')
            response = requests.get(xml_url)
            response.raise_for_status()  # Проверка на ошибки HTTP
            root = ET.fromstring(response.content)
        else:
            # Загрузка локального файла
            logging.info('Загрузка локального XML файла')
            if not os.path.exists(xml_url):
                logging.error(f'Файл не найден: {xml_url}')
                return []
            tree = ET.parse(xml_url)
            root = tree.getroot()
        
        products = []
        for product in root.findall('product'):
            try:
                product_data = {
                    'id': product.find('id').text,
                    'name': product.find('name').text,
                    'category': product.find('category').text,
                    'price': product.find('price').text,
                    'description': product.find('description').text
                }
                products.append(product_data)
            except AttributeError as e:
                logging.error(f'Ошибка при парсинге товара: {str(e)}')
                continue
        
        logging.info(f'Успешно загружено товаров: {len(products)}')
        return products
        
    except requests.exceptions.RequestException as e:
        logging.error(f'Ошибка при загрузке XML по URL: {str(e)}')
        return []
    except ET.ParseError as e:
        logging.error(f'Ошибка парсинга XML: {str(e)}')
        return []
    except Exception as e:
        logging.error(f'Непредвиденная ошибка при загрузке товаров: {str(e)}')
        return []


def format_products_for_prompt(products):
    """Форматирование данных о товарах для промпта"""
    if not products:
        return ""
    
    products_text = """ВАЖНО: Отвечая на вопросы о товарах, используйте ТОЛЬКО информацию из следующего списка доступных товаров. 
НЕ РЕКОМЕНДУЙТЕ товары, которых нет в списке. Если в списке только один товар определенной категории, не нужно придумывать другие.

Доступные товары:
"""
    for product in products:
        products_text += f"- {product['name']}\n"
        products_text += f"  Категория: {product['category']}\n"
        products_text += f"  Цена: {product['price']} руб.\n"
        products_text += f"  Описание: {product['description']}\n\n"
    
    products_text += "\nПожалуйста, используйте ТОЛЬКО эту информацию при ответе на вопросы о товарах. Не добавляйте и не рекомендуйте товары, которых нет в этом списке."
    return products_text


@app.route('/save_settings', methods=['POST'])
def save_settings():
    if 'username' not in session:
        return jsonify({'error': 'Не авторизован'}), 401

    website_url = request.form.get('website_url')
    chat_prompt = request.form.get('chat_prompt')
    xml_url = request.form.get('xml_url')

    # Загружаем товары из XML и проверяем результат
    products = load_products_from_xml(xml_url)
    if not products:
        return jsonify({'error': 'Не удалось загрузить товары из XML файла'}), 400

    logging.info(f"Сохранение настроек для пользователя {session['username']}")
    logging.info(f"Загружено товаров: {len(products)}")
    
    # Сохраняем настройки и данные о товарах
    user_settings[session['username']] = {
        'website_url': website_url,
        'chat_prompt': chat_prompt,
        'xml_url': xml_url,
        'products': products
    }

    # Генерация скрипта для встраивания
    embed_script = generate_embed_script(website_url)

    return jsonify({
        'success': True,
        'embed_script': embed_script,
        'products_count': len(products)
    })


def generate_embed_script(website_url):
    # Генерация уникального скрипта для встраивания
    script = f"""
    <style>
        #chat-widget-container {{
            position: fixed;
            bottom: 20px;
            left: 20px;
            z-index: 9999;
        }}
        
        #chat-widget-button {{
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: #007bff;
            cursor: pointer;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.3s ease;
        }}
        
        #chat-widget-button:hover {{
            transform: scale(1.1);
        }}
        
        #chat-widget-button svg {{
            width: 30px;
            height: 30px;
            fill: white;
        }}
        
        #chat-container {{
            display: none;
            position: fixed;
            bottom: 90px;
            left: 20px;
            width: 350px;
            height: 500px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 9999;
            overflow: hidden;
            transition: all 0.3s ease;
        }}
        
        #chat-container.visible {{
            display: block;
            animation: slideUp 0.3s ease;
        }}
        
        @keyframes slideUp {{
            from {{
                opacity: 0;
                transform: translateY(20px);
            }}
            to {{
                opacity: 1;
                transform: translateY(0);
            }}
        }}
        
        .unread-badge {{
            position: absolute;
            top: 0;
            right: 0;
            background: #dc3545;
            color: white;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            font-size: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            display: none;
        }}
    </style>
    
    <div id="chat-widget-container">
        <div id="chat-widget-button" onclick="toggleChat()">
            <div class="unread-badge">0</div>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
                <path d="M7 9h10v2H7zm0-3h10v2H7zm0 6h7v2H7z"/>
            </svg>
        </div>
        <div id="chat-container">
            <iframe id="chat-frame" 
                    src="{request.host_url}chat-frame?session_token={session.get('username', '')}"
                    style="width: 100%; height: 100%; border: none;">
            </iframe>
        </div>
    </div>
    
    <script>
        (function() {{
            let isOpen = false;
            let unreadCount = 0;
            const chatContainer = document.getElementById('chat-container');
            const unreadBadge = document.querySelector('.unread-badge');
            
            window.toggleChat = function() {{
                isOpen = !isOpen;
                chatContainer.classList.toggle('visible', isOpen);
                if (isOpen) {{
                    // Сброс счетчика непрочитанных сообщений при открытии
                    unreadCount = 0;
                    unreadBadge.style.display = 'none';
                }}
            }};
            
            // Функция для обновления счетчика непрочитанных сообщений
            window.updateUnreadCount = function() {{
                if (!isOpen) {{
                    unreadCount++;
                    unreadBadge.textContent = unreadCount;
                    unreadBadge.style.display = 'flex';
                }}
            }};
            
            // Слушаем сообщения от iframe
            window.addEventListener('message', function(event) {{
                if (event.data.type === 'newMessage') {{
                    updateUnreadCount();
                }}
            }});
            
            // Закрытие чата при клике вне его области
            document.addEventListener('click', function(event) {{
                const chatWidget = document.getElementById('chat-widget-container');
                if (isOpen && !chatWidget.contains(event.target)) {{
                    toggleChat();
                }}
            }});
        }})();
    </script>
    """
    return script


@app.route('/chat-frame')
def chat_frame():
    # Получаем токен сессии из параметров URL
    session_token = request.args.get('session_token', '')
    
    # Если токен есть и сессия не установлена, устанавливаем её
    if session_token and 'username' not in session:
        session['username'] = session_token
        
    return render_template('chat_frame.html')


@app.route('/check_auth')
def check_auth():
    """Проверка авторизации для чата"""
    if 'username' not in session:
        return jsonify({
            'authenticated': False,
            'redirect_url': url_for('login', _external=True)
        }), 401
    
    return jsonify({
        'authenticated': True,
        'username': session['username']
    })


@app.route('/process_chat', methods=['POST'])
def process_chat():
    try:
        message = request.form.get('message')
        if not message:
            return jsonify({'error': 'Сообщение не может быть пустым'}), 400

        # Получаем токен
        token = get_gigachat_token()
        if not token:
            return jsonify({'error': 'Не удалось получить токен GigaChat'}), 500

        # Получаем сохраненный промпт пользователя и данные о товарах
        username = session.get('username')
        user_settings_data = user_settings.get(username, {})
        
        # Проверяем наличие данных о товарах
        products = user_settings_data.get('products', [])
        if not products:
            logging.warning(f"Нет данных о товарах для пользователя {username}")
            return jsonify({'error': 'Пожалуйста, загрузите данные о товарах в настройках'}), 400

        logging.info(f"Обработка сообщения для пользователя {username}")
        logging.info(f"Количество доступных товаров: {len(products)}")
        
        # Базовый системный промпт с усиленными ограничениями
        base_system_prompt = """Вы - помощник магазина электроники. Ваша задача - помогать клиентам с выбором товаров и отвечать на их вопросы.

ВАЖНЫЕ ПРАВИЛА (СТРОГО ОБЯЗАТЕЛЬНЫ К ИСПОЛНЕНИЮ):
1. Отвечайте ТОЛЬКО на основе предоставленной информации о товарах
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО рекомендовать или упоминать товары, которых нет в списке
3. При вопросе о категории товаров перечисляйте ТОЛЬКО те товары, что есть в списке
4. Если запрашиваемого товара нет в наличии, честно сообщите об этом
5. Указывайте ТОЛЬКО те характеристики, которые есть в описании товара
6. СТРОГО ЗАПРЕЩЕНО придумывать или добавлять характеристики товаров, которых нет в описании
7. При ответе на вопрос "какие есть товары" или подобные, перечисляйте ТОЛЬКО те товары, что есть в списке
8. НИКОГДА не сравнивайте товары с несуществующими моделями
9. Если пользователь спрашивает о товаре, которого нет в списке, сообщите, что такого товара нет в наличии
10. При вопросах о категориях товаров упоминайте ТОЛЬКО существующие товары из предоставленного списка"""

        # Получаем пользовательские настройки промпта (дополнительные инструкции)
        user_prompt = user_settings_data.get('chat_prompt', '')
        if user_prompt:
            user_prompt = f"\nДополнительные инструкции:\n{user_prompt}"
        
        # Формируем полный промпт
        system_prompt = f"""{base_system_prompt}{user_prompt}

{format_products_for_prompt(products)}"""

        logging.info("Отправка запроса к GigaChat")
        logging.debug(f"Системный промпт: {system_prompt}")
        
        # Загружаем историю сообщений из базы данных
        messages = load_chat_history(username)
        if not messages:
            messages = []

        # Добавляем системный промпт и новое сообщение
        messages = [{"role": "system", "content": system_prompt}] + messages
        messages.append({"role": "user", "content": message})

        # Настройки для GigaChat с уменьшенной температурой для более точных ответов
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.1  # Низкая температура для более точных ответов
        }

        response = requests.post(
            GIGACHAT_API_URL,
            headers=headers,
            json=payload,
            verify=False
        )

        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('choices') and len(response_data['choices']) > 0:
                assistant_response = response_data['choices'][0]['message']['content']
                
                # Сохраняем сообщения в базу данных
                save_message_to_db(username, message, "user")
                save_message_to_db(username, assistant_response, "assistant")
                
                logging.info("Успешный ответ от GigaChat")
                return jsonify({'response': assistant_response})
            else:
                logging.error("Пустой ответ от GigaChat")
                return jsonify({'error': 'Пустой ответ от GigaChat'}), 500
        else:
            logging.error(f"Ошибка GigaChat: {response.status_code}")
            return jsonify({'error': f'Ошибка GigaChat: {response.status_code}'}), response.status_code

    except Exception as e:
        logging.error(f"Ошибка в process_chat: {str(e)}")
        return jsonify({'error': 'Произошла ошибка при обработке сообщения'}), 500


@app.route('/load_xml', methods=['POST'])
def load_xml():
    if 'username' not in session:
        return jsonify({'error': 'Не авторизован'}), 401

    xml_url = request.form.get('xml_url')
    try:
        response = requests.get(xml_url)
        tree = ET.fromstring(response.content)
        # Обработка XML файла
        # Здесь можно добавить логику обработки XML
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_settings')
def get_settings():
    try:
        # Проверяем авторизацию
        if 'username' not in session:
            logging.warning('Попытка получить настройки без авторизации')
            return jsonify({'error': 'Не авторизован', 'details': 'Требуется авторизация'}), 401
        
        username = session['username']
        logging.info(f'Получение настроек для пользователя: {username}')
        
        # Получаем данные пользователя
        user_data = user_settings.get(username)
        if user_data is None:
            logging.warning(f'Настройки не найдены для пользователя: {username}')
            return jsonify({
                'success': True,
                'settings': {
                    'website_url': '',
                    'chat_prompt': '',
                    'xml_url': '',
                    'embed_script': '',
                    'has_products': False,
                    'products_count': 0
                }
            })
        
        logging.info(f'Текущие настройки пользователя {username}: {user_data}')
        
        # Проверяем и загружаем товары
        products = user_data.get('products', [])
        if not products:
            xml_url = user_data.get('xml_url')
            if xml_url:
                logging.info(f'Попытка загрузить товары из XML для {username}: {xml_url}')
                try:
                    products = load_products_from_xml(xml_url)
                    if products:
                        logging.info(f'Успешно загружено {len(products)} товаров из XML')
                        user_data['products'] = products
                        user_settings[username] = user_data
                    else:
                        logging.warning('XML файл загружен, но товары не найдены')
                except Exception as xml_error:
                    logging.error(f'Ошибка при загрузке XML: {str(xml_error)}')
        
        # Формируем ответ
        settings = {
            'website_url': user_data.get('website_url', ''),
            'chat_prompt': user_data.get('chat_prompt', ''),
            'xml_url': user_data.get('xml_url', ''),
            'embed_script': generate_embed_script(user_data.get('website_url', '')) if user_data.get('website_url') else '',
            'has_products': bool(products),
            'products_count': len(products)
        }
        
        logging.info(f'Отправка настроек клиенту. Количество товаров: {len(products)}')
        return jsonify({
            'success': True,
            'settings': settings
        })
        
    except Exception as e:
        logging.error(f'Критическая ошибка при получении настроек: {str(e)}')
        return jsonify({
            'error': 'Произошла ошибка при получении настроек',
            'details': str(e)
        }), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5001)
