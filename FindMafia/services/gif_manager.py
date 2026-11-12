"""Reusable GIF sender. Empty/missing config never crashes the bot."""
import logging

import gif_config

log = logging.getLogger(__name__)


def get_gif(key: str) -> str:
    return (getattr(gif_config, key, "") or "").strip()


async def send_gif(bot, chat_id: int, key: str, thread_id: int | None = None) -> bool:
    """Send the animation configured under `key` (e.g. "NIGHT_GIF"). Returns True if sent."""
    gif = get_gif(key)
    if not gif:
        return False
    try:
        kw = {"message_thread_id": thread_id} if thread_id else {}
        await bot.send_animation(chat_id, gif, **kw)
        return True
    except Exception as e:  # bad file_id, no rights, ... -> just continue without the GIF
        log.warning("GIF %s failed: %s", key, e)
        return False
