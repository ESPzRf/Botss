"""Справочник событий логирования: группы, подписи и значения по умолчанию."""

from __future__ import annotations

# (ключ, название, короткое описание)
EventMeta = tuple[str, str, str]

EVENT_GROUPS: list[tuple[str, list[EventMeta]]] = [
    (
        "Участники",
        [
            ("member_join", "Вход участника", "Кто зашёл на сервер и возраст аккаунта"),
            ("member_leave", "Выход участника", "Кто покинул сервер и когда зашёл"),
            ("member_update", "Изменение участника", "Смена никнейма и ролей"),
        ],
    ),
    (
        "Сообщения",
        [
            ("message_delete", "Удаление сообщения", "Автор, канал и содержимое"),
            ("message_edit", "Редактирование сообщения", "Что было и что стало"),
            ("message_bulk_delete", "Массовое удаление", "Пачка удалённых сообщений"),
        ],
    ),
    (
        "Голосовые каналы",
        [
            ("voice_join", "Вход в голосовой канал", "Подключение к каналу"),
            ("voice_leave", "Выход из голосового канала", "Отключение от канала"),
            ("voice_move", "Перемещение между каналами", "Переход из канала в канал"),
        ],
    ),
    (
        "Каналы",
        [
            ("channel_create", "Создание канала", "Новый текстовый или голосовой канал"),
            ("channel_delete", "Удаление канала", "Канал удалён"),
            ("channel_update", "Изменение канала", "Название, тема, медленный режим"),
        ],
    ),
    (
        "Роли",
        [
            ("role_create", "Создание роли", "Новая роль на сервере"),
            ("role_delete", "Удаление роли", "Роль удалена"),
            ("role_update", "Изменение роли", "Название, цвет, права"),
        ],
    ),
    (
        "Модерация",
        [
            ("mod_action", "Действия модераторов", "Предупреждения, муты, баны и кики"),
            ("ban", "Бан участника", "Участник забанен"),
            ("unban", "Разбан участника", "Участник разбанен"),
        ],
    ),
    (
        "Приглашения",
        [
            ("invite_create", "Создание приглашения", "Кто создал инвайт"),
            ("invite_delete", "Удаление приглашения", "Инвайт больше не действует"),
        ],
    ),
    (
        "Ветки",
        [
            ("thread_create", "Создание ветки", "Новая ветка в канале"),
            ("thread_delete", "Удаление ветки", "Ветка удалена"),
        ],
    ),
    (
        "Сервер",
        [
            ("guild_update", "Изменение сервера", "Название, иконка, описание"),
            ("emoji_update", "Изменение эмодзи", "Добавлены или удалены эмодзи"),
        ],
    ),
]

EVENT_LABELS: dict[str, str] = {
    key: label for _, events in EVENT_GROUPS for key, label, _ in events
}
EVENT_DESCRIPTIONS: dict[str, str] = {
    key: description for _, events in EVENT_GROUPS for key, _, description in events
}

DEFAULT_EVENTS: dict[str, bool] = {key: True for key in EVENT_LABELS}
DEFAULT_EVENTS.update(
    {
        "voice_move": False,
        "channel_update": False,
        "role_update": False,
        "invite_create": False,
        "invite_delete": False,
        "emoji_update": False,
    }
)

ALL_EVENT_KEYS: tuple[str, ...] = tuple(EVENT_LABELS)
