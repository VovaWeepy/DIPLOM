document.addEventListener('DOMContentLoaded', function () {
    const chatIcon = document.getElementById('chatIcon');
    const chatWindow = document.getElementById('chatWindow');
    const closeChat = document.getElementById('closeChat');
    const chatForm = document.getElementById('chatForm');
    const chatMessages = document.getElementById('chatMessages');
    const messageInput = document.getElementById('message');

    // Загрузка сохраненных сообщений из localStorage
    function loadChatHistory() {
        const savedMessages = localStorage.getItem('chatHistory');
        if (savedMessages) {
            chatMessages.innerHTML = savedMessages;
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    // Сохранение сообщений в localStorage
    function saveChatHistory() {
        const messages = chatMessages.innerHTML;
        localStorage.setItem('chatHistory', messages);
    }

    // Открытие/закрытие чата
    chatIcon.addEventListener('click', function () {
        chatWindow.style.display = chatWindow.style.display === 'none' ? 'flex' : 'none';
        if (chatWindow.style.display === 'flex') {
            loadChatHistory();
        }
    });

    closeChat.addEventListener('click', function () {
        chatWindow.style.display = 'none';
        saveChatHistory();
    });

    // Отправка сообщений
    chatForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (!message) return;

        // Отображение сообщения пользователя
        const userMessage = document.createElement('div');
        userMessage.className = 'user-message';
        userMessage.textContent = 'Вы: ' + message;
        chatMessages.appendChild(userMessage);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Очистка поля ввода
        messageInput.value = '';

        // Отправка запроса к серверу
        fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: 'message=' + encodeURIComponent(message)
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                const errorMessage = document.createElement('div');
                errorMessage.className = 'assistant-message';
                errorMessage.textContent = 'Ошибка: ' + data.error;
                errorMessage.style.color = 'red';
                chatMessages.appendChild(errorMessage);
            } else {
                const botMessage = document.createElement('div');
                botMessage.className = 'assistant-message';
                botMessage.textContent = 'Ассистент: ' + data.response;
                chatMessages.appendChild(botMessage);
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
            saveChatHistory();
        })
        .catch(error => {
            const errorMessage = document.createElement('div');
            errorMessage.className = 'assistant-message';
            errorMessage.textContent = 'Ошибка связи с сервером';
            errorMessage.style.color = 'red';
            chatMessages.appendChild(errorMessage);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            saveChatHistory();
        });
    });

    // Инициализация: загрузка истории при открытии страницы
    loadChatHistory();
});