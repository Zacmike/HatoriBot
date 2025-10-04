from __future__ import annotations

from typing import Awaitable, Callable

import discord

from HatoriBotPy.db import (
    create_bet,
    get_bets_for_game,
    get_user_balance,
    set_user_balance,
    clear_bets_for_game,
)
from HatoriBotPy.utils import format_currency

BetCallback = Callable[[discord.Interaction, int, int], Awaitable[None]]
FinalizeCallback = Callable[[discord.Interaction, str], Awaitable[None]]


class BetModal(discord.ui.Modal):
    def __init__(
        self,
        team_name: str,
        game_id: str,
        team_index: int,
        on_success: BetCallback | None = None,
    ) -> None:
        super().__init__(title="Сделать ставку")
        self.team_name = team_name
        self.game_id = game_id
        self.team_index = team_index
        self._on_success = on_success
        self.amount = discord.ui.TextInput(
            label=f"Сумма ставки на {team_name}",
            placeholder="Введите сумму...",
            required=True,
            max_length=10,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        try:
            amount = int(self.amount.value)
        except ValueError:
            await interaction.response.send_message(
                "Пожалуйста, введите корректное число.",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                "Сумма должна быть положительной.",
                ephemeral=True,
            )
            return

        balance = await get_user_balance(interaction.user.id)
        if balance < amount:
            await interaction.response.send_message(
                f"Недостаточно средств для ставки. У вас {format_currency(balance)}",
                ephemeral=True,
            )
            return

        success = await create_bet(interaction.user.id, self.game_id, self.team_index, amount)
        if not success:
            await interaction.response.send_message(
                "Ошибка при создании ставки.",
                ephemeral=True,
            )
            return

        await set_user_balance(interaction.user.id, balance - amount)
        await interaction.response.send_message(
            f"✅ Ставка на {self.team_name} в размере {format_currency(amount)} принята!",
            ephemeral=True,
        )

        if self._on_success:
            await self._on_success(interaction, self.team_index, amount)


class BetView(discord.ui.View):
    def __init__(
        self,
        team1: str,
        team2: str,
        game_id: str,
        on_bet: BetCallback | None = None,
        on_refund: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(timeout=1800)
        self.team1 = team1
        self.team2 = team2
        self.game_id = game_id
        self._on_bet = on_bet
        self._on_refund = on_refund
        self._closed = False

    def close(self) -> None:
        self._closed = True
        for child in self.children:
            child.disabled = True
        self.stop()

    async def _show_modal(self, interaction: discord.Interaction, team_index: int) -> None:
        if self._closed:
            await interaction.response.send_message(
                "Ставки уже закрыты.",
                ephemeral=True,
            )
            return
        team_name = self.team1 if team_index == 1 else self.team2
        await interaction.response.send_modal(
            BetModal(team_name, self.game_id, team_index, self._on_bet)
        )

    @discord.ui.button(label="Поставить на команду 1", style=discord.ButtonStyle.success)
    async def bet_team1(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show_modal(interaction, 1)

    @discord.ui.button(label="Поставить на команду 2", style=discord.ButtonStyle.danger)
    async def bet_team2(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._show_modal(interaction, 2)

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        from HatoriBotPy.config import settings

        if not isinstance(interaction.user, discord.Member):
            return False

        role_ids = {role.id for role in interaction.user.roles}
        if settings.ADMIN_ROLE_ID and settings.ADMIN_ROLE_ID in role_ids:
            return True
        manager_role = settings.CUSTOM_GAME_MANAGER_ROLE_ID
        return bool(manager_role and manager_role in role_ids)

    @discord.ui.button(label="Вернуть ставки", style=discord.ButtonStyle.secondary)
    async def refund(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        if self._on_refund is None:
            await interaction.response.send_message("Функция возврата недоступна.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        await self._on_refund(interaction)


class WinnerView(discord.ui.View):
    def __init__(
        self,
        team1: str,
        team2: str,
        game_id: str,
        on_finalize: FinalizeCallback | None = None,
        on_refund: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.team1 = team1
        self.team2 = team2
        self.game_id = game_id
        self._on_finalize = on_finalize
        self._on_refund = on_refund

    def disable_all_items(self) -> None:
        for child in self.children:
            child.disabled = True
        self.stop()

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        from HatoriBotPy.config import settings

        if not isinstance(interaction.user, discord.Member):
            return False

        role_ids = {role.id for role in interaction.user.roles}
        if settings.ADMIN_ROLE_ID and settings.ADMIN_ROLE_ID in role_ids:
            return True
        manager_role = settings.CUSTOM_GAME_MANAGER_ROLE_ID
        return bool(manager_role and manager_role in role_ids)

    async def _process_winner(self, interaction: discord.Interaction, winning_team: int) -> None:
        bets = await get_bets_for_game(self.game_id)
        if not bets:
            await interaction.response.send_message("Ставок не найдено.", ephemeral=True)
            return

        total_bets_team1 = sum(bet["amount"] for bet in bets if bet["team"] == 1)
        total_bets_team2 = sum(bet["amount"] for bet in bets if bet["team"] == 2)
        total_pot = total_bets_team1 + total_bets_team2

        winning_bets = [bet for bet in bets if bet["team"] == winning_team]
        total_winning_bets = sum(bet["amount"] for bet in winning_bets)

        if total_winning_bets == 0:
            await interaction.response.send_message(
                "На победившую команду не было ставок.",
                ephemeral=True,
            )
            return

        for bet in winning_bets:
            win_amount = int((bet["amount"] / total_winning_bets) * total_pot)
            current_balance = await get_user_balance(bet["user_id"])
            await set_user_balance(bet["user_id"], current_balance + win_amount)

        await clear_bets_for_game(self.game_id)

        winning_team_name = self.team1 if winning_team == 1 else self.team2
        await interaction.response.send_message(
            f"✅ Выплаты произведены! Победила {winning_team_name}.",
            ephemeral=True,
        )

        if self._on_finalize:
            await self._on_finalize(interaction, winning_team_name)

        self.disable_all_items()
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Победила команда 1", style=discord.ButtonStyle.success)
    async def win_team1(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        await self._process_winner(interaction, 1)

    @discord.ui.button(label="Победила команда 2", style=discord.ButtonStyle.primary)
    async def win_team2(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        await self._process_winner(interaction, 2)

    @discord.ui.button(label="Вернуть все ставки", style=discord.ButtonStyle.secondary)
    async def return_bets(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return

        bets = await get_bets_for_game(self.game_id)
        if not bets:
            await interaction.response.send_message("Ставок не найдено.", ephemeral=True)
            return

        for bet in bets:
            current_balance = await get_user_balance(bet["user_id"])
            await set_user_balance(bet["user_id"], current_balance + bet["amount"])

        await clear_bets_for_game(self.game_id)

        if self._on_refund:
            await self._on_refund(interaction)

        await interaction.response.send_message("Ставки возвращены игрокам.", ephemeral=True)
        self.disable_all_items()
        await interaction.message.edit(view=self)