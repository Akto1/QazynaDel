import re

from contextlib import asynccontextmanager

from typing import Optional


import aiosqlite

from config import DATABASE_PATH


# ==================== Валидация ====================


PHONE_RE = re.compile(r"^\+?[\d\s\-\(\)]{10,20}$")

PRICE_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?$")



def validate_phone(p: str) -> bool:

    return bool(PHONE_RE.match(p.strip()))



def validate_price(s: str) -> Optional[float]:

    s = s.strip().replace(" ", "").replace(",", ".")

    if not PRICE_RE.match(s):

        return None

    try:

        v = float(s)

        return v if v > 0 else None

    except ValueError:

        return None



def validate_address(a: str) -> bool:

    return len(a.strip()) >= 5



# ==================== БД-хелпер ====================



@asynccontextmanager

async def _db():

    db = await aiosqlite.connect(DATABASE_PATH)

    db.row_factory = aiosqlite.Row

    await db.execute("PRAGMA journal_mode=WAL")

    await db.execute("PRAGMA foreign_keys=ON")

    try:

        yield db

    finally:

        await db.close()



async def init_db() -> None:

    """Инициализация: миграции + сидовые данные."""

    async with _db() as db:

        await db.execute(

            """

            CREATE TABLE IF NOT EXISTS schema_version (

                id INTEGER PRIMARY KEY CHECK (id = 1),

                version INTEGER NOT NULL DEFAULT 0

            )

        """

        )

        await db.commit()


        cur = await db.execute("SELECT version FROM schema_version WHERE id = 1")

        row = await cur.fetchone()

        current = row[0] if row else 0


        migrations = [

            _migration_v1,

            _migration_v2,

            _migration_v3,

            _migration_v4,

            _migration_v5,

            _migration_v6,  # reviews (отзывы после доставки)

            _migration_v7,  # support_threads (треды поддержки: direction, parent_id)

            _migration_v8,  # mailings (история рассылок)

            _migration_v9,  # categories.is_active (мягкое удаление категорий)

            _migration_v10, # products.is_stopped (стоп-лист: временно недоступен)

        ]

        for i, mig in enumerate(migrations, start=1):

            if current < i:

                await mig(db)

                await db.execute(

                    "INSERT OR REPLACE INTO schema_version (id, version) VALUES (1, ?)",

                    (i,),

                )

                await db.commit()


        await _seed_demo_data(db)



# ==================== Миграции ====================



async def _migration_v1(db: aiosqlite.Connection) -> None:

    """Базовая схема."""

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_id INTEGER UNIQUE NOT NULL,

            first_name TEXT,

            last_name TEXT,

            phone TEXT,

            address TEXT,

            language TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        CREATE TABLE IF NOT EXISTS categories (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            emoji TEXT DEFAULT '📦',

            sort_order INTEGER DEFAULT 0

        );

        CREATE TABLE IF NOT EXISTS products (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            category_id INTEGER NOT NULL,

            name TEXT NOT NULL,

            price REAL NOT NULL,

            photo_file_id TEXT,

            is_active BOOLEAN DEFAULT 1,

            description TEXT,

            stock INTEGER DEFAULT 999,

            FOREIGN KEY (category_id) REFERENCES categories(id)

        );

        CREATE TABLE IF NOT EXISTS cart_items (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            product_id INTEGER NOT NULL,

            quantity INTEGER NOT NULL DEFAULT 1,

            FOREIGN KEY (user_id) REFERENCES users(id),

            FOREIGN KEY (product_id) REFERENCES products(id)

        );

        CREATE TABLE IF NOT EXISTS orders (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            total_amount REAL NOT NULL,

            status TEXT DEFAULT 'new',

            delivery_time TEXT,

            payment_method TEXT,

            comment TEXT,

            address TEXT,

            phone TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id) REFERENCES users(id)

        );

        CREATE TABLE IF NOT EXISTS order_items (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            order_id INTEGER NOT NULL,

            product_id INTEGER NOT NULL,

            quantity INTEGER NOT NULL,

            price_at_moment REAL NOT NULL,

            FOREIGN KEY (order_id) REFERENCES orders(id),

            FOREIGN KEY (product_id) REFERENCES products(id)

        );

        CREATE TABLE IF NOT EXISTS addresses (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            label TEXT DEFAULT 'Основной',

            address TEXT NOT NULL,

            is_default BOOLEAN DEFAULT 0

        );

        CREATE TABLE IF NOT EXISTS support_messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            user_telegram_id INTEGER NOT NULL,

            user_message_id INTEGER,

            support_chat_id INTEGER,

            support_message_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id);

        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);

        CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id);

        """

    )



async def _migration_v2(db: aiosqlite.Connection) -> None:

    """Дополнительные таблицы."""

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS addresses (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            label TEXT DEFAULT 'Основной',

            address TEXT NOT NULL,

            is_default BOOLEAN DEFAULT 0

        );

        """

    )



