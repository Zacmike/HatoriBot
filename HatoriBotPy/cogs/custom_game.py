from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Set

import discord
from discord import app_commands
from discord.ext import commands

from ..config import settings
from ..db import (
    add_currency_for_message,
    clear_bets_for_game,
    get_bets_for_game,
    get_user_balance,
    set_user_balance,
)
from ..utils import get_team_names
from views.betting import BetView, WinnerView

VALORANT_MAPS = [
    {
        "name": "Ascent",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/5cb7e65c04a489eccd725ce693fdc11e99982e10-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Bind",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/7df1e6ee284810ef0cbf8db369c214a8cbf6578c-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Breeze",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/a4a0374222f9cc79f97e03dbb1122056e794176a-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Fracture",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/983a6d66978aabd3ccd4e51517298d9a0b5467d9-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Haven",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/bccc7b5f8647a4f654d4bb359247bce6e82c77ab-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Icebox",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/72853f583a0f6b25aed54870531756483a7b61de-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Split",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/878d51688c0f9dd0de827162e80c40811668e0c6-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Pearl",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/7ba5df090f5efee7988d8d33f4b43c3441cb1aab-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Lotus",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/67d199e0f7108bc60e8293d3f9a37538b0b55b11-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Sunset",
        "image": "https://cmsassets.rgpub.io/sanity/images/dsfx7636/news/5101e4ee241fbfca261bf8150230236c46c8b991-3840x2160.png?auto=format&fit=fill&q=80&w=1520",
    },
    {
        "name": "Abyss",
        "image": "https://imgsvc.trackercdn.com/url/size(1280x720),fit(cover),quality(100)/https%3A%2F%2Ftrackercdn.com%2Fghost%2Fimages%2F2024%2F6%2F9164_GPl-Uy0XIAEaY0n.jpg/image.jpg",
    },
]

MAX_PARTICIPANTS = 10
RECRUITMENT_TIMEOUT = 600
BET_COLLECTION_TIMEOUT = 180
GAME_DURATION_TIMEOUT = 3600
PARTICIPATION_REWARD = 100


@dataclass
class GameSession:
    game: str
    channel_id: int
    message_id: int
    manager_id: int
    team_names: tuple[str, str]
    voice_channel_id: Optional[int]
    participants: Set[int] = field(default_factory=set)
    recruitment_task: Optional[asyncio.Task] = None
    recruitment_view: Optional["RecruitmentView"] = None
    bets_open: bool = False
    bet_view: Optional[BetView] = None
    bet_view_message_id: Optional[int] = None
    bet_summary_message_id: Optional[int] = None
    bet_close_task: Optional[asyncio.Task] = None
    game_id: str = ""
    finished: bool = False
    game_close_task: Optional[asyncio.Task] = None
    winner_view_message_id: Optional[int] = None
    winner_view: Optional[WinnerView] = None


