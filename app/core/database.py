"""Асинхронная обёртка над sqlite3.

Одно соединение + блокировка: для нагрузки Discord-бота этого достаточно,
а WAL-режим позволяет читать базу извне (например, из скриптов) без блокировок.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TypeVar

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
T = TypeVar("T")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,  # autocommit; транзакции задаём явно
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")

        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version < SCHEMA_VERSION:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("База данных ещё не подключена")
        return self._conn

    async def close(self) -> None:
        if self._conn is None:
            return
        conn, self._conn = self._conn, None
        await asyncio.to_thread(conn.close)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._execute_sync, sql, params)

    def _execute_sync(self, sql: str, params: Sequence[Any]) -> int:
        cursor = self.conn.execute(sql, params)
        return int(cursor.lastrowid or 0)

    async def execute_count(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Выполняет UPDATE/DELETE и возвращает количество затронутых строк."""
        async with self._lock:
            return await asyncio.to_thread(self._execute_count_sync, sql, params)

    def _execute_count_sync(self, sql: str, params: Sequence[Any]) -> int:
        cursor = self.conn.execute(sql, params)
        return int(cursor.rowcount)

    async def executemany(self, sql: str, params: Iterable[Sequence[Any]]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._executemany_sync, sql, list(params))

    def _executemany_sync(self, sql: str, params: list[Sequence[Any]]) -> None:
        with self.conn:
            self.conn.executemany(sql, params)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        async with self._lock:
            return await asyncio.to_thread(
                lambda: self.conn.execute(sql, params).fetchone()
            )

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(
                lambda: self.conn.execute(sql, params).fetchall()
            )

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = 0) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    async def run_tx(self, callback: Callable[[sqlite3.Connection], T]) -> T:
        """Выполняет синхронный колбэк в одной транзакции BEGIN IMMEDIATE."""

        async with self._lock:
            return await asyncio.to_thread(self._run_tx_sync, callback)

    def _run_tx_sync(self, callback: Callable[[sqlite3.Connection], T]) -> T:
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = callback(conn)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return result

    async def checkpoint(self) -> None:
        """Сбрасывает WAL на диск (полезно перед бэкапом)."""
        async with self._lock:
            await asyncio.to_thread(lambda: self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"))