async def _migration_v3(db: aiosqlite.Connection) -> None:

    """Рефералка. Сейчас НЕ используется, оставлена для обратной совместимости."""

    if not await _column_exists(db, "users", "referral_code"):

        await db.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")

    if not await _column_exists(db, "users", "referred_by"):

        await db.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")

    if not await _column_exists(db, "users", "referral_balance"):

        await db.execute("ALTER TABLE users ADD COLUMN referral_balance REAL DEFAULT 0")

    if not await _column_exists(db, "users", "referral_count"):

        await db.execute(

            "ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0"

        )

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS support_messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            user_telegram_id INTEGER NOT NULL,

            user_message_id INTEGER,

            support_chat_id INTEGER,

            support_message_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        """

    )



async def _migration_v4(db: aiosqlite.Connection) -> None:

    """Новые поля для оплаты и фото доставки."""

    if not await _column_exists(db, "orders", "payment_confirmed_at"):

        await db.execute("ALTER TABLE orders ADD COLUMN payment_confirmed_at TIMESTAMP")

    if not await _column_exists(db, "orders", "delivery_photo_file_id"):

        await db.execute("ALTER TABLE orders ADD COLUMN delivery_photo_file_id TEXT")

    if not await _column_exists(db, "orders", "delivery_proof_text"):

        await db.execute("ALTER TABLE orders ADD COLUMN delivery_proof_text TEXT")



async def _migration_v5(db: aiosqlite.Connection) -> None:

    """Курьеры + привязка курьера к заказу."""

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS couriers (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_id INTEGER UNIQUE NOT NULL,

            name TEXT NOT NULL,

            phone TEXT,

            is_active BOOLEAN DEFAULT 1,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        );

        CREATE INDEX IF NOT EXISTS idx_couriers_active ON couriers(is_active);

        """

    )

    if not await _column_exists(db, "orders", "courier_id"):

        await db.execute("ALTER TABLE orders ADD COLUMN courier_id INTEGER")

    if not await _column_exists(db, "orders", "courier_assigned_at"):

        await db.execute("ALTER TABLE orders ADD COLUMN courier_assigned_at TIMESTAMP")



