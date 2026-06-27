import asyncio
import html
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import (
    ADMIN_ID,
    DELIVERY_FEE,
    MINIMUM_ORDER_AMOUNT,
    ORDER_STATUSES,
    PAYMENT_METHODS,
    SUPPORT_GROUP_ID,
    TIMEZONE,
    WORKING_HOURS_END,
    WORKING_HOURS_START,
    find_building,
    format_building_address,
)
from database import (
    add_category,
    add_courier,
    add_order_items,
    add_product,
    add_to_cart,
    assign_courier_to_order,
    cancel_order_user,
    category_has_active_products,
    clear_cart,
    create_mailing,
    create_order,
    delete_category,
    delete_courier,
    delete_product,
    get_all_orders,
    get_all_user_telegram_ids,
    get_average_rating,
    get_cart_items,
    get_cart_total,
    get_categories,
    get_category,
    get_courier,
    get_courier_delivered_today,
    get_courier_orders,
    get_couriers,
    get_or_create_user,
    get_order,
    get_order_items,
    get_order_review,
    get_product,
    get_products_by_category,
    get_products_by_category_with_stopped,
    get_recent_mailings,
    get_stats_day,
    get_stats_week,
    get_support_message_by_support_id,
    get_top_products,
    get_user_by_support_thread,
    get_user_by_telegram_id,
    get_user_language,
    get_user_orders,
    init_db,
    reorder,
    save_review,
    save_support_message,
    set_order_delivery_photo,
    set_order_payment_confirmed,
    set_product_stopped,
    update_mailing_progress,
    update_order_status,
    update_product,
    update_user_language,
    update_user_profile,
    validate_address,
    validate_phone,
    validate_price,
)
from keyboards import (
    address_keyboard,
    admin_cancel_kb,
    admin_categories_for_product_keyboard,
    admin_confirm_product_keyboard,
    admin_courier_pick_kb,
    admin_couriers_kb,
    admin_delete_category_kb,
    admin_main_keyboard,
    admin_mailing_keyboard,
    admin_order_status_keyboard,
    admin_products_keyboard,
    admin_skip_desc_kb,
    admin_skip_photo_keyboard,
    admin_stoplist_categories_kb,
    admin_stoplist_products_kb,
    back_to_main_keyboard,
    building_apartments_kb,
    buildings_kb,
    cart_keyboard,
    categories_keyboard,
    confirm_input_keyboard,
    confirm_order_keyboard,
    courier_main_kb,
    courier_order_actions_kb,
    courier_orders_kb,
    delivery_time_keyboard,
    empty_cart_keyboard,
    history_order_detail_kb,
    history_orders_keyboard,
    i_paid_keyboard,
    language_keyboard,
    main_menu_keyboard,
    mailing_categories_keyboard,
    mailing_photo_choice_keyboard,
    mailing_preview_keyboard,
    mailing_products_keyboard,
    payment_keyboard,
    phone_keyboard,
    product_detail_keyboard,
    products_keyboard,
    profile_keyboard,
    review_rating_keyboard,
    review_text_skip_keyboard,
    support_reply_keyboard,
)
from locales import t
from states import (
    AdminAddCategoryState,
    AdminAddProductState,
    AdminCourierState,
    AdminDeliveryState,
    AdminEditProductState,
    AdminMailingState,
    CheckoutState,
    ProfileState,
    ReviewState,
    SupportReplyState,
    SupportState,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Глобальное хранилище FSM, используется для ручной установки state из callback'ов,
# где Bot не имеет .dispatcher (aiogram 3.x).
_FSM_STORAGE = MemoryStorage()

router = Router()


# ==================== Хелперы ====================


async def safe_edit(target, text, reply_markup=None, parse_mode="HTML"):
    """edit_text с fallback'ом на edit_caption / answer (для фото-сообщений).
    Игнорирует «message is not modified» — Telegram ругается, если контент не изменился.
    Это нормальный случай, например, при удалении курьера, когда список визуально тот же."""
    try:
        await target.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        if "no text" not in msg:
            raise
    try:
        await target.edit_caption(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )
        return
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return
    except Exception:
        pass
    await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def resend(target, text, reply_markup=None, parse_mode="HTML"):
    """Удаляет target-сообщение и шлёт новое (надёжнее, чем edit_caption)."""
    try:
        await target.delete()
    except Exception:
        pass
    await target.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


# ==================== Фильтр: только админ ====================


class IsAdmin(BaseFilter):
    async def __call__(self, event):
        return getattr(event.from_user, "id", None) == ADMIN_ID


class IsCourier(BaseFilter):
    """Пропускает только активных курьеров (по telegram_id из таблицы couriers)."""

    async def __call__(self, event):
        tg_id = getattr(event.from_user, "id", None)
        if tg_id is None:
            return False
        from database import _db

        async with _db() as db:
            cur = await db.execute(
                "SELECT 1 FROM couriers WHERE telegram_id = ? AND is_active = 1",
                (tg_id,),
            )
            return await cur.fetchone() is not None


async def _is_courier(tg_id: int) -> bool:
    """Обычная (не-filter) проверка: является ли tg_id активным курьером."""
    if not tg_id:
        return False
    from database import _db

    async with _db() as db:
        cur = await db.execute(
            "SELECT 1 FROM couriers WHERE telegram_id = ? AND is_active = 1",
            (tg_id,),
        )
        return await cur.fetchone() is not None


# ==================== Парсинг callback ====================


def parse_cb(data: str) -> tuple[str, list[str]]:
    for prefix in [
        "add_to_cart",
        "cart_plus",
        "cart_minus",
        "category",
        "product",
        "lang",
        "time",
        "pay",
        "admin_view",
        "admin_process",
        "admin_cancel",
        "admin_status",
        "admin_orders",
        "admin_cat",
        "admin_edit_cat",
        "admin_edit_item",
        "admin_del_cat",
        "admin_del_item",
        "admin_courier_del",
        "admin_pick_courier",
        "courier_delivered",
        "courier_view_photo",
        "bld",
        "apt",
        "aptp",
        "c_order",
        "user_cancel",
        "reorder",
        "admin_confirm_pay",
        "admin_reject_pay",
        "i_paid",
        "confirm_address",
        "confirm_phone",
        "change_address",
        "change_phone",
        "history_view",
        "review_start",
        "review_rate",
        "review_skip",
        "review_view",
        "support_reply",
        "mailing_start",
        "mailing_cat",
        "mailing_product",
        "mailing_skip_photo",
        "mailing_skip_product",
        "mailing_back_to_cats",
        "mailing_cancel",
        "mailing_confirm_send",
        "mailing_edit_text",
        "mailing_history",
        "admin_delete_category",
        "admin_del_category",
        "admin_stop_cat",
        "admin_stop_toggle",
    ]:
        if data.startswith(prefix + "_") or (
            prefix.endswith("_") and data.startswith(prefix)
        ):
            rest = data[len(prefix) :]
            cleaned = rest.lstrip("_")
            return prefix.rstrip("_"), cleaned.split("_") if cleaned else []
    parts = data.split("_")
    logger.warning("parse_cb: no prefix matched for data=%r, parts=%r", data, parts)
    return parts[0], parts[1:]


def _e(value) -> str:
    """HTML-escape для пользовательского ввода, чтобы не ломать parse_mode='HTML'."""
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def _safe_int(value, default: int | None = None) -> int | None:
    """Безопасное приведение к int. Возвращает default при пустой/нечисловой строке."""
    if value is None or value == "":
        logger.warning("_safe_int: empty value, default=%r", default)
        return default
    try:
        return int(value)
    except (ValueError, TypeError) as e:
        logger.warning(
            "_safe_int: cannot convert %r, default=%r: %s", value, default, e
        )
        return default


def _local_now():
    """Локальное время с учётом TIMEZONE из config.
    Amvera хостит бота в UTC, а открытие/слоты — по локальному времени города."""
    if TIMEZONE is not None:
        try:
            return datetime.now(TIMEZONE)
        except Exception:
            pass
    return datetime.now()


def is_working() -> bool:
    return WORKING_HOURS_START <= _local_now().hour < WORKING_HOURS_END


def calc_delivery(total: float) -> tuple[float, float, str]:
    if total >= MINIMUM_ORDER_AMOUNT:
        return total, 0, "free"
    return total + DELIVERY_FEE, DELIVERY_FEE, "paid"


def next_delivery_time() -> str:
    now = _local_now()
    if now.hour >= 23:
        return "08:00–10:00"
    for s in [8, 10, 12, 14, 16, 18, 20]:
        if now.hour < s:
            return f"{s:02d}:00–{s + 2:02d}:00"
    return "08:00–10:00"


# ==================== Форматирование ====================


def format_cart(cart, total, lang):
    if not cart:
        return t(lang, "cart_empty")
    text = t(lang, "cart") + "\n\n"
    for item in cart:
        it = item["quantity"] * item["price"]
        text += (
            t(
                lang,
                "cart_item",
                name=item["name"],
                qty=item["quantity"],
                price=item["price"],
                total=it,
            )
            + "\n"
        )
    final, fee, dtype = calc_delivery(total)
    text += "\n" + t(lang, "cart_total", total=total)
    if dtype == "paid":
        text += "\n" + t(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + t(lang, "total_with_delivery", total=final)
    else:
        text += "\n" + t(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
        text += "\n" + t(lang, "total_free_delivery", total=final)
    return text


def format_admin_order(order, items, user_name):
    status = ORDER_STATUSES.get(order["status"], order["status"])
    text = f"📦 <b>Заказ #{order['id']}</b>\n"
    text += f"📊 <b>Статус:</b> {status}\n\n"
    text += f"👤 <b>Клиент:</b> {_e(user_name)}\n"
    text += f"📍 <b>Адрес:</b> {_e(order['address'])}\n"
    text += f"📞 <b>Телефон:</b> <code>{_e(order['phone'])}</code>\n"
    text += f"💰 <b>Сумма:</b> {order['total_amount']:.0f} ₸\n"
    text += f"⏰ <b>Время:</b> {_e(order['delivery_time'])}\n"
    text += f"💳 <b>Оплата:</b> {PAYMENT_METHODS.get(order['payment_method'], order['payment_method'])}\n"
    if order.get("comment"):
        text += f"📝 <b>Комментарий:</b> {_e(order['comment'])}\n"
    text += f"\n📋 <b>Товары:</b>\n"
    for item in items:
        text += f"• {_e(item['name'])} — {item['quantity']} шт.\n"
    if order.get("delivery_photo_file_id"):
        text += f"\n📸 <i>Фото доставки прикреплено</i>"
    elif order.get("delivery_proof_text"):
        text += f"\n📝 <i>Доставка: {_e(order['delivery_proof_text'])}</i>"
    return text


async def refresh_cart_view(callback, lang):
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    items = await get_cart_items(user["id"])
    total = await get_cart_total(user["id"])
    if not items:
        await callback.message.edit_text(
            t(lang, "cart_empty"),
            reply_markup=empty_cart_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            format_cart(items, total, lang),
            reply_markup=cart_keyboard(items, lang),
            parse_mode="HTML",
        )


# ============================================================
#   /start, язык, главное меню, профиль (без рефералки)
# ============================================================


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Если это курьер (и не админ) — сразу в курьерское меню
    if getattr(message.from_user, "id", None) != ADMIN_ID and await _is_courier(
        message.from_user.id
    ):
        await state.clear()
        await message.answer(
            "🚚 <b>Меню курьера</b>\n\n"
            "Здесь твои активные заказы и статистика за сегодня.",
            reply_markup=courier_main_kb(),
            parse_mode="HTML",
        )
        return
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    await state.update_data(last_category_id=None)
    lang = user.get("language") or "ru"
    if user.get("language"):
        await message.answer(
            t(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
        )
        return
    await message.answer(
        t("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    lang = args[0]
    await update_user_language(callback.from_user.id, lang)
    await callback.message.edit_text(t(lang, "language_changed"), parse_mode="HTML")
    await callback.message.answer(
        t(lang, "welcome"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "language")
async def process_change_language(callback: CallbackQuery):
    await callback.message.edit_text(
        t("ru", "choose_language"), reply_markup=language_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def process_main_menu(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    await callback.message.edit_text(
        t(lang, "main_menu"), reply_markup=main_menu_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "profile")
async def process_profile(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    text = t(
        lang,
        "profile",
        address=user["address"] or t(lang, "no_address"),
        phone=user["phone"] or t(lang, "no_phone"),
    )
    await callback.message.edit_text(
        text, reply_markup=profile_keyboard(lang), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "edit_address")
async def process_edit_address(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(t(lang, "enter_address"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_address)
    await callback.answer()


@router.message(ProfileState.waiting_address)
async def process_new_address(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    address = message.text.strip()
    if not validate_address(address):
        await message.answer(
            "❌ Адрес слишком короткий (минимум 5 символов)", parse_mode="HTML"
        )
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], address=address)
    await message.answer(
        t(lang, "address_updated"),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "edit_phone")
async def process_edit_phone(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(t(lang, "phone"), parse_mode="HTML")
    await state.set_state(ProfileState.waiting_phone)
    await callback.answer()


@router.message(ProfileState.waiting_phone)
async def process_new_phone(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Введите телефон (минимум 10 цифр).\n"
            "Примеры: +7 707 123 45 67, 87071234567, 7071234567",
            parse_mode="HTML",
        )
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    await update_user_profile(user["id"], phone=phone)
    await message.answer(
        t(lang, "phone_updated"),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await state.clear()


# ============================================================
#   Каталог и корзина
# ============================================================


@router.callback_query(F.data == "catalog")
async def process_catalog(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(last_category_id=None)
    cats = await get_categories()
    await callback.message.edit_text(
        t(lang, "catalog"),
        reply_markup=categories_keyboard(cats, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("category_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    await state.update_data(last_category_id=cat_id)
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer(t(lang, "error_category_empty"), show_alert=True)
        return
    await callback.message.edit_text(
        t(lang, "choose_product"),
        reply_markup=products_keyboard(products, cat_id, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product_"))
async def process_product(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    product = await get_product(pid)
    if not product:
        await callback.answer(t(lang, "error_product_not_found"), show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"]) if user else []
    in_cart = any(i["product_id"] == pid for i in items)
    text = t(
        lang, "product_detail", emoji="", name=product["name"], price=product["price"]
    )
    if product["description"]:
        text += "\n" + t(lang, "description", desc=product["description"])
    kb = product_detail_keyboard(pid, in_cart, lang)
    if product.get("photo_file_id"):
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product["photo_file_id"],
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await resend(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "back_to_products")
async def process_back_to_products(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    cat_id = data.get("last_category_id")
    if cat_id:
        products = await get_products_by_category(cat_id)
        if products:
            await resend(
                callback.message,
                t(lang, "choose_product"),
                reply_markup=products_keyboard(products, cat_id, lang),
                parse_mode="HTML",
            )
            await callback.answer()
            return
    cats = await get_categories()
    await resend(
        callback.message,
        t(lang, "catalog"),
        reply_markup=categories_keyboard(cats, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_to_cart_"))
async def process_add_to_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    await add_to_cart(user["id"], pid, 1)
    total = await get_cart_total(user["id"])
    await callback.answer(t(lang, "added_to_cart"))
    product = await get_product(pid)
    text = t(
        lang, "product_detail", emoji="", name=product["name"], price=product["price"]
    )
    text += "\n" + t(lang, "added_to_cart") + "\n"
    text += t(lang, "in_cart_total", total=total)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t(lang, "go_to_cart"), callback_data="cart"))
    b.row(
        InlineKeyboardButton(
            text=t(lang, "add_more"), callback_data=f"add_to_cart_{pid}"
        )
    )
    b.row(
        InlineKeyboardButton(
            text=t(lang, "back_to_products"), callback_data="back_to_products"
        )
    )
    await resend(callback.message, text, reply_markup=b.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "cart")
async def process_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_plus_"))
async def process_cart_plus(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cid = _safe_int(args[0])
    if cid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    for item in items:
        if item["id"] == cid:
            from database import update_cart_quantity

            await update_cart_quantity(cid, item["quantity"] + 1)
            break
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_minus_"))
async def process_cart_minus(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cid = _safe_int(args[0])
    if cid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    for item in items:
        if item["id"] == cid:
            from database import update_cart_quantity

            await update_cart_quantity(cid, item["quantity"] - 1)
            break
    await refresh_cart_view(callback, lang)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def process_clear_cart(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    await clear_cart(user["id"])
    await callback.message.edit_text(
        t(lang, "cart_cleared"),
        reply_markup=empty_cart_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer(t(lang, "cart_cleared"))


# ============================================================
#   Оформление заказа — с подтверждением адреса и телефона
# ============================================================


@router.callback_query(F.data == "checkout")
async def process_checkout(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    if not is_working():
        await callback.message.edit_text(
            t(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    items = await get_cart_items(user["id"])
    if not items:
        await callback.answer(t(lang, "error_empty_cart"), show_alert=True)
        return
    total = await get_cart_total(user["id"])
    await state.update_data(
        user_id=user["id"],
        phone=user["phone"],
        address=user["address"],
        cart_total=total,
    )
    if user["address"]:
        await callback.message.edit_text(
            t(lang, "address", address=user["address"]),
            reply_markup=address_keyboard(has_address=True, lang=lang),
            parse_mode="HTML",
        )
    else:
        # Нет сохранённого адреса — сразу показываем выбор корпуса (без свободного ввода текста).
        await callback.message.edit_text(
            t(lang, "pick_building"),
            reply_markup=buildings_kb(),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.callback_query(F.data == "use_saved_address")
async def process_use_saved_address(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    saved_address = data.get("address")
    # Показываем сохранённый адрес и просим подтвердить
    await callback.message.edit_text(
        t(lang, "confirm_address_prompt", address=saved_address),
        reply_markup=confirm_input_keyboard(
            lang, confirm_cb="confirm_address_yes", change_cb="change_address"
        ),
        parse_mode="HTML",
    )
    await state.update_data(delivery_address=saved_address)
    await state.set_state(CheckoutState.confirm_address)
    await callback.answer()


@router.callback_query(F.data == "enter_new_address")
async def process_enter_new_address(callback: CallbackQuery, state: FSMContext):
    """«Ввести новый адрес» — теперь это выбор корпуса из списка, без свободного ввода текста."""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "pick_building"),
        reply_markup=buildings_kb(),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


# ==================== Выбор корпуса и пэтера ====================


@router.callback_query(F.data == "noop")
async def process_noop(callback: CallbackQuery):
    """Заглушка для кнопок-индикаторов ('1/2')."""
    await callback.answer()


@router.callback_query(F.data.startswith("bld_"), CheckoutState.waiting_address)
async def process_pick_building(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал корпус — показываем пэтеры."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    building_id = _safe_int(args[0])
    building = find_building(building_id) if building_id else None
    if not building:
        await callback.answer("❌ Неизвестный корпус", show_alert=True)
        return
    await state.update_data(delivery_building_id=building_id)
    await callback.message.edit_text(
        t(lang, "pick_apartment", name=building["name"]),
        reply_markup=building_apartments_kb(building_id, page=0),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aptp_"), CheckoutState.waiting_address)
async def process_apt_page(callback: CallbackQuery, state: FSMContext):
    """Пагинация в списке пэтеров выбранного корпуса."""
    _, args = parse_cb(callback.data)
    building_id = _safe_int(args[0])
    page = _safe_int(args[1], default=0) or 0
    if not building_id or not find_building(building_id):
        await callback.answer("❌ Ошибка: корпус не найден", show_alert=True)
        return
    await state.update_data(delivery_building_id=building_id)
    await callback.message.edit_reply_markup(
        reply_markup=building_apartments_kb(building_id, page=page)
    )
    await callback.answer()


@router.callback_query(F.data == "aptb_back", CheckoutState.waiting_address)
async def process_back_to_buildings(callback: CallbackQuery, state: FSMContext):
    """Назад из пэтеров к списку корпусов."""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "pick_building"),
        reply_markup=buildings_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("apt_"), CheckoutState.waiting_address)
async def process_pick_apt(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал пэтер — автособираем адрес и просим подтвердить."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    building_id = _safe_int(args[0])
    apt = _safe_int(args[1])
    if not building_id or apt is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    building = find_building(building_id)
    if not building:
        await callback.answer("❌ Корпус не найден", show_alert=True)
        return
    if not (building["min_apt"] <= apt <= building["max_apt"]):
        await callback.answer("❌ Некорректный номер пэтера", show_alert=True)
        return
    full_address = format_building_address(building_id, apt)
    await state.update_data(
        delivery_building_id=building_id,
        delivery_apt=apt,
        delivery_address=full_address,
    )
    await callback.message.edit_text(
        t(lang, "confirm_address_prompt", address=full_address),
        reply_markup=confirm_input_keyboard(
            lang, confirm_cb="confirm_address_yes", change_cb="change_address"
        ),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.confirm_address)
    await callback.answer()


@router.callback_query(F.data == "use_saved_phone")
async def process_use_saved_phone(callback: CallbackQuery, state: FSMContext):
    """Юзер нажал «Использовать сохранённый телефон» — показываем подтверждение."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    saved_phone = data.get("phone")
    if not saved_phone:
        await callback.answer("Телефон не сохранён", show_alert=True)
        return
    await state.update_data(delivery_phone=saved_phone)
    await callback.message.edit_text(
        t(lang, "confirm_phone_prompt", phone=saved_phone),
        reply_markup=confirm_input_keyboard(
            lang, confirm_cb="confirm_phone_yes", change_cb="change_phone"
        ),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.confirm_phone)
    await callback.answer()


@router.callback_query(F.data == "enter_new_phone")
async def process_enter_new_phone(callback: CallbackQuery, state: FSMContext):
    """Юзер хочет ввести новый телефон."""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(t(lang, "phone"), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_phone)
    await callback.answer()


@router.message(CheckoutState.waiting_address)
async def process_address_ignore_text(message: Message, state: FSMContext):
    """Свободный ввод адреса больше не нужен — клиент выбирает корпус + пэтер кнопками.
    Если всё-таки прислали текст, мягко напоминаем про кнопки."""
    lang = await get_user_language(message.from_user.id)
    data = await state.get_data()
    # Если уже был выбран корпус — показываем его пэтеры
    if data.get("delivery_building_id"):
        await message.answer(
            t(lang, "pick_apartment", name=""),
            reply_markup=building_apartments_kb(data["delivery_building_id"], page=0),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            t(lang, "pick_building"),
            reply_markup=buildings_kb(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "change_address", CheckoutState.confirm_address)
async def process_change_address(callback: CallbackQuery, state: FSMContext):
    """«Изменить» — возвращаем к выбору корпуса."""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "pick_building"),
        reply_markup=buildings_kb(),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_address)
    await callback.answer()


@router.callback_query(F.data == "confirm_address_yes", CheckoutState.confirm_address)
async def process_confirm_address(callback: CallbackQuery, state: FSMContext):
    """Адрес подтверждён — идём к телефону (или дальше, если телефон уже был)."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    # Сохраняем адрес в профиль пользователя
    delivery_address = data.get("delivery_address")
    user_id = data.get("user_id")
    if not delivery_address or not user_id:
        # Защита: потеряли state (рестарт с MemoryStorage и т.п.)
        logger.warning(
            "process_confirm_address: missing state data keys, data=%s", data
        )
        await state.set_state(CheckoutState.waiting_address)
        await callback.message.edit_text(t(lang, "enter_address"), parse_mode="HTML")
        await callback.answer()
        return
    await update_user_profile(user_id, address=delivery_address)
    phone = data.get("phone")
    if phone:
        # Телефон уже есть — сразу показываем его для подтверждения.
        # Сохраняем в state под тем же ключом, что и при ручном вводе,
        # чтобы process_confirm_phone смог его прочитать.
        await state.update_data(delivery_phone=phone)
        await callback.message.edit_text(
            t(lang, "confirm_phone_prompt", phone=phone),
            reply_markup=confirm_input_keyboard(
                lang, confirm_cb="confirm_phone_yes", change_cb="change_phone"
            ),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.confirm_phone)
    else:
        await callback.message.edit_text(
            t(lang, "phone"),
            reply_markup=phone_keyboard(has_phone=False, lang=lang),
            parse_mode="HTML",
        )
        await state.set_state(CheckoutState.waiting_phone)
    await callback.answer()


@router.message(CheckoutState.waiting_phone)
async def process_phone_input(message: Message, state: FSMContext):
    """Приняли ввод телефона — просим подтвердить."""
    lang = await get_user_language(message.from_user.id)
    phone = message.text.strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Введите телефон (минимум 10 цифр).\n"
            "Примеры: +7 707 123 45 67, 87071234567, 7071234567",
            parse_mode="HTML",
        )
        return
    await state.update_data(delivery_phone=phone)
    await message.answer(
        t(lang, "confirm_phone_prompt", phone=phone),
        reply_markup=confirm_input_keyboard(
            lang, confirm_cb="confirm_phone_yes", change_cb="change_phone"
        ),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.confirm_phone)


@router.callback_query(F.data == "change_phone", CheckoutState.confirm_phone)
async def process_change_phone(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(t(lang, "phone"), parse_mode="HTML")
    await state.set_state(CheckoutState.waiting_phone)
    await callback.answer()


@router.callback_query(F.data == "confirm_phone_yes", CheckoutState.confirm_phone)
async def process_confirm_phone(callback: CallbackQuery, state: FSMContext):
    """Телефон подтверждён — показываем выбор времени доставки."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    # Сохраняем телефон в профиль
    delivery_phone = data.get("delivery_phone")
    user_id = data.get("user_id")
    if not delivery_phone or not user_id:
        # Защита: потеряли state (рестарт с MemoryStorage и т.п.)
        logger.warning("process_confirm_phone: missing state data keys, data=%s", data)
        await state.set_state(CheckoutState.waiting_phone)
        await callback.message.edit_text(
            t(lang, "phone"),
            reply_markup=phone_keyboard(has_phone=False, lang=lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await update_user_profile(user_id, phone=delivery_phone)
    await callback.message.edit_text(
        t(lang, "delivery_time"),
        reply_markup=delivery_time_keyboard(lang),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_delivery_time)
    await callback.answer()


@router.callback_query(F.data.startswith("time_"), CheckoutState.waiting_delivery_time)
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    time_data = "_".join(args)
    if time_data == "late":
        await callback.answer("Выберите время на завтра", show_alert=True)
        return
    delivery_time = next_delivery_time() if time_data == "asap" else time_data
    await state.update_data(delivery_time=delivery_time)
    await callback.message.edit_text(
        t(lang, "payment"), reply_markup=payment_keyboard(lang), parse_mode="HTML"
    )
    await state.set_state(CheckoutState.waiting_payment)
    await callback.answer()


@router.callback_query(F.data.startswith("pay_"), CheckoutState.waiting_payment)
async def process_payment_selection(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    payment_method = args[0]
    await state.update_data(payment_method=payment_method)
    await callback.message.edit_text(
        t(lang, "comment"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "skip"), callback_data="skip_comment"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(CheckoutState.waiting_comment)
    await callback.answer()


@router.callback_query(F.data == "skip_comment", CheckoutState.waiting_comment)
async def process_skip_comment(callback: CallbackQuery, state: FSMContext):
    await state.update_data(comment="")
    await show_order_confirmation(callback.message, state)
    await callback.answer()


@router.message(CheckoutState.waiting_comment)
async def process_comment_input(message: Message, state: FSMContext):
    await state.update_data(comment=message.text.strip())
    await show_order_confirmation(message, state)


async def show_order_confirmation(target, state: FSMContext):
    """Финальный экран подтверждения заказа."""
    tg_id = target.from_user.id if hasattr(target, "from_user") else target.chat.id
    lang = await get_user_language(tg_id)
    data = await state.get_data()
    # Защита: если state потерялся, отправляем в начало чекаута
    required = (
        "user_id",
        "delivery_address",
        "delivery_phone",
        "delivery_time",
        "payment_method",
    )
    missing = [k for k in required if not data.get(k)]
    if missing:
        logger.warning(
            "show_order_confirmation: missing state keys %s, data=%s", missing, data
        )
        await state.clear()
        try:
            await target.answer(
                "⚠️ Сессия истекла. Откройте корзину и оформите заказ заново.",
                reply_markup=back_to_main_keyboard(lang),
            )
        except Exception:
            pass
        return
    items = await get_cart_items(data["user_id"])
    total = await get_cart_total(data["user_id"])
    final, fee, dtype = calc_delivery(total)
    await state.update_data(final_total=final, delivery_fee=fee)

    text = t(lang, "confirm_order") + "\n\n"
    text += t(lang, "confirm_address", address=data["delivery_address"]) + "\n"
    text += t(lang, "confirm_phone", phone=data["delivery_phone"]) + "\n"
    text += t(lang, "confirm_time", time=data["delivery_time"]) + "\n"
    text += (
        t(
            lang,
            "confirm_payment",
            payment=PAYMENT_METHODS.get(data["payment_method"], data["payment_method"]),
        )
        + "\n"
    )
    if data.get("comment"):
        text += t(lang, "confirm_comment", comment=data["comment"]) + "\n"
    text += "\n" + t(lang, "confirm_items") + "\n"
    for item in items:
        it = item["quantity"] * item["price"]
        text += (
            t(
                lang,
                "cart_item",
                name=item["name"],
                qty=item["quantity"],
                price=item["price"],
                total=it,
            )
            + "\n"
        )
    text += "\n" + t(lang, "cart_total", total=total)
    if dtype == "paid":
        text += "\n" + t(lang, "delivery_fee", fee=fee, min=MINIMUM_ORDER_AMOUNT)
    else:
        text += "\n" + t(lang, "free_delivery", min=MINIMUM_ORDER_AMOUNT)
    text += "\n" + t(lang, "confirm_total", total=final)
    await target.answer(
        text, reply_markup=confirm_order_keyboard(lang), parse_mode="HTML"
    )
    await state.set_state(CheckoutState.confirm_order)


# ============================================================
#   Подтверждение и оплата заказа
# ============================================================


@router.callback_query(F.data == "confirm_order", CheckoutState.confirm_order)
async def process_confirm_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Создаёт заказ. Для Kaspi — статус awaiting_payment и показ реквизитов.
    Для наличных — сразу processing."""
    lang = await get_user_language(callback.from_user.id)
    if not is_working():
        await callback.message.edit_text(
            t(lang, "closed", start=WORKING_HOURS_START, end=WORKING_HOURS_END),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    data = await state.get_data()
    # Защита: если state потерялся (рестарт MemoryStorage) — отправляем в начало чекаута
    required = (
        "user_id",
        "delivery_address",
        "delivery_phone",
        "delivery_time",
        "payment_method",
    )
    missing = [k for k in required if not data.get(k)]
    if missing:
        logger.warning(
            "process_confirm_order: missing state keys %s, data=%s", missing, data
        )
        await state.clear()
        await callback.message.edit_text(
            "⚠️ Сессия истекла. Начнём заново — откройте корзину и оформите заказ.",
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    user_id = data["user_id"]
    items = await get_cart_items(user_id)
    if not items:
        await callback.answer(t(lang, "error_empty_cart"), show_alert=True)
        return
    final = data.get("final_total", await get_cart_total(user_id))

    if data["payment_method"] == "kaspi":
        # Создаём заказ в статусе awaiting_payment
        order_id = await create_order(
            user_id=user_id,
            total_amount=final,
            delivery_time=data["delivery_time"],
            payment_method=data["payment_method"],
            comment=data.get("comment", ""),
            address=data["delivery_address"],
            phone=data["delivery_phone"],
            status="awaiting_payment",
        )
        await add_order_items(
            order_id,
            [
                {
                    "product_id": i["product_id"],
                    "quantity": i["quantity"],
                    "price": i["price"],
                }
                for i in items
            ],
        )
        await clear_cart(user_id)

        # Показываем пользователю что чек отправлен в Kaspi.
        # Кнопок у клиента нет — он просто оплачивает в Kaspi и ждёт.
        await callback.message.edit_text(
            t(lang, "order_awaiting_payment", id=order_id, total=final),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer(t(lang, "thank_you"))

        # Уведомляем админа с подсказкой отправить чек
        order = await get_order(order_id)
        oitems = await get_order_items(order_id)
        user_name = user_display_name(order, "Клиент")
        admin_text = format_admin_order(order, oitems, user_name)
        admin_text += (
            f"\n\n💳 <b>Действие:</b> отправьте чек на оплату через Kaspi-кабинет "
            f"на номер <code>{_e(order['phone'])}</code>.\n"
            f"Когда деньги поступят — нажмите «Оплата получена» ниже."
        )
        # Кнопка «Оплата получена» прямо здесь — админу не нужно идти в /admin
        b = InlineKeyboardBuilder()
        b.row(
            InlineKeyboardButton(
                text="💰 Оплата получена",
                callback_data=f"admin_confirm_pay_{order_id}",
            )
        )
        b.row(
            InlineKeyboardButton(
                text="❌ Отменить заказ",
                callback_data=f"admin_reject_pay_{order_id}",
            )
        )
        try:
            await bot.send_message(
                ADMIN_ID, admin_text, reply_markup=b.as_markup(), parse_mode="HTML"
            )
        except Exception as e:
            logger.error("admin notify failed: %s", e)

    else:
        # Наличные — сразу processing
        order_id = await create_order(
            user_id=user_id,
            total_amount=final,
            delivery_time=data["delivery_time"],
            payment_method=data["payment_method"],
            comment=data.get("comment", ""),
            address=data["delivery_address"],
            phone=data["delivery_phone"],
            status="processing",
        )
        await add_order_items(
            order_id,
            [
                {
                    "product_id": i["product_id"],
                    "quantity": i["quantity"],
                    "price": i["price"],
                }
                for i in items
            ],
        )
        await clear_cart(user_id)
        order = await get_order(order_id)
        oitems = await get_order_items(order_id)
        user_name = user_display_name(order, "Клиент")
        await callback.message.edit_text(
            t(lang, "order_accepted_cash", id=order_id, total=final),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer(t(lang, "thank_you"))
        try:
            await bot.send_message(
                ADMIN_ID,
                format_admin_order(order, oitems, user_name),
                reply_markup=admin_order_status_keyboard(order_id, "processing"),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("admin notify failed: %s", e)


# ============================================================
#   «Я оплатил» — пользователь подтверждает перевод Kaspi
# ============================================================
#   Админ: подтверждение/отклонение оплаты
# ============================================================


@router.callback_query(F.data.startswith("admin_confirm_pay_"), IsAdmin())
async def process_admin_confirm_payment(callback: CallbackQuery, bot: Bot):
    _, args = parse_cb(callback.data)
    order_id = _safe_int(args[0])
    if order_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    order = await get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await set_order_payment_confirmed(order_id)
    await update_order_status(order_id, "processing")
    order = await get_order(order_id)
    items = await get_order_items(order_id)
    user_name = user_display_name(order, "Клиент")
    # Клиенту
    try:
        await bot.send_message(
            order["telegram_id"],
            t(
                await get_user_language(order["telegram_id"]),
                "payment_confirmed",
                id=order_id,
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("notify client failed: %s", e)
    # Админу — обновить карточку заказа
    await callback.message.edit_text(
        format_admin_order(order, items, user_name),
        reply_markup=admin_order_status_keyboard(order_id, "processing"),
        parse_mode="HTML",
    )
    await callback.answer("Оплата подтверждена")


@router.callback_query(F.data.startswith("admin_reject_pay_"), IsAdmin())
async def process_admin_reject_payment(callback: CallbackQuery, bot: Bot):
    _, args = parse_cb(callback.data)
    order_id = _safe_int(args[0])
    if order_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    order = await get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await update_order_status(order_id, "cancelled")
    # Возвращаем товар на склад
    items = await get_order_items(order_id)
    for item in items:


        # decrease_stock уменьшает — нам нужно обратно
        # проще: ручной update
        pass  # ниже
    # Возврат товара на склад
    from database import _db

    async with _db() as db:
        for item in items:
            await db.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (item["quantity"], item["product_id"]),
            )
        await db.commit()

    order = await get_order(order_id)
    user_name = user_display_name(order, "Клиент")
    try:
        await bot.send_message(
            order["telegram_id"],
            t(
                await get_user_language(order["telegram_id"]),
                "payment_rejected",
                id=order_id,
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("notify client failed: %s", e)
    await callback.message.edit_text(
        format_admin_order(order, items, user_name) + "\n\n❌ <b>Оплата отклонена</b>",
        reply_markup=admin_order_status_keyboard(order_id, "cancelled"),
        parse_mode="HTML",
    )
    await callback.answer("Заказ отменён")


# ============================================================
#   История заказов
# ============================================================


@router.callback_query(F.data == "history")
async def process_history(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    orders = await get_user_orders(user["id"], limit=10)
    if not orders:
        await callback.message.edit_text(
            t(lang, "no_orders"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        t(lang, "history_title"),
        reply_markup=history_orders_keyboard(orders, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("history_view_"))
async def process_history_view(callback: CallbackQuery):
    """Детальный просмотр заказа из истории — с кнопками повтора/отмены/отзыва.
    Один и тот же экран для всех заказов, кнопки появляются по контексту."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    # Раньше: get_order() + get_order_review() = 2 запроса.
    # Теперь: get_user_orders() сразу возвращает orders.* + review_id + review_rating
    # через LEFT JOIN — один запрос вместо двух. Юзер видит только свои заказы,
    # так что фильтруем по user_id и ищем нужный id в списке.
    user_orders = await get_user_orders(user["id"], limit=20)
    order = next((o for o in user_orders if o["id"] == oid), None)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await get_order_items(oid)
    user_name = order.get("first_name") or "Клиент"
    if order.get("last_name"):
        user_name += f" {order['last_name']}"
    status = ORDER_STATUSES.get(order["status"], order["status"])
    text = (
        f"📦 <b>Заказ #{order['id']}</b>\n\n"
        f"📊 <b>Статус:</b> {status}\n"
        f"💰 <b>Сумма:</b> {order['total_amount']:.0f} ₸\n"
        f"📍 <b>Адрес:</b> {_e(order.get('address'))}\n"
        f"📞 <b>Телефон:</b> <code>{_e(order.get('phone'))}</code>\n"
        f"⏰ <b>Время:</b> {_e(order.get('delivery_time'))}\n"
        f"💳 <b>Оплата:</b> {PAYMENT_METHODS.get(order.get('payment_method', ''), order.get('payment_method', '—'))}\n\n"
        f"📋 <b>Товары:</b>\n"
    )
    for item in items:
        # FIX: в БД поле price_at_moment, в некоторых местах кода — price
        item_price = item.get('price') or item.get('price_at_moment') or 0
        text += f"• {_e(item['name'])} — {item['quantity']} шт. × {float(item_price):.0f} ₸\n"
    text += f"\n🕐 {order['created_at']}"
    # order уже содержит review_id / review_rating из LEFT JOIN — history_order_detail_kb
    # сам решит, показывать «Оставить отзыв» или «Мой отзыв».
    await callback.message.edit_text(
        text,
        reply_markup=history_order_detail_kb(order, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("user_cancel_"))
async def process_user_cancel(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await cancel_order_user(oid, user["id"])
    if ok:
        await callback.message.edit_text(
            f"❌ <b>Заказ #{oid} отменён</b>", parse_mode="HTML"
        )
        await callback.answer("Заказ отменён")
    else:
        await callback.answer("❌ Нельзя отменить этот заказ", show_alert=True)


@router.callback_query(F.data.startswith("reorder_"))
async def process_reorder(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    ok = await reorder(oid, user["id"])
    if ok:
        await callback.answer(t(lang, "reorder_done", id=oid))
        await refresh_cart_view(callback, lang)
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


# ============================================================
#   Отзывы (Feature 1) — после доставки заказа
# ============================================================


def _render_stars(rating: int) -> str:
    return "⭐" * int(rating)


@router.callback_query(F.data.startswith("review_start_"))
async def process_review_start(callback: CallbackQuery, state: FSMContext):
    """Юзер нажал «Оставить отзыв» на доставленном заказе."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    order = await get_order(oid)
    if not order or not user or order["user_id"] != user["id"]:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["status"] != "delivered":
        await callback.answer(t(lang, "review_only_delivered"), show_alert=True)
        return
    existing = await get_order_review(oid)
    if existing:
        await callback.answer(t(lang, "review_already"), show_alert=True)
        return
    await state.set_state(ReviewState.waiting_rating)
    await state.update_data(review_order_id=oid)
    await callback.message.edit_text(
        t(lang, "review_prompt", id=oid),
        reply_markup=review_rating_keyboard(oid, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("review_rate_"), ReviewState.waiting_rating
)
async def process_review_rate(callback: CallbackQuery, state: FSMContext):
    """Юзер выбрал оценку 1–5 — спрашиваем комментарий."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    rating = _safe_int(args[1])
    if oid is None or rating is None or not (1 <= rating <= 5):
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    order = await get_order(oid)
    if not order or not user or order["user_id"] != user["id"]:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order["status"] != "delivered":
        await callback.answer(t(lang, "review_only_delivered"), show_alert=True)
        await state.clear()
        return
    if await get_order_review(oid):
        await callback.answer(t(lang, "review_already"), show_alert=True)
        await state.clear()
        return
    await state.update_data(review_rating=rating)
    await state.set_state(ReviewState.waiting_comment)
    await callback.message.edit_text(
        t(lang, "review_ask_text"),
        reply_markup=review_text_skip_keyboard(oid, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ReviewState.waiting_comment)
async def process_review_comment(message: Message, state: FSMContext):
    """Комментарий — сохраняем с рейтингом. Пустой текст тоже принимаем
    (на случай, если юзер просто хочет сохранить оценку без слов)."""
    lang = await get_user_language(message.from_user.id)
    data = await state.get_data()
    oid = data.get("review_order_id")
    rating = data.get("review_rating")
    if not oid or not rating:
        await state.clear()
        await message.answer(t(lang, "error_user_not_found"), parse_mode="HTML")
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer(t(lang, "error_user_not_found"), parse_mode="HTML")
        return
    comment = (message.text or "").strip()[:1000] or None
    saved = await save_review(oid, user["id"], int(rating), comment)
    await state.clear()
    if not saved:
        await message.answer(
            t(lang, "review_already"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        return
    stars = _render_stars(int(rating))
    await message.answer(
        t(lang, "review_thanks", stars=stars),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    # Админу — уведомление (без спама, текстом)
    try:
        order = await get_order(oid)
        u_name = user_display_name(user, "Клиент")
        admin_text = (
            f"⭐ <b>Новый отзыв на заказ #{oid}</b>\n\n"
            f"👤 {html.escape(u_name)}\n"
            f"⭐ Оценка: {stars}\n"
        )
        if comment:
            admin_text += f"💬 {html.escape(comment)}\n"
        await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        logger.error("notify admin about review failed: %s", e)


@router.callback_query(F.data.startswith("review_skip_"), ReviewState.waiting_comment)
async def process_review_skip(callback: CallbackQuery, state: FSMContext):
    """Пропуск комментария — сохраняем только оценку."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    oid = data.get("review_order_id")
    rating = data.get("review_rating")
    if not oid or not rating:
        await state.clear()
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await state.clear()
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    saved = await save_review(oid, user["id"], int(rating), None)
    await state.clear()
    if not saved:
        await callback.answer(t(lang, "review_already"), show_alert=True)
        await callback.message.edit_text(
            t(lang, "review_already"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        return
    stars = _render_stars(int(rating))
    await callback.message.edit_text(
        t(lang, "review_thanks", stars=stars),
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("review_view_"))
async def process_review_view(callback: CallbackQuery):
    """Показать отзыв, который юзер оставил на этот заказ."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    user = await get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer(t(lang, "error_user_not_found"), show_alert=True)
        return
    review = await get_order_review(oid)
    if not review:
        await callback.answer(t(lang, "review_already"), show_alert=True)
        return
    stars = _render_stars(review["rating"])
    comment = review["comment"] or t(lang, "review_no_comment")
    text = (
        f"📦 <b>Заказ #{oid}</b>\n\n"
        + t(
            lang,
            "review_user_text",
            rating=stars,
            comment=html.escape(comment),
        )
    )
    await callback.message.edit_text(
        text,
        reply_markup=back_to_main_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   Поддержка
# ============================================================


@router.callback_query(F.data == "support")
async def process_support(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "support_prompt"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "cancel"), callback_data="main_menu"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await state.set_state(SupportState.waiting_message)
    await callback.answer()


@router.message(SupportState.waiting_message)
async def process_support_message(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer(t(lang, "error_user_not_found"))
        await state.clear()
        return
    if not SUPPORT_GROUP_ID:
        await message.answer("❌ Служба поддержки не настроена.")
        await state.clear()
        return
    try:
        text = f"💬 <b>Сообщение от пользователя</b>\n"
        text += f"👤 {message.from_user.full_name} (ID: <code>{message.from_user.id}</code>)\n"
        if message.text:
            text += f"\n📝 {message.text}"
        elif message.caption:
            text += f"\n📝 {message.caption}"
        sent = await message.bot.send_message(SUPPORT_GROUP_ID, text, parse_mode="HTML")
        await save_support_message(
            user_id=user["id"],
            user_telegram_id=message.from_user.id,
            user_message_id=message.message_id,
            support_chat_id=SUPPORT_GROUP_ID,
            support_message_id=sent.message_id,
        )
        await message.answer(
            t(lang, "support_sent"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("support send failed: %s", e)
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")
    await state.clear()


@router.message(F.chat.id == SUPPORT_GROUP_ID, F.reply_to_message)
async def process_support_reply(message: Message):
    """Админ ответил на сообщение пользователя в группе поддержки
    (reply к сообщению бота) — бот пересылает ответ пользователю с кнопкой
    «Ответить», чтобы переписка стала тредом."""
    if not SUPPORT_GROUP_ID or message.from_user.id != ADMIN_ID:
        return
    record = await get_support_message_by_support_id(
        message.reply_to_message.message_id
    )
    if not record:
        return
    thread_id = record.get("thread_id") or record["id"]
    try:
        # Текст админа (может содержать фото с caption — приоритет caption)
        body = message.caption or message.text or ""
        sent_user_msg = await message.bot.send_message(
            record["user_telegram_id"],
            f"💬 <b>Ответ поддержки:</b>\n\n{body}",
            reply_markup=support_reply_keyboard(thread_id, await get_user_language(record["user_telegram_id"])),
            parse_mode="HTML",
        )
        # Сохраняем факт ответа поддержки в тред (для истории и админа)
        await save_support_message(
            user_id=record["user_id"],
            user_telegram_id=record["user_telegram_id"],
            user_message_id=sent_user_msg.message_id,
            support_chat_id=SUPPORT_GROUP_ID,
            support_message_id=message.message_id,
            direction="to_user",
            parent_id=record["id"],
            thread_id=thread_id,
        )
    except Exception as e:
        logger.error("support reply failed: %s", e)


@router.callback_query(F.data.startswith("support_reply_"))
async def process_support_reply_start(callback: CallbackQuery, state: FSMContext):
    """Юзер нажал «Ответить» под сообщением поддержки — переходим в режим
    ввода ответа. После отправки сообщение уйдёт в группу как часть треда."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    thread_id = _safe_int(args[0])
    if thread_id is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    await state.set_state(SupportReplyState.waiting_reply)
    await state.update_data(reply_thread_id=thread_id)
    await callback.message.answer(
        t(lang, "support_reply_prompt"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "cancel"), callback_data="main_menu"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SupportReplyState.waiting_reply)
async def process_support_reply_text(message: Message, state: FSMContext):
    """Ответ пользователя в тред — пересылаем в группу поддержки."""
    lang = await get_user_language(message.from_user.id)
    data = await state.get_data()
    thread_id = data.get("reply_thread_id")
    if not thread_id:
        await state.clear()
        await message.answer(
            t(lang, "support_thread_not_found"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
        return
    if not SUPPORT_GROUP_ID:
        await state.clear()
        await message.answer("❌ Поддержка не настроена")
        return
    user = await get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer(t(lang, "error_user_not_found"))
        return
    u_name = user_display_name(user, "Клиент")
    body_text = message.caption or message.text or ""
    if not body_text and not message.photo:
        await message.answer("❌ Отправьте текст или фото", parse_mode="HTML")
        return
    # Формируем заголовок и ссылку на тред для админа
    header = t(
        lang,
        "support_reply_to_group",
        name=u_name,
        tg_id=message.from_user.id,
        text="",
    ).rstrip()
    full_text = (
        f"{header}\n"
        f"<i>(тред #{thread_id})</i>\n\n"
        f"{html.escape(body_text or '—')}"
    )
    try:
        # Если есть фото — шлём фото с caption; иначе просто текст
        if message.photo:
            photo = message.photo[-1]
            sent = await message.bot.send_photo(
                SUPPORT_GROUP_ID,
                photo=photo.file_id,
                caption=full_text,
                parse_mode="HTML",
            )
        else:
            sent = await message.bot.send_message(
                SUPPORT_GROUP_ID, full_text, parse_mode="HTML"
            )
        # Сохраняем в тред
        await save_support_message(
            user_id=user["id"],
            user_telegram_id=message.from_user.id,
            user_message_id=message.message_id,
            support_chat_id=SUPPORT_GROUP_ID,
            support_message_id=sent.message_id,
            direction="to_support",
            parent_id=thread_id,
            thread_id=thread_id,
        )
        await state.clear()
        await message.answer(
            t(lang, "support_reply_sent"),
            reply_markup=back_to_main_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("support reply to group failed: %s", e)
        await state.clear()
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")


# ============================================================
#   Хелпер для админа
# ============================================================


def user_display_name(user, fallback="Клиент"):
    if not user:
        return fallback
    parts = [user.get("first_name"), user.get("last_name")]
    name = " ".join(p for p in parts if p).strip()
    return name or fallback


# ============================================================
#   АДМИН-ПАНЕЛЬ
# ============================================================


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message):
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_back", IsAdmin())
async def process_admin_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔧 <b>Панель администратора</b>\n\nВыберите раздел:",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_products", IsAdmin())
async def process_admin_products(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛠 <b>Управление товарами</b>\n\nВыберите действие:",
        reply_markup=admin_products_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# --- Чек-лист (стоп-лист) ---

@router.callback_query(F.data == "admin_stoplist", IsAdmin())
async def process_admin_stoplist(callback: CallbackQuery):
    """Корневой экран чек-листа: выбор категории."""
    cats = await get_categories(active_only=False)
    if not cats:
        await callback.message.edit_text(
            "🛒 <b>Чек-лист пуст</b>\n\nСначала добавьте категории и товары.",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🛒 <b>Чек-лист</b>\n\n"
        "Здесь можно временно скрывать товары из каталога (нет в наличии, "
        "не привозят). Исторические заказы остаются без изменений.\n\n"
        "Выберите категорию:",
        reply_markup=admin_stoplist_categories_kb(cats),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_stop_cat_"), IsAdmin())
async def process_admin_stop_cat(callback: CallbackQuery):
    """Товары категории в чек-листе с кнопками toggle."""
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("Ошибка: пустой идентификатор", show_alert=True)
        return
    category = await get_category(cat_id)
    products = await get_products_by_category_with_stopped(cat_id)
    if not products:
        await callback.answer("В этой категории пока нет товаров", show_alert=True)
        return
    stopped_count = sum(1 for p in products if p.get("is_stopped") == 1 and p.get("is_active") == 1)
    text = (
        f"🛒 <b>{_e(category['name'])}</b>\n\n"
        f"Всего товаров: <b>{len([p for p in products if p.get('is_active')==1])}</b>\n"
        f"В стоп-листе: <b>{stopped_count}</b>\n\n"
        f"🟢 — в продаже · 🔴 — временно недоступен\n"
        f"Нажмите на товар, чтобы переключить."
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_stoplist_products_kb(products),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_stop_toggle_"), IsAdmin())
async def process_admin_stop_toggle(callback: CallbackQuery):
    """Переключить товар: если в стоп-листе — вернуть в продажу, и наоборот."""
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("Ошибка: пустой идентификатор", show_alert=True)
        return
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    is_currently_stopped = product.get("is_stopped") == 1
    new_state = not is_currently_stopped
    ok = await set_product_stopped(pid, new_state)
    if not ok:
        await callback.answer("❌ Не удалось изменить статус", show_alert=True)
        return
    if new_state:
        text_action = f"🔴 <b>{_e(product['name'])}</b> добавлен в стоп-лист"
    else:
        text_action = f"🟢 <b>{_e(product['name'])}</b> возвращён в продажу"
    await callback.answer(text_action, show_alert=True)
    # Перерисовываем список товаров категории
    category_id = product["category_id"]
    category = await get_category(category_id)
    products = await get_products_by_category_with_stopped(category_id)
    stopped_count = sum(1 for p in products if p.get("is_stopped") == 1 and p.get("is_active") == 1)
    text = (
        f"🛒 <b>{_e(category['name'])}</b>\n\n"
        f"Всего товаров: <b>{len([p for p in products if p.get('is_active')==1])}</b>\n"
        f"В стоп-листе: <b>{stopped_count}</b>\n\n"
        f"🟢 — в продаже · 🔴 — временно недоступен\n"
        f"Нажмите на товар, чтобы переключить."
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_stoplist_products_kb(products),
        parse_mode="HTML",
    )


# --- Заказы ---


def _order_btn_text(order):
    user_name = order.get("first_name") or "Клиент"
    status_short = ORDER_STATUSES.get(order["status"], order["status"])
    text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
    if len(text) > 60:
        user_name = user_name[:10] + "…"
        text = f"📦 #{order['id']} • {order['total_amount']:.0f}₸ • {user_name} • {status_short}"
    return text


@router.callback_query(F.data == "admin_orders", IsAdmin())
async def process_admin_all_orders(callback: CallbackQuery):
    orders = await get_all_orders(limit=50)
    if not orders:
        await callback.message.edit_text(
            "📋 <b>Заказов пока нет</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for o in orders:
        b.row(
            InlineKeyboardButton(
                text=_order_btn_text(o), callback_data=f"admin_view_{o['id']}"
            )
        )
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await callback.message.edit_text(
        "📋 <b>Все заказы</b>\n\n<i>Нажмите на заказ для управления.</i>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_orders_"), IsAdmin())
async def process_admin_orders_by_status(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    status = args[0]
    orders = await get_all_orders(status=status, limit=50)
    if not orders:
        await callback.message.edit_text(
            f"📋 <b>Нет заказов со статусом '{ORDER_STATUSES.get(status, status)}'</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for o in orders:
        user_name = o.get("first_name") or "Клиент"
        created = o["created_at"][:16] if o.get("created_at") else ""
        text = f"📦 #{o['id']} • {o['total_amount']:.0f}₸ • {user_name} • {created}"
        if len(text) > 60:
            user_name = user_name[:10] + "…"
            text = f"📦 #{o['id']} • {o['total_amount']:.0f}₸ • {user_name} • {created}"
        b.row(InlineKeyboardButton(text=text, callback_data=f"admin_view_{o['id']}"))
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await callback.message.edit_text(
        f"📋 <b>Заказы: {ORDER_STATUSES.get(status, status)}</b>\n\n"
        "<i>Нажмите на заказ для управления.</i>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_"), IsAdmin())
async def process_admin_view_order(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    order = await get_order(oid)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    items = await get_order_items(oid)
    user_name = user_display_name(order, "Клиент")
    await callback.message.edit_text(
        format_admin_order(order, items, user_name),
        reply_markup=admin_order_status_keyboard(oid, order["status"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_status_"), IsAdmin())
async def process_admin_change_status(callback: CallbackQuery, bot: Bot):
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    new_status = args[1]
    order = await get_order(oid)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if new_status == "delivered":
        # Админ вручную закрывает заказ (без фото — фото присылает курьер).
        await update_order_status(oid, "delivered")
        order = await get_order(oid)
        items = await get_order_items(oid)
        user_name = user_display_name(order, "Клиент")
        try:
            await bot.send_message(
                order["telegram_id"],
                f"✅ <b>Заказ #{oid}</b>\n\nВаш заказ доставлен! Спасибо за покупку 🙌",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("notify client about delivery failed: %s", e)
        await safe_edit(
            callback.message,
            format_admin_order(order, items, user_name),
            reply_markup=admin_order_status_keyboard(oid, "delivered"),
        )
        await callback.answer("✅ Заказ закрыт")
        return

    if new_status == "sent":
        # Перед отправкой — обязательно выбираем курьера
        await state_set_admin_pick_courier(callback, bot, oid, order)
        return

    # Остальные статусы — обновляем как раньше
    await update_order_status(oid, new_status)
    order = await get_order(oid)
    items = await get_order_items(oid)
    user_name = user_display_name(order, "Клиент")

    status_messages = {
        "processing": f"📦 <b>Заказ #{oid}</b>\n\nВаш заказ принят в работу!",
        "sent": f"🚚 <b>Заказ #{oid}</b>\n\nВаш заказ отправлен курьером!",
    }
    if new_status in status_messages:
        try:
            await bot.send_message(
                order["telegram_id"], status_messages[new_status], parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.message.edit_text(
        format_admin_order(order, items, user_name),
        reply_markup=admin_order_status_keyboard(oid, new_status),
        parse_mode="HTML",
    )
    await callback.answer(f"Статус: {ORDER_STATUSES.get(new_status, new_status)}")


async def state_set_courier_delivery(bot, courier_tg_id, order_id):
    """Ставим state 'waiting_proof' в чат курьера (НЕ админа),
    чтобы хендлер process_delivery_proof сработал именно у курьера."""
    state = FSMContext(
        storage=_FSM_STORAGE,
        key=StorageKey(
            bot_id=bot.id,
            chat_id=courier_tg_id,
            user_id=courier_tg_id,
        ),
    )
    await state.update_data(delivery_order_id=order_id)
    await state.set_state(AdminDeliveryState.waiting_proof)


@router.callback_query(F.data.startswith("courier_delivered_"), IsCourier())
async def process_courier_delivered_btn(callback: CallbackQuery, state: FSMContext):
    """Курьер нажал 'Я доставил' — ставим waiting_proof в его чат."""
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    order = await get_order(oid)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order.get("courier_telegram_id") != callback.from_user.id:
        await callback.answer("Вы не назначены на этот заказ", show_alert=True)
        return
    if order["status"] not in ("sent", "processing"):
        await callback.answer(
            f"Заказ уже в статусе: {ORDER_STATUSES.get(order['status'], order['status'])}",
            show_alert=True,
        )
        return
    await state.set_state(AdminDeliveryState.waiting_proof)
    await state.update_data(delivery_order_id=oid)
    await callback.message.edit_text(
        f"📸 <b>Заказ #{oid}</b>\n\n"
        f"Отправьте <b>фото</b> подтверждения доставки.\n"
        f"Или напишите текстом — например, «оставлено у двери».",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminDeliveryState.waiting_proof)
async def process_delivery_proof(message: Message, state: FSMContext):
    """Курьер прислал фото или текст — сохраняем, переводим заказ в 'delivered',
    уведомляем клиента и админа."""
    data = await state.get_data()
    order_id = data.get("delivery_order_id")
    if not order_id:
        await state.clear()
        return
    order = await get_order(order_id)
    if not order:
        await message.answer("❌ Заказ не найден")
        await state.clear()
        return
    # Проверяем, что отправитель — действительно курьер этого заказа.
    if order.get("courier_telegram_id") != message.from_user.id:
        await message.answer(
            "❌ Вы не назначены курьером на этот заказ. Обратитесь к администратору."
        )
        await state.clear()
        return

    courier_name = order.get("courier_name") or "Курьер"
    user_lang = await get_user_language(order["telegram_id"])

    photo_file_id: str | None = None
    proof_text: str | None = None
    if message.photo:
        photo = message.photo[-1]
        photo_file_id = photo.file_id
        await set_order_delivery_photo(order_id, photo_file_id)
    else:
        # Текст — оставлено у двери и т.п.
        proof_text = (message.text or "").strip() or None
        await set_order_delivery_photo(order_id, None, text=proof_text)

    # Закрываем заказ
    await update_order_status(order_id, "delivered")
    order = await get_order(order_id)
    items = await get_order_items(order_id)

    # Клиенту — сначала текстовое уведомление, ПОТОМ фото отдельным сообщением
    # (раньше фото отправлялось с caption=... — получалось слитно с уведомлением о доставке)
    try:
        await message.bot.send_message(
            order["telegram_id"],
            t(user_lang, "delivery_notification_user_text", id=order_id),
            parse_mode="HTML",
        )
        if photo_file_id:
            # Фото — отдельное сообщение с короткой подписью
            await message.bot.send_photo(
                order["telegram_id"],
                photo=photo_file_id,
                caption=t(user_lang, "delivery_photo_caption", id=order_id),
                parse_mode="HTML",
            )
        # FEATURE 1: после доставки — предложение оставить отзыв (с кнопками-звёздами).
        # Не отправляем второй раз, если отзыв уже есть (защита от дублей).
        if not await get_order_review(order_id):
            await message.bot.send_message(
                order["telegram_id"],
                t(user_lang, "review_prompt", id=order_id),
                reply_markup=review_rating_keyboard(order_id, user_lang),
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error("send delivery notification to client failed: %s", e)

    # Курьеру — короткое подтверждение
    try:
        await message.answer(
            f"✅ <b>Заказ #{order_id} закрыт</b>\n\n"
            f"Спасибо! Статус обновлён, клиент уведомлён.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Админу — уведомление с кнопкой «Посмотреть фото»
    try:
        await _notify_admin_delivery_done(
            message.bot, order, items, courier_name, photo_file_id, proof_text
        )
    except Exception as e:
        logger.error("notify admin about delivery failed: %s", e)

    await state.clear()


async def _notify_admin_delivery_done(
    bot, order, items, courier_name, photo_file_id, proof_text
):
    """Шлёт админу уведомление о завершении доставки + кнопку «Посмотреть фото»."""
    user_name = order.get("first_name") or "Клиент"
    if order.get("last_name"):
        user_name += f" {order['last_name']}"
    text = (
        f"✅ <b>Заказ #{order['id']} доставлен</b>\n\n"
        f"👤 Клиент: {html.escape(user_name)}\n"
        f"🚚 Курьер: {html.escape(courier_name)}\n"
        f"📍 Адрес: {html.escape(order.get('address') or '—')}\n"
        f"💰 Сумма: {order.get('total_amount', 0):.0f} ₸\n"
    )
    if proof_text:
        text += f"\n💬 <b>Комментарий курьера:</b> {html.escape(proof_text)}"

    kb = None
    if photo_file_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📸 Посмотреть фото",
                        callback_data=f"courier_view_photo_{order['id']}",
                    )
                ]
            ]
        )

    await bot.send_message(ADMIN_ID, text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("courier_view_photo_"), IsAdmin())
async def process_courier_view_photo(callback: CallbackQuery, bot: Bot):
    """Админ нажал 'Посмотреть фото' — присылаем фото ему в личку."""
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    order = await get_order(oid)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if not order.get("delivery_photo_file_id"):
        await callback.answer(
            "Фото нет — курьер оставил текстовое подтверждение", show_alert=True
        )
        return
    try:
        await bot.send_photo(
            callback.from_user.id,
            photo=order["delivery_photo_file_id"],
            caption=f"📸 Фото доставки заказа #{oid}",
        )
        await callback.answer("Фото отправлено в личку", show_alert=False)
    except Exception as e:
        logger.error("send photo to admin failed: %s", e)
        await callback.answer("⚠️ Не удалось отправить фото", show_alert=True)


# ==================== Меню курьера ====================


@router.callback_query(F.data == "c_menu", IsCourier())
async def process_courier_menu(callback: CallbackQuery, state: FSMContext):
    """Главное меню курьера."""
    await state.clear()
    orders = await get_courier_orders(callback.from_user.id)
    today = await get_courier_delivered_today(callback.from_user.id)
    text = (
        "🚚 <b>Меню курьера</b>\n\n"
        f"📦 Активных заказов: <b>{len(orders)}</b>\n"
        f"✅ Доставлено сегодня: <b>{len(today)}</b>"
    )
    await safe_edit(callback.message, text, reply_markup=courier_main_kb())
    await callback.answer()


@router.callback_query(F.data == "c_orders", IsCourier())
async def process_courier_orders(callback: CallbackQuery):
    """Список активных заказов курьера."""
    orders = await get_courier_orders(callback.from_user.id)
    if not orders:
        await safe_edit(
            callback.message,
            "📦 <b>Мои заказы</b>\n\n"
            "Активных заказов нет — жди, когда админ назначит тебе новый.",
            reply_markup=courier_main_kb(),
        )
        await callback.answer()
        return
    lines = [f"📦 <b>Мои заказы</b> ({len(orders)})\n"]
    for o in orders:
        status = ORDER_STATUSES.get(o["status"], o["status"])
        lines.append(
            f"• #{o['id']} — {status}\n"
            f"   📍 {html.escape(o.get('address') or '—')}\n"
            f"   🕐 {html.escape(o.get('delivery_time') or '—')}\n"
            f"   💰 {o.get('total_amount', 0):.0f} ₸"
        )
    await safe_edit(
        callback.message,
        "\n".join(lines),
        reply_markup=courier_orders_kb(orders),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("c_order_"), IsCourier())
async def process_courier_order_detail(callback: CallbackQuery):
    """Детали конкретного заказа + кнопка «Я доставил»."""
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    if oid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    order = await get_order(oid)
    if not order or order.get("courier_telegram_id") != callback.from_user.id:
        await callback.answer("Заказ не найден или не ваш", show_alert=True)
        return
    if order["status"] not in ("sent", "processing"):
        await callback.answer(
            f"Заказ уже в статусе: {ORDER_STATUSES.get(order['status'], order['status'])}",
            show_alert=True,
        )
        return
    user_name = order.get("first_name") or "Клиент"
    if order.get("last_name"):
        user_name += f" {order['last_name']}"
    text = (
        f"📦 <b>Заказ #{order['id']}</b>\n\n"
        f"👤 Клиент: {html.escape(user_name)}\n"
        f"📞 Телефон: {html.escape(order.get('phone') or '—')}\n"
        f"📍 Адрес: {html.escape(order.get('address') or '—')}\n"
        f"🕐 Время: {html.escape(order.get('delivery_time') or '—')}\n"
        f"💳 Оплата: {PAYMENT_METHODS.get(order.get('payment_method', ''), '—')}\n"
        f"💰 Сумма: {order.get('total_amount', 0):.0f} ₸\n"
    )
    if order.get("comment"):
        text += f"💬 {html.escape(order['comment'])}\n"
    text += "\n📦 <b>Состав:</b>\n"
    items = await get_order_items(oid)
    for it in items:
        qty = it.get("quantity", 0)
        price = it.get("price") or it.get("price_at_moment") or 0
        text += f"  • {html.escape(it['name'])} × {qty}\n"
    text += f"\nКогда доставите — нажмите «✅ Я доставил»."
    await safe_edit(callback.message, text, reply_markup=courier_order_actions_kb(oid))
    await callback.answer()


@router.callback_query(F.data == "c_today", IsCourier())
async def process_courier_today(callback: CallbackQuery):
    """Заказы, доставленные курьером сегодня."""
    orders = await get_courier_delivered_today(callback.from_user.id)
    if not orders:
        await safe_edit(
            callback.message,
            "✅ <b>Сегодня доставлено</b>\n\nПока пусто.",
            reply_markup=courier_main_kb(),
        )
        await callback.answer()
        return
    total = sum(o.get("total_amount", 0) for o in orders)
    lines = [
        f"✅ <b>Сегодня доставлено</b> ({len(orders)})\n",
        f"💰 Общая сумма: <b>{total:.0f} ₸</b>\n",
    ]
    for o in orders:
        lines.append(
            f"• #{o['id']} — {o.get('total_amount', 0):.0f} ₸ — "
            f"{html.escape(o.get('address') or '—')}"
        )
    await safe_edit(callback.message, "\n".join(lines), reply_markup=courier_main_kb())
    await callback.answer()


@router.callback_query(F.data == "c_help", IsCourier())
async def process_courier_help(callback: CallbackQuery):
    """Краткая справка по работе курьера."""
    text = (
        "❓ <b>Помощь курьеру</b>\n\n"
        "1. Тебе придёт сообщение о новом заказе — с адресом, временем и составом.\n"
        "2. Открой <b>«📦 Мои заказы»</b> чтобы посмотреть все активные.\n"
        "3. Когда доставишь — открой заказ, нажми <b>«✅ Я доставил»</b>.\n"
        "4. Бот попросит фото или текст («оставлено у двери»).\n"
        "5. После этого заказ закрывается, клиент и админ получают уведомление.\n\n"
        "❓ Если что-то не работает — пиши админу."
    )
    await safe_edit(callback.message, text, reply_markup=courier_main_kb())
    await callback.answer()


# --- Статистика ---


@router.callback_query(F.data == "admin_stats", IsAdmin())
async def process_admin_stats(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📅 За сегодня", callback_data="admin_stats_day"))
    b.row(InlineKeyboardButton(text="📅 За неделю", callback_data="admin_stats_week"))
    b.row(InlineKeyboardButton(text="◀️ В админ-панель", callback_data="admin_back"))
    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\nВыберите период:",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


async def _stats_text(period):
    if period == "day":
        stats = await get_stats_day()
    else:
        stats = await get_stats_week()
    top = await get_top_products(period, 3)
    label = "сегодня" if period == "day" else "неделю"
    text = f"📊 <b>Статистика за {label}</b>\n\n"
    text += f"📦 Заказов: <b>{stats['orders']}</b>\n"
    text += f"💰 Выручка: <b>{stats['revenue']:.0f} ₸</b>\n"
    text += f"📈 Средний чек: <b>{stats['avg_check']:.0f} ₸</b>\n"
    text += f"❌ Отмен: <b>{stats['cancelled']}</b>\n\n"
    if top:
        text += "🔥 <b>Топ-3 товара:</b>\n"
        for i, p in enumerate(top, 1):
            text += f"{i}. {p['name']} — {p['qty']} шт. ({p['revenue']:.0f} ₸)\n"
    else:
        text += "🔥 Топ товаров пока нет."
    return text


@router.callback_query(F.data == "admin_stats_day", IsAdmin())
async def process_admin_stats_day(callback: CallbackQuery):
    text = await _stats_text("day")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await callback.message.edit_text(
        text, reply_markup=b.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_stats_week", IsAdmin())
async def process_admin_stats_week(callback: CallbackQuery):
    text = await _stats_text("week")
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_stats"))
    await callback.message.edit_text(
        text, reply_markup=b.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
#   ДОБАВЛЕНИЕ ТОВАРА (AdminAddProductState)
# ============================================================


@router.callback_query(F.data == "admin_add_product", IsAdmin())
async def process_admin_add_product(callback: CallbackQuery, state: FSMContext):
    cats = await get_categories()
    await callback.message.edit_text(
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(cats),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_category)
    await callback.answer()


@router.callback_query(
    F.data.startswith("admin_cat_"), IsAdmin(), AdminAddProductState.waiting_category
)
async def process_admin_select_category(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    await state.update_data(category_id=cat_id)
    await callback.message.edit_text(
        "✏️ <b>Введите название товара:</b>\n\nНапример: Молоко 3.2% 1л",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_name)
    await callback.answer()


@router.message(AdminAddProductState.waiting_name, IsAdmin())
async def process_admin_product_name(message: Message, state: FSMContext):
    await state.update_data(product_name=message.text.strip())
    await message.answer(
        "💰 <b>Введите цену товара (в тенге):</b>\n\nНапример: 890",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_price)


@router.message(AdminAddProductState.waiting_price, IsAdmin())
async def process_admin_product_price(message: Message, state: FSMContext):
    price = validate_price(message.text)
    if price is None:
        await message.answer(
            "❌ <b>Неверная цена!</b>\n\nВведите положительное число, например: 890",
            parse_mode="HTML",
        )
        return
    await state.update_data(product_price=price)
    await message.answer(
        "📝 <b>Введите описание товара:</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_desc_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_description)


@router.callback_query(
    F.data == "admin_skip_desc", IsAdmin(), AdminAddProductState.waiting_description
)
async def process_admin_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_description="")
    await callback.message.answer(
        "📸 <b>Отправьте фото товара</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_photo_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_image)
    await callback.answer()


@router.message(AdminAddProductState.waiting_description, IsAdmin())
async def process_admin_product_desc(message: Message, state: FSMContext):
    await state.update_data(product_description=message.text.strip())
    await message.answer(
        "📸 <b>Отправьте фото товара</b>\n\nИли нажмите 'Пропустить':",
        reply_markup=admin_skip_photo_keyboard(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddProductState.waiting_image)


@router.callback_query(
    F.data == "admin_skip_photo", IsAdmin(), AdminAddProductState.waiting_image
)
async def process_admin_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(product_image=None)
    await show_admin_product_preview(callback.message, state)
    await callback.answer()


@router.message(AdminAddProductState.waiting_image, IsAdmin())
async def process_admin_product_photo(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer(
            "❌ <b>Отправьте фото или нажмите 'Пропустить'</b>",
            reply_markup=admin_skip_photo_keyboard(),
            parse_mode="HTML",
        )
        return
    photo = message.photo[-1]
    await state.update_data(product_image=photo.file_id)
    await show_admin_product_preview(message, state)


async def show_admin_product_preview(target, state: FSMContext):
    data = await state.get_data()
    text = (
        f"📋 <b>Проверьте данные товара:</b>\n\n"
        f"📦 <b>Категория ID:</b> {data['category_id']}\n"
        f"🏷 <b>Название:</b> {data['product_name']}\n"
        f"💰 <b>Цена:</b> {data['product_price']:.0f} ₸\n"
        f"📝 <b>Описание:</b> {data.get('product_description', 'Нет') or 'Нет'}\n"
        f"📸 <b>Фото:</b> {'Есть' if data.get('product_image') else 'Нет'}\n"
    )
    await target.answer(
        text, reply_markup=admin_confirm_product_keyboard(), parse_mode="HTML"
    )
    await state.set_state(AdminAddProductState.confirm)


@router.callback_query(
    F.data == "admin_save_product", IsAdmin(), AdminAddProductState.confirm
)
async def process_admin_save_product(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = await add_product(
        category_id=data["category_id"],
        name=data["product_name"],
        price=data["product_price"],
        description=data.get("product_description") or None,
        photo_file_id=data.get("product_image") or None,
    )
    await callback.message.edit_text(
        f"✅ <b>Товар добавлен!</b>\n\nID: {pid}\nНазвание: {data['product_name']}\n"
        f"Цена: {data['product_price']:.0f} ₸",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer("Товар сохранён!")


@router.callback_query(
    F.data == "admin_change_product", IsAdmin(), AdminAddProductState.confirm
)
async def process_admin_change_product(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminAddProductState.waiting_category)
    cats = await get_categories()
    await callback.message.edit_text(
        "➕ <b>Добавление нового товара</b>\n\nВыберите категорию:",
        reply_markup=admin_categories_for_product_keyboard(cats),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   РЕДАКТИРОВАНИЕ ТОВАРА (AdminEditProductState)
# ============================================================


@router.callback_query(F.data == "admin_edit_product", IsAdmin())
async def process_admin_edit_product(callback: CallbackQuery):
    cats = await get_categories()
    b = InlineKeyboardBuilder()
    for cat in cats:
        b.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"admin_edit_cat_{cat['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))
    await callback.message.edit_text(
        "📝 <b>Выберите категорию для редактирования:</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_cat_"), IsAdmin())
async def process_admin_edit_cat(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for p in products:
        b.row(
            InlineKeyboardButton(
                text=f"✏️ {p['name']} — {p['price']:.0f} ₸",
                callback_data=f"admin_edit_item_{p['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product"))
    await callback.message.edit_text(
        "📝 <b>Выберите товар для редактирования:</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_edit_item_"), IsAdmin())
async def process_admin_edit_item(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(edit_product_id=pid)
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🏷 Название", callback_data="admin_edit_field_name")
    )
    b.row(InlineKeyboardButton(text="💰 Цена", callback_data="admin_edit_field_price"))
    b.row(
        InlineKeyboardButton(text="📝 Описание", callback_data="admin_edit_field_desc")
    )
    b.row(InlineKeyboardButton(text="📸 Фото", callback_data="admin_edit_field_photo"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_edit_product"))
    text = (
        f"📋 <b>Текущие данные товара:</b>\n\n"
        f"ID: {product['id']}\n🏷 Название: {product['name']}\n"
        f"💰 Цена: {product['price']:.0f} ₸\n"
        f"📝 Описание: {product.get('description') or 'Нет'}\n"
        f"📸 Фото: {'Есть' if product.get('photo_file_id') else 'Нет'}\n\n"
        f"Выберите что редактировать:"
    )
    await callback.message.edit_text(
        text, reply_markup=b.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_name", IsAdmin())
async def process_admin_edit_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ <b>Введите новое название товара:</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_name)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_price", IsAdmin())
async def process_admin_edit_price(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💰 <b>Введите новую цену (в тенге):</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_price)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_desc", IsAdmin())
async def process_admin_edit_desc(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📝 <b>Введите новое описание:</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_description)
    await callback.answer()


@router.callback_query(F.data == "admin_edit_field_photo", IsAdmin())
async def process_admin_edit_photo(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📸 <b>Отправьте новое фото:</b>",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminEditProductState.waiting_image)
    await callback.answer()


@router.message(AdminEditProductState.waiting_name, IsAdmin())
async def process_edit_name_save(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, name=message.text.strip())
        await message.answer(
            "✅ <b>Название обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminEditProductState.waiting_price, IsAdmin())
async def process_edit_price_save(message: Message, state: FSMContext):
    price = validate_price(message.text)
    if price is None:
        await message.answer(
            "❌ <b>Неверная цена!</b>\n\nВведите положительное число, например: 890",
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, price=price)
        await message.answer(
            "✅ <b>Цена обновлена!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminEditProductState.waiting_description, IsAdmin())
async def process_edit_desc_save(message: Message, state: FSMContext):
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        await update_product(pid, description=message.text.strip())
        await message.answer(
            "✅ <b>Описание обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


@router.message(AdminEditProductState.waiting_image, IsAdmin())
async def process_edit_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ <b>Отправьте фото</b>", parse_mode="HTML")
        return
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if pid:
        photo = message.photo[-1]
        await update_product(pid, photo_file_id=photo.file_id)
        await message.answer(
            "✅ <b>Фото обновлено!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    await state.clear()


# ============================================================
#   УДАЛЕНИЕ ТОВАРА
# ============================================================


@router.callback_query(F.data == "admin_delete_product", IsAdmin())
async def process_admin_delete_product(callback: CallbackQuery):
    cats = await get_categories()
    b = InlineKeyboardBuilder()
    for cat in cats:
        b.row(
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"admin_del_cat_{cat['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_products"))
    await callback.message.edit_text(
        "🗑 <b>Выберите категорию для удаления товаров:</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_cat_"), IsAdmin())
async def process_admin_del_cat(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    products = await get_products_by_category(cat_id)
    if not products:
        await callback.answer("В этой категории нет товаров", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for p in products:
        b.row(
            InlineKeyboardButton(
                text=f"🗑 {p['name']} — {p['price']:.0f} ₸",
                callback_data=f"admin_del_item_{p['id']}",
            )
        )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_delete_product"))
    await callback.message.edit_text(
        "🗑 <b>Выберите товар для удаления:</b>",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_item_"), IsAdmin())
async def process_admin_del_item(callback: CallbackQuery, state: FSMContext):
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(delete_product_id=pid)
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="✅ Да, удалить", callback_data="admin_confirm_delete"
        )
    )
    b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_delete_product"))
    await callback.message.edit_text(
        f"🗑 <b>Удалить товар?</b>\n\n🏷 {product['name']}\n💰 {product['price']:.0f} ₸\n\n"
        f"Товар будет скрыт из каталога.",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_delete", IsAdmin())
async def process_admin_confirm_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = data.get("delete_product_id")
    if pid:
        await delete_product(pid)
        await callback.message.edit_text(
            "✅ <b>Товар удалён!</b>",
            reply_markup=admin_main_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка", show_alert=True)
    await state.clear()
    await callback.answer()


# ============================================================
#   УДАЛЕНИЕ КАТЕГОРИИ (мягкое)
# ============================================================
#
# Логика:
# 1. Админ жмёт «🗑 Удалить категорию» — видит список всех категорий
#    (активные помечены 🟢, удалённые ⚪) с количеством товаров.
# 2. Кликает категорию → показываем подтверждение с числом товаров.
# 3. Если товары есть — блокируем с понятным сообщением (delete_category вернёт False,
#    но мы блокируем заранее на UI, чтобы не было пустых кликов).
# 4. Если пустая (count=0) — удаляем мягко (is_active=0), категория
#    исчезает из каталога у клиентов, но архивные заказы остаются целыми.
# ============================================================


@router.callback_query(F.data == "admin_delete_category", IsAdmin())
async def process_admin_delete_category(callback: CallbackQuery):
    """Список категорий с количеством активных товаров в каждой."""
    lang = await get_user_language(callback.from_user.id)
    cats = await get_categories(active_only=False)
    if not cats:
        await callback.message.edit_text(
            t(lang, "admin_delete_category_empty"),
            reply_markup=admin_products_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    # Считаем товары для каждой категории одним запросом через IN (...)
    async with __import__("database")._db() as conn:
        ids = [c["id"] for c in cats]
        placeholders = ",".join("?" * len(ids))
        cur = await conn.execute(
            f"SELECT category_id, COUNT(*) FROM products "
            f"WHERE is_active = 1 AND category_id IN ({placeholders}) "
            f"GROUP BY category_id",
            ids,
        )
        counts = {r[0]: r[1] for r in await cur.fetchall()}
    for c in cats:
        c["products_count"] = counts.get(c["id"], 0)
    await callback.message.edit_text(
        t(lang, "admin_delete_category_title"),
        reply_markup=admin_delete_category_kb(cats),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_del_category_"), IsAdmin())
async def process_admin_del_category_pick(callback: CallbackQuery, state: FSMContext):
    """Админ выбрал категорию — проверяем товары и либо показываем
    подтверждение, либо блокируем с понятным сообщением."""
    lang = await get_user_language(callback.from_user.id)
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    cat = await get_category(cat_id)
    if not cat:
        await callback.answer(t(lang, "admin_delete_category_not_found"), show_alert=True)
        return
    count = await category_has_active_products(cat_id)
    if count > 0:
        # Не пускаем к подтверждению — сразу объясняем почему
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_delete_category"))
        await callback.message.edit_text(
            t(
                lang, "admin_delete_category_blocked",
                name=f"{cat['emoji']} {html.escape(cat['name'])}",
                count=count,
            ),
            reply_markup=b.as_markup(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    # Категория пустая — показываем подтверждение
    await state.update_data(delete_category_id=cat_id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="✅ Да, удалить", callback_data="admin_confirm_delete_category"
        )
    )
    b.row(
        InlineKeyboardButton(
            text="❌ Отмена", callback_data="admin_delete_category"
        )
    )
    await callback.message.edit_text(
        t(
            lang, "admin_delete_category_confirm",
            name=f"{cat['emoji']} {html.escape(cat['name'])}",
            count=count,
        ),
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_confirm_delete_category", IsAdmin())
async def process_admin_confirm_delete_category(callback: CallbackQuery, state: FSMContext):
    """Финальное удаление пустой категории."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    cat_id = data.get("delete_category_id")
    if not cat_id:
        await callback.answer("Ошибка", show_alert=True)
        await state.clear()
        return
    # Перепроверяем прямо перед удалением — защита от гонки:
    # между показом подтверждения и кликом «Да» другой админ мог добавить товар.
    count = await category_has_active_products(cat_id)
    if count > 0:
        await callback.message.edit_text(
            t(
                lang, "admin_delete_category_blocked",
                name=str(cat_id), count=count,
            ),
            reply_markup=admin_products_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return
    cat = await get_category(cat_id)
    if not cat:
        await callback.answer(t(lang, "admin_delete_category_not_found"), show_alert=True)
        await state.clear()
        return
    await delete_category(cat_id)
    await state.clear()
    await callback.message.edit_text(
        t(
            lang, "admin_delete_category_done",
            name=f"{cat['emoji']} {html.escape(cat['name'])}",
        ),
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   ДОБАВЛЕНИЕ КАТЕГОРИИ (AdminAddCategoryState)
# ============================================================


@router.callback_query(F.data == "admin_add_category", IsAdmin())
async def process_admin_add_category(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ <b>Добавление категории</b>\n\n"
        "Введите название и эмодзи через запятую:\nНапример: Молочное, 🥛",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminAddCategoryState.waiting_name)
    await callback.answer()


@router.message(AdminAddCategoryState.waiting_name, IsAdmin())
async def process_admin_new_category(message: Message, state: FSMContext):
    parts = message.text.strip().split(",")
    if len(parts) >= 2:
        name = parts[0].strip()
        emoji = parts[1].strip()
    else:
        name = parts[0].strip()
        emoji = "📦"
    cid = await add_category(name, emoji)
    await message.answer(
        f"✅ <b>Категория добавлена!</b>\n\nID: {cid}\nНазвание: {name}\nЭмодзи: {emoji}",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(F.data == "admin_cancel", IsAdmin())
async def process_admin_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Операция отменена</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   КУРЬЕРЫ
# ============================================================


async def _format_courier_order(order: dict, items: list[dict]) -> str:
    """Текст заказа для отправки курьеру."""
    user_name = order.get("first_name") or "Клиент"
    if order.get("last_name"):
        user_name += f" {order['last_name']}"
    lines = [
        f"🚚 <b>Новый заказ #{order['id']}</b>",
        "",
        f"👤 <b>Клиент:</b> {html.escape(user_name)}",
        f"📍 <b>Адрес:</b> {html.escape(order.get('address') or '—')}",
        f"📞 <b>Телефон:</b> {html.escape(order.get('phone') or '—')}",
        f"🕐 <b>Время доставки:</b> {html.escape(order.get('delivery_time') or '—')}",
        f"💳 <b>Оплата:</b> {PAYMENT_METHODS.get(order.get('payment_method', ''), order.get('payment_method', '—'))}",
        f"💰 <b>Сумма:</b> {order.get('total_amount', 0):.0f} ₸",
    ]
    if order.get("comment"):
        lines.append(f"💬 <b>Комментарий:</b> {html.escape(order['comment'])}")
    lines += ["", "📦 <b>Состав заказа:</b>"]
    for it in items:
        qty = it.get("quantity", 0)
        price = it.get("price") or it.get("price_at_moment") or 0
        lines.append(f"  • {html.escape(it['name'])} × {qty} = {qty * price:.0f} ₸")
    return "\n".join(lines)


async def _send_order_to_courier(bot: Bot, order: dict, items: list[dict]) -> bool:
    """Шлёт курьеру карточку заказа + кнопку «Я доставил». Возвращает True если успешно."""
    courier = (
        await get_courier(order["courier_id"]) if order.get("courier_id") else None
    )
    if not courier:
        logger.warning(
            "send to courier: courier_id=%s not found", order.get("courier_id")
        )
        return False
    text = await _format_courier_order(order, items)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Я доставил",
                    callback_data=f"courier_delivered_{order['id']}",
                )
            ]
        ]
    )
    try:
        await bot.send_message(
            courier["telegram_id"],
            text + "\n\n🚚 <b>Когда доставите</b> — нажмите кнопку ниже, "
            "бот попросит фото или текстовое подтверждение.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.error("send to courier %s failed: %s", courier["telegram_id"], e)
        return False


@router.callback_query(F.data == "admin_couriers", IsAdmin())
async def process_admin_couriers(callback: CallbackQuery):
    couriers = await get_couriers(active_only=False)
    if not couriers:
        text = (
            "🚚 <b>Курьеры</b>\n\n"
            "Курьеров пока нет. Добавьте первого — нажмите кнопку ниже."
        )
    else:
        lines = ["🚚 <b>Курьеры</b>\n"]
        for c in couriers:
            mark = "🟢" if c.get("is_active") else "⚪"
            phone = f" • {c['phone']}" if c.get("phone") else ""
            lines.append(
                f"{mark} <b>{html.escape(c['name'])}</b> "
                f"(id: <code>{c['telegram_id']}</code>){phone}"
            )
        text = "\n".join(lines)
    await callback.message.edit_text(
        text, reply_markup=admin_couriers_kb(couriers), parse_mode="HTML"
    )
    await callback.answer()


# --- Добавление курьера через FSM ---


@router.callback_query(F.data == "admin_courier_add", IsAdmin())
async def process_admin_courier_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "➕ <b>Добавление курьера</b>\n\n"
        "Шаг 1 из 3.\n"
        "Отправьте <b>Telegram ID</b> курьера (только цифры).",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminCourierState.waiting_telegram_id)
    await callback.answer()


@router.message(AdminCourierState.waiting_telegram_id, IsAdmin())
async def process_courier_telegram_id(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(
            "❌ Telegram ID должен быть числом. Попробуйте ещё раз.",
            reply_markup=admin_cancel_kb(),
        )
        return
    tg_id = int(raw)
    await state.update_data(courier_telegram_id=tg_id)
    await message.answer(
        "✅ Принял Telegram ID.\n\nШаг 2 из 3.\nТеперь введите <b>имя курьера</b>.",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminCourierState.waiting_name)


@router.message(AdminCourierState.waiting_name, IsAdmin())
async def process_courier_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "❌ Имя слишком короткое. Попробуйте ещё раз.",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(courier_name=name)
    await message.answer(
        f"✅ Имя: <b>{html.escape(name)}</b>\n\n"
        "Шаг 3 из 3.\n"
        "Введите <b>телефон курьера</b>.\n"
        "Или нажмите «Пропустить».",
        reply_markup=admin_skip_desc_kb(),
        parse_mode="HTML",
    )
    await state.set_state(AdminCourierState.waiting_phone)


@router.callback_query(F.data == "admin_skip_desc", AdminCourierState.waiting_phone)
async def process_courier_skip_phone(callback: CallbackQuery, state: FSMContext):
    await _save_courier_and_finish(callback.message, state, phone=None)
    await callback.answer()


@router.message(AdminCourierState.waiting_phone, IsAdmin())
async def process_courier_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip()
    if not validate_phone(phone):
        await message.answer(
            "❌ Похоже на некорректный телефон. Попробуйте ещё раз "
            "или нажмите «Пропустить».",
            reply_markup=admin_skip_desc_kb(),
        )
        return
    await _save_courier_and_finish(message, state, phone=phone)


async def _save_courier_and_finish(target, state: FSMContext, phone: str | None):
    data = await state.get_data()
    tg_id = data.get("courier_telegram_id")
    name = data.get("courier_name")
    if not tg_id or not name:
        await state.clear()
        await target.answer(
            "⚠️ Что-то пошло не так — начните заново.",
            reply_markup=admin_main_keyboard(),
        )
        return
    await add_courier(tg_id, name, phone)
    await state.clear()
    text = (
        f"✅ <b>Курьер добавлен</b>\n\n"
        f"👤 {html.escape(name)}\n"
        f"🆔 Telegram: <code>{tg_id}</code>\n"
    )
    if phone:
        text += f"📞 {html.escape(phone)}\n"
    try:
        await target.edit_text(
            text, reply_markup=admin_main_keyboard(), parse_mode="HTML"
        )
    except Exception:
        await target.answer(text, reply_markup=admin_main_keyboard(), parse_mode="HTML")


# --- Удаление курьера (мягкое) ---


@router.callback_query(F.data.startswith("admin_courier_del_"), IsAdmin())
async def process_admin_courier_delete(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cid = _safe_int(args[0])
    if cid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return
    await delete_courier(cid)
    couriers = await get_couriers(active_only=False)
    await callback.answer("🗑 Курьер удалён", show_alert=True)
    # Перерисовываем список. safe_edit игнорирует 'message is not modified',
    # если курьер был единственный и визуально ничего не изменилось.
    if not couriers:
        text = "🚚 <b>Курьеры</b>\n\nКурьеров пока нет."
    else:
        lines = ["🚚 <b>Курьеры</b>\n"]
        for c in couriers:
            mark = "🟢" if c.get("is_active") else "⚪"
            phone = f" • {c['phone']}" if c.get("phone") else ""
            lines.append(
                f"{mark} <b>{html.escape(c['name'])}</b> "
                f"(id: <code>{c['telegram_id']}</code>){phone}"
            )
        text = "\n".join(lines)
    await safe_edit(callback.message, text, reply_markup=admin_couriers_kb(couriers))


# --- Назначение курьера на заказ ---


async def state_set_admin_pick_courier(callback, bot, order_id, order):
    """Админ нажал «Отправить» — показываем выбор курьера."""
    couriers = await get_couriers(active_only=True)
    if not couriers:
        await callback.message.edit_text(
            "⚠️ <b>Нет активных курьеров</b>\n\n"
            "Сначала добавьте курьера в разделе «🚚 Курьеры».",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="➕ Добавить курьера",
                            callback_data="admin_courier_add",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="◀️ К заказу",
                            callback_data=f"admin_view_{order_id}",
                        )
                    ],
                ]
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    items = await get_order_items(order_id)
    header = (
        f"🚚 <b>Назначьте курьера на заказ #{order_id}</b>\n\n"
        f"Сумма: <b>{order['total_amount']:.0f} ₸</b>\n"
        f"Адрес: {html.escape(order.get('address') or '—')}\n"
    )
    await callback.message.edit_text(
        header,
        reply_markup=admin_courier_pick_kb(couriers, order_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pick_courier_"), IsAdmin())
async def process_admin_pick_courier(callback: CallbackQuery, bot: Bot):
    """Админ выбрал курьера — назначаем, меняем статус, уведомляем клиента и курьера."""
    _, args = parse_cb(callback.data)
    oid = _safe_int(args[0])
    cid = _safe_int(args[1])
    if oid is None or cid is None:
        await callback.answer("❌ Ошибка: пустой идентификатор", show_alert=True)
        return

    courier = await get_courier(cid)
    if not courier or not courier.get("is_active"):
        await callback.answer("Курьер не найден или удалён", show_alert=True)
        return

    # 1) Меняем статус и привязываем курьера
    await update_order_status(oid, "sent")
    await assign_courier_to_order(oid, cid)
    order = await get_order(oid)
    items = await get_order_items(oid)

    # 2) Уведомляем клиента
    try:
        await bot.send_message(
            order["telegram_id"],
            f"🚚 <b>Заказ #{oid}</b>\n\n"
            f"Ваш заказ отправлен курьеру "
            f"<b>{html.escape(courier['name'])}</b>!",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("notify client about courier failed: %s", e)

    # 3) Шлём карточку заказа курьеру
    sent_ok = await _send_order_to_courier(bot, order, items)

    # 4) Обновляем экран админа
    user_name = user_display_name(order, "Клиент")
    admin_text = format_admin_order(order, items, user_name)
    admin_text += (
        f"\n\n🚚 <b>Курьер:</b> {html.escape(courier['name'])}"
        f" (id: <code>{courier['telegram_id']}</code>)"
    )
    if not sent_ok:
        admin_text += (
            "\n\n⚠️ <i>Не удалось уведомить курьера (он мог не запустить бота).</i>"
        )
    await callback.message.edit_text(
        admin_text,
        reply_markup=admin_order_status_keyboard(oid, "sent"),
        parse_mode="HTML",
    )
    await callback.answer(
        f"✅ Назначен: {courier['name']}" if sent_ok else "⚠️ Курьер не уведомлён",
        show_alert=not sent_ok,
    )


# ============================================================
#   Рассылки об акциях (Feature 4)
# ============================================================
#
# Алгоритм:
# 1. Админ жмёт «📣 Рассылка» → мы спрашиваем текст.
# 2. Получаем текст → предлагаем прислать фото ИЛИ выбрать товар из каталога.
#    Можно прикрепить оба (фото вступит основным, карточка товара дополнительно).
# 3. Превью → админ подтверждает → берём всех пользователей из БД
#    и рассылаем пачками через семафор (Telegram держит ~30 concurrent outbound;
#    ставим 25 чтобы не упереться в flood limit).
# ============================================================


# Параллельных отправок одновременно. 25 — с запасом от лимита ~30/сек на бота.
_MAILING_CONCURRENCY = 25


async def _send_one_mailing(bot: Bot, uid: int, photo_file_id: str | None,
                             full_text: str, product: dict | None) -> bool:
    """Шлёт одно сообщение пользователю. Возвращает True при успехе."""
    try:
        if photo_file_id:
            await bot.send_photo(
                uid, photo=photo_file_id, caption=full_text, parse_mode="HTML"
            )
        else:
            await bot.send_message(uid, full_text, parse_mode="HTML")
        # Если прикреплён товар с фото — отдельной карточкой с ценой
        if product and product.get("photo_file_id"):
            prod_caption = (
                f"📦 <b>{html.escape(product['name'])}</b>\n"
                f"💰 <b>{product['price']:.0f} ₸</b>"
            )
            await bot.send_photo(
                uid, photo=product["photo_file_id"], caption=prod_caption,
                parse_mode="HTML",
            )
        return True
    except Exception as e:
        # Часто юзер просто заблокировал бота — это нормальный кейс, не ERROR
        logger.warning("mailing send to %s failed: %s", uid, e)
        return False


async def _broadcast_mailing(bot: Bot, mailing_id: int, text: str | None,
                             photo_file_id: str | None, product: dict | None,
                             user_ids: list[int], admin_chat_id: int) -> tuple[int, int]:
    """Параллельная рассылка через семафор. Возвращает (sent, failed).

    1000 юзеров ≈ 2-3 сек вместо ~50 сек при последовательной отправке."""
    product_caption = ""
    if product:
        product_caption = (
            f"\n\n📦 <b>{html.escape(product['name'])}</b>\n"
            f"💰 <b>{product['price']:.0f} ₸</b>"
        )
        if product.get("description"):
            product_caption += f"\n📝 {html.escape(product['description'])}"
    full_text = (text or "") + product_caption

    sem = asyncio.Semaphore(_MAILING_CONCURRENCY)

    async def bound(uid: int) -> bool:
        async with sem:
            return await _send_one_mailing(bot, uid, photo_file_id, full_text, product)

    # gather() отдаёт event loop другим задачам — бот отвечает на сообщения
    # параллельно с рассылкой, а не висит 50 секунд.
    results = await asyncio.gather(*(bound(u) for u in user_ids))
    sent = sum(1 for ok in results if ok)
    failed = len(results) - sent
    await update_mailing_progress(mailing_id, sent, failed)
    return sent, failed


@router.callback_query(F.data == "admin_mailing", IsAdmin())
async def process_admin_mailing(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📣 <b>Рассылки</b>\n\n"
        "Отправьте клиентам информацию об акциях, скидках или новинках.\n\n"
        "Можно прикрепить фото или карточку товара из каталога.",
        reply_markup=admin_mailing_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "mailing_start", IsAdmin())
async def process_mailing_start(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminMailingState.waiting_text)
    await callback.message.edit_text(
        t(lang, "mailing_ask_text"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "cancel"), callback_data="mailing_cancel"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminMailingState.waiting_text, IsAdmin())
async def process_mailing_text(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("❌ Слишком короткий текст. Напишите хотя бы пару слов.")
        return
    if len(text) > 4000:
        await message.answer("❌ Слишком длинный текст (лимит Telegram — 4096 символов).")
        return
    await state.update_data(mailing_text=text)
    await state.set_state(AdminMailingState.waiting_photo)
    await message.answer(
        t(lang, "mailing_ask_photo_or_product"),
        reply_markup=mailing_photo_choice_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(AdminMailingState.waiting_photo, IsAdmin())
async def process_mailing_photo(message: Message, state: FSMContext):
    """Прислали фото для рассылки — сохраняем file_id и предлагаем выбор товара."""
    lang = await get_user_language(message.from_user.id)
    if not message.photo:
        await message.answer(
            "❌ Отправьте фото или нажмите «Без фото».",
            reply_markup=mailing_photo_choice_keyboard(lang),
            parse_mode="HTML",
        )
        return
    photo = message.photo[-1]
    await state.update_data(mailing_photo=photo.file_id)
    await state.set_state(AdminMailingState.selecting_product)
    cats = await get_categories()
    await message.answer(
        t(lang, "mailing_choose_category"),
        reply_markup=mailing_categories_keyboard(cats),
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "mailing_skip_photo", IsAdmin(), AdminMailingState.waiting_photo
)
async def process_mailing_skip_photo(callback: CallbackQuery, state: FSMContext):
    """Пропуск фото — сразу предлагаем выбор товара (опционально)."""
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminMailingState.selecting_product)
    cats = await get_categories()
    await callback.message.edit_text(
        t(lang, "mailing_choose_category"),
        reply_markup=mailing_categories_keyboard(cats),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mailing_cat_"), IsAdmin())
async def process_mailing_pick_category(callback: CallbackQuery):
    _, args = parse_cb(callback.data)
    cat_id = _safe_int(args[0])
    if cat_id is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    products = await get_products_by_category(cat_id)
    lang = await get_user_language(callback.from_user.id)
    if not products:
        await callback.answer(t(lang, "error_category_empty"), show_alert=True)
        return
    await callback.message.edit_text(
        t(lang, "mailing_choose_product"),
        reply_markup=mailing_products_keyboard(products, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mailing_product_"), IsAdmin())
async def process_mailing_pick_product(callback: CallbackQuery, state: FSMContext):
    """Товар выбран — переходим к превью рассылки."""
    _, args = parse_cb(callback.data)
    pid = _safe_int(args[0])
    if pid is None:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    product = await get_product(pid)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(mailing_product=product)
    await _show_mailing_preview(callback.message, state)
    await callback.answer()


@router.callback_query(
    F.data == "mailing_skip_product", IsAdmin(), AdminMailingState.selecting_product
)
async def process_mailing_skip_product(callback: CallbackQuery, state: FSMContext):
    """Без товара — сразу к превью."""
    await _show_mailing_preview(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "mailing_back_to_cats", IsAdmin())
async def process_mailing_back_to_cats(callback: CallbackQuery):
    """Назад к выбору категории."""
    cats = await get_categories()
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        t(lang, "mailing_choose_category"),
        reply_markup=mailing_categories_keyboard(cats),
        parse_mode="HTML",
    )
    await callback.answer()


async def _show_mailing_preview(target, state: FSMContext):
    """Рендерит превью и кладёт state в previewing."""
    lang = await get_user_language(
        target.from_user.id if hasattr(target, "from_user") else target.chat.id
    )
    data = await state.get_data()
    text = data.get("mailing_text") or ""
    photo = data.get("mailing_photo")
    product = data.get("mailing_product")
    user_ids = await get_all_user_telegram_ids()
    count = len(user_ids)
    preview_text = t(lang, "mailing_preview_title", count=count) + "\n\n"
    preview_text += "📝 <b>Текст:</b>\n" + html.escape(text) + "\n\n"
    if photo:
        preview_text += "📸 <b>Фото:</b> прикреплено\n"
    if product:
        preview_text += (
            f"📦 <b>Товар:</b> {html.escape(product['name'])} — "
            f"{product['price']:.0f} ₸\n"
        )
    if count == 0:
        await target.answer(
            t(lang, "mailing_no_users"),
            reply_markup=admin_mailing_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
        return
    if photo:
        try:
            await target.answer_photo(
                photo=photo,
                caption=preview_text,
                reply_markup=mailing_preview_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            await target.answer(
                preview_text,
                reply_markup=mailing_preview_keyboard(lang),
                parse_mode="HTML",
            )
    else:
        await target.answer(
            preview_text,
            reply_markup=mailing_preview_keyboard(lang),
            parse_mode="HTML",
        )
    await state.set_state(AdminMailingState.previewing)


@router.callback_query(F.data == "mailing_edit_text", IsAdmin())
async def process_mailing_edit(callback: CallbackQuery, state: FSMContext):
    """Изменить — начинаем заново с текста."""
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminMailingState.waiting_text)
    await callback.message.edit_text(
        t(lang, "mailing_ask_text"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "cancel"), callback_data="mailing_cancel"
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "mailing_confirm_send", IsAdmin())
async def process_mailing_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Финальная отправка — берём всех юзеров, создаём запись mailing,
    идём по списку с задержкой."""
    lang = await get_user_language(callback.from_user.id)
    data = await state.get_data()
    text = data.get("mailing_text")
    photo = data.get("mailing_photo")
    product = data.get("mailing_product")
    user_ids = await get_all_user_telegram_ids()
    if not user_ids:
        await callback.message.edit_text(
            t(lang, "mailing_no_users"),
            reply_markup=admin_mailing_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return
    mailing_id = await create_mailing(
        text=text, photo_file_id=photo, product_id=(product or {}).get("id"),
        recipients_count=len(user_ids),
    )
    # Сразу отвечаем админу, чтобы не висел callback
    await callback.message.edit_text(
        "⏳ <b>Рассылка запущена…</b>\n\n"
        f"Получателей: {len(user_ids)}\n"
        "Как закончим — пришлю отчёт.",
        reply_markup=admin_mailing_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer()
    # Рассылаем в фоне
    sent, failed = await _broadcast_mailing(
        bot, mailing_id, text, photo, product, user_ids, callback.from_user.id
    )
    report = t(
        lang, "mailing_done", total=len(user_ids), sent=sent, failed=failed
    )
    try:
        await bot.send_message(callback.from_user.id, report, parse_mode="HTML")
    except Exception as e:
        logger.error("mailing report to admin failed: %s", e)


@router.callback_query(F.data == "mailing_cancel", IsAdmin())
async def process_mailing_cancel(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(
        t(lang, "mailing_cancelled"),
        reply_markup=admin_mailing_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "mailing_history", IsAdmin())
async def process_mailing_history(callback: CallbackQuery):
    lang = await get_user_language(callback.from_user.id)
    items = await get_recent_mailings(limit=10)
    if not items:
        await callback.message.edit_text(
            t(lang, "mailing_admin_history") + "\n\n<i>Пока пусто.</i>",
            reply_markup=admin_mailing_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    lines = [t(lang, "mailing_admin_history"), ""]
    for m in items:
        date_str = (m.get("created_at") or "")[:16]
        lines.append(
            t(
                lang, "mailing_history_line",
                id=m["id"], date=date_str,
                sent=m.get("sent_count", 0), total=m.get("recipients_count", 0),
            )
        )
        if m.get("product_name"):
            lines.append(
                t(lang, "mailing_history_with_product", name=m["product_name"])
            )
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=admin_mailing_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
#   Запуск
# ============================================================
#
# Запуск в одном процессе с API (Mini App):
#   Используй `python main.py` — там поднимается и бот, и aiohttp-сервер.
# Запуск только бота (без API):
#   `python bot.py` — для отладки или если Mini App ещё не нужен.
# ============================================================


def build_bot_and_dispatcher() -> tuple[Bot, Dispatcher]:
    """Создаёт Bot и Dispatcher. Используется main.py для совместного запуска
    с API. Здесь же FSM storage и router регистрируются."""
    bot = Bot(token=__import__("config").BOT_TOKEN)
    dp = Dispatcher(storage=_FSM_STORAGE)
    dp.include_router(router)
    return bot, dp


async def run_bot() -> None:
    """Только бот, без API. Для `python bot.py`."""
    await init_db()
    logger.info("Database initialized")
    bot, dp = build_bot_and_dispatcher()
    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
