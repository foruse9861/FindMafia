from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from game import roles as R


def _name(p):
    return p.name[:20]


def targets_for(game, player, action) -> list:
    me = player.user_id
    ps = game.players.values()
    if action.target == "dead":
        return [p for p in ps if not p.alive]
    pool = [p for p in ps if p.alive]
    if action.target == "others":
        pool = [p for p in pool if p.user_id != me]
        if action.key == "kill":
            pool = [p for p in pool if R.team_of(p.role) != "mafia"]
    if action.key == "protect" and player.last_protected is not None:
        pool = [p for p in pool if p.user_id != player.last_protected]
    return pool


def usable_actions(player) -> list:
    return [a for a in R.ROLES[player.role].actions if a.uses is None or player.uses.get(a.key, 0) > 0]


def action_menu(game, player, mode: str | None = None) -> M:
    gid, tok = game.game_id, game.phase_token
    acts = usable_actions(player)
    rows = []
    if mode is None and len(acts) > 1:
        for a in acts:
            rows.append([B(a.label, callback_data=f"act:{gid}:{tok}:{'go' if a.target is None else 'm'}:{a.key}")])
    else:
        a = next((x for x in acts if x.key == mode), acts[0] if acts else None)
        if a is not None and a.target is None:
            rows.append([B(a.label, callback_data=f"act:{gid}:{tok}:go:{a.key}")])
        elif a is not None:
            btns = [B(_name(p), callback_data=f"act:{gid}:{tok}:t:{a.key}:{game.idx_of(p.user_id)}") for p in targets_for(game, player, a)]
            rows += [btns[i:i + 2] for i in range(0, len(btns), 2)]
            if len(acts) > 1:
                rows.append([B("⬅ Back", callback_data=f"act:{gid}:{tok}:back")])
    rows.append([B("⏭ Skip tonight", callback_data=f"act:{gid}:{tok}:skip")])
    return M(rows)


def vote_keyboard(game) -> M:
    gid, tok = game.game_id, game.phase_token
    btns = [B(_name(p), callback_data=f"vote:{gid}:{tok}:{game.idx_of(p.user_id)}") for p in game.alive_players()]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([B("⏭ Skip vote", callback_data=f"vote:{gid}:{tok}:s")])
    return M(rows)
