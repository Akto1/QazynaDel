from __future__ import annotations



import asyncio


import json


import logging


import os


from pathlib import Path


from typing import Optional



from aiohttp import web


from aiogram import Bot



import config


import database as db


from auth import extract_init_data_from_request, validate_init_data


from locales import LANGUAGES



base_dir = os.path.dirname(os.path.abspath(__file__))


static_dir = os.path.join(base_dir, 'static')




logger = logging.getLogger(__name__)



WEBAPP_DIR = Path(__file__).parent / "static"



# Кэш file_id → URL от Telegram CDN. Файлы на CDN неизменны, можно кэшировать навсегда.


# На очень больших объёмах можно добавить LRU + TTL, для бота с ~100 товаров — overkill.


_file_url_cache: dict[str, str] = {}


_file_lock = asyncio.Lock()




# ==================== Утилиты ====================




def _json_error(status: int, error: str, **extra) -> web.Response:


    body = {"error": error, **extra}


    return web.json_response(body, status=status)




async def _auth(request) -> Optional[dict]:


    init_data = extract_init_data_from_request(request)




    user = validate_init_data(init_data) if init_data else None


    if not user:



        return None


    return user




def _require_auth(handler):


    """Декоратор: пускает только с валидным initData."""


    async def wrapped(request):


        user = await _auth(request)


        if not user:


            return _json_error(401, "unauthorized", hint="init_data missing or invalid")


        request["user_id"] = user["user_id"]


        request["tg_user"] = user["raw_user"]


        return await handler(request)


    return wrapped




async def _get_or_create_user(request) -> dict:


    """Ленивая регистрация юзера из Telegram-данных."""


    tg = request["tg_user"]


    return await db.get_or_create_user(


        telegram_id=tg["id"],


        first_name=tg.get("first_name"),


        last_name=tg.get("last_name"),


    )




async def _resolve_file_url(bot: Bot, file_id: str) -> Optional[str]:


    """file_id → прямая ссылка на Telegram CDN. Кэшируется."""


    if file_id in _file_url_cache:


        return _file_url_cache[file_id]


    async with _file_lock:


        # double-check после захвата лока


        if file_id in _file_url_cache:


            return _file_url_cache[file_id]


        try:


            f = await bot.get_file(file_id)


        except Exception as e:


            logger.warning("getFile(%s) failed: %s", file_id, e)


            return None


        url = f"https://api.telegram.org/file/bot{config.BOT_TOKEN}/{f.file_path}"


        _file_url_cache[file_id] = url


        return url




def _serialize_product(p: dict, image_url: Optional[str]) -> dict:


    return {


        "id": p["id"],


        "category_id": p["category_id"],


        "name": p["name"],


        "price": float(p["price"]),


        "description": p.get("description"),


        "image_url": image_url,


        "in_stock": (p.get("stock") or 0) > 0,


        "is_stopped": bool(p.get("is_stopped") or 0),  # в стоп-листе (антидоступен)


    }




# ==================== Handlers: статика ====================




async def handle_index(request):


    return web.FileResponse(WEBAPP_DIR / "index.html")




async def handle_static(request):


    rel = request.match_info["path"]


    # Защита от path traversal: только имя файла


    safe = Path(rel).name


    target = WEBAPP_DIR / safe


    if not target.exists() or not target.is_file():


        raise web.HTTPNotFound()


    # Кэширование статики агрессивное — index.html не кэшируем, css/js можно


    if safe in ("index.html", "app.js", "styles.css"):


        # JS/HTML/CSS — без кэша, чтобы обновления подхватывались сразу


        headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


    else:


        headers = {"Cache-Control": "public, max-age=3600"}


    return web.FileResponse(target, headers=headers)




async def handle_file_proxy(request):


    """file_id → 302 на Telegram CDN. Используется только для отладки;


    фронт обычно получает готовый image_url прямо в /api/products."""


    file_id = request.match_info["file_id"]


    bot: Bot = request.app["bot"]


    url = await _resolve_file_url(bot, file_id)


    if not url:


        return _json_error(404, "file_not_found")


    raise web.HTTPFound(url)




# ==================== Handlers: API ====================




@_require_auth