class RecruitmentView(discord.ui.View):
    def __init__(self, cog: "CustomGame", initiator_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.initiator_id = initiator_id
        self.message_id: Optional[int] = None

    def attach(self, message_id: int) -> None:
        self.message_id = message_id

    def disable_all_items(self) -> None:
        for child in self.children:
            child.disabled = True
        super().stop()

    async def _has_permission(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.id == self.initiator_id:
            return True
        return self.cog._is_manager(interaction.user)

    @discord.ui.button(label="Завершить набор", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._has_permission(interaction):
            await interaction.response.send_message("Недостаточно прав для завершения набора.", ephemeral=True)
            return
        if self.message_id is None:
            await interaction.response.send_message("Сессия не найдена.", ephemeral=True)
            return
        session = self.cog.sessions.get(self.message_id)
        if not session:
            await interaction.response.send_message("Сессия уже завершена.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.cog.finish_recruitment(session, interaction)


class CustomGame(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions: Dict[int, GameSession] = {}
        self.channel_index: Dict[int, int] = {}

    def _is_manager(self, member: discord.Member) -> bool:
        manager_role = settings.CUSTOM_GAME_MANAGER_ROLE_ID
        if manager_role and any(role.id == manager_role for role in member.roles):
            return True
        admin_role = settings.ADMIN_ROLE_ID
        return bool(admin_role and any(role.id == admin_role for role in member.roles))

    @app_commands.command(name="customgame", description="Запустить набор на кастомную игру")
    @app_commands.describe(game="Название игры (Valorant, Dota 2, LoL, CS)")
    async def customgame(self, interaction: discord.Interaction, game: str) -> None:
        if not isinstance(interaction.user, discord.Member) or not self._is_manager(interaction.user):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return

        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("Команда недоступна в этом контексте.", ephemeral=True)
            return

        if channel.id in self.channel_index:
            await interaction.response.send_message("В этом канале уже идет набор на кастомную игру.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        team_names = tuple(get_team_names(game))
        voice_channel_id = getattr(getattr(interaction.user.voice, "channel", None), "id", None)

        view = RecruitmentView(self, interaction.user.id)
        embed = self._build_recruitment_embed(game, team_names, set())
        message = await channel.send(embed=embed, view=view)
        await message.add_reaction("🎮")

        session = GameSession(
            game=game,
            channel_id=channel.id,
            message_id=message.id,
            manager_id=interaction.user.id,
            team_names=team_names,
            voice_channel_id=voice_channel_id,
        )
        session.game_id = f"{channel.id}:{message.id}"
        session.recruitment_view = view

        view.attach(message.id)

        self.sessions[message.id] = session
        self.channel_index[channel.id] = message.id

        session.recruitment_task = self.bot.loop.create_task(self._auto_close(session))

        await interaction.followup.send("Набор запущен. Реагируйте на 🎮, чтобы участвовать.", ephemeral=True)

    async def _auto_close(self, session: GameSession) -> None:
        try:
            await asyncio.sleep(RECRUITMENT_TIMEOUT)
        except asyncio.CancelledError:
            return
        await self.finish_recruitment(session, None)

    async def finish_recruitment(self, session: GameSession, interaction: Optional[discord.Interaction]) -> None:
        if session.finished:
            return
        session.finished = True

        if session.recruitment_task:
            session.recruitment_task.cancel()
            session.recruitment_task = None

        channel = self.bot.get_channel(session.channel_id)
        if not isinstance(channel, discord.TextChannel):
            self._cleanup_session(session)
            return

        try:
            message = await channel.fetch_message(session.message_id)
        except discord.NotFound:
            self._cleanup_session(session)
            return

        if session.recruitment_view:
            session.recruitment_view.disable_all_items()
            try:
                await message.edit(view=session.recruitment_view)
            except discord.HTTPException:
                pass

        participants = list(session.participants)
        if len(participants) < 2:
            embed = discord.Embed(
                title=f"Набор на {session.game}",
                description="Недостаточно участников для начала игры.",
                color=discord.Color.red(),
            )
            await message.edit(embed=embed)
            self._cleanup_session(session)
            return

        random.shuffle(participants)
        limited_participants = participants[:MAX_PARTICIPANTS]

        for user_id in limited_participants:
            try:
                await add_currency_for_message(user_id, PARTICIPATION_REWARD)
            except Exception:
                continue

        team_one = limited_participants[::2]
        team_two = limited_participants[1::2]

        map_info = random.choice(VALORANT_MAPS) if session.game.lower() == "valorant" else None
        distribution_embed = self._build_distribution_embed(session, team_one, team_two, map_info)
        await channel.send(embed=distribution_embed)

        await self._move_players(session, team_one, team_two, channel.guild)

        await self._start_betting(session, channel)

    async def _start_betting(self, session: GameSession, channel: discord.TextChannel) -> None:
        async def _bet_callback(_: discord.Interaction, __: int, ___: int) -> None:
            await self._update_bets_summary(session)

        async def _bet_refund(interaction: discord.Interaction) -> None:
            await self._handle_bet_refund(session, interaction)

        bet_view = BetView(
            session.team_names[0],
            session.team_names[1],
            session.game_id,
            on_bet=_bet_callback,
            on_refund=_bet_refund,
        )
        session.bet_view = bet_view
        session.bets_open = True

        bet_embed = discord.Embed(
            title=f"Ставки на {session.game}",
            description=(
                f"**{session.team_names[0]}** vs **{session.team_names[1]}**\n\n"
                f"Ставки открыты на {BET_COLLECTION_TIMEOUT // 60} минуты."
            ),
            color=discord.Color.gold(),
        )

        bet_message = await channel.send(embed=bet_embed, view=bet_view)
        session.bet_view_message_id = bet_message.id

        await self._update_bets_summary(session)

        session.bet_close_task = self.bot.loop.create_task(self._auto_close_bets(session, channel))
        if session.game_close_task:
            session.game_close_task.cancel()
        session.game_close_task = self.bot.loop.create_task(self._auto_close_game(session))

    async def _auto_close_bets(self, session: GameSession, channel: discord.TextChannel) -> None:
        try:
            await asyncio.sleep(BET_COLLECTION_TIMEOUT)
        except asyncio.CancelledError:
            return
        await self._close_bets(session, channel)

    async def _close_bets(self, session: GameSession, channel: discord.TextChannel) -> None:
        if not session.bets_open:
            return
        await self._cancel_open_bets(session, channel, status=None)

        async def _finalize_callback(interaction: discord.Interaction, team_name: str) -> None:
            await self._finalize_session(session, interaction, f"Победила {team_name}")

        async def _refund_callback(interaction: discord.Interaction) -> None:
            await self._finalize_session(session, interaction, "Ставки возвращены")

        winner_view = WinnerView(
            session.team_names[0],
            session.team_names[1],
            session.game_id,
            on_finalize=_finalize_callback,
            on_refund=_refund_callback,
        )

        session.winner_view = winner_view
        winner_message = await channel.send("Ставки закрыты. Выберите исход:", view=winner_view)
        session.winner_view_message_id = winner_message.id

    async def _cancel_open_bets(
        self,
        session: GameSession,
        channel: discord.TextChannel,
        status: Optional[str],
    ) -> None:
        session.bets_open = False

        if session.bet_close_task:
            session.bet_close_task.cancel()
            session.bet_close_task = None

        if session.bet_view:
            session.bet_view.close()
            if session.bet_view_message_id:
                try:
                    message = await channel.fetch_message(session.bet_view_message_id)
                    await message.edit(view=session.bet_view)
                except discord.HTTPException:
                    pass

        await self._update_bets_summary(session, closed=True, status=status)

    async def _handle_bet_refund(self, session: GameSession, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Невозможно вернуть ставки в этом контексте.", ephemeral=True)
            return

        status_message = "Ставки возвращены администратором."
        await self._cancel_open_bets(session, channel, status=status_message)
        refunded = await self._refund_all_bets(session)

        if refunded:
            await interaction.followup.send("Все ставки возвращены игрокам.", ephemeral=True)
            await channel.send("Ставки на игру возвращены администратором.")
        else:
            await interaction.followup.send("Активных ставок не найдено.", ephemeral=True)

        await self._update_bets_summary(session, closed=True, status=status_message if refunded else "Ставок не было.")

        self._cleanup_session(session)

    async def _refund_all_bets(self, session: GameSession) -> bool:
        bets = await get_bets_for_game(session.game_id)
        if not bets:
            await clear_bets_for_game(session.game_id)
            return False

        for bet in bets:
            current_balance = await get_user_balance(bet["user_id"])
            await set_user_balance(bet["user_id"], current_balance + int(bet["amount"]))

        await clear_bets_for_game(session.game_id)
        return True

    async def _auto_close_game(self, session: GameSession) -> None:
        try:
            await asyncio.sleep(GAME_DURATION_TIMEOUT)
        except asyncio.CancelledError:
            return

        current = self.sessions.get(session.message_id)
        if current is not session:
            return

        channel = self.bot.get_channel(session.channel_id)
        if not isinstance(channel, discord.TextChannel):
            self._cleanup_session(session)
            return

        if session.bets_open:
            await self._cancel_open_bets(session, channel, status="Игра автоматически закрыта. Ставки возвращены.")
        else:
            await self._update_bets_summary(session, closed=True, status="Игра автоматически закрыта.")

        if session.winner_view and session.winner_view_message_id:
            try:
                message = await channel.fetch_message(session.winner_view_message_id)
                session.winner_view.disable_all_items()
                await message.edit(view=session.winner_view)
            except discord.HTTPException:
                pass

        refunded = await self._refund_all_bets(session)

        final_status = "Игра автоматически закрыта. Ставки возвращены." if refunded else "Игра автоматически закрыта."
        await self._update_bets_summary(session, closed=True, status=final_status)

        if refunded:
            await channel.send("Игра автоматически закрыта. Все ставки возвращены.")
        else:
            await channel.send("Игра автоматически закрыта.")

        self._cleanup_session(session)

    async def _finalize_session(self, session: GameSession, interaction: discord.Interaction, status: str) -> None:
        await self._update_bets_summary(session, closed=True, status=status)
        try:
            await interaction.channel.send(status)
        except Exception:
            pass
        self._cleanup_session(session)

    def _cleanup_session(self, session: GameSession) -> None:
        self.sessions.pop(session.message_id, None)
        self.channel_index.pop(session.channel_id, None)
        if session.recruitment_task and not session.recruitment_task.done():
            session.recruitment_task.cancel()
        if session.bet_close_task and not session.bet_close_task.done():
            session.bet_close_task.cancel()
        if session.game_close_task and not session.game_close_task.done():
            session.game_close_task.cancel()
        session.winner_view = None
        session.winner_view_message_id = None

    async def _update_bets_summary(
        self,
        session: GameSession,
        closed: bool = False,
        status: Optional[str] = None,
    ) -> None:
        channel_id = settings.BETS_CHANNEL_ID
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = await self._build_bets_embed(session, closed=closed, status=status)

        try:
            if session.bet_summary_message_id:
                message = await channel.fetch_message(session.bet_summary_message_id)
                await message.edit(embed=embed)
            else:
                message = await channel.send(embed=embed)
                session.bet_summary_message_id = message.id
        except discord.HTTPException:
            pass

    async def _build_bets_embed(
        self,
        session: GameSession,
        closed: bool,
        status: Optional[str],
    ) -> discord.Embed:
        bets = await get_bets_for_game(session.game_id)
        totals = {1: 0, 2: 0}
        counts = {1: 0, 2: 0}
        total_amount = 0
        for bet in bets:
            team = int(bet["team"])
            amount = int(bet["amount"])
            totals[team] += amount
            counts[team] += 1
            total_amount += amount

        embed = discord.Embed(
            title=f"Ставки на {session.game}",
            color=discord.Color.gold() if not closed else discord.Color.darker_grey(),
        )
        if status:
            embed.description = status
        elif closed:
            embed.description = "Прием ставок завершен."
        else:
            embed.description = "Ставки открыты."

        embed.add_field(name="Всего ставок", value=str(total_amount), inline=False)

        for index, team_name in enumerate(session.team_names, start=1):
            team_total = totals[index]
            team_count = counts[index]
            if team_total:
                coefficient = total_amount / team_total if team_total else 0
                value = (
                    f"Ставок: {team_count}\n"
                    f"Сумма: {team_total} монет\n"
                    f"Коэффициент: {coefficient:.2f}"
                )
            else:
                value = "Ставок нет"
            embed.add_field(name=team_name, value=value, inline=True)

        return embed

    def _build_recruitment_embed(
        self,
        game: str,
        team_names: tuple[str, str],
        participants: Set[int],
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Набор на {game}",
            description="Реагируйте на 🎮, чтобы участвовать.",
            color=discord.Color.blue(),
        )
        if participants:
            mentions = []
            for uid in list(participants)[:MAX_PARTICIPANTS]:
                user = self.bot.get_user(uid)
                mentions.append(user.mention if user else f"<@{uid}>")
            if len(participants) > MAX_PARTICIPANTS:
                mentions.append(f"... и еще {len(participants) - MAX_PARTICIPANTS}")
            embed.add_field(
                name=f"Участники ({len(participants)})",
                value="\n".join(mentions),
                inline=False,
            )
        else:
            embed.add_field(name="Участники", value="-", inline=False)
        embed.add_field(name="Команда 1", value=team_names[0], inline=True)
        embed.add_field(name="Команда 2", value=team_names[1], inline=True)
        embed.set_footer(text=f"Лимит игроков: {MAX_PARTICIPANTS}")
        return embed

    def _build_distribution_embed(
        self,
        session: GameSession,
        team_one: Sequence[int],
        team_two: Sequence[int],
        map_info: Optional[dict],
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Распределение завершено!",
            description=f"Игра: {session.game}",
            color=discord.Color.green(),
        )
        embed.add_field(
            name=session.team_names[0],
            value=self._format_mentions(team_one),
            inline=True,
        )
        embed.add_field(
            name=session.team_names[1],
            value=self._format_mentions(team_two),
            inline=True,
        )
        if map_info:
            embed.set_image(url=map_info["image"])
            embed.set_footer(text=f"Карта: {map_info['name']}")
        return embed

    def _format_mentions(self, user_ids: Sequence[int]) -> str:
        if not user_ids:
            return "-"
        return "\n".join(f"<@{uid}>" for uid in user_ids)

    async def _move_players(
        self,
        session: GameSession,
        team_one: Sequence[int],
        team_two: Sequence[int],
        guild: discord.Guild,
    ) -> None:
        if session.voice_channel_id is None:
            return
        voice_channel = guild.get_channel(session.voice_channel_id)
        if not isinstance(voice_channel, (discord.VoiceChannel, discord.StageChannel)):
            return
        category = voice_channel.category
        if category is None:
            return
        target_one = next(
            (vc for vc in category.voice_channels if session.team_names[0].lower() in vc.name.lower()),
            None,
        )
        target_two = next(
            (vc for vc in category.voice_channels if session.team_names[1].lower() in vc.name.lower()),
            None,
        )
        if not target_one or not target_two:
            return
        for uid in team_one:
            member = await self._get_member(guild, uid)
            if member and member.voice and member.voice.channel:
                try:
                    await member.move_to(target_one)
                except Exception:
                    continue
        for uid in team_two:
            member = await self._get_member(guild, uid)
            if member and member.voice and member.voice.channel:
                try:
                    await member.move_to(target_two)
                except Exception:
                    continue

    async def _get_member(self, guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:
            return None

    async def _remove_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            user = self.bot.get_user(payload.user_id) or await self.bot.fetch_user(payload.user_id)
            await message.remove_reaction(payload.emoji, user)
        except Exception:
            pass

    async def _update_recruitment_message(self, session: GameSession) -> None:
        channel = self.bot.get_channel(session.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(session.message_id)
            embed = self._build_recruitment_embed(session.game, session.team_names, session.participants)
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != "🎮":
            return
        session = self.sessions.get(payload.message_id)
        if not session or session.finished:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if payload.user_id in session.participants:
            return
        if len(session.participants) >= MAX_PARTICIPANTS:
            user = self.bot.get_user(payload.user_id) or await self.bot.fetch_user(payload.user_id)
            if user:
                try:
                    await user.send("Достигнут лимит участников (10).")
                except Exception:
                    pass
            await self._remove_reaction(payload)
            return
        session.participants.add(payload.user_id)
        await self._update_recruitment_message(session)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if str(payload.emoji) != "🎮":
            return
        session = self.sessions.get(payload.message_id)
        if not session or session.finished:
            return
        session.participants.discard(payload.user_id)
        await self._update_recruitment_message(session)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CustomGame(bot))