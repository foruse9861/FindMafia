"""
Rich message helpers: HTML builders, limit checks, send/edit with automatic plain-HTML fallback.

Rich messages are NOT wrapped by python-telegram-bot 22.x, so we call the raw Bot API through
`bot.do_api_request(...)`. Every screen is a `Screen(rich, plain)`; both versions are built from the same data.
"""
import asyncio
import html as _html
import logging
import random
import re
import warnings
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

import config

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", message=".*do_api_request.*")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
ZW = ["\u200b", "\u200c", "\u200d", "\u2060"]


# ----------------------------------------------------------------- HTML builders
def esc(text) -> str:
    """Escape user-controlled text for element content."""
    return _html.escape(str(text), quote=False)


def attr(text) -> str:
    return _html.escape(str(text), quote=True)


def check_callback_data(data: str) -> str:
    if not (1 <= len(data.encode("utf-8")) <= 64):
        raise ValueError(f"callback_data must be 1-64 bytes: {data!r}")
    return data


def pill(label, data: str, style: str | None = None) -> str:
    """Colored pill button inside a rich message. style: success(green) danger(red) primary(blue) None(neutral)."""
    check_callback_data(data)
    pad_l, pad_r = "".join(random.choice(ZW) for _ in range(random.randint(1, 2))), "".join(random.choice(ZW) for _ in range(random.randint(1, 2)))
    st = f' style="{style}"' if style else ""
    return f'<tg-button type="callback_data"{st} data="{attr(data)}">{pad_l}{esc(label)}{pad_r}</tg-button>'


def pill_rows(pills: list[str], per_row: int | None = None) -> str:
    per_row = min(per_row or config.RICH_PILLS_PER_ROW, 8)
    rows = [pills[i:i + per_row] for i in range(0, len(pills), per_row)]
    return "".join(f"<tg-button-row>{''.join(r)}</tg-button-row>" for r in rows)


def table(rows: list[list], header: list | None = None, escape: bool = True) -> str:
    cols = max([len(r) for r in rows] + ([len(header)] if header else [1]))
    if cols > config.RICH_TABLE_MAX_COLS:
        raise ValueError("too many table columns")
    f = esc if escape else str
    out = ["<table bordered compact>"]
    if header:
        out.append("<tr>" + "".join(f"<th>{f(h)}</th>" for h in header) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{f(c)}</td>" for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def section(title: str, body: str, level: int = 4) -> str:
    return f"<h{level}>{esc(title)}</h{level}>{body}"


def details(summary: str, body: str) -> str:
    return f"<details><summary>{esc(summary)}</summary>{body}</details>"


def bullet_list(items: list[str], ordered: bool = False, escape: bool = True) -> str:
    tag = "ol" if ordered else "ul"
    f = esc if escape else str
    return f"<{tag}>" + "".join(f"<li>{f(i)}</li>" for i in items) + f"</{tag}>"


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# ----------------------------------------------------------------- limits
_BLOCK_RE = re.compile(r"<(p|h[1-6]|li|tr|blockquote|details|tg-button-row|pre|ul|ol|table|hr|aside|footer)\b", re.I)
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)\b[^>]*?(/?)>")
_VOID = {"br", "hr", "img"}


def _max_nesting(html: str) -> int:
    depth = best = 0
    for m in _TAG_RE.finditer(html):
        closing, name, selfclose = m.group(1), m.group(2).lower(), m.group(3)
        if name in _VOID or selfclose:
            continue
        if closing:
            depth = max(0, depth - 1)
        else:
            depth += 1
            best = max(best, depth)
    return best


def check_rich_limits(html: str) -> tuple[bool, dict]:
    info = {
        "chars": len(html),
        "blocks": len(_BLOCK_RE.findall(html)),
        "nesting": _max_nesting(html),
    }
    ok = (info["chars"] <= config.RICH_MAX_CHARS and info["blocks"] <= config.RICH_MAX_BLOCKS
          and info["nesting"] <= config.RICH_MAX_NESTING)
    return ok, info