async def _migration_v6(db: aiosqlite.Connection) -> None:

    """Отзывы после доставки.


    Связь 1-к-1 с заказом: один заказ - один отзыв.

    rating от 1 до 5, comment необязательный."""

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS reviews (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            order_id INTEGER UNIQUE NOT NULL,

            user_id INTEGER NOT NULL,

            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),

            comment TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (order_id) REFERENCES orders(id),

            FOREIGN KEY (user_id) REFERENCES users(id)

        );

        CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);

        CREATE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id);

        """

    )



async def _migration_v7(db: aiosqlite.Connection) -> None:

    """Треды поддержки: direction ('to_support' / 'to_user') + parent_id.


    Раньше support_messages хранила только user→support. Теперь в той же таблице

    храним и обратные сообщения support→user, чтобы пользователь мог ответить

    и переписка продолжалась в группе поддержки как тред."""

    if not await _column_exists(db, "support_messages", "direction"):

        await db.execute(

            "ALTER TABLE support_messages "

            "ADD COLUMN direction TEXT DEFAULT 'to_support'"

        )

    if not await _column_exists(db, "support_messages", "parent_id"):

        await db.execute("ALTER TABLE support_messages ADD COLUMN parent_id INTEGER")

    if not await _column_exists(db, "support_messages", "thread_id"):

        await db.execute("ALTER TABLE support_messages ADD COLUMN thread_id INTEGER")

    # Заполним thread_id для существующих записей (= id, чтобы каждая старая запись

    # стала своим собственным тредом - пользователю будет предложено начать новый,

    # если он захочет ответить; обратная совместимость не ломается).

    await db.execute(

        "UPDATE support_messages SET thread_id = id WHERE thread_id IS NULL"

    )

    await db.executescript(

        """

        CREATE INDEX IF NOT EXISTS idx_support_thread ON support_messages(thread_id);

        CREATE INDEX IF NOT EXISTS idx_support_direction ON support_messages(direction);

        """

    )



async def _migration_v8(db: aiosqlite.Connection) -> None:

    """История рассылок: что было разослано, когда, скольким пользователям.


    product_id опциональный - для рассылок-акций с привязкой к конкретному товару.

    text и photo_file_id опциональны, но хотя бы одно из двух должно быть."""

    await db.executescript(

        """

        CREATE TABLE IF NOT EXISTS mailings (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            text TEXT,

            photo_file_id TEXT,

            product_id INTEGER,

            recipients_count INTEGER DEFAULT 0,

            sent_count INTEGER DEFAULT 0,

            failed_count INTEGER DEFAULT 0,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id) REFERENCES products(id)

        );

        CREATE INDEX IF NOT EXISTS idx_mailings_created ON mailings(created_at);

        """

    )



async def _migration_v9(db: aiosqlite.Connection) -> None:

    """Мягкое удаление категорий: добавляем is_active.


    Та же логика, что у товаров и курьеров - категория прячется из каталога,

    но исторические заказы остаются целыми. Удалить можно только пустую

    категорию (без активных товаров), иначе - ошибка, чтобы не терять данные."""

    if not await _column_exists(db, "categories", "is_active"):

        await db.execute(

            "ALTER TABLE categories ADD COLUMN is_active BOOLEAN DEFAULT 1"

        )

    # Существующие категории - все активные (DEFAULT 1 уже сработал на ALTER)



async def _migration_v10(db: aiosqlite.Connection) -> None:

    """Стоп-лист товаров: is_stopped.


    Отдельный флаг от is_active:

    - is_active=0 - товар удалён (soft delete), в админке через «Удалить товар»

    - is_stopped=1 - товар временно недоступен (нет в наличии, не привозят).

      В админке через раздел «Чек-лист», можно вернуть в продажу.


    Оба флага независимы. Товар показывается в каталоге только если ОБА = 0."""

    if not await _column_exists(db, "products", "is_stopped"):

        await db.execute(

            "ALTER TABLE products ADD COLUMN is_stopped BOOLEAN DEFAULT 0"

        )



async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:

    cur = await db.execute(f"PRAGMA table_info({table})")

    rows = await cur.fetchall()

    return any(row[1] == column for row in rows)



async def _seed_demo_data(db: aiosqlite.Connection) -> None:

    """Раньше сюда заливались демо-категории и товары. Сейчас пусто:

    база стартует с нуля, товары добавляет админ через бота."""

    # === Миграции только ДОБАВЛЯЮТ (ALTER TABLE / CREATE TABLE IF NOT EXISTS),

    # ничего не удаляют и не переименовывают. Это значит:

    #   1) Можно спокойно копировать qazyna_delivery.db между ноутом и сервером -

    #      структура гарантированно совпадёт.

    #   2) Если на ноуте уже есть набитые категории/товары, они перенесутся as is.

    return



# ==================== Пользователи ====================



async def get_or_create_user(

    telegram_id: int, first_name: str | None = None, last_name: str | None = None

) -> dict:

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)

        )

        user = await cur.fetchone()

        if user:

            return dict(user)

        cur = await db.execute(

            "INSERT INTO users (telegram_id, first_name, last_name) VALUES (?, ?, ?)",

            (telegram_id, first_name, last_name),

        )

        await db.commit()

        cur = await db.execute(

            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)

        )

        return dict(await cur.fetchone())



async def update_user_profile(

    user_id: int, phone: str | None = None, address: str | None = None

) -> None:

    async with _db() as db:

        if phone:

            await db.execute(

                "UPDATE users SET phone = ? WHERE id = ?", (phone, user_id)

            )

        if address:

            await db.execute(

                "UPDATE users SET address = ? WHERE id = ?", (address, user_id)

            )

        await db.commit()



async def get_user_by_telegram_id(telegram_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_user_language(telegram_id: int) -> str:

    async with _db() as db:

        cur = await db.execute(

            "SELECT language FROM users WHERE telegram_id = ?", (telegram_id,)

        )

        r = await cur.fetchone()

        return r[0] if r and r[0] else "ru"



async def update_user_language(telegram_id: int, language: str) -> None:

    async with _db() as db:

        await db.execute(

            "UPDATE users SET language = ? WHERE telegram_id = ?",

            (language, telegram_id),

        )

        await db.commit()



# ==================== Категории и товары ====================



async def get_categories(active_only: bool = True) -> list[dict]:

    async with _db() as db:

        if active_only:

            cur = await db.execute(

                "SELECT * FROM categories WHERE is_active = 1 ORDER BY sort_order, id"

            )

        else:

            cur = await db.execute(

                "SELECT * FROM categories ORDER BY is_active DESC, sort_order, id"

            )


        result = [dict(r) for r in await cur.fetchall()]

        print(f"DEBUG: Результат из базы: {result}")  # ДОБАВЬ ЭТО

        return result



async def get_category(category_id: int) -> dict | None:

    """Получить категорию по id (без фильтра по is_active - чтобы админ видел и удалённые)."""

    async with _db() as db:

        cur = await db.execute("SELECT * FROM categories WHERE id = ?", (category_id,))

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_products_by_category(category_id: int, include_stopped: bool = False) -> list[dict]:

    """Товары категории.


    По умолчанию НЕ включаем стоп-лист — это для inline-каталога в боте.

    Для Mini App передаём include_stopped=True, чтобы показать карточку

    с пометкой «Стоп-лист» (вместо полного исчезновения)."""

    async with _db() as db:

        if include_stopped:

            cur = await db.execute(

                "SELECT * FROM products WHERE category_id = ? AND is_active = 1 ORDER BY is_stopped, name",

                (category_id,),

            )

        else:

            cur = await db.execute(

                "SELECT * FROM products WHERE category_id = ? AND is_active = 1 AND is_stopped = 0 ORDER BY name",

                (category_id,),

            )

        return [dict(r) for r in await cur.fetchall()]



async def category_has_active_products(category_id: int) -> int:

    """Сколько активных товаров в категории. Используется при удалении -

    если > 0, не даём удалить, чтобы не терять данные."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT COUNT(*) FROM products WHERE category_id = ? AND is_active = 1",

            (category_id,),

        )

        row = await cur.fetchone()

        return int(row[0]) if row else 0



