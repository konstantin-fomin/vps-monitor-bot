# 🖥️ VPS Monitor Bot

> Лёгкий Telegram-бот для мониторинга личного VPS и VPN-сервера на базе AmneziaWG — все метрики и статусы в одном месте прямо в Telegram.


---

## ✨ Возможности

- 🩺 **Сводка здоровья сервера** — быстрый обзор состояния VPS одной командой
- 📊 **Системные метрики** — CPU, RAM, диск и сетевой трафик в реальном времени
- 🐳 **Docker-контейнеры** — статус всех запущенных контейнеров
- 🔐 **VPN-устройства** — список клиентов AmneziaWG с читаемыми именами
- 🟢 **Онлайн/офлайн** — определение активности клиента по времени последнего handshake
- ⌨️ **Inline-кнопки** — удобная навигация без запоминания команд
- 🔒 **Защита по chat ID** — бот отвечает только авторизованному пользователю

---

## 📱 Команды

| Команда | Описание |
|---|---|
| `/start` | Главное меню с inline-кнопками |
| `/health` | Краткая сводка состояния VPS |
| `/status` | Подробные метрики сервера |
| `/vpn` | Список VPN-устройств и их статус |
| `/containers` | Статус Docker-контейнеров |
| `/rawvpn` | Raw-вывод диагностики VPN |

---

## 🛠️ Стек

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** — async Telegram Bot API
- **[psutil](https://github.com/giampaolo/psutil)** — системные метрики (CPU, RAM, диск, сеть)
- **[Docker SDK for Python](https://docker-py.readthedocs.io/)** — мониторинг контейнеров
- **Docker Compose** — контейнеризация и деплой

---

## 🚀 Деплой

### Требования
- Docker и Docker Compose на VPS
- Токен бота от [@BotFather](https://t.me/BotFather)
- Ваш Telegram chat ID

### Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/konstantin-fomin/vps-monitor-bot.git
cd vps-monitor-bot

# 2. Создать .env файл
cp .env.example .env
nano .env

# 3. Запустить
docker compose up -d --build

# 4. Проверить логи
docker logs --tail=50 vps-monitor-bot
```

### Обновление

```bash
git pull
docker compose up -d --build
```

---

## ⚙️ Переменные окружения

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен бота от @BotFather |
| `ALLOWED_CHAT_ID` | Telegram chat ID авторизованного пользователя |
| `DEVICE_NAMES` | Маппинг VPN IP → читаемое имя устройства *(опционально)* |
| `CLIENT_ALIASES` | Маппинг имени Amnezia-клиента → читаемое имя *(опционально)* |
| `ONLINE_SECONDS_THRESHOLD` | Порог определения онлайн-статуса в секундах |

---

## 📁 Структура проекта

```
vps-monitor-bot/
├── bot.py              # Основная логика бота и handlers
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 🔒 Безопасность

- Никогда не коммить `.env` — токен и chat ID должны быть только на сервере
- `ALLOWED_CHAT_ID` обязателен: бот не стартует без явно заданного chat ID
- Docker socket даёт широкие возможности инспекции контейнеров и требует аккуратного деплоя

---

## 🔐 Security notes

- `ALLOWED_CHAT_ID` is required for safety and must be set before starting the bot.
- Docker socket access is powerful and should be used carefully.
- `.env` must not be committed; keep real tokens and chat IDs only on the server.
- Screenshots should not include tokens, public IPs, endpoints, chat IDs, or raw VPN output.

---

*Сделано для личного использования на собственном VPS.*
