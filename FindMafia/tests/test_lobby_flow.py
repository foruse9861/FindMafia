"""Run:  python -m tests.test_lobby_flow     (no Telegram needed - uses a fake network layer)"""
import asyncio
import logging

import config
from game import engine, lobby
from tests.fake_request import FakeRequest
from tests.harness import boot, cb_update, chat, msg_update, send, shutdown, user
from utils import rich

config.EDIT_INTERVAL = 0.05
lobby.MIN_REFRESH_GAP = 0.01
logging.getLogger().setLevel(logging.ERROR)

G1, G2 = -1001, -1002


def reset():
    engine.GAMES.clear(); engine.BY_CHAT.clear(); engine.USER_GAME.clear()
    rich.state.failures = 0; rich.state.disabled = False; rich.chat_rich_off.clear()


async def start_players(app, ids):
    for i in ids:
        await send(app, msg_update(app, "/start", user(i), chat(i, "private")))


async def join(app, fake, game, uid):
    await send(app, cb_update(app, f"lob:join:{game.game_id}", user(uid), chat(game.chat_id), game.lobby_msg_id))


def last_answer(fake):
    a = fake.of("answerCallbackQuery")
    return a[-1] if a else {}


async def t_full_game_start():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, range(1, 8))
    rich_menu = [p for p in fake.of("sendRichMessage") if p["chat_id"] == 1]
    assert rich_menu and '"html"' in str(rich_menu[0]["rich_message"]).replace("'", '"'), "main menu must be a rich message"
    assert "MAFIA WORLD" in str(rich_menu[0]["rich_message"])
    assert "reply_markup" in rich_menu[0], "menu keyboard must be sent"

    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    assert game.count == 1 and game.lobby_msg_id
    for uid in (2, 3, 4, 5, 6):
        await join(app, fake, game, uid)
    assert game.count == 6
    await join(app, fake, game, 3)
    assert "already joined" in last_answer(fake)["text"]
    # a 2nd /play in the same group is refused
    await send(app, msg_update(app, "/play", user(7), chat(G1)))
    assert "already running" in fake.of("sendMessage")[-1]["text"]
    # player 7 cannot be in two games
    await send(app, msg_update(app, "/play", user(7), chat(G2)))
    g2 = engine.BY_CHAT[G2]
    await join(app, fake, game, 7) if False else None
    await send(app, cb_update(app, f"lob:join:{game.game_id}", user(7), chat(G1), game.lobby_msg_id))
    assert "another game" in last_answer(fake)["text"]
    await send(app, cb_update(app, f"lob:cancel:{g2.game_id}", user(7), chat(G2), g2.lobby_msg_id))
    assert G2 not in engine.BY_CHAT

    # non-host cannot start; host can
    fake.clear()
    await send(app, cb_update(app, f"lob:start:{game.game_id}", user(2), chat(G1), game.lobby_msg_id))
    assert "host or a group admin" in last_answer(fake)["text"]
    fake.clear()
    await send(app, cb_update(app, f"lob:start:{game.game_id}", user(1), chat(G1), game.lobby_msg_id))
    assert game.status == "active", game.status
    cards = [p for p in fake.of("sendRichMessage") if p["chat_id"] in range(1, 7)]
    assert len(cards) == 6 and all("YOUR ROLE" in str(c["rich_message"]) for c in cards)
    group_calls = [(n, p) for n, p in fake.calls if p.get("chat_id") == G1]
    leak = [p for n, p in group_calls if "YOUR ROLE" in str(p)]
    assert not leak, "role card leaked into the group!"
    from database.db import db
    row = await db.fetchone("SELECT status FROM games WHERE game_id=?", (game.game_id,))
    assert row["status"] == "active"
    roles = await db.fetchall("SELECT role FROM game_players WHERE game_id=?", (game.game_id,))
    assert all(r["role"] for r in roles)
    print("ok full_game_start")


async def t_leave_host_transfer_and_empty():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, [1, 2])
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    await join(app, fake, game, 2)
    await send(app, cb_update(app, f"lob:leave:{game.game_id}", user(1), chat(G1), game.lobby_msg_id))
    assert game.host_id == 2 and game.count == 1
    await send(app, cb_update(app, f"lob:leave:{game.game_id}", user(2), chat(G1), game.lobby_msg_id))
    assert G1 not in engine.BY_CHAT and game.status == "cancelled"
    print("ok leave/host-transfer/empty")


async def t_countdown_cancel_not_enough():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, [1, 2])
    config_lobby = 0.2
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    import time
    game.lobby_deadline = time.monotonic() + config_lobby
    await asyncio.sleep(0.8)
    assert game.status == "cancelled"
    print("ok countdown_cancel")


async def t_countdown_autostart():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, range(1, 6))
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    for uid in range(2, 6):
        await join(app, fake, game, uid)
    import time
    game.lobby_deadline = time.monotonic() + 0.2
    await asyncio.sleep(1.0)
    assert game.status == "active", game.status
    print("ok countdown_autostart")


