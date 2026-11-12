"""Role definitions (English; texts live next to data so they can be translated later) and balanced distribution."""
import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Action:
    key: str
    label: str                 # button label
    target: str | None         # "others" | "any" | "dead" | None (no target)
    uses: int | None = None    # None = unlimited


@dataclass(frozen=True)
class Role:
    key: str
    name: str
    team: str                  # town | mafia | neutral
    emoji: str
    goal: str
    mission: str
    abilities: tuple
    tip: str
    advanced: bool = False
    actions: tuple = field(default_factory=tuple)
    min_players: int = 5


TEAM_NAMES = {"town": "Town", "mafia": "Mafia", "neutral": "Neutral"}
TEAM_STYLE = {"town": "success", "mafia": "danger", "neutral": "primary"}
TEAM_EMOJI = {"town": "🟢", "mafia": "🔴", "neutral": "🔵"}
TOWN_GOAL = "Help the Town find and remove all Mafia and killers."
MAFIA_GOAL = "Kill until the Mafia team equals or outnumbers everyone else."

_R = [
    # ------------------------------------------------------------------ TOWN
    Role("villager", "Villager", "town", "👨‍🌾", TOWN_GOAL,
         "You have no special power. Your voice and your vote are your weapons.",
         ("Talk during the day and share your suspicions.", "Vote to eliminate a suspect."),
         "Watch who defends whom. Mafia members often protect each other."),
    Role("doctor", "Doctor", "town", "🩺", TOWN_GOAL,
         "Protect one player every night from attacks.",
         ("Choose one player to protect (you may choose yourself).", "You cannot protect the same player on two nights in a row."),
         "Protect players who seem important to the Town, like a player who shares good clues.",
         actions=(Action("protect", "🛡 Protect", "any"),)),
    Role("detective", "Detective", "town", "🕵️", TOWN_GOAL,
         "Investigate one player every night to learn their team.",
         ("Learn if a player is Town, Mafia or Neutral.", "Beware: a Godfather looks like Town and a framed player looks like Mafia."),
         "Do not reveal yourself too early. The Mafia will hunt you.",
         actions=(Action("investigate", "🔍 Investigate", "others"),)),
    Role("bodyguard", "Bodyguard", "town", "💂", TOWN_GOAL,
         "Guard another player. If they are attacked, you take the hit instead.",
         ("Choose one other player to guard each night.", "If your target is attacked, you and one attacker both die and the target lives."),
         "Guard the player you believe is the Detective or Doctor.",
         actions=(Action("guard", "💂 Guard", "others"),), min_players=7),
    Role("mayor", "Mayor", "town", "🎩", TOWN_GOAL,
         "Your vote counts double during the day. Nobody knows this.",
         ("Your vote automatically counts as 2 votes.", "You have no night action."),
         "Use your strong vote wisely. Stay alive and stay quiet.", min_players=9),
    Role("sheriff", "Sheriff", "town", "⭐", TOWN_GOAL,
         "Interrogate one player each night to see if they are suspicious.",
         ("Mafia members, Serial Killers and Arsonists look Suspicious.", "A Godfather looks Not Suspicious. A framed player looks Suspicious."),
         "Suspicious does not always mean Mafia. Combine your clues with others.", advanced=True,
         actions=(Action("interrogate", "⭐ Interrogate", "others"),), min_players=8),
    Role("vigilante", "Vigilante", "town", "🔫", TOWN_GOAL,
         "You may shoot one player at night. You only have 2 bullets.",
         ("Choose a player to shoot at night (2 bullets total).", "You can shoot an innocent Town player by mistake."),
         "Only shoot when you are very sure.", advanced=True,
         actions=(Action("shoot", "🔫 Shoot", "others", uses=2),), min_players=10),
    Role("medium", "Medium", "town", "🔮", TOWN_GOAL,
         "Speak with the spirits: learn the true role of one dead player each night.",
         ("Choose a dead player and learn their role.", "Very useful in Hardcore Mode where roles stay hidden."),
         "Share what you learn carefully.", advanced=True,
         actions=(Action("seance", "🔮 Contact spirit", "dead"),), min_players=11),
    Role("veteran", "Veteran", "town", "🎖️", TOWN_GOAL,
         "Go on alert to kill anyone who visits you at night. You can do this 2 times.",
         ("Choose to go on alert (2 uses).", "Everyone who targets you on an alert night dies."),
         "Go on alert when you think you are the Mafia's next target.", advanced=True,
         actions=(Action("alert", "🎖️ Go on alert", None, uses=2),), min_players=12),
    Role("jailor", "Jailor", "town", "⛓️", TOWN_GOAL,
         "Jail a player: they cannot act tonight and cannot be attacked. You may execute one prisoner once.",
         ("Jail one player each night (they are safe and blocked).", "Execute a prisoner once in the whole game."),
         "Execute only when you are certain your prisoner is evil.", advanced=True,
         actions=(Action("jail", "⛓️ Jail", "others"), Action("execute", "⚖️ Execute (1 use)", "others", uses=1)), min_players=13),
    # ------------------------------------------------------------------ MAFIA
    Role("mafia", "Mafia", "mafia", "🔪", MAFIA_GOAL,
         "Choose a victim every night together with your team.",
         ("Vote with your team on tonight's victim.", "You can chat privately with your Mafia team."),
         "Blend in during the day. Blame others calmly.",
         actions=(Action("kill", "🔪 Kill", "others"),)),
    Role("godfather", "Godfather", "mafia", "🕴️", MAFIA_GOAL,
         "Leader of the Mafia. You look innocent to investigators.",
         ("Your kill choice overrides the team's vote.", "Detectives and Sheriffs see you as Not Mafia."),
         "Let your team take the heat.", advanced=True,
         actions=(Action("kill", "🔪 Kill", "others"),), min_players=8),
    Role("consigliere", "Consigliere", "mafia", "📜", MAFIA_GOAL,
         "Investigate one player each night to learn their exact role.",
         ("Learn the exact role of a player.", "You do not take part in the kill vote."),
         "Tell your team who the Doctor and Detective are.", advanced=True,
         actions=(Action("investigate_role", "📜 Investigate role", "others"),), min_players=10),
    Role("framer", "Framer", "mafia", "🖼️", MAFIA_GOAL,
         "Frame an innocent player so investigators see them as Mafia.",
         ("Choose a player to frame tonight.", "You do not take part in the kill vote."),
         "Frame players who will be investigated.", advanced=True,
         actions=(Action("frame", "🖼️ Frame", "others"),), min_players=12),
    Role("silencer", "Silencer", "mafia", "🤐", MAFIA_GOAL,
         "Silence a player so they cannot speak during the next day.",
         ("Choose a player to silence.", "Their group messages are removed during the day (the bot needs the Delete Messages right)."),
         "Silence the loudest detective-like player.", advanced=True,
         actions=(Action("silence", "🤐 Silence", "others"),), min_players=12),
    Role("consort", "Consort", "mafia", "💋", MAFIA_GOAL,
         "Distract a player so their night action fails.",
         ("Choose a player to block tonight.", "They are told they were distracted."),
         "Block the Doctor on the night you attack.", advanced=True,
         actions=(Action("block", "💋 Distract", "others"),), min_players=14),
    Role("janitor", "Janitor", "mafia", "🧹", MAFIA_GOAL,
         "Clean a player: if they die tonight, nobody learns their role. 2 uses.",
         ("Choose a player to clean.", "If that player dies, their role stays hidden."),
         "Clean the victim you expect to be killed.", advanced=True,
         actions=(Action("clean", "🧹 Clean", "others", uses=2),), min_players=16),
    # ------------------------------------------------------------------ NEUTRAL
    Role("serial_killer", "Serial Killer", "neutral", "🗡️", "Be the last killer standing.",
         "Kill one player every night. You survive Mafia attacks.",
         ("Choose a victim each night.", "The Mafia cannot kill you at night."),
         "Stay quiet and never reveal yourself.", advanced=True,
         actions=(Action("murder", "🗡️ Murder", "others"),), min_players=10),
    Role("jester", "Jester", "neutral", "🤡", "Get voted out during the day. If you succeed, you win and the game ends.",
         "Act suspicious, but not too suspicious.",
         ("You have no night action.", "If the Town votes you out, you win alone."),
         "Be funny and confusing.", advanced=True, min_players=7),
    Role("survivor", "Survivor", "neutral", "🦺", "Stay alive until the end. You win together with any winning team.",
         "Survive. You have a bulletproof vest (2 uses).",
         ("Use the vest to protect yourself tonight.", "You win if you are alive when the game ends."),
         "Stay neutral and stay alive.", advanced=True,
         actions=(Action("vest", "🦺 Use vest (2 uses)", None, uses=2),), min_players=7),
    Role("arsonist", "Arsonist", "neutral", "🔥", "Be the last killer standing.",
         "Douse players in gasoline, then ignite them all at once.",
         ("Douse one player each night.", "Ignite to burn every doused player."),
         "Douse quietly, ignite when many are doused.", advanced=True,
         actions=(Action("douse", "⛽ Douse", "others"), Action("ignite", "🔥 Ignite all doused", None)), min_players=12),
    Role("executioner", "Executioner", "neutral", "🪓", "Get your secret target voted out. If you succeed, you win and the game ends.",
         "Convince the Town to vote out your target.",
         ("You receive a Town target at the start.", "If your target dies in another way, you become a Jester."),
         "Cast doubt on your target.", advanced=True, min_players=9),
]