async def delete_category(category_id: int) -> bool:

    """Мягкое удаление категории (is_active=0). Возвращает True если удалили.


    ВАЖНО: вызывающий код ДОЛЖЕН предварительно проверить

    category_has_active_products() - иначе мы рискуем спрятать категорию

    с активными товарами, и каталог пользователя сломается.

    Сделано намеренно без каскада - чтобы не терять данные."""

    async with _db() as db:

        cur = await db.execute("SELECT is_active FROM categories WHERE id = ?", (category_id,))

        row = await cur.fetchone()

        if not row:

            return False

        await db.execute(

            "UPDATE categories SET is_active = 0 WHERE id = ?", (category_id,)

        )

        await db.commit()

        return True



async def get_product(product_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))

        row = await cur.fetchone()

        return dict(row) if row else None



async def add_product(

    category_id: int,

    name: str,

    price: float,

    description: str | None = None,

    photo_file_id: str | None = None,

) -> int:

    async with _db() as db:

        cur = await db.execute(

            "INSERT INTO products (category_id, name, price, description, photo_file_id, is_active) "

            "VALUES (?, ?, ?, ?, ?, 1)",

            (category_id, name, price, description, photo_file_id),

        )

        await db.commit()

        return cur.lastrowid



async def update_product(

    product_id: int,

    name: str | None = None,

    price: float | None = None,

    description: str | None = None,

    photo_file_id: str | None = None,

) -> None:

    async with _db() as db:

        fields, vals = [], []

        if name is not None:

            fields.append("name = ?")

            vals.append(name)

        if price is not None:

            fields.append("price = ?")

            vals.append(price)

        if description is not None:

            fields.append("description = ?")

            vals.append(description)

        if photo_file_id is not None:

            fields.append("photo_file_id = ?")

            vals.append(photo_file_id)

        if fields:

            vals.append(product_id)

            await db.execute(

                f"UPDATE products SET {', '.join(fields)} WHERE id = ?", vals

            )

            await db.commit()



async def delete_product(product_id: int) -> None:

    async with _db() as db:

        await db.execute(

            "UPDATE products SET is_active = 0 WHERE id = ?", (product_id,)

        )

        await db.commit()



async def set_product_stopped(product_id: int, stopped: bool) -> bool:

    """Поставить товар в стоп-лист или снять с него. Возвращает True если изменили.


    В отличие от delete_product (is_active=0), здесь товар НЕ удаляется —

    просто скрывается из каталога пока не вернётся в наличии. Исторические

    заказы остаются с этим товаром без изменений."""

    async with _db() as db:

        cur = await db.execute(

            "UPDATE products SET is_stopped = ? WHERE id = ? AND is_active = 1",

            (1 if stopped else 0, product_id),

        )

        await db.commit()

        return cur.rowcount > 0



async def get_products_by_category_with_stopped(category_id: int) -> list[dict]:

    """Для админки: возвращает ВСЕ товары категории (включая стоп-лист и удалённые),

    чтобы админ видел стоп-лист и мог им управлять."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT *, CASE WHEN is_stopped=1 THEN 'stopped'

                            WHEN is_active=0 THEN 'deleted'

                            ELSE 'active' END AS status_label

               FROM products WHERE category_id = ? ORDER BY is_stopped, is_active, name""",

            (category_id,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_all_stopped_products() -> list[dict]:

    """Все товары в стоп-листе, со всех категорий."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT p.*, c.name AS category_name, c.emoji AS category_emoji

               FROM products p LEFT JOIN categories c ON p.category_id = c.id

               WHERE p.is_stopped = 1 AND p.is_active = 1

               ORDER BY c.name, p.name"""

        )

        return [dict(r) for r in await cur.fetchall()]



async def add_category(name: str, emoji: str = "📦", sort_order: int = 0) -> int:

    async with _db() as db:

        cur = await db.execute(

            "INSERT INTO categories (name, emoji, sort_order) VALUES (?, ?, ?)",

            (name, emoji, sort_order),

        )

        await db.commit()

        return cur.lastrowid



# ==================== Корзина ====================



