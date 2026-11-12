"""Fake network layer: records every Bot API call and returns valid JSON - no Telegram needed."""
import asyncio
import itertools
import json
import time

from telegram.request import BaseRequest


class FakeRequest(BaseRequest):
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail: dict[str, list] = {}          # method -> list of (status, description) to raise (consumed one by one; sticky if "*")
        self.sticky: dict[str, tuple] = {}       # method -> (status, description) always failing
        self._mid = itertools.count(100)
        self.blocked_users: set[int] = set()     # chat ids that "blocked the bot"

    # --- BaseRequest API
    async def initialize(self): pass
    async def shutdown(self): pass

    @property
    def read_timeout(self): return 5

    async def do_request(self, url, method, request_data=None, read_timeout=None, write_timeout=None,
                         connect_timeout=None, pool_timeout=None):
        name = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        # nested JSON-ish values arrive already json-serialised by PTB for dict/list params
        for k, v in list(params.items()):
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    params[k] = json.loads(v)
                except ValueError:
                    pass
        self.calls.append((name, params))
        if name == "getUpdates":
            await asyncio.sleep(0.05)
            return 200, self._ok([])
        chat = params.get("chat_id")
        if chat in self.blocked_users and name.startswith("send"):
            return 403, self._err(403, "Forbidden: bot was blocked by the user")
        if name in self.sticky:
            return self.sticky[name][0], self._err(*self.sticky[name])
        if self.fail.get(name):
            st, desc = self.fail[name].pop(0)
            return st, self._err(st, desc)
        return 200, self._ok(self._result(name, params))

    # --- helpers
    def _ok(self, result): return json.dumps({"ok": True, "result": result}).encode()
    def _err(self, code, desc): return json.dumps({"ok": False, "error_code": code, "description": desc}).encode()

    def _result(self, name, p):
        if name == "getMe":
            return {"id": 999, "is_bot": True, "first_name": "Mafia World", "username": "MafiaWorldBot",
                    "can_join_groups": True, "can_read_all_group_messages": True, "supports_inline_queries": False}
        if name in ("sendMessage", "sendRichMessage", "sendAnimation", "editMessageText"):
            mid = p.get("message_id") or next(self._mid)
            return {"message_id": int(mid), "date": int(time.time()), "chat": {"id": int(p.get("chat_id", 0)), "type": "private"},
                    "text": "x"}
        if name == "getChatMember":
            return {"status": "member", "user": {"id": int(p.get("user_id", 0)), "is_bot": False, "first_name": "U"}}
        return True

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def of(self, name: str) -> list[dict]:
        return [p for n, p in self.calls if n == name]

    def clear(self):
        self.calls.clear()
