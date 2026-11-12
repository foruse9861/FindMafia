"""
All screens. Every screen is built ONCE from a small Doc structure and rendered twice:
rich HTML  +  plain Telegram HTML (fallback). So both versions can never drift apart.
All visible English strings live in STRINGS so more languages can be added later.
"""
import html as _html

import config
from game import roles as R
from services import xp_system
from services.achievements import ACHIEVEMENTS
from utils import rich
from utils.rich import Screen, esc, fmt_time, paginate

STRINGS = {
    "en": {
        "title": "🎭 MAFIA WORLD",
        "welcome": "Play Mafia with your friends right inside Telegram. Easy to learn, exciting to win!",
        "quick_start": "Quick Start",
        "step1": "Add me to your group and make me an admin.",
        "step2": "Send /play in the group.",
        "step3": "Tap Join Game and wait for the game to start.",
        "play_title": "🎮 Play Mafia",
        "play_body": "Mafia is played in a Telegram group with 5 to 30 players.",
        "lobby_title": "🎭 MAFIA GAME LOBBY",
        "back": "⬅️ Back to Menu",
    }
}
LANG = "en"


def tr(key: str, **kw) -> str:
    s = STRINGS.get(LANG, STRINGS["en"]).get(key) or STRINGS["en"][key]
    return s.format(**kw) if kw else s


_PILL_EMOJI = {"success": "🟢", "danger": "🔴", "primary": "🔵", None: "⚪"}


class Doc:
    """Tiny document model rendered to rich HTML and plain Telegram HTML."""

    def __init__(self):
        self.b: list = []

    def h(self, text, level=3):
        self.b.append(("h", text, level)); return self

    def p(self, text, raw=False):
        self.b.append(("p", text, raw)); return self

    def quote(self, title, lines):
        self.b.append(("quote", title, list(lines))); return self

    def table(self, rows, header=None):
        self.b.append(("table", rows, header)); return self

    def ul(self, items, ordered=False):
        self.b.append(("ul", list(items), ordered)); return self

    def details(self, summary, sub: "Doc"):
        self.b.append(("details", summary, sub)); return self

    def pills(self, items):
        """items: [(label, callback_data, style)]"""
        self.b.append(("pills", list(items))); return self

    # ---------------------------------------------------------- rendering
    def rich(self) -> str:
        out = []
        for blk in self.b:
            k = blk[0]
            if k == "h":
                out.append(f"<h{blk[2]}>{esc(blk[1])}</h{blk[2]}>")
            elif k == "p":
                out.append(f"<p>{blk[1] if blk[2] else esc(blk[1])}</p>")
            elif k == "quote":
                inner = (f"<p><b>{esc(blk[1])}</b></p>" if blk[1] else "") + "".join(f"<p>{esc(x)}</p>" for x in blk[2])
                out.append(f"<blockquote>{inner}</blockquote>")
            elif k == "table":
                out.append(rich.table(blk[1], blk[2]))
            elif k == "ul":
                out.append(rich.bullet_list(blk[1], ordered=blk[2]))
            elif k == "details":
                out.append(rich.details(blk[1], blk[2].rich()))
            elif k == "pills":
                out.append(rich.pill_rows([rich.pill(l, d, s) for l, d, s in blk[1]]))
        return "".join(out)

    def plain(self) -> str:
        out = []
        for blk in self.b:
            k = blk[0]
            if k == "h":
                out.append(f"<b>{esc(blk[1])}</b>")
            elif k == "p":
                out.append(blk[1] if blk[2] else esc(blk[1]))
            elif k == "quote":
                lines = ([f"<b>{esc(blk[1])}</b>"] if blk[1] else []) + [esc(x) for x in blk[2]]
                out.append("<blockquote>" + "\n".join(lines) + "</blockquote>")
            elif k == "table":
                rows, header = blk[1], blk[2]
                lines = []
                if header:
                    lines.append(" | ".join(f"<b>{esc(h)}</b>" for h in header))
                for r in rows:
                    if len(r) == 2 and not header:
                        lines.append(f"• <b>{esc(r[0])}:</b> {esc(r[1])}")
                    else:
                        lines.append(" | ".join(esc(c) for c in r))
                out.append("\n".join(lines))
            elif k == "ul":
                out.append("\n".join((f"{i + 1}. " if blk[2] else "• ") + esc(x) for i, x in enumerate(blk[1])))
            elif k == "details":
                out.append(f"<b>{esc(blk[1])}</b>\n{blk[2].plain()}")
            elif k == "pills":
                lab = [f"{_PILL_EMOJI.get(s, '⚪')} {esc(l)}" for l, _d, s in blk[1]]
                out.append("\n".join("  ".join(lab[i:i + 3]) for i in range(0, len(lab), 3)))
        return "\n\n".join(out)

    def screen(self) -> Screen:
        return Screen(self.rich(), self.plain())


