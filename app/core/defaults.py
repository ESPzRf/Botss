"""Стартовые наборы достижений и подписи условий."""

from __future__ import annotations

CONDITION_LABELS = {
    "messages": "Сообщения",
    "voice_minutes": "Минуты в голосе",
    "level": "Уровень",
    "loyalty": "Баллы лояльности",
    "days": "Дней на сервере",
}

CONDITION_UNITS = {
    "messages": "сообщ.",
    "voice_minutes": "мин",
    "level": "ур.",
    "loyalty": "баллов",
    "days": "дней",
}

DEFAULT_ACHIEVEMENTS: list[dict] = [
    {
        "code": "first_steps",
        "title": "Первый шаг",
        "description": "Написать первое сообщение на сервере",
        "emoji": "👋",
        "condition_type": "messages",
        "threshold": 1,
        "reward_loyalty": 10,
    },
    {
        "code": "talker_100",
        "title": "Болтун",
        "description": "Написать 100 сообщений",
        "emoji": "💬",
        "condition_type": "messages",
        "threshold": 100,
        "reward_loyalty": 50,
    },
    {
        "code": "talker_1000",
        "title": "Душа компании",
        "description": "Написать 1 000 сообщений",
        "emoji": "🗣️",
        "condition_type": "messages",
        "threshold": 1000,
        "reward_loyalty": 200,
    },
    {
        "code": "voice_60",
        "title": "В эфире",
        "description": "Провести 1 час в голосовых каналах",
        "emoji": "🎙️",
        "condition_type": "voice_minutes",
        "threshold": 60,
        "reward_loyalty": 50,
    },
    {
        "code": "voice_600",
        "title": "Голосовой ветеран",
        "description": "Провести 10 часов в голосовых каналах",
        "emoji": "📻",
        "condition_type": "voice_minutes",
        "threshold": 600,
        "reward_loyalty": 200,
    },
    {
        "code": "level_5",
        "title": "Пятый уровень",
        "description": "Достичь 5 уровня",
        "emoji": "⭐",
        "condition_type": "level",
        "threshold": 5,
        "reward_loyalty": 100,
    },
    {
        "code": "level_25",
        "title": "Ветеран сервера",
        "description": "Достичь 25 уровня",
        "emoji": "🌟",
        "condition_type": "level",
        "threshold": 25,
        "reward_loyalty": 500,
    },
    {
        "code": "loyal_500",
        "title": "Лояльный",
        "description": "Накопить 500 баллов лояльности",
        "emoji": "💎",
        "condition_type": "loyalty",
        "threshold": 500,
        "reward_loyalty": 0,
    },
    {
        "code": "days_30",
        "title": "Старожил",
        "description": "Пробыть на сервере 30 дней",
        "emoji": "📅",
        "condition_type": "days",
        "threshold": 30,
        "reward_loyalty": 200,
    },
]
