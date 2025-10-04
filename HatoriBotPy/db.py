from __future__ import annotations

from typing import Any, Optional

import asyncpg

from HatoriBotPy.config import settings
import logging


logger = logging.getLogger("HatoriBotPy.db")


_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        logger.info("Подключение к базе данных %s", settings.DATABASE_URL)
        try:
            _pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=10)
        except Exception:
            logger.exception("Не удалось создать пул подключений к базе данных")
            raise
        else:
            logger.info("Пул подключений к базе данных создан")
    return _pool


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                game_id TEXT NOT NULL,
                team INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                item_key TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price INTEGER NOT NULL,
                purchased_at TIMESTAMP DEFAULT NOW()
            );
            """
        )


async def query(sql: str, *params: Any) -> list[asyncpg.Record]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *params)


async def execute(sql: str, *params: Any) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *params)


async def get_user_balance(user_id: int | str) -> int:
    uid = str(user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM users WHERE id=$1", uid)

            if row is None:
                await conn.execute("INSERT INTO users (id, balance) VALUES ($1, 0)", uid)
                return 0

            return int(row["balance"])


async def set_user_balance(user_id: int | str, balance: int) -> bool:
    uid = str(user_id)
    result = await execute("UPDATE users SET balance = $1 WHERE id = $2", balance, uid)
    return result.upper().startswith("UPDATE")


async def add_currency(user_id: int | str, amount: int) -> int:
    uid = str(user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (id, balance) VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET balance = users.balance + EXCLUDED.balance
            RETURNING balance
            """,
            uid,
            amount,
        )
        return int(row["balance"]) if row else 0


async def add_currency_for_message(user_id: int | str, amount: int) -> int:
    return await add_currency(user_id, amount)


async def add_currency_for_voice(user_id: int | str, amount: int) -> int:
    return await add_currency(user_id, amount)


async def create_bet(user_id: int | str, game_id: str, team: int, amount: int) -> bool:
    uid = str(user_id)
    try:
        await execute(
            "INSERT INTO bets (user_id, game_id, team, amount) VALUES ($1, $2, $3, $4)",
            uid,
            game_id,
            team,
            amount,
        )
        return True
    except Exception:
        return False


async def get_bets_for_game(game_id: str) -> list[asyncpg.Record]:
    return await query("SELECT user_id, team, amount FROM bets WHERE game_id = $1", game_id)


async def record_purchase(user_id: int | str, item_key: str, item_name: str, price: int) -> None:
    uid = str(user_id)
    await execute(
        "INSERT INTO purchases (user_id, item_key, item_name, price) VALUES ($1, $2, $3, $4)",
        uid,
        item_key,
        item_name,
        price,
    )


async def clear_bets_for_game(game_id: str) -> None:
    await execute("DELETE FROM bets WHERE game_id = $1", game_id)