async def handle_me(request):


    user = await _get_or_create_user(request)


    return web.json_response({


        "telegram_id": user["telegram_id"],


        "first_name": user.get("first_name"),


        "last_name": user.get("last_name"),


        "phone": user.get("phone"),


        "address": user.get("address"),


        "language": user.get("language") or "ru",


        "languages": LANGUAGES,


        "delivery": {


            "minimum_order": config.MINIMUM_ORDER_AMOUNT,


            "delivery_fee": config.DELIVERY_FEE,


            "free_from": config.MINIMUM_ORDER_AMOUNT,


        },


        "support_group_id": config.SUPPORT_GROUP_ID,


        "kaspi_phone": config.KASPI_PHONE,


        "kaspi_holder": config.KASPI_HOLDER,


    })




@_require_auth


async def handle_categories(request):



    cats = await db.get_categories(active_only=True)


    # Считаем товары одним запросом


    counts: dict[int, int] = {}


    if cats:


        ids = [c["id"] for c in cats]


        placeholders = ",".join("?" * len(ids))


        async with db._db() as conn:


            cur = await conn.execute(


                f"SELECT category_id, COUNT(*) FROM products "


                f"WHERE is_active = 1 AND category_id IN ({placeholders}) "


                f"GROUP BY category_id",


                ids,


            )


            counts = {r[0]: r[1] for r in await cur.fetchall()}


            # Перед return web.json_response



    return web.json_response([


        {


            "id": c["id"],


            "name": c["name"],


            "emoji": c.get("emoji") or "📦",


            "sort_order": c.get("sort_order", 0),


            "products_count": counts.get(c["id"], 0),


        }


        for c in cats


    ])




@_require_auth


async def handle_category_products(request: web.Request) -> web.Response:



    try:


        # ПЕЧАТАЕМ, ЧТО ПРИХОДИТ В МАРШРУТЕ




        category_id = int(request.match_info["cat_id"])  # Исправлено на cat_id


    except Exception as e:



        return _json_error(400, f"Ошибка в роуте: {str(e)}")



    # ... остальной код ...



    # Читаем query-параметр ?page= из URL. Если его нет, берём 1 страницу.


    try:


        page = int(request.query.get("page", 1))


        if page < 1:


            page = 1


    except ValueError:


        page = 1



    # Лимит товаров на один экран


    PRODUCTS_PER_PAGE = 20



    # Запрашиваем из БД только нужную страницу


    products = await db.get_products_by_category_paginated(


        category_id=category_id,


        page=page,


        limit=PRODUCTS_PER_PAGE


    )



    # Собираем ссылки на фото из Телеграма (оригинальная логика шаблона)


    bot: Bot = request.app["bot"]


    file_ids = [p["photo_file_id"] for p in products if p.get("photo_file_id")]



    urls = await asyncio.gather(*[_resolve_file_url(bot, fid) for fid in file_ids])


    url_iter = iter(urls)



    out = []


    for p in products:


        img = None


        if p.get("photo_file_id"):


            img = next(url_iter)


        out.append(_serialize_product(p, img))



    # Отдаем точно такой же чистый JSON-массив, фронтенд не сломается


    # Добавь это временно прямо перед return web.json_response(out)


        # ... твой код ...


        # Перед return web.json_response(out) добавь:



    return web.json_response(out)



@_require_auth


async def handle_product(request):


    pid = int(request.match_info["pid"])


    product = await db.get_product(pid)


    if not product or not product.get("is_active"):


        return _json_error(404, "product_not_found")


    bot: Bot = request.app["bot"]


    img_url = None


    if product.get("photo_file_id"):


        img_url = await _resolve_file_url(bot, product["photo_file_id"])


    return web.json_response(_serialize_product(product, img_url))




@_require_auth


async def handle_buildings(request):


    """Список корпусов с пэтерами для UI оформления."""


    out = []


    for b in config.BUILDINGS:


        out.append({


            "id": b["id"],


            "name": b["name"],


            "min_apt": b["min_apt"],


            "max_apt": b["max_apt"],


        })


    return web.json_response({


        "complex": config.BUILDING_COMPLEX,


        "buildings": out,


        "time_slots": config.DELIVERY_TIME_SLOTS,


        "payment_methods": [


            {"id": k, "label": v} for k, v in config.PAYMENT_METHODS.items()


        ],


    })




