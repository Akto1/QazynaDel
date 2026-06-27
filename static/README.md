# QazynaDelivery — бот + Telegram Mini App

Доставка продуктов. Два интерфейса в одном процессе:

- **Telegram-бот** — админка, поддержка, уведомления о статусе, фото доставки
- **Mini App** — каталог, корзина, оформление, история заказов (как Kaspi)

## Структура

```
project/
├── config.py        # конфиг (BOT_TOKEN, WEBAPP_URL, API_PORT, ...)
├── database.py      # SQLite + миграции (v1…v9)
├── locales.py       # переводы ru/kk/en
├── keyboards.py     # inline-кнопки бота
├── states.py        # FSM-состояния
├── bot.py           # aiogram-бот
├── auth.py          # валидация Telegram initData (HMAC)
├── api.py           # aiohttp REST API + статика Mini App
├── webapp/
│   ├── index.html
│   ├── styles.css
│   └── app.js       # SPA-логика (vanilla JS)
├── main.py          # точка входа: бот + API вместе
└── bot.py           # можно запускать отдельно (только бот)
```

## Запуск локально (разработка)

```bash
# 1. Зависимости
pip install aiogram==3.4.1 aiosqlite python-dotenv

# 2. .env
cat > .env <<EOF
BOT_TOKEN=1234567890:AAFakeTokenForTesting1234567890
ADMIN_ID=123
SUPPORT_GROUP_ID=-100
WEBAPP_URL=https://your-app.amvera.io
API_HOST=0.0.0.0
API_PORT=8080
TIMEZONE=Asia/Almaty
EOF

# 3. Бот + API вместе
python main.py

# Или только бот (без Mini App):
python bot.py
```

## Запуск на Amvera (продакшн)

### Шаг 1: Залить код
```bash
git init && git add . && git commit -m "init"
git remote add amvera <url из amvera>
git push amvera main
```

### Шаг 2: Переменные окружения в Amvera
В настройках приложения добавить:
```
BOT_TOKEN       = <от @BotFather>
ADMIN_ID        = <твой Telegram ID>
SUPPORT_GROUP_ID= -100xxxxxxxxxx
WEBAPP_URL      = https://<твой-app>.amvera.io
API_HOST        = 0.0.0.0
API_PORT        = 8080
TIMEZONE        = Asia/Almaty
```

### Шаг 3: Команда запуска
В настройках Amvera указать команду:
```
python main.py
```

Amvera автоматически:
- Поднимет процесс на порту 8080
- Даст HTTPS-домен (`<app>.amvera.io`)
- Запустит healthcheck

## Настройка Mini App в @BotFather

После того как Amvera дал домен:

1. Открыть `@BotFather`
2. `/mybots` → выбрать бота → `Bot Settings` → `Menu Button`
3. Ввести URL: `https://<твой-app>.amvera.io`
4. Готово — в боте появится кнопка слева от поля ввода, открывающая Mini App

Опционально:
- `Web App` → установить иконку и описание в `@BotFather`

## Как работает Mini App

1. Пользователь нажимает в боте кнопку «🛍 Открыть магазин» (WebAppInfo)
2. Telegram открывает `<WEBAPP_URL>` в WebView
3. JS (`app.js`) читает `window.Telegram.WebApp.initData` — подпись, подтверждающая юзера
4. Все API-запросы идут с заголовком `Authorization: tma <initData>`
5. Сервер (`api.py`) проверяет HMAC-SHA256 подписи через `bot_token` → доверяет `user_id`
6. Каталог, корзина, оформление — как обычный сайт, но стилизовано под Telegram-тему

### Что есть в Mini App
- 🏠 Главная — категории чипами + рекомендации
- 📦 Категория — сетка товаров с фото и ценами
- 🛍 Карточка товара — большое фото, описание, степпер количества
- 🛒 Корзина — с +/- , итогом, доставкой
- ✅ Оформление — корпус → квартира (те же кнопки что в боте), телефон, время, оплата, комментарий
- 📋 Заказы — список с статусными бэйджами
- 📄 Детали заказа — повторить, оставить отзыв (1-5 звёзд + комментарий)
- 👤 Профиль — данные, поддержка

### Что осталось в боте
- Админка (заказы, товары, категории, курьеры, рассылки)
- Поддержка (треды с клиентом)
- Уведомления о смене статуса
- Фото доставки
- Выбор языка
- Приём/отправка оплаты Kaspi

## Переменные окружения

| Переменная | Обязательна | Описание |
|---|---|---|
| `BOT_TOKEN` | да | Токен от @BotFather |
| `ADMIN_ID` | да | Telegram ID главного админа |
| `SUPPORT_GROUP_ID` | нет | ID группы поддержки (int, отрицательный для супергрупп) |
| `WEBAPP_URL` | для Mini App | Полный HTTPS URL до Mini App |
| `API_HOST` | нет | Хост aiohttp (по умолчанию `0.0.0.0`) |
| `API_PORT` | нет | Порт aiohttp (по умолчанию `8080`) |
| `TIMEZONE` | нет | IANA timezone (по умолчанию `Asia/Almaty`) |
| `KASPI_PHONE` | нет | Телефон Kaspi для оплаты |
| `KASPI_HOLDER` | нет | Имя держателя Kaspi |

## Особенности

- **Soft-delete везде**: товары, категории, курьеры — `is_active=0`. Заказы сохраняются навсегда.
- **Картинки через Telegram CDN**: `file_id` → `https://api.telegram.org/file/bot...`. Кэш в памяти процесса.
- **Одна БД на двоих**: бот и API читают/пишут в один SQLite файл. SQLite корректно сериализует записи.
- **Graceful shutdown**: SIGTERM останавливает оба сервиса чисто.
- **Бот работает и без Mini App**: если `WEBAPP_URL` пуст, главное меню показывает старые inline-кнопки.

## Что в планах

- [ ] Kaspi Pay (онлайн-оплата) — нужен merchant ID
- [ ] Поиск по товарам
- [ ] Фильтры (по цене, наличию)
- [ ] Избранное
- [ ] Push-уведомления о скидках через WebApp push API
- [ ] Трекинг курьера на карте