"""Helpers to feed fake updates into a real Application."""
import asyncio
import itertools
import os
import tempfile
import time

from telegram import Update

_uid = itertools.count(1)
_mid = itertools.count(1000)


def new_app(fake):
    import config
    from database.db import db
    import main
    db.path = os.path.join(tempfile.mkdtemp(), "t.db")
    app = main.build_application("1:TEST", fake)
    return app, main


async def boot(fake):
    app, main = new_app(fake)
    await app.initialize()
    await main.post_init(app)
    return app


def user(uid, name=None):
    return {"id": uid, "is_bot": False, "first_name": name or f"P{uid}", "username": f"p{uid}"}


def chat(cid, typ="supergroup"):
    d = {"id": cid, "type": typ}
    if typ != "private":
        d["title"] = "Test Group"
    return d


def msg_update(app, text, u, c, **extra):
    m = {"message_id": next(_mid), "date": int(time.time()), "chat": c, "from": u, "text": text}
    if text.startswith("/"):
        cmd = text.split()[0]
        m["entities"] = [{"type": "bot_command", "offset": 0, "length": len(cmd)}]
    m.update(extra)
    return Update.de_json({"update_id": next(_mid), "message": m}, app.bot)


def cb_update(app, data, u, c, message_id):
    cq = {"id": str(next(_mid)), "from": u, "chat_instance": "ci", "data": data,
          "message": {"message_id": message_id, "date": int(time.time()), "chat": c, "text": "x"}}
    return Update.de_json({"update_id": next(_mid), "callback_query": cq}, app.bot)


async def send(app, upd):
    from utils import validators
    validators._last_action.clear()          # tests act faster than a human
    await app.process_update(upd)


async def shutdown(app):
    import main
    from game import engine
    for g in list(engine.GAMES.values()):
        g.cancel_tasks(except_current=False)
    await asyncio.sleep(0.05)
    await main.post_shutdown(app)
    await app.shutdown()