@_require_auth


async def handle_cart(request):


    user = await _get_or_create_user(request)


    items = await db.get_cart_items(user["id"])


    total = await db.get_cart_total(user["id"])


    delivery_fee = 0 if total >= config.MINIMUM_ORDER_AMOUNT else config.DELIVERY_FEE


    grand_total = total + delivery_fee


    return web.json_response({


        "items": [


            {


                "cart_item_id": i["id"],


                "product_id": i["product_id"],


                "name": i["name"],


                "price": float(i["price"]),


                "quantity": i["quantity"],


                "line_total": float(i["price"]) * i["quantity"],


                "photo_file_id": i.get("photo_file_id"),


            }


            for i in items


        ],


        "subtotal": float(total),


        "delivery_fee": float(delivery_fee),


        "grand_total": float(grand_total),


        "free_from": float(config.MINIMUM_ORDER_AMOUNT),


    })




async def _read_json(request) -> dict:


    try:


        return await request.json()


    except (json.JSONDecodeError, Exception):


        return {}




@_require_auth


async def handle_cart_add(request):


    user = await _get_or_create_user(request)


    body = await _read_json(request)


    pid = body.get("product_id")


    qty = int(body.get("quantity") or 1)


    if not pid or qty < 1:


        return _json_error(400, "bad_request")


    product = await db.get_product(int(pid))


    if not product or not product.get("is_active"):


        return _json_error(404, "product_not_found")


    await db.add_to_cart(user["id"], int(pid), qty)


    return await handle_cart(request)




@_require_auth


async def handle_cart_update(request):


    user = await _get_or_create_user(request)


    body = await _read_json(request)


    cid = body.get("cart_item_id")


    qty = int(body.get("quantity") or 0)


    if not cid:


        return _json_error(400, "bad_request")


    await db.update_cart_quantity(int(cid), qty)


    return await handle_cart(request)




@_require_auth


async def handle_cart_clear(request):


    user = await _get_or_create_user(request)


    await db.clear_cart(user["id"])


    return await handle_cart(request)




@_require_auth


async def handle_checkout(request):


    """Создать заказ из текущей корзины."""


    user = await _get_or_create_user(request)


    body = await _read_json(request)


    address = (body.get("address") or "").strip()


    phone = (body.get("phone") or "").strip()


    delivery_time = (body.get("delivery_time") or "").strip()


    payment_method = (body.get("payment_method") or "").strip()


    comment = (body.get("comment") or "").strip()


    if not all([address, phone, delivery_time, payment_method]):


        return _json_error(400, "missing_fields",


                           required=["address", "phone", "delivery_time", "payment_method"])


    if payment_method not in config.PAYMENT_METHODS:


        return _json_error(400, "invalid_payment_method")


    if not db.validate_phone(phone):


        return _json_error(400, "invalid_phone")



    items = await db.get_cart_items(user["id"])


    if not items:


        return _json_error(400, "cart_empty")


    total = await db.get_cart_total(user["id"])


    grand_total = total if total >= config.MINIMUM_ORDER_AMOUNT else total + config.DELIVERY_FEE



    # Kaspi → awaiting_payment, иначе processing


    status = "awaiting_payment" if payment_method == "kaspi" else "processing"


    order_id = await db.create_order(


        user_id=user["id"],


        total_amount=grand_total,


        delivery_time=delivery_time,


        payment_method=payment_method,


        comment=comment,


        address=address,


        phone=phone,


        status=status,


    )


    await db.add_order_items(order_id, [


        {"product_id": i["product_id"], "quantity": i["quantity"], "price": i["price"]}


        for i in items


    ])


    await db.clear_cart(user["id"])


    # Сохраняем адрес/телефон в профиль — для следующих заказов


    await db.update_user_profile(user["id"], phone=phone, address=address)


    tg = request["tg_user"]



    # === Уведомление админу + кнопки управления ===


    bot: Bot = request.app["bot"]


    try:


        items_lines = "\n".join(


            f"  • {i['name']} × {i['quantity']} = {float(i['price']) * i['quantity']:.0f} ₸"


            for i in items


        )


        pay_label = config.PAYMENT_METHODS.get(payment_method, payment_method)


        admin_text = (


            f"🛒 <b>Новый заказ #{order_id}</b>\n\n"


            f"💰 <b>Сумма:</b> {grand_total:.0f} ₸\n"


            f"💳 <b>Оплата:</b> {pay_label}\n"


            f"📍 <b>Адрес:</b> {address}\n"


            f"🕐 <b>Время:</b> {delivery_time}\n"


            f"📞 <b>Телефон:</b> <code>{phone}</code>\n"


        )


        if comment:


            admin_text += f"💬 <b>Комментарий:</b> {comment}\n"


        admin_text += f"\n📦 <b>Товары:</b>\n{items_lines}\n\n"


        admin_text += f"👤 Клиент: {tg.get('first_name', '')} {tg.get('last_name', '') or ''} (<code>{tg['id']}</code>)"



        # Кнопки зависят от способа оплаты


        from aiogram.utils.keyboard import InlineKeyboardBuilder


        from aiogram.types import InlineKeyboardButton


        kb = InlineKeyboardBuilder()


        if payment_method == "kaspi":


            kb.row(


                InlineKeyboardButton(text="💰 Оплата получена", callback_data=f"admin_confirm_pay_{order_id}"),


                InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_reject_pay_{order_id}"),


            )


        kb.row(


            InlineKeyboardButton(text="📦 Взять в работу", callback_data=f"admin_status_{order_id}_processing"),


        )


        kb.row(


            InlineKeyboardButton(text="📋 Все заказы", callback_data="admin_orders"),


        )


        await bot.send_message(


            chat_id=config.ADMIN_ID,


            text=admin_text,


            parse_mode="HTML",


            reply_markup=kb.as_markup(),


        )


    except Exception as e:


        logger.warning("Failed to send admin notification for order %s: %s", order_id, e)



    return web.json_response({


        "order_id": order_id,


        "status": status,


        "total": float(grand_total),


        "payment_method": payment_method,


        "kaspi_phone": config.KASPI_PHONE,


        "kaspi_holder": config.KASPI_HOLDER,


    })




