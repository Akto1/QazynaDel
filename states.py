from aiogram.fsm.state import State, StatesGroup


class CheckoutState(StatesGroup):
    waiting_address = State()
    confirm_address = State()  # ждём «да, адрес верный» / «изменить»
    waiting_phone = State()
    confirm_phone = State()  # ждём «да, телефон верный» / «изменить»
    waiting_delivery_time = State()
    waiting_payment = State()
    waiting_comment = State()
    confirm_order = State()
    waiting_payment_confirmation = State()  # ждём «я оплатил» от пользователя


class ProfileState(StatesGroup):
    waiting_address = State()
    waiting_phone = State()


class SupportState(StatesGroup):
    waiting_message = State()


class SupportReplyState(StatesGroup):
    """Пользователь отвечает на сообщение поддержки (тред)."""

    waiting_reply = State()


class ReviewState(StatesGroup):
    """Оценка и опциональный комментарий после доставки."""

    waiting_rating = State()
    waiting_comment = State()


class AdminAddProductState(StatesGroup):
    waiting_category = State()
    waiting_name = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()
    confirm = State()


class AdminEditProductState(StatesGroup):
    waiting_name = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()


class AdminAddCategoryState(StatesGroup):
    waiting_name = State()


class AdminDeliveryState(StatesGroup):
    """Доставка заказа — админ/курьер шлёт фото или текстовое описание."""

    waiting_proof = State()  # ждём фото или текст («оставлено у двери»)


class AdminCourierState(StatesGroup):
    """Добавление курьера: админ вводит telegram_id → имя → телефон."""

    waiting_telegram_id = State()
    waiting_name = State()
    waiting_phone = State()


class AdminMailingState(StatesGroup):
    """Рассылка об акции: админ пишет текст, опционально прикладывает фото
    или привязывает товар из каталога, подтверждает и рассылает."""

    waiting_text = State()  # ждём текст рассылки
    has_text = State()  # текст уже введён, ждём фото или выбор товара
    waiting_photo = State()  # ждём фото (опционально)
    selecting_product = State()  # ждём выбор товара из каталога (опционально)
    previewing = State()  # показываем превью, ждём «отправить» / «отмена» / «изменить»