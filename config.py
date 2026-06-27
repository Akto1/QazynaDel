import os

from dotenv import load_dotenv

load_dotenv()

# На первом месте ИМЯ переменной, на втором — твой токен как подстраховка
BOT_TOKEN = os.getenv("BOT_TOKEN", "8740191163:AAFhfQ0ooixwGDdwO1pY_vHPPIUhNyNXUok")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен."
    )

ADMIN_ID = int(os.getenv("ADMIN_ID", 2061576320))

SUPPORT_GROUP_ID = int(os.getenv("SUPPORT_GROUP_ID", -5208123471))

# === Telegram Mini App (static/marketplace) ===
# URL должен быть HTTPS. На Amvera даётся автоматически.
# Примеры:
#   WEBAPP_URL=https://your-app.amvera.io
#   WEBAPP_URL=https://shop.example.com
# Если не задан — кнопка «Открыть магазин» не показывается,
# весь бот работает через inline-кнопки (как раньше).
WEBAPP_URL = os.getenv("WEBAPP_URL", " https://saddlebag-patchwork-astronomy.ngrok-free.dev ").rstrip("/")

# === API-сервер (aiohttp внутри процесса бота) ===
# Порт, на котором поднимается HTTP API + статика Mini App.
# По умолчанию 8080 — стандарт для Amvera и большинства PaaS.
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))

# === Бизнес-логика ===
MINIMUM_ORDER_AMOUNT = 5000
DELIVERY_FEE = 200
WORKING_HOURS_START = 0
WORKING_HOURS_END = 24

# === Часовой пояс для определения «мы открыты?» ===
# Бот хостится на Amvera в UTC, но работает по локальному времени города.
# Меняй в .env: TIMEZONE=Asia/Almaty (по умолчанию Алматы)
try:
    from zoneinfo import ZoneInfo

    TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Almaty"))
except Exception:
    TIMEZONE = None  # fallback на серверное время, если zoneinfo недоступен

# === Реквизиты Kaspi для приёма оплаты ===
# Эти данные бот показывает пользователю при оформлении заказа с оплатой Kaspi.
# ОБЯЗАТЕЛЬНО заполни в .env, иначе бот возьмёт дефолт и будут неверные реквизиты.
KASPI_PHONE = os.getenv("KASPI_PHONE", "+7 700 000 00 00")
KASPI_HOLDER = os.getenv("KASPI_HOLDER", "Иван Иванов")

DELIVERY_TIME_SLOTS = [
    "08:00–10:00",
    "10:00–12:00",
    "12:00–14:00",
    "14:00–16:00",
    "16:00–18:00",
    "18:00–20:00",
    "20:00–22:00",
]

# === Корпуса и пэтерлер (для выбора адреса без свободного ввода) ===
# Уникальный id, отображаемое имя, диапазон пэтеров.
# При добавлении нового корпуса в БД ничего менять не нужно — хватит этого списка.
BUILDINGS = [
    {"id": 1, "name": "Негізгі корпус", "min_apt": 1, "max_apt": 49},
    {"id": 2, "name": "корпус 1", "min_apt": 1, "max_apt": 28},
    {"id": 3, "name": "корпус 2", "min_apt": 1, "max_apt": 28},
    {"id": 4, "name": "корпус 3", "min_apt": 1, "max_apt": 28},
    {"id": 5, "name": "корпус 4", "min_apt": 1, "max_apt": 24},
    {"id": 6, "name": "корпус 5", "min_apt": 1, "max_apt": 24},
    {"id": 7, "name": "корпус 6", "min_apt": 1, "max_apt": 24},
    {"id": 8, "name": "корпус 7", "min_apt": 1, "max_apt": 24},
    {"id": 9, "name": "корпус 8", "min_apt": 1, "max_apt": 24},
    {"id": 10, "name": "корпус 9", "min_apt": 1, "max_apt": 28},
    {"id": 11, "name": "корпус 10", "min_apt": 1, "max_apt": 28},
    {"id": 12, "name": "корпус 11", "min_apt": 1, "max_apt": 28},
    {"id": 13, "name": "корпус 12", "min_apt": 1, "max_apt": 49},
]
BUILDING_COMPLEX = "«ҚАЙРАТ» ықшам ауданы, 135/4"


def find_building(building_id: int) -> dict | None:
    for b in BUILDINGS:
        if b["id"] == building_id:
            return b
    return None


def format_building_address(building_id: int, apt: int) -> str:
    """Автоматически собирает строку адреса из выбора клиента.
    Используется и в подтверждении, и при сохранении в заказ."""
    b = find_building(building_id)
    if not b:
        return ""
    return f"{BUILDING_COMPLEX}, {b['name']}, кв. {apt}"


PAYMENT_METHODS = {
    "kaspi": "💳 Перевод по Kaspi",
    "cash": "💵 Наличные курьеру",
}

# === Статусы заказов ===
# awaiting_payment — создан, ждём перевод от клиента (только для Kaspi)
# paid            — деньги поступили (подтверждено админом), ждём сборки
# processing      — собирается
# sent            — отправлен курьером
# delivered       — доставлен (с фото)
# cancelled       — отменён
ORDER_STATUSES = {
    "awaiting_payment": "💳 Ожидает оплаты",
    "paid": "💰 Оплачен",
    "processing": "📦 Собирается",
    "sent": "🚚 Отправлен",
    "delivered": "✅ Доставлен",
    "cancelled": "❌ Отменён",
}

DATABASE_PATH = "qazyna_delivery.db"
