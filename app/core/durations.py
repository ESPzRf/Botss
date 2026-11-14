"""Разбор и форматирование длительностей наказаний."""

from __future__ import annotations

import re

_PERMANENT = {
    "perm",
    "permanent",
    "forever",
    "inf",
    "infinity",
    "навсегда",
    "бессрочно",
    "вечно",
    "0",
}

_UNITS: dict[str, int] = {
    # секунды
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "с": 1, "сек": 1, "секунда": 1, "секунды": 1, "секунд": 1,
    # минуты
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "м": 60, "мин": 60, "минута": 60, "минуты": 60, "минут": 60,
    # часы
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
    # дни
    "d": 86400, "day": 86400, "days": 86400,
    "д": 86400, "день": 86400, "дня": 86400, "дней": 86400, "сутки": 86400,
    # недели
    "w": 604800, "week": 604800, "weeks": 604800,
    "н": 604800, "нед": 604800, "неделя": 604800, "недели": 604800, "недель": 604800,
}

_TOKEN_RE = re.compile(r"(\d+)\s*([a-zA-Zа-яА-ЯёЁ]+)")
_MAX_SECONDS = 10 * 365 * 86400


class DurationError(ValueError):
    """Некорректная строка длительности."""


def parse_duration(raw: str) -> int | None:
    """Превращает ``1d 2h 30m`` в секунды. ``None`` — бессрочно.

    Поддерживаются английские и русские единицы, пробелы и запятые.
    Число без единицы считается минутами.
    """
    text = raw.strip().lower().replace("ё", "е")
    if not text:
        raise DurationError("Укажите длительность, например 1h 30m или 7d.")
    if text in _PERMANENT:
        return None
    if text.isdigit():
        seconds = int(text) * 60
        if seconds <= 0:
            raise DurationError("Длительность должна быть больше нуля.")
        return seconds

    matches = list(_TOKEN_RE.finditer(text))
    if not matches:
        raise DurationError("Не удалось распознать длительность. Пример: 1h 30m, 7d.")

    total = 0
    consumed_from = 0
    for match in matches:
        gap = text[consumed_from:match.start()]
        if gap.replace(" ", "").replace(",", "").replace(";", ""):
            raise DurationError(f"Лишние символы в длительности: «{gap.strip()}».")
        amount = int(match.group(1))
        unit = match.group(2)
        if unit not in _UNITS:
            raise DurationError(f"Неизвестная единица «{unit}». Используйте s, m, h, d, w.")
        total += amount * _UNITS[unit]
        consumed_from = match.end()

    tail = text[consumed_from:].replace(" ", "").replace(",", "").replace(";", "")
    if tail:
        raise DurationError("Каждое число должно иметь единицу измерения: 30m, 12h, 7d.")

    if total <= 0:
        raise DurationError("Длительность должна быть больше нуля.")
    if total > _MAX_SECONDS:
        raise DurationError("Слишком большая длительность (максимум 10 лет).")
    return total


def plural_ru(number: int, forms: tuple[str, str, str]) -> str:
    """1 день / 2 дня / 5 дней."""
    number = abs(number) % 100
    if 11 <= number <= 19:
        return forms[2]
    last = number % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def format_duration(seconds: int | None, *, short: bool = True) -> str:
    """Человекочитаемая длительность."""
    if seconds is None:
        return "бессрочно"
    seconds = max(0, int(seconds))
    if seconds == 0:
        return "0 сек"

    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days} {plural_ru(days, ('день', 'дня', 'дней'))}" if not short else f"{days} д")
    if hours:
        parts.append(f"{hours} {plural_ru(hours, ('час', 'часа', 'часов'))}" if not short else f"{hours} ч")
    if minutes and not (short and days):
        parts.append(f"{minutes} {plural_ru(minutes, ('минута', 'минуты', 'минут'))}" if not short else f"{minutes} мин")
    if secs and not days and not hours and not minutes:
        parts.append(f"{secs} {plural_ru(secs, ('секунда', 'секунды', 'секунд'))}" if not short else f"{secs} сек")
    return " ".join(parts) if parts else "0 сек"