async def get_cart_items(user_id: int) -> list[dict]:

    async with _db() as db:

        cur = await db.execute(

            """SELECT c.id, c.product_id, c.quantity, p.name, p.price, p.photo_file_id

               FROM cart_items c JOIN products p ON c.product_id = p.id

               WHERE c.user_id = ?""",

            (user_id,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_cart_total(user_id: int) -> float:

    async with _db() as db:

        cur = await db.execute(

            """SELECT COALESCE(SUM(c.quantity * p.price), 0) FROM cart_items c

               JOIN products p ON c.product_id = p.id WHERE c.user_id = ?""",

            (user_id,),

        )

        r = await cur.fetchone()

        return r[0] or 0.0



async def add_to_cart(user_id: int, product_id: int, quantity: int = 1) -> bool:

    async with _db() as db:

        cur = await db.execute(

            "SELECT id, quantity FROM cart_items WHERE user_id = ? AND product_id = ?",

            (user_id, product_id),

        )

        existing = await cur.fetchone()

        if existing:

            await db.execute(

                "UPDATE cart_items SET quantity = ? WHERE id = ?",

                (existing[1] + quantity, existing[0]),

            )

        else:

            await db.execute(

                "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?)",

                (user_id, product_id, quantity),

            )

        await db.commit()

        return True



async def update_cart_quantity(cart_item_id: int, quantity: int) -> None:

    async with _db() as db:

        if quantity <= 0:

            await db.execute("DELETE FROM cart_items WHERE id = ?", (cart_item_id,))

        else:

            await db.execute(

                "UPDATE cart_items SET quantity = ? WHERE id = ?",

                (quantity, cart_item_id),

            )

        await db.commit()



async def clear_cart(user_id: int) -> None:

    async with _db() as db:

        await db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))

        await db.commit()



# ==================== Курьеры ====================



async def add_courier(telegram_id: int, name: str, phone: str | None = None) -> int:

    """Создаёт или реактивирует курьера. При повторе telegram_id - обновляет имя/телефон."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT id, is_active FROM couriers WHERE telegram_id = ?", (telegram_id,)

        )

        existing = await cur.fetchone()

        if existing:

            await db.execute(

                "UPDATE couriers SET name = ?, phone = ?, is_active = 1 WHERE id = ?",

                (name, phone, existing[0]),

            )

            await db.commit()

            return existing[0]

        cur = await db.execute(

            "INSERT INTO couriers (telegram_id, name, phone, is_active) VALUES (?, ?, ?, 1)",

            (telegram_id, name, phone),

        )

        await db.commit()

        return cur.lastrowid



async def get_couriers(active_only: bool = True) -> list[dict]:

    async with _db() as db:

        if active_only:

            cur = await db.execute(

                "SELECT * FROM couriers WHERE is_active = 1 ORDER BY name"

            )

        else:

            cur = await db.execute(

                "SELECT * FROM couriers ORDER BY is_active DESC, name"

            )

        return [dict(r) for r in await cur.fetchall()]



async def get_courier(courier_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute("SELECT * FROM couriers WHERE id = ?", (courier_id,))

        row = await cur.fetchone()

        return dict(row) if row else None



async def delete_courier(courier_id: int) -> None:

    """Мягкое удаление - is_active = 0, чтобы не ломать архивные заказы."""

    async with _db() as db:

        await db.execute(

            "UPDATE couriers SET is_active = 0 WHERE id = ?", (courier_id,)

        )

        await db.commit()



async def assign_courier_to_order(order_id: int, courier_id: int) -> None:

    async with _db() as db:

        await db.execute(

            "UPDATE orders SET courier_id = ?, courier_assigned_at = CURRENT_TIMESTAMP "

            "WHERE id = ?",

            (courier_id, order_id),

        )

        await db.commit()



# ==================== Заказы ====================



async def create_order(

    user_id: int,

    total_amount: float,

    delivery_time: str,

    payment_method: str,

    comment: str,

    address: str,

    phone: str,

    status: str = "new",

) -> int:

    async with _db() as db:

        cur = await db.execute(

            """INSERT INTO orders

               (user_id, total_amount, delivery_time, payment_method, comment, address, phone, status)

               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",

            (

                user_id,

                total_amount,

                delivery_time,

                payment_method,

                comment,

                address,

                phone,

                status,

            ),

        )

        await db.commit()

        return cur.lastrowid



async def add_order_items(order_id: int, items: list[dict]) -> None:

    async with _db() as db:

        for item in items:

            await db.execute(

                """INSERT INTO order_items (order_id, product_id, quantity, price_at_moment)

                   VALUES (?, ?, ?, ?)""",

                (order_id, item["product_id"], item["quantity"], item["price"]),

            )

            await db.execute(

                "UPDATE products SET stock = stock - ? WHERE id = ?",

                (item["quantity"], item["product_id"]),

            )

        await db.commit()



