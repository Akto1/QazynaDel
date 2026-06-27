from datetime import datetime


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BUILDINGS, DELIVERY_TIME_SLOTS, PAYMENT_METHODS, WEBAPP_URL, WORKING_HOURS_END, ORDER_STATUSES

from locales import LANGUAGES, t


# ==================== Главное меню ====================



def main_menu_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    # Если задан WEBAPP_URL — главная кнопка открывает Mini App (как Kaspi).

    # Иначе — fallback на старый inline-каталог.

    if WEBAPP_URL:

        b.row(

            InlineKeyboardButton(

                text="🛍 Открыть магазин",

                web_app=WebAppInfo(url=WEBAPP_URL),

            )

        )

        # В Mini App корзина и история тоже есть, но кнопки в боте оставим

        # как quick-access — кто-то привык.

        b.row(

            InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"),

            InlineKeyboardButton(text=t(lang, "menu_history"), callback_data="history"),

        )

        b.row(

            InlineKeyboardButton(text=t(lang, "menu_support"), callback_data="support"),

            InlineKeyboardButton(text=t(lang, "menu_language"), callback_data="language"),

        )

        b.row(InlineKeyboardButton(text=t(lang, "menu_profile"), callback_data="profile"))

    else:

        b.row(InlineKeyboardButton(text=t(lang, "menu_catalog"), callback_data="catalog"))

        b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))

        b.row(

            InlineKeyboardButton(text=t(lang, "menu_history"), callback_data="history"),

            InlineKeyboardButton(text=t(lang, "menu_profile"), callback_data="profile"),

        )

        b.row(

            InlineKeyboardButton(text=t(lang, "menu_support"), callback_data="support"),

            InlineKeyboardButton(text=t(lang, "menu_language"), callback_data="language"),

        )

    return b.as_markup()



def back_to_main_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))

    return b.as_markup()



def language_keyboard():

    b = InlineKeyboardBuilder()

    for code, name in LANGUAGES.items():

        b.row(InlineKeyboardButton(text=name, callback_data=f"lang_{code}"))

    return b.as_markup()



# ==================== Подтверждение данных (новое) ====================



