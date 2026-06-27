# CHANGELOG — добавленные функции

Четыре новых фичи в QazynaDelivery. Все изменения обратно совместимы —
миграции применяются только если БД ещё не на нужной версии.

## 1. ⭐ Отзыв после доставки

**Что делает:** после того как курьер отметил заказ доставленным, клиент
получает сообщение с просьбой оценить доставку (1–5 звёзд) и опционально
оставить комментарий.

**Файлы:**
- `database.py` — миграция `v6` создаёт таблицу `reviews`
  (UNIQUE на `order_id` — один отзыв на заказ).
  Хелперы: `save_review`, `get_order_review`, `get_user_reviews`,
  `get_average_rating`.
- `bot.py` — после `process_delivery_proof` отправляет клиенту
  `review_prompt` с `review_rating_keyboard`. Хендлеры:
  `process_review_start`, `process_review_rate`, `process_review_comment`,
  `process_review_skip`, `process_review_view`.
- `keyboards.py` — `review_rating_keyboard` (5 звёзд) +
  `review_text_skip_keyboard` (пропуск комментария).
- `locales.py` — 12 новых ключей во всех 3 языках (`rating_1..5`,
  `review_prompt`, `review_thanks`, и т.д.).
- `states.py` — `ReviewState` (waiting_rating / waiting_comment).

**Поток:**
1. Курьер отправляет фото/текст подтверждения → `process_delivery_proof`
   переводит заказ в `delivered`, уведомляет клиента, **и если отзыва ещё
   нет** — отправляет `review_prompt` с 5 кнопками-звёздами.
2. Юзер жмёт звёздочку → бот просит комментарий (можно пропустить).
3. После сохранения — `review_thanks` и уведомление админу в личку.

## 2. 🔁 Повторить заказ в один тап

**Что делает:** в истории заказов каждый заказ теперь — кнопка; в карточке
заказа появляются `🔁 Повторить` / `❌ Отменить` / `⭐ Оставить отзыв`.
«Повторить» кладёт все позиции заказа в корзину одним нажатием.

**Файлы:**
- `database.py` — `get_user_orders` дополнен LEFT JOIN `reviews`,
  чтобы UI знал, есть ли уже отзыв (прячет кнопку).
- `bot.py` — `process_history` теперь показывает кнопки заказов,
  новый `process_history_view` рисует детальную карточку с действиями.
- `keyboards.py` — `history_orders_keyboard`, `history_order_detail_kb`.
- `locales.py` — `history_title`, `btn_reorder`, `btn_cancel_order`,
  `btn_leave_review`, `btn_view_review`, `order_cancelled`, и т.д.

**Поток:**
1. Юзер жмёт «История» → видит список заказов-кнопок.
2. Жмёт на заказ → детальная карточка + кнопки действий (контекстные:
   «Отменить» только для `new`/`awaiting_payment`/`paid`,
   «Оставить отзыв» только для `delivered` без отзыва).
3. «Повторить» → `reorder()` хелпер кладёт товары в корзину → переход в корзину.

## 3. 💬 Ответы в поддержке (тред)

**Что делает:** поддержка и клиент общаются в одном треде. Когда админ
отвечает в группе поддержки (reply к сообщению бота), бот пересылает
ответ пользователю с кнопкой **«💬 Ответить»**. Ответ пользователя
уходит обратно в группу как часть того же треда.

**Файлы:**
- `database.py` — миграция `v7` добавляет в `support_messages`:
  `direction` (`'to_support'` | `'to_user'`), `parent_id`, `thread_id`.
  Хелперы: `get_thread_messages`, `get_user_by_support_thread`,
  `get_last_support_thread_for_user`, `get_support_message_by_user_id`.
- `bot.py` — `process_support_reply` сохраняет direction=`to_user` и
  шлёт кнопку `support_reply_keyboard(thread_id)`. Новые хендлеры:
  `process_support_reply_start`, `process_support_reply_text`.
