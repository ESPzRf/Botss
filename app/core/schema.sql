-- Схема базы данных Guardian (SQLite), версия 1.
-- Все временные метки хранятся строками ISO-8601 в UTC.

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id                  INTEGER PRIMARY KEY,
    name                      TEXT    NOT NULL DEFAULT '',
    icon                      TEXT,
    log_channel_id            INTEGER,
    mod_log_channel_id        INTEGER,
    events_json               TEXT    NOT NULL DEFAULT '{}',
    ignore_channels_json      TEXT    NOT NULL DEFAULT '[]',
    ignore_users_json         TEXT    NOT NULL DEFAULT '[]',
    autorole_ids_json         TEXT    NOT NULL DEFAULT '[]',
    autorole_bots             INTEGER NOT NULL DEFAULT 0,
    restore_roles             INTEGER NOT NULL DEFAULT 0,
    mute_role_id              INTEGER,
    escalations_json          TEXT    NOT NULL DEFAULT '[]',
    xp_enabled                INTEGER NOT NULL DEFAULT 1,
    xp_min                    INTEGER NOT NULL DEFAULT 15,
    xp_max                    INTEGER NOT NULL DEFAULT 25,
    xp_cooldown               INTEGER NOT NULL DEFAULT 60,
    xp_voice_per_min          INTEGER NOT NULL DEFAULT 5,
    xp_ignore_channels_json   TEXT    NOT NULL DEFAULT '[]',
    xp_ignore_roles_json      TEXT    NOT NULL DEFAULT '[]',
    level_up_channel_id       INTEGER,
    level_up_message          TEXT    NOT NULL DEFAULT '🎉 {user}, новый уровень — **{level}**!',
    level_roles_json          TEXT    NOT NULL DEFAULT '[]',
    loyalty_enabled           INTEGER NOT NULL DEFAULT 1,
    loyalty_per_message       INTEGER NOT NULL DEFAULT 1,
    loyalty_per_voice_min     INTEGER NOT NULL DEFAULT 2,
    achievements_enabled      INTEGER NOT NULL DEFAULT 1,
    achievements_channel_id   INTEGER,
    shop_enabled              INTEGER NOT NULL DEFAULT 1,
    created_at                TEXT    NOT NULL,
    updated_at                TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS warnings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    moderator_id    INTEGER NOT NULL,
    reason          TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    removed_by      INTEGER,
    removed_at      TEXT,
    removed_reason  TEXT
);
CREATE INDEX IF NOT EXISTS idx_warnings_user  ON warnings (guild_id, user_id, active);
CREATE INDEX IF NOT EXISTS idx_warnings_guild ON warnings (guild_id, active, created_at DESC);

CREATE TABLE IF NOT EXISTS cases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    moderator_id  INTEGER NOT NULL,
    kind          TEXT    NOT NULL,
    reason        TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    expires_at    TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    ended_at      TEXT,
    ended_by      INTEGER,
    end_reason    TEXT,
    extra_json    TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_cases_user   ON cases (guild_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_active ON cases (guild_id, active, expires_at);
CREATE INDEX IF NOT EXISTS idx_cases_guild  ON cases (guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS member_stats (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    xp            INTEGER NOT NULL DEFAULT 0,
    level         INTEGER NOT NULL DEFAULT 0,
    messages      INTEGER NOT NULL DEFAULT 0,
    voice_seconds INTEGER NOT NULL DEFAULT 0,
    loyalty       INTEGER NOT NULL DEFAULT 0,
    last_xp_at    TEXT,
    updated_at    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_stats_xp ON member_stats (guild_id, xp DESC);

CREATE TABLE IF NOT EXISTS member_roles (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    role_ids_json TEXT    NOT NULL DEFAULT '[]',
    updated_at    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS role_panels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER,
    title       TEXT    NOT NULL DEFAULT 'Роли',
    description TEXT    NOT NULL DEFAULT '',
    mode        TEXT    NOT NULL DEFAULT 'toggle',
    created_by  INTEGER,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_panels_guild ON role_panels (guild_id);

CREATE TABLE IF NOT EXISTS role_panel_options (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id   INTEGER NOT NULL REFERENCES role_panels (id) ON DELETE CASCADE,
    role_id    INTEGER NOT NULL,
    label      TEXT    NOT NULL DEFAULT '',
    emoji      TEXT,
    style      INTEGER NOT NULL DEFAULT 2,
    position   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (panel_id, role_id)
);

CREATE TABLE IF NOT EXISTS achievements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    code            TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    emoji           TEXT    NOT NULL DEFAULT '🏆',
    condition_type  TEXT    NOT NULL,
    threshold       INTEGER NOT NULL,
    reward_role_id  INTEGER,
    reward_loyalty  INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    UNIQUE (guild_id, code)
);
CREATE INDEX IF NOT EXISTS idx_achievements_guild ON achievements (guild_id, enabled);

CREATE TABLE IF NOT EXISTS member_achievements (
    guild_id       INTEGER NOT NULL,
    user_id        INTEGER NOT NULL,
    achievement_id INTEGER NOT NULL REFERENCES achievements (id) ON DELETE CASCADE,
    unlocked_at    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id, achievement_id)
);
CREATE INDEX IF NOT EXISTS idx_member_achievements_user ON member_achievements (guild_id, user_id);

CREATE TABLE IF NOT EXISTS shop_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    role_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    price       INTEGER NOT NULL DEFAULT 100,
    stock       INTEGER NOT NULL DEFAULT -1,
    enabled     INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_guild ON shop_items (guild_id, enabled);

CREATE TABLE IF NOT EXISTS shop_purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    item_id    INTEGER,
    price      INTEGER NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_guild ON shop_purchases (guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS web_sessions (
    token        TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    username     TEXT    NOT NULL,
    avatar       TEXT,
    guilds_json  TEXT    NOT NULL DEFAULT '[]',
    csrf         TEXT    NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON web_sessions (expires_at);