def confirm_input_keyboard(

    lang="ru", confirm_cb="confirm_data", change_cb="change_data"

):

    """Универсальная клавиатура: ✅ Всё верно / ✏️ Изменить."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(text=t(lang, "all_correct"), callback_data=confirm_cb),

        InlineKeyboardButton(text=t(lang, "change"), callback_data=change_cb),

    )

    return b.as_markup()



def i_paid_keyboard(lang="ru", order_id=None):

    """Кнопка 'Я оплатил' — после создания Kaspi-заказа."""

    b = InlineKeyboardBuilder()

    cb = "i_paid" if order_id is None else f"i_paid_{order_id}"

    b.row(InlineKeyboardButton(text=t(lang, "i_paid"), callback_data=cb))

    return b.as_markup()



# ==================== Каталог ====================



def categories_keyboard(categories, lang="ru"):

    b = InlineKeyboardBuilder()

    for cat in categories:

        b.row(

            InlineKeyboardButton(

                text=f"{cat['emoji']} {cat['name']}",

                callback_data=f"category_{cat['id']}",

            )

        )

    b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))

    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="main_menu"))

    return b.as_markup()



def products_keyboard(products, category_id, lang="ru"):

    b = InlineKeyboardBuilder()

    for p in products:

        b.row(

            InlineKeyboardButton(

                text=f"🛒 {p['name']} — {p['price']:.0f} ₸",

                callback_data=f"product_{p['id']}",

            )

        )

    b.row(InlineKeyboardButton(text=t(lang, "menu_cart"), callback_data="cart"))

    b.row(

        InlineKeyboardButton(

            text=t(lang, "back_to_categories"), callback_data="catalog"

        )

    )

    return b.as_markup()



def product_detail_keyboard(product_id, in_cart=False, lang="ru"):

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "add_more"), callback_data=f"add_to_cart_{product_id}"

        )

    )

    if in_cart:

        b.row(InlineKeyboardButton(text=t(lang, "go_to_cart"), callback_data="cart"))

    b.row(

        InlineKeyboardButton(

            text=t(lang, "back_to_products"), callback_data="back_to_products"

        )

    )

    return b.as_markup()



# ==================== Корзина ====================



def cart_keyboard(items, lang="ru"):

    b = InlineKeyboardBuilder()

    for item in items:

        b.row(

            InlineKeyboardButton(

                text=f"➖ {item['name'][:20]} ({item['quantity']})",

                callback_data=f"cart_minus_{item['id']}",

            ),

            InlineKeyboardButton(text="➕", callback_data=f"cart_plus_{item['id']}"),

        )

    b.row(InlineKeyboardButton(text=t(lang, "clear_cart"), callback_data="clear_cart"))

    b.row(InlineKeyboardButton(text=t(lang, "checkout"), callback_data="checkout"))

    b.row(

        InlineKeyboardButton(text=t(lang, "continue_shopping"), callback_data="catalog")

    )

    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))

    return b.as_markup()



def empty_cart_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(text=t(lang, "continue_shopping"), callback_data="catalog")

    )

    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))

    return b.as_markup()



# ==================== Оформление заказа ====================



def address_keyboard(has_address=False, lang="ru"):

    b = InlineKeyboardBuilder()

    if has_address:

        b.row(

            InlineKeyboardButton(

                text=t(lang, "use_saved"), callback_data="use_saved_address"

            )

        )

    b.row(

        InlineKeyboardButton(

            text=t(lang, "enter_new"), callback_data="enter_new_address"

        )

    )

    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="cart"))

    return b.as_markup()



def phone_keyboard(has_phone=False, lang="ru"):

    """Клавиатура при вводе телефона: можно использовать сохранённый или ввести новый."""

    b = InlineKeyboardBuilder()

    if has_phone:

        b.row(

            InlineKeyboardButton(

                text=t(lang, "use_saved"), callback_data="use_saved_phone"

            )

        )

    b.row(

        InlineKeyboardButton(text=t(lang, "enter_new"), callback_data="enter_new_phone")

    )

    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="cart"))

    return b.as_markup()



def delivery_time_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    now = datetime.now()

    if now.hour >= WORKING_HOURS_END:

        b.row(InlineKeyboardButton(text=t(lang, "too_late"), callback_data="time_late"))

        b.row(

            InlineKeyboardButton(

                text=t(lang, "tomorrow_slot", slot="08:00–10:00"),

                callback_data="time_завтра_08:00–10:00",

            )

        )

        b.row(

            InlineKeyboardButton(

                text=t(lang, "tomorrow_slot", slot="10:00–12:00"),

                callback_data="time_завтра_10:00–12:00",

            )

        )

    else:

        b.row(InlineKeyboardButton(text=t(lang, "asap"), callback_data="time_asap"))

        for slot in DELIVERY_TIME_SLOTS:

            b.row(

                InlineKeyboardButton(

                    text=t(lang, "time_slot", slot=slot), callback_data=f"time_{slot}"

                )

            )

    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="checkout"))

    return b.as_markup()



def payment_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    for key, value in PAYMENT_METHODS.items():

        b.row(InlineKeyboardButton(text=value, callback_data=f"pay_{key}"))

    b.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="checkout"))

    return b.as_markup()



def confirm_order_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(text=t(lang, "confirm_btn"), callback_data="confirm_order")

    )

    b.row(InlineKeyboardButton(text=t(lang, "change_data"), callback_data="checkout"))

    b.row(InlineKeyboardButton(text=t(lang, "back_to_cart"), callback_data="cart"))

    return b.as_markup()



# ==================== Профиль ====================



def profile_keyboard(lang="ru"):

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(text=t(lang, "edit_address"), callback_data="edit_address")

    )

    b.row(InlineKeyboardButton(text=t(lang, "edit_phone"), callback_data="edit_phone"))

    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))

    return b.as_markup()



# ==================== Админ ====================



def admin_main_keyboard():

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text="💳 Ожидают оплаты", callback_data="admin_orders_awaiting"

        )

    )

    b.row(

        InlineKeyboardButton(text="🆕 Новые заказы", callback_data="admin_orders_new")

    )

    b.row(

        InlineKeyboardButton(

            text="📦 В работе", callback_data="admin_orders_processing"

        )

    )

    b.row(

        InlineKeyboardButton(text="🚚 Отправленные", callback_data="admin_orders_sent")

    )

    b.row(

        InlineKeyboardButton(

            text="✅ Доставленные", callback_data="admin_orders_delivered"

        )

    )

    b.row(InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"))

    b.row(InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"))

    b.row(

        InlineKeyboardButton(

            text="🛠 Управление товарами", callback_data="admin_products"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="🛒 Чек-лист", callback_data="admin_stoplist"

        )

    )

    b.row(InlineKeyboardButton(text="🚚 Курьеры", callback_data="admin_couriers"))

    b.row(InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_mailing"))

    return b.as_markup()



def admin_order_status_keyboard(order_id, current_status):

    """Кнопки изменения статуса заказа админом."""

    b = InlineKeyboardBuilder()

    flow = {

        "awaiting_payment": [

            ("paid", "💰 Оплата получена"),

            ("cancelled", "❌ Отменить"),

        ],

        "new": [("processing", "📦 Взять в работу"), ("cancelled", "❌ Отменить")],

        "paid": [("processing", "📦 Взять в работу"), ("cancelled", "❌ Отменить")],

        "processing": [("sent", "🚚 Отправить"), ("cancelled", "❌ Отменить")],

        "sent": [("delivered", "✅ Доставлен"), ("cancelled", "❌ Отменить")],

    }

    if current_status in flow:

        for status, text in flow[current_status]:

            b.row(

                InlineKeyboardButton(

                    text=text, callback_data=f"admin_status_{order_id}_{status}"

                )

            )

    b.row(InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"))

    return b.as_markup()



def admin_couriers_kb(couriers):

    """Список курьеров с кнопками удаления + добавить нового."""

    b = InlineKeyboardBuilder()

    for c in couriers:

        line = (

            f"{'🟢' if c.get('is_active') else '⚪'} {c['name']} (@{c['telegram_id']})"

        )

        if c.get("phone"):

            line += f" • {c['phone']}"

        b.row(

            InlineKeyboardButton(

                text=f"❌ {line}", callback_data=f"admin_courier_del_{c['id']}"

            )

        )

    b.row(

        InlineKeyboardButton(

            text="➕ Добавить курьера", callback_data="admin_courier_add"

        )

    )

    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))

    return b.as_markup()



def admin_courier_pick_kb(couriers, order_id):

    """Выпадающий список выбора курьера для назначения на заказ."""

    b = InlineKeyboardBuilder()

    for c in couriers:

        text = f"👤 {c['name']}"

        if c.get("phone"):

            text += f" • {c['phone']}"

        b.row(

            InlineKeyboardButton(

                text=text, callback_data=f"admin_pick_courier_{order_id}_{c['id']}"

            )

        )

    b.row(

        InlineKeyboardButton(text="◀️ К заказу", callback_data=f"admin_view_{order_id}")

    )

    return b.as_markup()



def admin_products_keyboard():

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text="➕ Добавить товар", callback_data="admin_add_product"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="📝 Редактировать товар", callback_data="admin_edit_product"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="🗑 Удалить товар", callback_data="admin_delete_product"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="➕ Добавить категорию", callback_data="admin_add_category"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="🗑 Удалить категорию", callback_data="admin_delete_category"

        )

    )

    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back"))

    return b.as_markup()



def admin_stoplist_categories_kb(categories):

    """Список категорий для раздела «Чек-лист»."""

    b = InlineKeyboardBuilder()

    for cat in categories:

        b.row(

            InlineKeyboardButton(

                text=f"{cat['emoji']} {cat['name']}",

                callback_data=f"admin_stop_cat_{cat['id']}",

            )

        )

    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))

    return b.as_markup()



def admin_stoplist_products_kb(products):

    """Список товаров категории с toggle-кнопками стоп-листа."""

    b = InlineKeyboardBuilder()

    for p in products:

        if p.get('is_active') == 0:

            continue  # удалённые не показываем

        is_stopped = p.get('is_stopped') == 1

        if is_stopped:

            mark = "🔴"

            label_action = "Вернуть"

        else:

            mark = "🟢"

            label_action = "В стоп-лист"

        text = f"{label_action}: {p['name'][:40]} — {p['price']:.0f} ₸ {mark}"

        b.row(

            InlineKeyboardButton(

                text=text, callback_data=f"admin_stop_toggle_{p['id']}"

            )

        )

    b.row(InlineKeyboardButton(text="◀️ К категориям", callback_data="admin_stoplist"))

    return b.as_markup()



def admin_delete_category_kb(categories: list[dict]) -> InlineKeyboardMarkup:

    """Список категорий с пометкой о количестве товаров.


    Удалить можно только пустую категорию — это ясно из подписи кнопки.

    Непустые всё равно кликабельны: при нажатии бот покажет ошибку с

    понятным объяснением (а не молча ничего не сделает)."""

    b = InlineKeyboardBuilder()

    for cat in categories:

        mark = "🟢" if cat.get("is_active") else "⚪"

        # products_count добавляется в хендлере (через category_has_active_products)

        cnt = cat.get("products_count", 0)

        text = f"{mark} {cat['emoji']} {cat['name']} • {cnt} шт."

        b.row(

            InlineKeyboardButton(

                text=text, callback_data=f"admin_del_category_{cat['id']}"

            )

        )

    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))

    return b.as_markup()



def admin_categories_for_product_keyboard(categories):

    b = InlineKeyboardBuilder()

    for cat in categories:

        if not cat.get("id"):

            continue

        b.row(

            InlineKeyboardButton(

                text=f"{cat['emoji']} {cat['name']}",

                callback_data=f"admin_cat_{cat['id']}",

            )

        )

    if not b.buttons:

        b.row(

            InlineKeyboardButton(text="(нет категорий)", callback_data="admin_cancel")

        )

    else:

        b.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_cancel"))

    return b.as_markup()



def admin_confirm_product_keyboard():

    b = InlineKeyboardBuilder()

    b.row(InlineKeyboardButton(text="✅ Сохранить", callback_data="admin_save_product"))

    b.row(

        InlineKeyboardButton(text="🔄 Изменить", callback_data="admin_change_product")

    )

    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))

    return b.as_markup()



def admin_skip_photo_keyboard():

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(text="⏭ Пропустить фото", callback_data="admin_skip_photo")

    )

    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"))

    return b.as_markup()



def admin_cancel_kb():

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]

        ]

    )



def admin_skip_desc_kb():

    return InlineKeyboardMarkup(

        inline_keyboard=[

            [

                InlineKeyboardButton(

                    text="⏭ Пропустить", callback_data="admin_skip_desc"

                )

            ],

            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")],

        ]

    )



# ==================== Выбор корпуса / пэтера (без свободного ввода адреса) ====================



# Сколько пэтеров на одной странице: 5 колонок × 6 рядов = 30.

# Корпус с 49 пэтерами получает 2 страницы: 1–30 и 31–49.

_APT_PER_PAGE = 30

_APT_COLS = 5



def buildings_kb() -> InlineKeyboardMarkup:

    """Сетка кнопок со всеми корпусами. По 2 в ряд — компактно."""

    b = InlineKeyboardBuilder()

    for building in BUILDINGS:

        b.row(

            InlineKeyboardButton(

                text=f"🏢 {building['name']}",

                callback_data=f"bld_{building['id']}",

            )

        )

    b.row(InlineKeyboardButton(text="◀️ В корзину", callback_data="cart"))

    return b.as_markup()



def building_apartments_kb(building_id: int, page: int = 0) -> InlineKeyboardMarkup:

    """Сетка пэтеров в выбранном корпусе, 5 в ряд, с пагинацией.

    callback_data: apt_{building_id}_{apt}"""

    building = next((b for b in BUILDINGS if b["id"] == building_id), None)

    if building is None:

        return InlineKeyboardMarkup(inline_keyboard=[])


    apts = list(range(building["min_apt"], building["max_apt"] + 1))

    total_pages = max(1, (len(apts) + _APT_PER_PAGE - 1) // _APT_PER_PAGE)

    page = max(0, min(page, total_pages - 1))

    start = page * _APT_PER_PAGE

    page_apts = apts[start : start + _APT_PER_PAGE]


    b = InlineKeyboardBuilder()

    for i in range(0, len(page_apts), _APT_COLS):

        chunk = page_apts[i : i + _APT_COLS]

        b.row(

            *[

                InlineKeyboardButton(

                    text=str(apt),

                    callback_data=f"apt_{building_id}_{apt}",

                )

                for apt in chunk

            ]

        )

    # Пагинация

    nav = []

    if page > 0:

        nav.append(

            InlineKeyboardButton(

                text="◀️ Назад",

                callback_data=f"aptp_{building_id}_{page - 1}",

            )

        )

    nav.append(

        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")

    )

    if page < total_pages - 1:

        nav.append(

            InlineKeyboardButton(

                text="Вперёд ▶️",

                callback_data=f"aptp_{building_id}_{page + 1}",

            )

        )

    b.row(*nav)

    b.row(InlineKeyboardButton(text="◀️ К корпусам", callback_data="aptb_back"))

    return b.as_markup()



# ==================== Меню курьера ====================



def courier_main_kb() -> InlineKeyboardMarkup:

    """Главное меню для курьера (доступно через /start)."""

    b = InlineKeyboardBuilder()

    b.row(InlineKeyboardButton(text="📦 Мои заказы", callback_data="c_orders"))

    b.row(InlineKeyboardButton(text="✅ Сегодня доставлено", callback_data="c_today"))

    b.row(InlineKeyboardButton(text="❓ Помощь", callback_data="c_help"))

    return b.as_markup()



def courier_orders_kb(orders) -> InlineKeyboardMarkup:

    """Список активных заказов курьера — каждая строка кликабельна."""

    b = InlineKeyboardBuilder()

    for o in orders:

        b.row(

            InlineKeyboardButton(

                text=f"📦 #{o['id']} • {o.get('address') or '—'}",

                callback_data=f"c_order_{o['id']}",

            )

        )

    b.row(InlineKeyboardButton(text="◀️ В меню курьера", callback_data="c_menu"))

    return b.as_markup()



def courier_order_actions_kb(order_id: int) -> InlineKeyboardMarkup:

    """Кнопки действий курьера на конкретном заказе."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text="✅ Я доставил", callback_data=f"courier_delivered_{order_id}"

        )

    )

    b.row(InlineKeyboardButton(text="◀️ К моим заказам", callback_data="c_orders"))

    return b.as_markup()