@_require_auth


async def handle_orders(request):


    user = await _get_or_create_user(request)


    orders = await db.get_user_orders(user["id"], limit=10)


    return web.json_response([


        {


            "id": o["id"],


            "status": o["status"],


            "status_label": config.ORDER_STATUSES.get(o["status"], o["status"]),


            "total": float(o["total_amount"]),


            "created_at": o["created_at"],


            "address": o.get("address"),


            "review_id": o.get("review_id"),


            "review_rating": o.get("review_rating"),


        }


        for o in orders


    ])




@_require_auth


async def handle_order_detail(request):


    user = await _get_or_create_user(request)


    oid = int(request.match_info["oid"])


    order = await db.get_order(oid)


    if not order or order["user_id"] != user["id"]:


        return _json_error(404, "order_not_found")


    items = await db.get_order_items(oid)


    review = await db.get_order_review(oid)


    return web.json_response({


        "id": order["id"],


        "status": order["status"],


        "status_label": config.ORDER_STATUSES.get(order["status"], order["status"]),


        "total": float(order["total_amount"]),


        "address": order.get("address"),


        "phone": order.get("phone"),


        "delivery_time": order.get("delivery_time"),


        "payment_method": order.get("payment_method"),


        "payment_label": config.PAYMENT_METHODS.get(order.get("payment_method", ""), "—"),


        "comment": order.get("comment"),


        "created_at": order["created_at"],


        "items": [


            {


                "name": i["name"],


                "quantity": i["quantity"],


                "price": float(i.get("price") or i.get("price_at_moment") or 0),


            }


            for i in items


        ],


        "review": {


            "rating": review["rating"],


            "comment": review["comment"],


            "created_at": review["created_at"],


        } if review else None,


    })




@_require_auth


async def handle_order_reorder(request):


    user = await _get_or_create_user(request)


    oid = int(request.match_info["oid"])


    ok = await db.reorder(oid, user["id"])


    if not ok:


        return _json_error(404, "order_not_found")


    return await handle_cart(request)




@_require_auth