async def get_order(order_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute(

            """SELECT o.*, u.telegram_id, u.first_name, u.last_name,

                      c.name AS courier_name, c.phone AS courier_phone,

                      c.telegram_id AS courier_telegram_id

               FROM orders o

               JOIN users u ON o.user_id = u.id

               LEFT JOIN couriers c ON o.courier_id = c.id

               WHERE o.id = ?""",

            (order_id,),

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_order_items(order_id: int) -> list[dict]:

    async with _db() as db:

        cur = await db.execute(

            """SELECT oi.*, p.name FROM order_items oi

               JOIN products p ON oi.product_id = p.id WHERE oi.order_id = ?""",

            (order_id,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def update_order_status(order_id: int, status: str) -> None:

    async with _db() as db:

        await db.execute(

            "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)

        )

        await db.commit()



async def set_order_payment_confirmed(order_id: int) -> None:

    """Админ подтвердил поступление оплаты - проставляем временную метку."""

    async with _db() as db:

        await db.execute(

            "UPDATE orders SET status = 'paid', payment_confirmed_at = CURRENT_TIMESTAMP WHERE id = ?",

            (order_id,),

        )

        await db.commit()



async def set_order_delivery_photo(

    order_id: int, file_id: str | None, text: str | None = None

) -> None:

    """Сохранить фото или текстовое подтверждение доставки."""

    async with _db() as db:

        if file_id:

            await db.execute(

                "UPDATE orders SET delivery_photo_file_id = ?, status = 'delivered' WHERE id = ?",

                (file_id, order_id),

            )

        elif text:

            await db.execute(

                "UPDATE orders SET delivery_proof_text = ?, status = 'delivered' WHERE id = ?",

                (text, order_id),

            )

        await db.commit()



async def get_user_orders(user_id: int, limit: int = 5) -> list[dict]:

    """История заказов пользователя. В каждой строке есть review_id и review_rating,

    если отзыв уже оставлен (LEFT JOIN). Удобно для UI: показать «Оставить отзыв»

    только когда отзыва ещё нет."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT o.*, r.id AS review_id, r.rating AS review_rating

               FROM orders o LEFT JOIN reviews r ON r.order_id = o.id

               WHERE o.user_id = ? ORDER BY o.created_at DESC LIMIT ?""",

            (user_id, limit),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_all_orders(status: str | None = None, limit: int = 50) -> list[dict]:

    async with _db() as db:

        if status:

            cur = await db.execute(

                """SELECT o.*, u.telegram_id, u.first_name, u.last_name

                   FROM orders o JOIN users u ON o.user_id = u.id

                   WHERE o.status = ? ORDER BY o.created_at DESC LIMIT ?""",

                (status, limit),

            )

        else:

            cur = await db.execute(

                """SELECT o.*, u.telegram_id, u.first_name, u.last_name

                   FROM orders o JOIN users u ON o.user_id = u.id

                   ORDER BY o.created_at DESC LIMIT ?""",

                (limit,),

            )

        return [dict(r) for r in await cur.fetchall()]



async def get_courier_orders(

    courier_telegram_id: int,

    statuses: tuple[str, ...] = ("sent", "processing"),

    limit: int = 30,

) -> list[dict]:

    """Заказы, назначенные на курьера (по его telegram_id) в указанных статусах.

    Используется для меню курьера «Мои заказы»."""

    async with _db() as db:

        placeholders = ",".join("?" * len(statuses))

        cur = await db.execute(

            f"""SELECT o.*, u.telegram_id, u.first_name, u.last_name,

                      c.name AS courier_name, c.phone AS courier_phone,

                      c.telegram_id AS courier_telegram_id

               FROM orders o

               JOIN users u ON o.user_id = u.id

               LEFT JOIN couriers c ON o.courier_id = c.id

               WHERE c.telegram_id = ?

                 AND o.status IN ({placeholders})

               ORDER BY o.created_at DESC

               LIMIT ?""",

            (courier_telegram_id, *statuses, limit),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_courier_delivered_today(courier_telegram_id: int) -> list[dict]:

    """Заказы, доставленные этим курьером сегодня (для статистики в его меню)."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT o.*, u.telegram_id, u.first_name, u.last_name,

                      c.name AS courier_name, c.phone AS courier_phone,

                      c.telegram_id AS courier_telegram_id

               FROM orders o

               JOIN users u ON o.user_id = u.id

               LEFT JOIN couriers c ON o.courier_id = c.id

               WHERE c.telegram_id = ?

                 AND o.status = 'delivered'

                 AND date(o.created_at) = date('now')

               ORDER BY o.created_at DESC""",

            (courier_telegram_id,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_orders_awaiting_payment() -> list[dict]:

    """Заказы, ожидающие подтверждения оплаты от админа."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT o.*, u.telegram_id, u.first_name, u.last_name

               FROM orders o JOIN users u ON o.user_id = u.id

               WHERE o.status = 'awaiting_payment' ORDER BY o.created_at DESC""",

        )

        return [dict(r) for r in await cur.fetchall()]



async def cancel_order_user(order_id: int, user_id: int) -> bool:

    async with _db() as db:

        cur = await db.execute(

            "SELECT status, user_id FROM orders WHERE id = ?", (order_id,)

        )

        row = await cur.fetchone()

        # Отменить можно только в начальных статусах

        if not row or row[1] != user_id:

            return False

        if row[0] not in ("new", "awaiting_payment", "paid"):

            return False

        # Возвращаем товар на склад

        items = await get_order_items(order_id)

        for item in items:

            await db.execute(

                "UPDATE products SET stock = stock + ? WHERE id = ?",

                (item["quantity"], item["product_id"]),

            )

        await db.execute(

            "UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,)

        )

        await db.commit()

        return True



async def reorder(order_id: int, user_id: int) -> bool:

    """Повторить заказ - положить все позиции в корзину.


    Раньше открывалось N+1 соединений к БД (по одному на каждый товар).

    Теперь всё в одной транзакции: один SELECT для владельца + один SELECT

    для позиций + executemany для новых + N UPDATE для уже-существующих.

    Для заказа из 10 позиций: 12 открытий БД → 1 открытие."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT user_id FROM orders WHERE id = ?", (order_id,)

        )

        row = await cur.fetchone()

        if not row or row[0] != user_id:

            return False

        cur = await db.execute(

            "SELECT product_id, quantity FROM order_items WHERE order_id = ?",

            (order_id,),

        )

        items = await cur.fetchall()

        if not items:

            return True

        # Какие позиции уже в корзине - чтобы потом либо вставить, либо добавить qty

        product_ids = [r[0] for r in items]

        placeholders = ",".join("?" * len(product_ids))

        cur = await db.execute(

            f"SELECT product_id, id FROM cart_items "

            f"WHERE user_id = ? AND product_id IN ({placeholders})",

            (user_id, *product_ids),

        )

        existing = {r[0]: r[1] for r in await cur.fetchall()}

        # Bulk insert новых позиций

        to_insert = [

            (user_id, r[0], r[1]) for r in items if r[0] not in existing

        ]

        if to_insert:

            await db.executemany(

                "INSERT INTO cart_items (user_id, product_id, quantity) "

                "VALUES (?, ?, ?)",

                to_insert,

            )

        # Update количества для существующих

        for r in items:

            if r[0] in existing:

                await db.execute(

                    "UPDATE cart_items SET quantity = quantity + ? WHERE id = ?",

                    (r[1], existing[r[0]]),

                )

        await db.commit()

        return True



# ==================== Поддержка (треды) ====================



async def save_support_message(

    user_id: int,

    user_telegram_id: int,

    user_message_id: int,

    support_chat_id: int,

    support_message_id: int,

    direction: str = "to_support",

    parent_id: int | None = None,

    thread_id: int | None = None,

) -> int:

    """Сохраняет сообщение в тред. Возвращает id строки (нужно для ответа).


    direction:

      - 'to_support' - пользователь написал в поддержку

      - 'to_user'    - поддержка ответила пользователю

    parent_id - id предыдущего сообщения в этом треде (для древовидного вида).

    thread_id - id первого сообщения треда (= thread_id родителя или свой id).

    """

    async with _db() as db:

        cur = await db.execute(

            """INSERT INTO support_messages

               (user_id, user_telegram_id, user_message_id,

                support_chat_id, support_message_id, direction, parent_id, thread_id)

               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",

            (

                user_id,

                user_telegram_id,

                user_message_id,

                support_chat_id,

                support_message_id,

                direction,

                parent_id,

                thread_id,

            ),

        )

        new_id = cur.lastrowid

        # Если thread_id не задан - это первое сообщение треда, thread_id = свой id

        if thread_id is None:

            await db.execute(

                "UPDATE support_messages SET thread_id = ? WHERE id = ?",

                (new_id, new_id),

            )

        await db.commit()

        return new_id



async def get_support_message_by_support_id(support_message_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM support_messages WHERE support_message_id = ?",

            (support_message_id,),

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_support_message_by_user_id(user_message_id: int) -> dict | None:

    """Найти запись в support_messages по user_message_id (нужно для

    группировки ответов пользователя в существующий тред)."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM support_messages WHERE user_message_id = ?",

            (user_message_id,),

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_thread_messages(thread_id: int) -> list[dict]:

    """Все сообщения треда, отсортированные по времени."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM support_messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC",

            (thread_id,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_last_support_thread_for_user(user_id: int) -> dict | None:

    """Последний тред поддержки для пользователя (по любому сообщению в нём).

    Используется, когда юзер нажал 'Ответить' - чтобы понять, в какой тред писать."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT * FROM support_messages

               WHERE user_id = ?

               ORDER BY created_at DESC, id DESC LIMIT 1""",

            (user_id,),

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_user_by_support_thread(thread_id: int) -> dict | None:

    """Получить user_id и telegram_id пользователя по id треда (любое сообщение из треда)."""

    async with _db() as db:

        cur = await db.execute(

            "SELECT user_id, user_telegram_id FROM support_messages "

            "WHERE thread_id = ? LIMIT 1",

            (thread_id,),

        )

        row = await cur.fetchone()

        return dict(row) if row else None



# ==================== Отзывы (после доставки) ====================



async def save_review(order_id: int, user_id: int, rating: int, comment: str | None) -> bool:

    """Сохранить отзыв. У одного заказа - один отзыв (UNIQUE).

    Возвращает True если сохранён, False если уже был."""

    async with _db() as db:

        try:

            await db.execute(

                "INSERT INTO reviews (order_id, user_id, rating, comment) "

                "VALUES (?, ?, ?, ?)",

                (order_id, user_id, rating, comment),

            )

            await db.commit()

            return True

        except Exception:

            # UNIQUE(order_id) сработал - отзыв уже есть

            return False



async def get_order_review(order_id: int) -> dict | None:

    async with _db() as db:

        cur = await db.execute(

            "SELECT * FROM reviews WHERE order_id = ?", (order_id,)

        )

        row = await cur.fetchone()

        return dict(row) if row else None



async def get_user_reviews(user_id: int, limit: int = 20) -> list[dict]:

    async with _db() as db:

        cur = await db.execute(

            """SELECT r.*, o.total_amount, o.created_at AS order_date

               FROM reviews r JOIN orders o ON r.order_id = o.id

               WHERE r.user_id = ? ORDER BY r.created_at DESC LIMIT ?""",

            (user_id, limit),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_average_rating() -> float:

    """Средняя оценка по всем отзывам (для админ-статистики)."""

    async with _db() as db:

        cur = await db.execute("SELECT AVG(rating) FROM reviews")

        r = await cur.fetchone()

        return float(r[0]) if r and r[0] else 0.0



# ==================== Рассылки ====================



async def create_mailing(

    text: str | None,

    photo_file_id: str | None,

    product_id: int | None,

    recipients_count: int,

) -> int:

    """Создать запись о начале рассылки, вернуть её id."""

    async with _db() as db:

        cur = await db.execute(

            """INSERT INTO mailings

               (text, photo_file_id, product_id, recipients_count)

               VALUES (?, ?, ?, ?)""",

            (text, photo_file_id, product_id, recipients_count),

        )

        await db.commit()

        return cur.lastrowid



async def update_mailing_progress(

    mailing_id: int, sent: int, failed: int

) -> None:

    async with _db() as db:

        await db.execute(

            "UPDATE mailings SET sent_count = ?, failed_count = ? WHERE id = ?",

            (sent, failed, mailing_id),

        )

        await db.commit()



async def get_recent_mailings(limit: int = 10) -> list[dict]:

    """Последние рассылки - для админ-истории."""

    async with _db() as db:

        cur = await db.execute(

            """SELECT m.*, p.name AS product_name, p.price AS product_price

               FROM mailings m LEFT JOIN products p ON m.product_id = p.id

               ORDER BY m.created_at DESC LIMIT ?""",

            (limit,),

        )

        return [dict(r) for r in await cur.fetchall()]



async def get_all_user_telegram_ids() -> list[int]:

    """Все telegram_id пользователей (для рассылки)."""

    async with _db() as db:

        cur = await db.execute("SELECT telegram_id FROM users")

        return [r[0] for r in await cur.fetchall()]



# ==================== Статистика ====================



async def get_stats_day() -> dict:

    async with _db() as db:

        cur = await db.execute("""

            SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)

            FROM orders WHERE date(created_at) = date('now') AND status != 'cancelled'

        """)

        row = await cur.fetchone()

        cur = await db.execute("""

            SELECT COUNT(*) FROM orders WHERE date(created_at) = date('now') AND status = 'cancelled'

        """)

        c = await cur.fetchone()

        return {

            "orders": row[0] or 0,

            "revenue": row[1] or 0,

            "avg_check": row[2] or 0,

            "cancelled": c[0] or 0,

        }



async def get_stats_week() -> dict:

    async with _db() as db:

        cur = await db.execute("""

            SELECT COUNT(*), COALESCE(SUM(total_amount), 0), COALESCE(AVG(total_amount), 0)

            FROM orders WHERE created_at >= date('now', '-7 days') AND status != 'cancelled'

        """)

        row = await cur.fetchone()

        cur = await db.execute("""

            SELECT COUNT(*) FROM orders WHERE created_at >= date('now', '-7 days') AND status = 'cancelled'

        """)

        c = await cur.fetchone()

        return {

            "orders": row[0] or 0,

            "revenue": row[1] or 0,

            "avg_check": row[2] or 0,

            "cancelled": c[0] or 0,

        }



async def get_top_products(period: str = "day", limit: int = 3) -> list[dict]:

    async with _db() as db:

        if period == "day":

            df = "date(o.created_at) = date('now')"

        else:

            df = "o.created_at >= date('now', '-7 days')"

        cur = await db.execute(

            f"""

            SELECT p.name, SUM(oi.quantity) as qty,

                   SUM(oi.quantity * oi.price_at_moment) as revenue

            FROM order_items oi

            JOIN orders o ON oi.order_id = o.id

            JOIN products p ON oi.product_id = p.id

            WHERE {df} AND o.status != 'cancelled'

            GROUP BY oi.product_id ORDER BY qty DESC LIMIT ?

        """,

            (limit,),

        )

        return [dict(r) for r in await cur.fetchall()]


async def get_products_by_category_paginated(category_id: int, page: int = 1, limit: int = 20) -> list[dict]:

        """Получить товары категории порциями (постранично) для Mini App"""

        async with _db() as db:

            # Вычисляем сдвиг (offset) для SQL запроса

            offset = (page - 1) * limit


            cur = await db.execute(

                """SELECT * FROM products

                   WHERE category_id = ? AND is_active = 1

                   ORDER BY is_stopped, id DESC

                   LIMIT ? OFFSET ?""",

                (category_id, limit, offset)

            )

            rows = await cur.fetchall()

            return [dict(r) for r in rows]