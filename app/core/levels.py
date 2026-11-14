"""Формула уровней и прогресса опыта."""

from __future__ import annotations

BASE_XP = 100


def xp_for_level(level: int) -> int:
    """Суммарный опыт, необходимый для достижения уровня."""
    if level <= 0:
        return 0
    return BASE_XP * level * (level + 1) // 2


def level_for_xp(xp: int) -> int:
    """Уровень по суммарному опыту."""
    xp = max(0, int(xp))
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def level_progress(xp: int) -> tuple[int, int, int, int]:
    """(уровень, опыт внутри уровня, нужно для следующего, процент 0..100)."""
    xp = max(0, int(xp))
    level = level_for_xp(xp)
    current = xp - xp_for_level(level)
    needed = xp_for_level(level + 1) - xp_for_level(level)
    percent = int(current / needed * 100) if needed else 100
    return level, current, needed, min(100, max(0, percent))


def progress_bar(percent: int, length: int = 10) -> str:
    filled = round(length * max(0, min(100, percent)) / 100)
    return "█" * filled + "░" * (length - filled)


def format_number(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")