async def handle_order_review(request):


    user = await _get_or_create_user(request)


    oid = int(request.match_info["oid"])


    body = await _read_json(request)


    rating = int(body.get("rating") or 0)


    comment = (body.get("comment") or "").strip() or None


    if not (1 <= rating <= 5):


        return _json_error(400, "invalid_rating")


    order = await db.get_order(oid)


    if not order or order["user_id"] != user["id"]:


        return _json_error(404, "order_not_found")


    if order["status"] != "delivered":


        return _json_error(400, "order_not_delivered")


    saved = await db.save_review(oid, user["id"], rating, comment)


    if not saved:


        return _json_error(409, "review_exists")


    return web.json_response({"ok": True, "rating": rating})




@_require_auth


async def handle_support(request):


    """Шлёт сообщение пользователя в группу поддержки.



    Бот уже умеет пересылать сообщения из SupportState, но Mini App — это


    WebApp-интерфейс, оттуда сообщения боту не приходят. Поэтому отдельный


    эндпоинт: фронт шлёт текст, мы сами отправляем в SUPPORT_GROUP_ID."""


    user = await _get_or_create_user(request)


    body = await _read_json(request)


    text = (body.get("text") or "").strip()


    if not text:


        return _json_error(400, "empty_message")


    if len(text) > 4000:


        return _json_error(400, "message_too_long")


    bot: Bot = request.app["bot"]


    tg_user = request["tg_user"]


    first_name = tg_user.get("first_name") or "Юзер"


    last_name = tg_user.get("last_name") or ""


    username = tg_user.get("username")


    user_line = f"{first_name} {last_name}".strip()


    if username:


        user_line += f" (@{username})"


    user_line += f" · <code>{tg_user['id']}</code>"


    try:


        await bot.send_message(


            chat_id=config.SUPPORT_GROUP_ID,


            text=f"💬 <b>Вопрос из Mini App</b>\n\n"


                 f"👤 {user_line}\n\n"


                 f"📝 {text}",


            parse_mode="HTML",


        )


    except Exception as e:


        logger.warning("Failed to send support message to group: %s", e)


        return _json_error(502, "support_unavailable", hint=str(e))


    return web.json_response({"ok": True})




# ==================== Сборка приложения ====================




def build_app(bot: Bot) -> web.Application:


    app = web.Application()


    app["bot"] = bot



    # 1. Сначала статика (указываем путь к папке 'static')


    # Если папка называется 'webapp', поменяй path='webapp'


    app.router.add_static('/static/', path='static', name='static')



    # 2. Роуты (только по одному разу!)


    app.router.add_get("/", handle_index)


    app.router.add_get("/api/file/{file_id}", handle_file_proxy)


    app.router.add_get("/api/me", handle_me)


    app.router.add_get("/api/categories", handle_categories)


    app.router.add_get("/api/categories/{cat_id}/products", handle_category_products)


    app.router.add_get("/api/products/{pid}", handle_product)


    app.router.add_get("/api/buildings", handle_buildings)


    app.router.add_get("/api/cart", handle_cart)


    app.router.add_post("/api/cart/add", handle_cart_add)


    app.router.add_post("/api/cart/update", handle_cart_update)


    app.router.add_post("/api/cart/clear", handle_cart_clear)


    app.router.add_post("/api/checkout", handle_checkout)


    app.router.add_get("/api/orders", handle_orders)


    app.router.add_get("/api/orders/{oid}", handle_order_detail)


    app.router.add_post("/api/orders/{oid}/reorder", handle_order_reorder)


    app.router.add_post("/api/orders/{oid}/review", handle_order_review)


    app.router.add_post("/api/support", handle_support)



    # 3. Ловушка 404 (самая последняя!)


    async def not_found(request):


        return _json_error(404, "not_found", path=request.path)



    app.router.add_route("*", "/{tail:.*}", not_found)




    return app




async def run_api(bot: Bot) -> None:


    """Запуск aiohttp в текущем event loop. Блокирует до отмены."""


    app = build_app(bot)


    runner = web.AppRunner(app)


    await runner.setup()


    site = web.TCPSite(runner, config.API_HOST, config.API_PORT)


    await site.start()


    logger.info("API + Mini App started at http://%s:%s", config.API_HOST, config.API_PORT)


    try:


        # держим корутину живой


        while True:


            await asyncio.sleep(3600)


    except asyncio.CancelledError:


        pass


    finally:


        await runner.cleanup()
