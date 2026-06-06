"""
Модуль для работы с базой данных SQLite (через aiosqlite).
Содержит функции инициализации и CRUD-операции для предупреждений и экономики.
"""

import datetime
import logging

import aiosqlite

from config import Config

logger = logging.getLogger("database")
DB_PATH = Config.DB_PATH


async def init_db() -> None:
    """Создаёт таблицы, если они не существуют."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица предупреждений
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id  INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,
                mod_id    INTEGER NOT NULL,
                reason    TEXT    NOT NULL,
                created_at TEXT   NOT NULL
            )
        """)

        # Таблица баланса игроков
        await db.execute("""
            CREATE TABLE IF NOT EXISTS economy (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                balance     INTEGER NOT NULL DEFAULT 100,
                last_daily  TEXT,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        await db.commit()
    logger.info("Таблицы БД проверены / созданы.")


# ─────────────────────── WARNINGS ───────────────────────

async def add_warning(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    """
    Добавляет предупреждение в БД.
    Возвращает общее количество предупреждений пользователя.
    """
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?,?,?,?,?)",
            (guild_id, user_id, mod_id, reason, now),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
    return row[0] if row else 1


async def get_warnings(guild_id: int, user_id: int) -> list[dict]:
    """Возвращает список предупреждений пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id ASC",
            (guild_id, user_id),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def clear_warnings(guild_id: int, user_id: int) -> None:
    """Удаляет все предупреждения пользователя (после автобана)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.commit()


# ─────────────────────── ECONOMY ───────────────────────

async def get_balance(guild_id: int, user_id: int) -> int:
    """Возвращает баланс пользователя, создаёт запись при первом обращении."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Создаём запись с начальным балансом, если её нет
        await db.execute(
            "INSERT OR IGNORE INTO economy (guild_id, user_id, balance) VALUES (?,?,?)",
            (guild_id, user_id, Config.STARTING_BALANCE),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT balance FROM economy WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
    return row[0] if row else Config.STARTING_BALANCE


async def update_balance(guild_id: int, user_id: int, amount: int) -> int:
    """
    Изменяет баланс на указанное значение (может быть отрицательным).
    Возвращает новый баланс.
    """
    # Убеждаемся, что запись существует
    await get_balance(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE economy SET balance = balance + ? WHERE guild_id=? AND user_id=?",
            (amount, guild_id, user_id),
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT balance FROM economy WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
    return row[0] if row else 0


async def set_balance(guild_id: int, user_id: int, amount: int) -> None:
    """Устанавливает точное значение баланса."""
    await get_balance(guild_id, user_id)  # создаём запись если нет
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE economy SET balance=? WHERE guild_id=? AND user_id=?",
            (amount, guild_id, user_id),
        )
        await db.commit()


async def get_last_daily(guild_id: int, user_id: int) -> datetime.datetime | None:
    """Возвращает дату последнего получения ежедневного бонуса."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT last_daily FROM economy WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()
    if row and row[0]:
        return datetime.datetime.fromisoformat(row[0])
    return None


async def set_last_daily(guild_id: int, user_id: int) -> None:
    """Обновляет время последнего получения бонуса."""
    await get_balance(guild_id, user_id)
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE economy SET last_daily=? WHERE guild_id=? AND user_id=?",
            (now, guild_id, user_id),
        )
        await db.commit()


async def get_top(guild_id: int, limit: int = 10) -> list[dict]:
    """Возвращает топ-N богатейших игроков на сервере."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, balance FROM economy WHERE guild_id=? ORDER BY balance DESC LIMIT ?",
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]
