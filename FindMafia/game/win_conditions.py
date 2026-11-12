"""Win conditions. Returns None while the game goes on."""
from game import roles as R


def evaluate(game) -> dict | None:
    alive = game.alive_players()
    if not alive:
        return {"kind": "draw", "team": None, "winners": [], "title": "Draw", "text": "Nobody is left alive. Nobody wins."}
    mafia = [p for p in alive if R.team_of(p.role) == "mafia"]
    killers = [p for p in alive if p.role in R.HOSTILE_NEUTRAL]
    town = [p for p in alive if R.team_of(p.role) == "town"]
    survivors = [p.user_id for p in alive if p.role == "survivor"]

    if not mafia and not killers:
        w = [p.user_id for p in game.players.values() if R.team_of(p.role) == "town" and not p.fled] + survivors
        return {"kind": "team", "team": "town", "winners": w, "title": "TOWN WINS!", "text": "All Mafia and killers are gone. The village is safe!"}
    if mafia and not killers and len(mafia) >= len(alive) - len(mafia):
        w = [p.user_id for p in game.players.values() if R.team_of(p.role) == "mafia" and not p.fled] + survivors
        return {"kind": "team", "team": "mafia", "winners": w, "title": "MAFIA WINS!", "text": "The Mafia now equals everyone else. The village has fallen!"}
    if killers and not mafia and not town and len(killers) == 1:
        k = killers[0]
        return {"kind": "solo", "team": "neutral", "winners": [k.user_id], "title": f"{R.ROLES[k.role].name.upper()} WINS!",
                "text": f"{k.name} is the last killer standing."}
    return None


def solo_win(game, uid: int, why: str) -> dict:
    p = game.players[uid]
    return {"kind": "solo", "team": "neutral", "winners": [uid], "title": f"{R.ROLES[p.role].name.upper()} WINS!", "text": why}
