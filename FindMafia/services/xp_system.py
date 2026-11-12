"""XP / level maths (DB writes for rewards are added with the end-of-game logic)."""
import math

XP = {"participate": 10, "win": 25, "survive": 5, "elimination": 3, "daily": 15}


def level_for(xp: int) -> int:
    return 1 + int(math.sqrt(max(0, xp) / 100))


def xp_for_level(level: int) -> int:
    return 100 * (level - 1) ** 2


def progress(xp: int) -> tuple[int, int, int]:
    """(level, xp_into_level, xp_needed_for_next)"""
    lv = level_for(xp)
    base = xp_for_level(lv)
    return lv, xp - base, xp_for_level(lv + 1) - base


def bar(done: int, total: int, width: int = 10) -> str:
    filled = 0 if total <= 0 else min(width, int(width * done / total))
    return "▰" * filled + "▱" * (width - filled)