def _who(u: dict) -> str:
    return f"@{u['username']}" if u.get("username") else (u.get("first_name") or str(u.get("user_id")))


# ============================================================= menu screens
def main_menu() -> Screen:
    d = Doc().h(tr("title")).p(tr("welcome"))
    d.quote(tr("quick_start"), [f"1. {tr('step1')}", f"2. {tr('step2')}", f"3. {tr('step3')}"])
    return d.screen()


def play_instructions(bot_username: str) -> Screen:
    d = Doc().h(tr("play_title")).p(tr("play_body"))
    d.ul(["Add the bot to your group and make it an admin (it needs the Delete Messages right).",
          "Send /play in the group to open a lobby.",
          "Friends tap Join Game. Each player must press Start in a private chat with me once, so I can send secret roles.",
          "When enough players joined, the host taps Start or the timer starts the game."], ordered=True)
    return d.screen()


def how_to_play() -> Screen:
    d = Doc().h("📖 How to Play").p("Mafia is a game of hidden roles. Town tries to find the Mafia, the Mafia tries to hide and kill.")
    d.details("🎯 Goal", Doc().ul([
        "Town wins when all Mafia and killers are gone.",
        "Mafia wins when they equal or outnumber everyone else.",
        "Neutral roles have their own goals (see All Roles)."]))
    d.details("🌙 Night", Doc().ul([
        "Everyone sleeps. Special roles get a private message with buttons.",
        "Choose a target in the private chat. Mafia members choose the victim together.",
        "Nothing secret is ever shown in the group."]))
    d.details("☀️ Day", Doc().ul([
        "The bot tells who died. Their role is revealed (unless Hardcore Mode is on).",
        "Everybody discusses who looks suspicious.",
        "Then voting starts. The player with the most votes is eliminated."]))
    d.details("💡 Tips for beginners", Doc().ul([
        "Read the role message in private - it tells you exactly what to do.",
        "Do not reveal your role too early.",
        "If you are dead, do not give hints. Spectators cannot help."]))
    return d.screen()


def all_roles() -> Screen:
    d = Doc().h("🎭 All Roles").p("Tap a team to see its roles. Simple roles are used in normal games; advanced roles can be enabled by group admins.")
    for team in ("town", "mafia", "neutral"):
        items = [f"{r.emoji} {r.name}{' (advanced)' if r.advanced else ''} - {r.mission}" for r in R.ROLES.values() if r.team == team]
        d.details(f"{R.TEAM_EMOJI[team]} {R.TEAM_NAMES[team]} team", Doc().ul(items))
    return d.screen()


def settings_private(rich_on: bool) -> Screen:
    d = Doc().h("⚙️ Settings")
    d.table([["Rich message look (this chat)", "ON" if rich_on else "OFF"], ["Language", "English"]])
    d.p("If messages look empty or broken in your Telegram app, switch the rich look OFF. Group settings are changed by group admins with /admin.")
    return d.screen()


def profile(p: dict, fav_role: str | None, earned: set) -> Screen:
    lv, into, need = xp_system.progress(p["xp"])
    games = p["games"]
    winp = f"{(100 * p['wins'] / games):.0f}%" if games else "0%"
    fav = R.ROLES[fav_role].name if fav_role in R.ROLES else "-"
    d = Doc().h(f"👤 {p['first_name'] or p['user_id']}")
    d.table([["Username", f"@{p['username']}" if p.get("username") else "-"], ["Player ID", p["user_id"]], ["Level", lv],
             ["XP", p["xp"]], ["Total games", games], ["Games won", p["wins"]], ["Games lost", p["losses"]],
             ["Mafia wins", p["mafia_wins"]], ["Town wins", p["town_wins"]], ["Neutral wins", p["neutral_wins"]],
             ["Eliminations", p["eliminations"]], ["Survival count", p["survived"]], ["Win percentage", winp],
             ["Favorite role", fav]])
    d.p(f"Level {lv}  {xp_system.bar(into, need)}  {into}/{need} XP")
    d.h("🏅 Badges", 4)
    d.pills([(ACHIEVEMENTS[k][0], f"pill:b:{k}", "success" if k in earned else None) for k in ACHIEVEMENTS])
    return d.screen()


