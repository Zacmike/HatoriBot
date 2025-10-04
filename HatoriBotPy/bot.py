from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

import discord
from discord.ext import commands

from .config import settings
from .db import add_currency_for_message, add_currency_for_voice, init_db
from views.voice import VoiceWelcomeView


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HatoriBotPy")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # type: ignore[override]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is running!\n")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _start_keepalive_server() -> None:
    try:
        server = ThreadingHTTPServer(("0.0.0.0", settings.KEEPALIVE_PORT), _HealthHandler)
    except Exception:
        logger.exception("Не удалось запустить keepalive-сервер")
        return

    thread = threading.Thread(target=server.serve_forever, name="KeepAliveServer", daemon=True)
    thread.start()
    logger.info("Keepalive-сервер запущен на порту %s", settings.KEEPALIVE_PORT)


class HatoriBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)

        self._message_ts: Dict[int, float] = {}
        self._voice_reward_tasks: Dict[int, asyncio.Task[None]] = {}
        self._voice_channels_file = Path("data") / "channels.json"
        self._voice_message_channels = self._load_voice_channels()

    async def setup_hook(self) -> None:
        await init_db()
        for ext in (
            "HatoriBotPy.cogs.balance",
            "HatoriBotPy.cogs.custom_game",
            "HatoriBotPy.cogs.shop",
        ):
            try:
                await self.load_extension(ext)
                logger.info("Загружено расширение: %s", ext)
            except Exception:
                logger.exception("Не удалось загрузить расширение %s", ext)
        await self.sync_commands()

    async def on_ready(self) -> None:
        logger.info("Вошел в систему как %s (%s)", self.user, self.user.id if self.user else "-" )

    async def sync_commands(self) -> None:
        try:
            if settings.GUILD_ID:
                guild_obj = discord.Object(id=settings.GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(
                    "Синхронизировано %d команд с гильдией %s",
                    len(synced),
                    settings.GUILD_ID,
                )
            else:
                synced = await self.tree.sync()
                logger.info("Синхронизировано %d глобальных команд", len(synced))
        except Exception:
            logger.exception("Не удалось синхронизировать команды")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        now = time.monotonic()
        uid = message.author.id
        last = self._message_ts.get(uid, 0.0)
        cooldown = settings.MESSAGE_COOLDOWN_MS / 1000.0

        if now - last >= cooldown:
            try:
                await add_currency_for_message(uid, settings.MESSAGE_REWARD_AMOUNT)
                self._message_ts[uid] = now
            except Exception:
                logger.exception("Не удалось добавить валюту за сообщение")

        await self.process_commands(message)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or member.guild is None:
            return

        new_channel = after.channel
        old_channel = before.channel

        if old_channel and (new_channel is None or new_channel.id != old_channel.id):
            self._stop_voice_reward(member.id)

        if not new_channel or new_channel.type not in {
            discord.ChannelType.voice,
            discord.ChannelType.stage_voice,
        }:
            return

        await self._send_voice_welcome(new_channel)

        if member.id not in self._voice_reward_tasks:
            self._start_voice_reward(member.id)

    def _load_voice_channels(self) -> set[int]:
        try:
            if self._voice_channels_file.is_file():
                with self._voice_channels_file.open("r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    return {int(cid) for cid in data}
        except Exception:
            logger.exception("Не удалось загрузить список обработанных голосовых каналов")
        return set()

    def _save_voice_channels(self) -> None:
        try:
            self._voice_channels_file.parent.mkdir(parents=True, exist_ok=True)
            with self._voice_channels_file.open("w", encoding="utf-8") as fp:
                json.dump(sorted(self._voice_message_channels), fp, ensure_ascii=False)
        except Exception:
            logger.exception("Не удалось сохранить список обработанных голосовых каналов")

    async def _send_voice_welcome(self, channel: discord.abc.GuildChannel) -> None:
        channel_id = getattr(channel, "id", None)
        if channel_id is None or channel_id in self._voice_message_channels:
            return

        view = VoiceWelcomeView()
        try:
            await channel.send(
                "Добро пожаловать в голосовой канал! Выберите действие ниже:",
                view=view,
            )
            self._voice_message_channels.add(channel_id)
            self._save_voice_channels()
        except Exception:
            logger.exception("Не удалось отправить приветствие в голосовой канал")

    def _start_voice_reward(self, user_id: int) -> None:
        if user_id in self._voice_reward_tasks:
            return

        async def runner() -> None:
            interval = max(1, int(settings.VOICE_REWARD_INTERVAL))
            amount = settings.VOICE_REWARD_AMOUNT
            try:
                await add_currency_for_voice(user_id, amount)
                logger.info("Начислено %s валюты за вход в голосовой канал", amount)
                while True:
                    await asyncio.sleep(interval)
                    await add_currency_for_voice(user_id, amount)
                    logger.debug(
                        "Начислено %s валюты пользователю %s за активность в голосе",
                        amount,
                        user_id,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Не удалось начислить валюту за активность в голосе")

        task = self.loop.create_task(runner())
        self._voice_reward_tasks[user_id] = task

    def _stop_voice_reward(self, user_id: int) -> None:
        task = self._voice_reward_tasks.pop(user_id, None)
        if task is None:
            return
        task.cancel()


def main() -> None:
    bot = HatoriBot()
    _start_keepalive_server()
    bot.run(settings.DISCORD_TOKEN)


if __name__ == "__main__":
    main()