"""Callback / permission validation and simple rate limiting."""
import time
from collections import OrderedDict

from telegram.constants import ChatMemberStatus

import config

_last_action: dict[int, float] = {}
_seen_callbacks: "OrderedDict[str, None]" = OrderedDict()


def rate_limited(user_id: int, min_gap: float = 0.4) -> bool:
    now = time.monotonic()
    last = _last_action.get(user_id, 0.0)
    if now - last < min_gap:
        return True
    _last_action[user_id] = now
    if len(_last_action) > 5000:
        for k in list(_last_action)[:2500]:
            _last_action.pop(k, None)
    return False


def seen_callback(query_id: str) -> bool:
    """True if this callback id was already processed (duplicate delivery)."""
    if query_id in _seen_callbacks:
        return True
    _seen_callbacks[query_id] = None
    if len(_seen_callbacks) > 2000:
        _seen_callbacks.popitem(last=False)
    return False


def is_owner(user_id: int) -> bool:
    return user_id in config.OWNER_IDS


async def is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    if is_owner(user_id):
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def parse_data(data: str) -> list[str]:
    return data.split(":")