def paginate(items: list, page: int, per_page: int) -> tuple[list, int, int]:
    pages = max(1, -(-len(items) // per_page))
    page = min(max(0, page), pages - 1)
    return items[page * per_page:(page + 1) * per_page], page, pages


# ----------------------------------------------------------------- screens & state
@dataclass
class Screen:
    rich: str
    plain: str


class _RichState:
    failures = 0
    disabled = False


state = _RichState()
chat_rich_off: set[int] = set()


def rich_enabled(chat_id: int | None = None) -> bool:
    return config.RICH_MESSAGES and not state.disabled and (chat_id not in chat_rich_off)


def _rich_ok():
    state.failures = 0


def _rich_failed(err: Exception):
    state.failures += 1
    log.warning("Rich message failed (%d/3): %s", state.failures, err)
    if state.failures >= 3 and not state.disabled:
        state.disabled = True
        log.warning("Rich messages DISABLED until restart after 3 consecutive failures; using plain HTML.")


def _plain_text(screen: Screen) -> str:
    t = screen.plain
    if len(t) > config.PLAIN_MAX_CHARS:
        log.warning("plain screen too long (%d); truncating", len(t))
        t = t[: config.PLAIN_MAX_CHARS - 1] + "…"
    return t


async def _call(bot, endpoint: str, kwargs: dict):
    try:
        return await bot.do_api_request(endpoint, api_kwargs=kwargs)
    except RetryAfter as e:
        await asyncio.sleep(min(float(e.retry_after) + 0.5, 10))
        return await bot.do_api_request(endpoint, api_kwargs=kwargs)


async def send_screen(bot, chat_id: int, screen: Screen, reply_markup: InlineKeyboardMarkup | None = None,
                      thread_id: int | None = None) -> int | None:
    """Send a screen as rich message; falls back to plain HTML. Returns message_id. Raises Forbidden if the user blocked the bot."""
    if rich_enabled(chat_id):
        ok, info = check_rich_limits(screen.rich)
        if not ok:
            log.warning("rich screen over budget %s -> plain fallback", info)
        else:
            try:
                kw = {"chat_id": chat_id, "rich_message": {"html": screen.rich}}
                if reply_markup is not None:
                    kw["reply_markup"] = reply_markup
                if thread_id:
                    kw["message_thread_id"] = thread_id
                res = await _call(bot, "sendRichMessage", kw)
                _rich_ok()
                return res["message_id"] if isinstance(res, dict) else getattr(res, "message_id", None)
            except Forbidden:
                raise
            except BadRequest as e:          # NOTE: BadRequest is a subclass of NetworkError in PTB
                _rich_failed(e)
            except NetworkError:
                raise                         # timeouts etc. are not a rich-message problem
            except TelegramError as e:
                _rich_failed(e)
    kw = {}
    if thread_id:
        kw["message_thread_id"] = thread_id
    msg = await bot.send_message(chat_id, _plain_text(screen), parse_mode=ParseMode.HTML, reply_markup=reply_markup,
                                 link_preview_options=_NO_PREVIEW, **kw)
    return msg.message_id


async def edit_screen(bot, chat_id: int, message_id: int, screen: Screen,
                      reply_markup: InlineKeyboardMarkup | None = None) -> bool:
    """Edit a screen in place. Returns False if the message no longer exists."""
    if rich_enabled(chat_id):
        ok, info = check_rich_limits(screen.rich)
        if ok:
            try:
                kw = {"chat_id": chat_id, "message_id": message_id, "rich_message": {"html": screen.rich}}
                if reply_markup is not None:
                    kw["reply_markup"] = reply_markup
                await _call(bot, "editMessageText", kw)
                _rich_ok()
                return True
            except BadRequest as e:
                m = str(e).lower()
                if "not modified" in m:
                    return True
                if "not found" in m or "can't be edited" in m:
                    return False
                _rich_failed(e)
            except (Forbidden, NetworkError):
                raise
            except TelegramError as e:
                _rich_failed(e)
        else:
            log.warning("rich screen over budget %s -> plain fallback", info)
    try:
        await bot.edit_message_text(_plain_text(screen), chat_id=chat_id, message_id=message_id, parse_mode=ParseMode.HTML,
                                    reply_markup=reply_markup, link_preview_options=_NO_PREVIEW)
        return True
    except BadRequest as e:
        m = str(e).lower()
        if "not modified" in m:
            return True
        if "not found" in m or "can't be edited" in m:
            return False
        raise
    except RetryAfter as e:
        await asyncio.sleep(min(float(e.retry_after) + 0.5, 10))
        return await edit_screen(bot, chat_id, message_id, screen, reply_markup)


def check_ptb_version():
    """Startup guard: PTB 22.x with do_api_request is mandatory."""
    import telegram
    major = int(telegram.__version__.split(".")[0])
    if major != 22 or not hasattr(telegram.Bot, "do_api_request"):
        raise SystemExit("Install python-telegram-bot 22.x:  pip install -U 'python-telegram-bot>=22,<23'  "
                         f"(found {telegram.__version__})")