# ==================== Отзывы (после доставки) ====================



def review_rating_keyboard(order_id: int, lang="ru") -> InlineKeyboardMarkup:

    """5 кнопок-звёзд для оценки."""

    b = InlineKeyboardBuilder()

    for n in (1, 2, 3, 4, 5):

        b.row(

            InlineKeyboardButton(

                text=t(lang, f"rating_{n}"),

                callback_data=f"review_rate_{order_id}_{n}",

            )

        )

    b.row(

        InlineKeyboardButton(

            text=t(lang, "to_main_menu"), callback_data="main_menu"

        )

    )

    return b.as_markup()



def review_text_skip_keyboard(order_id: int, lang="ru") -> InlineKeyboardMarkup:

    """После оценки — выбор: написать комментарий или пропустить."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "review_skip"), callback_data=f"review_skip_{order_id}"

        )

    )

    return b.as_markup()



# ==================== История заказов (с действиями) ====================



def history_orders_keyboard(orders, lang="ru") -> InlineKeyboardMarkup:

    """Список заказов в истории. Каждый заказ — отдельная кнопка-строка.


    Под основным списком — кнопка «Назад» в главное меню.

    Действия (повторить/отменить/отзыв) показываем в детальной карточке заказа —

    это упрощает UI и не перегружает экран."""

    b = InlineKeyboardBuilder()

    for o in orders:

        status = ORDER_STATUSES.get(o["status"], o["status"])

        text = t(lang, "order_actions", id=o["id"], total=o["total_amount"], status=status)

        if len(text) > 60:

            text = f"📦 #{o['id']} • {o['total_amount']:.0f}₸ • {status}"

        b.row(InlineKeyboardButton(text=text, callback_data=f"history_view_{o['id']}"))

    b.row(InlineKeyboardButton(text=t(lang, "to_main_menu"), callback_data="main_menu"))

    return b.as_markup()



def history_order_detail_kb(order, lang="ru") -> InlineKeyboardMarkup:

    """Кнопки действий на конкретном заказе из истории.


    — Повторить: если товары ещё активны (is_active=1) — кладём их в корзину.

    — Отменить: только если заказ в начальных статусах (отмена через cancel_order_user).

    — Оставить отзыв: только если delivered и ещё нет отзыва.

    — Посмотреть отзыв: если отзыв уже оставлен."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "btn_reorder"),

            callback_data=f"reorder_{order['id']}",

        )

    )

    if order["status"] in ("new", "awaiting_payment", "paid"):

        b.row(

            InlineKeyboardButton(

                text=t(lang, "btn_cancel_order"),

                callback_data=f"user_cancel_{order['id']}",

            )

        )

    if order["status"] == "delivered":

        if order.get("review_id"):

            b.row(

                InlineKeyboardButton(

                    text=t(lang, "btn_view_review"),

                    callback_data=f"review_view_{order['id']}",

                )

            )

        else:

            b.row(

                InlineKeyboardButton(

                    text=t(lang, "btn_leave_review"),

                    callback_data=f"review_start_{order['id']}",

                )

            )

    b.row(

        InlineKeyboardButton(

            text=t(lang, "back"), callback_data="history"

        )

    )

    return b.as_markup()



