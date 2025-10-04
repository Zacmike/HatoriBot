from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..db import get_user_balance
from ..utils import format_currency


class Balance(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="balance", description="Показать баланс пользователя")
    @app_commands.describe(user="Пользователь")
    async def balance(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        target = user or interaction.user
        await interaction.response.send_message(
            f"Баланс пользователя {target.mention}: {format_currency(await get_user_balance(target.id))}",
            ephemeral=True,
        )

    @commands.command(name="balance", aliases=("bal", "монеты"))
    async def balance_prefix(self, ctx: commands.Context, user: discord.User | None = None) -> None:
        target = user or ctx.author
        bal = await get_user_balance(target.id)
        await ctx.send(f"Баланс пользователя {target.mention}: {format_currency(bal)}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Balance(bot))