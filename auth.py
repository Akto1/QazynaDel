"""Аутентификация Telegram Mini App.

Когда юзер открывает Mini App, Telegram вставляет в window.Telegram.WebApp.initData
строку вида:

    query_id=...&user=%7B%22id%22%3A...%7D&auth_date=...&hash=abc...

hash — это HMAC-SHA256 от data_check_string (все пары key=value из initData,
отсортированные по ключу, через \\n) с ключом HMAC-SHA256(bot_token, 'WebAppData').

Если наш пересчёт совпал с присланным hash — initData валидна, и в user пришёл
настоящий Telegram-пользователь.

Дополнительно проверяем auth_date, чтобы старые/пересланные запросы не принимались.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

import config


# Сколько секунд initData считается свежей. Telegram рекомендует не больше суток,
# но мы ставим час — если юзер оставил вкладку открытой на дню, лучше попросить
# перезайти, чем молча принимать устаревший токен.
_INIT_DATA_TTL_SEC = 3600


def validate_init_data(init_data: str) -> Optional[dict]:
    """Проверяет подпись initData. Возвращает dict с user-данными или None.

    Возвращаемый dict содержит как минимум ключ 'user_id' (int) и 'raw_user' (dict
    с полями id, first_name, last_name, username — что прислал Telegram)."""
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None
    hash_received = parsed.pop("hash", None)
    if not hash_received:
        return None

    # data_check_string — пары key=value, отсортированные по ключу
    data_check_string = "\n".join(
        f"{k}={parsed[k]}" for k in sorted(parsed.keys())
    )

    # secret_key = HMAC-SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, hash_received):
        return None

    # Проверка свежести
    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except (TypeError, ValueError):
        return None
    if auth_date < int(time.time()) - _INIT_DATA_TTL_SEC:
        return None

    # Извлекаем пользователя
    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None
    user_id = user.get("id")
    if not isinstance(user_id, int):
        return None

    return {
        "user_id": user_id,
        "raw_user": user,
        "auth_date": auth_date,
    }


def extract_init_data_from_request(request) -> Optional[str]:
    """Достаёт initData из запроса: сначала Authorization: tma <initData>,
    затем из query (?_auth=...). Authorization приоритетнее — его ставит fetch()."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("tma "):
        return auth_header[4:].strip()
    # Запасной вариант для случаев, когда заголовок нельзя (например, <img src>)
    return request.query.get("_auth") or None