def statistics(p: dict, weekly=None, rewards=None) -> Screen:
    g = p["games"]
    pct = lambda a: f"{(100 * a / g):.0f}%" if g else "0%"
    d = Doc().h("📊 My Statistics")
    d.table([["Games played", g], ["Wins", f"{p['wins']} ({pct(p['wins'])})"], ["Losses", p["losses"]],
             ["Wins as Mafia", p["mafia_wins"]], ["Wins as Town", p["town_wins"]], ["Wins as Neutral", p["neutral_wins"]],
             ["Times survived", f"{p['survived']} ({pct(p['survived'])})"], ["Eliminations", p["eliminations"]]])
    if not g:
        d.p("You have not played yet. Join a game in a group to get statistics!")
    if weekly:
        d.h("📅 Weekly challenges", 4).table([[n, f"{min(c, t)}/{t}"] for n, c, t in weekly])
    if rewards:
        d.h("🎁 Recent rewards", 4).table([[r["reason"], f"+{r['xp']} XP"] for r in rewards])
    return d.screen()


LB_PERIODS = [("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("all", "All time")]
LB_PER_PAGE = 10


def leaderboard(period: str, rows: list[dict], page: int) -> Screen:
    title = dict(LB_PERIODS)[period]
    d = Doc().h(f"🏆 Leaderboard - {title}")
    if not rows:
        d.p("Nobody has XP in this period yet. Be the first!")
        return d.screen()
    base = page * LB_PER_PAGE
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{(medals[base + i] if base + i < 3 else str(base + i + 1) + '.')} {_who(r)} - {r['score']} XP" for i, r in enumerate(rows)]
    if page == 0:
        d.quote("Top 3", lines[:3])
        if lines[3:]:
            d.quote("Ranks 4-10", lines[3:])
    else:
        d.quote(f"Ranks {base + 1}-{base + len(rows)}", lines)
    return d.screen()


# ============================================================= lobby
def lobby(game, host_name: str) -> Screen:
    d = Doc().h(tr("lobby_title"))
    d.table([["Host", host_name], ["Players", f"{game.count}/{game.max_players}"], ["Minimum", game.min_players],
             ["Starts in", fmt_time(game.seconds_left())]])
    if game.count:
        d.h("Players", 4)
        shown = list(game.players.values())[:config.RICH_PILLS_PER_PAGE]
        d.pills([(p.name, f"pill:j:{game.game_id}:{game.idx_of(p.user_id)}", None) for p in shown])
        if game.count > len(shown):
            d.p(f"+{game.count - len(shown)} more - tap Player List")
    else:
        d.p("Nobody joined yet. Tap Join Game!")
    return d.screen()


def player_list(game, page: int) -> tuple[Screen, int, int]:
    items = list(game.players.values())
    chunk, page, pages = paginate(items, page, config.RICH_TABLE_ROWS_PER_PAGE)
    base = page * config.RICH_TABLE_ROWS_PER_PAGE
    d = Doc().h("👥 Player List")
    d.table([[base + i + 1, p.name] for i, p in enumerate(chunk)], header=["#", "Player"])
    d.p(f"Page {page + 1}/{pages} - {game.count} player(s)")
    return d.screen(), page, pages


def game_started(game, mafia_count: int) -> Screen:
    d = Doc().h("🎬 THE GAME HAS STARTED!")
    d.table([["Players", game.count], ["Mafia team size", mafia_count]])
    d.quote("Check your private chat", ["Your secret role has been sent to you by the bot. Do not show it to anyone!"])
    return d.screen()


# ============================================================= private role card
def role_card(role_key: str, teammates: list[str] | None = None, target_name: str | None = None) -> Screen:
    r = R.ROLES[role_key]
    d = Doc().h(f"🎭 YOUR ROLE: {r.name.upper()}")
    rows = [["Team", R.TEAM_NAMES[r.team]], ["Goal", r.goal]]
    if teammates:
        rows.append(["Your team", ", ".join(teammates)])
    if target_name:
        rows.append(["Your target", target_name])
    d.table(rows)
    d.quote("Your mission", [r.mission])
    d.h("Your abilities", 4).ul(r.abilities)
    d.details("📖 Role Information", Doc().p(r.tip))
    d.pills([(R.TEAM_NAMES[r.team], f"pill:t:{r.team}", R.TEAM_STYLE[r.team])])
    return d.screen()


def notice(title: str, text: str) -> Screen:
    return Doc().h(title).p(text).screen()


# ============================================================= in-game screens
def players_block(game, d: Doc):
    """Public alive/dead pills (green = alive, red = dead). Public info only."""
    alive = [p for p in game.players.values() if p.alive]
    dead = [p for p in game.players.values() if not p.alive]
    cap_a, cap_d = config.RICH_PILLS_PER_PAGE, config.RICH_PILLS_PER_PAGE // 2
    if alive:
        d.h(f"🟢 Alive ({len(alive)})", 4)
        d.pills([(p.name, f"pill:a:{game.game_id}:{game.idx_of(p.user_id)}", "success") for p in alive[:cap_a]])
        if len(alive) > cap_a:
            d.p(f"+{len(alive) - cap_a} more alive")
    if dead:
        d.h(f"🔴 Dead ({len(dead)})", 4)
        d.pills([(p.name, f"pill:a:{game.game_id}:{game.idx_of(p.user_id)}", "danger") for p in dead[:cap_d]])
        if len(dead) > cap_d:
            d.p(f"+{len(dead) - cap_d} more dead")


def night_screen(game, seconds: int) -> Screen:
    alive = len(game.alive_players())
    d = Doc().h(f"🌙 Night {game.day_no}").p("The village falls asleep. Special roles: check your private chat with me!")
    d.table([["Alive", alive], ["Dead", game.count - alive], ["Night ends in", f"{seconds}s"]])
    players_block(game, d)
    return d.screen()


def day_screen(game, lines: list[str], discuss_seconds: int) -> Screen:
    d = Doc().h(f"☀️ Day {game.day_no}")
    d.quote("What happened last night", lines or ["Nobody died tonight."])
    players_block(game, d)
    d.p(f"Discuss who looks suspicious. Voting starts in {fmt_time(discuss_seconds)}.")
    return d.screen()


def action_prompt(game, role, choice: str | None = None, mode_hint: str | None = None) -> Screen:
    d = Doc().h(f"🌙 Night {game.day_no} - {role.emoji} {role.name}")
    d.p(role.mission)
    d.p(mode_hint or "Choose below. You can change your choice until the night ends.")
    if choice:
        d.quote("Your choice", [choice])
    return d.screen()


def private_result(title: str, rows: list[list]) -> Screen:
    return Doc().h(title, 4).table(rows, header=["Target", "Result"]).screen()


def vote_screen(game, rows: list[list], left: int, secret: bool, skip_count: int, total_voters: int, voted: int) -> Screen:
    d = Doc().h(f"🗳 Voting - Day {game.day_no}")
    d.p(f"Closes in {fmt_time(left)}  -  {voted}/{total_voters} voted")
    if rows:
        shown = rows[:config.RICH_TABLE_ROWS_PER_PAGE]
        d.table(shown, header=["Player", "Votes"] if secret else ["Player", "Votes", "Voters"])
        if len(rows) > len(shown):
            d.p(f"+{len(rows) - len(shown)} more")
    else:
        d.p("No votes yet. Tap a name below to vote. You can change your vote until time is up.")
    if skip_count:
        d.p(f"Skipped: {skip_count}")
    return d.screen()


def vote_result(game, rows: list[list], secret: bool, outcome: str) -> Screen:
    d = Doc().h("🗳 Voting result")
    if rows:
        d.table(rows[:config.RICH_TABLE_ROWS_PER_PAGE], header=["Player", "Votes"] if secret else ["Player", "Votes", "Voters"])
    d.quote("Result", [outcome])
    return d.screen()


def elimination(name: str, role_key: str | None, how: str) -> Screen:
    d = Doc().h("⚖️ Eliminated")
    if role_key:
        r = R.ROLES[role_key]
        d.quote(f"{name} {how}", [f"They were {r.emoji} {r.name}."])
        d.pills([(r.name, f"pill:t:{r.team}", "danger")])
    else:
        d.quote(f"{name} {how}", ["Their role stays hidden (Hardcore Mode)."])
    return d.screen()


def game_over(title: str, subtitle: str, rows: list[list], days: int) -> Screen:
    d = Doc().h(f"🏁 {title}").p(subtitle)
    d.table([["Days played", days]])
    for i in range(0, len(rows), config.RICH_TABLE_ROWS_PER_PAGE):
        d.table(rows[i:i + config.RICH_TABLE_ROWS_PER_PAGE], header=["Player", "Role", "Result", "XP"])
    return d.screen()


def weekly_and_rewards(challenges: list[tuple[str, int, int]], rewards: list[dict]) -> list:
    return [(n, f"{min(c, t)}/{t}") for n, c, t in challenges], [[r["reason"], f"+{r['xp']}"] for r in rewards]