async def t_not_started_user_gets_link():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, [1])
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    await send(app, cb_update(app, f"lob:join:{game.game_id}", user(9), chat(G1), game.lobby_msg_id))
    assert "t.me/MafiaWorldBot" in last_answer(fake).get("url", ""), last_answer(fake)
    assert game.count == 1
    print("ok join_requires_private_start")


async def t_blocked_dm_cancels_safely():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, range(1, 6))
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    for uid in range(2, 6):
        await join(app, fake, game, uid)
    fake.blocked_users.add(4)
    await send(app, cb_update(app, f"lob:start:{game.game_id}", user(1), chat(G1), game.lobby_msg_id))
    assert game.status == "cancelled"
    assert "P4" in str(fake.of("editMessageText")[-1])
    print("ok blocked_dm_cancels_safely")


async def t_wrong_chat_and_pills():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await start_players(app, [1, 2])
    await send(app, msg_update(app, "/play", user(1), chat(G1)))
    game = engine.BY_CHAT[G1]
    # callback arriving from a different chat is rejected
    await send(app, cb_update(app, f"lob:join:{game.game_id}", user(2), chat(G2), game.lobby_msg_id))
    assert "no longer active" in last_answer(fake)["text"] and game.count == 1
    # pill tap = popup only
    fake.clear()
    await send(app, cb_update(app, f"pill:j:{game.game_id}:0", user(2), chat(G1), game.lobby_msg_id))
    assert "joined the game" in last_answer(fake)["text"]
    assert not [n for n in fake.names() if n not in ("answerCallbackQuery",)], fake.names()
    await send(app, cb_update(app, "pill:t:mafia", user(2), chat(2, "private"), 5))
    assert last_answer(fake)["text"] == "Team: Mafia"
    # over-long callback_data can never be built
    try:
        rich.pill("x", "pill:a:" + "я" * 40)
        assert False
    except ValueError:
        pass
    print("ok wrong_chat_and_pills")


async def t_rich_fallback_three_failures():
    reset(); fake = FakeRequest(); app = await boot(fake)
    fake.sticky["sendRichMessage"] = (400, "Bad Request: method not found")
    fake.sticky["editMessageText"] = (400, "Bad Request: can't parse rich_message") if False else (200, "")
    fake.sticky.pop("editMessageText")
    for i in range(1, 5):
        await send(app, msg_update(app, "/start", user(i), chat(i, "private")))
    assert rich.state.disabled, "rich should be auto-disabled after 3 failures"
    plain = [p for p in fake.of("sendMessage") if p.get("parse_mode") == "HTML" and "MAFIA WORLD" in p["text"]]
    assert len(plain) == 4, len(plain)
    attempts = len(fake.of("sendRichMessage"))
    assert attempts == 3, attempts   # 4th /start did not even try rich
    print("ok rich_fallback_3_failures")


async def t_per_chat_rich_off_and_unmodified():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await send(app, msg_update(app, "/start", user(1), chat(1, "private")))
    mid = fake.of("sendRichMessage")[-1]  # first message id comes from fake counter
    fake.clear()
    await send(app, cb_update(app, "menu:rich", user(1), chat(1, "private"), 777))
    assert 1 in rich.chat_rich_off
    assert fake.of("editMessageText") and "rich_message" not in fake.of("editMessageText")[-1]
    fake.clear()
    # "message is not modified" must not crash and not count as a failure
    reset(); fake2 = FakeRequest(); app2 = await boot(fake2)
    fake2.fail["editMessageText"] = [(400, "Bad Request: message is not modified")]
    await send(app2, cb_update(app2, "menu:how", user(1), chat(1, "private"), 5))
    assert rich.state.failures == 0
    print("ok per_chat_rich_toggle_and_not_modified")


async def t_menu_sections():
    reset(); fake = FakeRequest(); app = await boot(fake)
    await send(app, msg_update(app, "/start", user(1), chat(1, "private")))
    for sec in ("play", "profile", "stats", "lb:all:0", "lb:day:0", "how", "roles", "settings", "home"):
        fake.clear()
        await send(app, cb_update(app, f"menu:{sec}", user(1), chat(1, "private"), 55))
        ed = fake.of("editMessageText")
        assert ed and "rich_message" in ed[-1], sec
    print("ok menu_sections")


_apps = []
_orig_boot = boot


async def boot(fake):  # noqa: F811
    app = await _orig_boot(fake)
    _apps.append(app)
    return app


async def main():
    for t in (t_full_game_start, t_leave_host_transfer_and_empty, t_countdown_cancel_not_enough, t_countdown_autostart,
              t_not_started_user_gets_link, t_blocked_dm_cancels_safely, t_wrong_chat_and_pills,
              t_rich_fallback_three_failures, t_per_chat_rich_off_and_unmodified, t_menu_sections):
        try:
            await asyncio.wait_for(t(), 30)
        finally:
            while _apps:
                await shutdown(_apps.pop())
    print("ALL LOBBY TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