- `keyboards.py` — `support_reply_keyboard`.
- `locales.py` — `support_reply_btn`, `support_reply_prompt`,
  `support_reply_sent`, и т.д.
- `states.py` — `SupportReplyState.waiting_reply`.

**Поток:**
1. Клиент: «💬 Поддержка» → пишет сообщение → уходит в группу.
2. Админ в группе: **Reply** к сообщению бота → бот пересылает клиенту
   с кнопкой «💬 Ответить».
3. Клиент жмёт кнопку → пишет ответ → бот пересылает в группу как
   часть треда, помечая `(тред #N)`.

## 4. 📣 Рассылка об акциях (фото + товар)

**Что делает:** админ собирает рассылку в три шага: текст → фото/товар →
превью → отправка всем пользователям из БД. Можно прикрепить и фото, и
товар (товар шлётся как карточка с фото, названием и ценой).

**Файлы:**
- `database.py` — миграция `v8` создаёт `mailings` (text, photo_file_id,
  product_id, recipients_count, sent_count, failed_count, created_at).
  Хелперы: `create_mailing`, `update_mailing_progress`,
  `get_recent_mailings`, `get_all_user_telegram_ids`.
- `bot.py` — `process_admin_mailing` (вход в меню рассылки),
  `process_mailing_start` → `process_mailing_text` →
  `process_mailing_photo` → выбор товара → `_show_mailing_preview` →
  `process_mailing_send` (запускает `_broadcast_mailing` в фоне).
  Рассылка идёт с задержкой 50 мс между сообщениями (под лимит Telegram
  ~30 msg/sec).
- `keyboards.py` — `admin_mailing_keyboard`, `mailing_categories_keyboard`,
  `mailing_products_keyboard`, `mailing_photo_choice_keyboard`,
  `mailing_preview_keyboard`.
- `locales.py` — все ключи `mailing_*` + `admin_mailing`.
- `states.py` — `AdminMailingState` (waiting_text → waiting_photo →
  selecting_product → previewing).
- Админ-меню (`admin_main_keyboard`) получило кнопку `📣 Рассылка`.

**Поток:**
1. Админ: `/admin` → `📣 Рассылка` → `📣 Создать рассылку`.
2. Пишет текст → отправляет фото **или** выбирает категорию/товар
   **или** пропускает и то и другое.
3. Бот показывает превью (с фото если есть) + кнопки «🚀 Отправить всем» /
   «✏️ Изменить» / «❌ Отмена».
4. После подтверждения бот создаёт запись в `mailings`, идёт по всем
   `telegram_id` пользователей, шлёт сообщение с задержкой, обновляет
   `sent_count` / `failed_count`.
5. Админу приходит финальный отчёт.

## Совместимость

- **Миграции идемпотентны** — `schema_version` в БД отслеживает, какие
  миграции уже применены. Если БД была на v5, она просто доедет до v8
  при следующем запуске.
- **`save_support_message` обратно совместима** — новые аргументы
  (`direction`, `parent_id`, `thread_id`) имеют дефолты, старые вызовы
  продолжают работать.
- **`get_user_orders` обратно совместима** — добавлены колонки `review_id`
  и `review_rating` через LEFT JOIN. Старый код, который просто итерирует
  по `dict`, не сломается.
- **Все переводы** добавлены сразу в ru/kk/en, не осталось непереведённых
  ключей для новых строк.

## Что протестировано

- ✅ AST парсит все 6 файлов без ошибок
- ✅ Бот импортируется, миграции применяются, polling стартует
- ✅ End-to-end smoke-тесты по каждой фиче (см. логи проверки):
  - отзыв сохраняется, дубль блокируется UNIQUE-индексом
  - история показывает `review_id`/`review_rating`
  - тред поддержки корректно собирается из 3 сообщений
  - рассылка создаётся с привязкой к товару
  - reorder кладёт товары в корзину
  - cancel блокируется для delivered