ROLES: dict[str, Role] = {r.key: r for r in _R}
HOSTILE_NEUTRAL = {"serial_killer", "arsonist"}
BENIGN_NEUTRAL = {"jester", "survivor", "executioner"}
KILLER_MAFIA = {"mafia", "godfather"}


def team_of(role_key: str) -> str:
    return ROLES[role_key].team


def get(role_key: str) -> Role:
    return ROLES[role_key]


# ------------------------------------------------------------------ distribution
def mafia_size(n: int) -> int:
    return max(1, n // 4)


def distribution(n: int, advanced: bool = False, rng: random.Random | None = None) -> list[str]:
    """Balanced list of n role keys. Beginners (advanced=False) only get simple roles."""
    rng = rng or random
    m = mafia_size(n)
    mafia: list[str] = []
    if advanced:
        order = ["godfather", "mafia", "consigliere", "framer", "silencer", "consort", "janitor"]
        pool = [k for k in order if ROLES[k].min_players <= n]
        if n < 8:
            pool = ["mafia"]
        mafia = pool[:m]
        mafia += ["mafia"] * (m - len(mafia))
    else:
        mafia = ["mafia"] * m

    neutral: list[str] = []
    if advanced:
        k = 0 if n < 7 else 1 if n < 10 else 2 if n < 16 else 3 if n < 22 else 4
        pool = [r.key for r in _R if r.team == "neutral" and r.min_players <= n]
        rng.shuffle(pool)
        neutral = pool[:k]

    town_pool = [k for k in ("doctor", "detective", "bodyguard", "mayor") if ROLES[k].min_players <= n]
    specials = town_pool[:]
    if advanced:
        extra_pool = [r.key for r in _R if r.team == "town" and r.advanced and r.min_players <= n]
        rng.shuffle(extra_pool)
        specials += extra_pool[: max(0, (n - 8) // 3)]

    free = n - len(mafia) - len(neutral)
    # Town must be a clear majority over evil at the start
    while free < len(mafia) + len(neutral) + 2 and neutral:
        neutral.pop()
        free = n - len(mafia) - len(neutral)
    specials = specials[:free]
    town = specials + ["villager"] * (free - len(specials))
    roles = mafia + neutral + town
    assert len(roles) == n
    return roles


def assign_roles(user_ids: list[int], advanced: bool = False, rng: random.Random | None = None) -> dict[int, str]:
    rng = rng or random
    roles = distribution(len(user_ids), advanced, rng)
    rng.shuffle(roles)
    return dict(zip(user_ids, roles))


def validate_distribution(roles: list[str]) -> bool:
    """Every game must have a valid win path for Town and at least one killer-capable evil side."""
    teams = [team_of(r) for r in roles]
    town, mafia = teams.count("town"), teams.count("mafia")
    evil = mafia + sum(1 for r in roles if r in HOSTILE_NEUTRAL)
    return town >= 2 and mafia >= 1 and town > evil