# ==================== Поддержка: ответ пользователя ====================



def support_reply_keyboard(thread_id: int, lang="ru") -> InlineKeyboardMarkup:

    """Кнопка под сообщением поддержки — юзер может ответить прямо в тред."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "support_reply_btn"),

            callback_data=f"support_reply_{thread_id}",

        )

    )

    return b.as_markup()



# ==================== Рассылка (админ) ====================



def admin_mailing_keyboard() -> InlineKeyboardMarkup:

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text="📣 Создать рассылку", callback_data="mailing_start"

        )

    )

    b.row(

        InlineKeyboardButton(

            text="📜 История рассылок", callback_data="mailing_history"

        )

    )

    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))

    return b.as_markup()



def mailing_categories_keyboard(categories) -> InlineKeyboardMarkup:

    """Выбор категории для прикрепления товара к рассылке."""

    b = InlineKeyboardBuilder()

    for cat in categories:

        b.row(

            InlineKeyboardButton(

                text=f"{cat['emoji']} {cat['name']}",

                callback_data=f"mailing_cat_{cat['id']}",

            )

        )

    b.row(

        InlineKeyboardButton(

            text="⏭ Без товара", callback_data="mailing_skip_product"

        )

    )

    b.row(InlineKeyboardButton(text="◀️ Отмена", callback_data="mailing_cancel"))

    return b.as_markup()



def mailing_products_keyboard(products, lang="ru") -> InlineKeyboardMarkup:

    """Товары выбранной категории — для прикрепления к рассылке."""

    b = InlineKeyboardBuilder()

    for p in products:

        b.row(

            InlineKeyboardButton(

                text=f"📦 {p['name']} — {p['price']:.0f} ₸",

                callback_data=f"mailing_product_{p['id']}",

            )

        )

    b.row(

        InlineKeyboardButton(

            text="◀️ К категориям", callback_data="mailing_back_to_cats"

        )

    )

    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="mailing_cancel"))

    return b.as_markup()



def mailing_photo_choice_keyboard(lang="ru") -> InlineKeyboardMarkup:

    """После текста: выбор — прислать фото или пропустить."""

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "mailing_skip_photo"),

            callback_data="mailing_skip_photo",

        )

    )

    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="mailing_cancel"))

    return b.as_markup()



def mailing_preview_keyboard(lang="ru") -> InlineKeyboardMarkup:

    b = InlineKeyboardBuilder()

    b.row(

        InlineKeyboardButton(

            text=t(lang, "mailing_send"),

            callback_data="mailing_confirm_send",

        )

    )

    b.row(

        InlineKeyboardButton(

            text=t(lang, "mailing_edit"),

            callback_data="mailing_edit_text",

        )

    )

    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="mailing_cancel"))

    return b.as_markup()