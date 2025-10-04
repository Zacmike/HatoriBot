from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from ..config import settings
from ..constants import SHOP_ITEMS
from ..db import get_user_balance, record_purchase, set_user_balance


class Shop(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="shop", description="Магазин виртуальных товаров")
    async def shop(self, interaction: discord.Interaction) -> None:
        options = [
            discord.SelectOption(
                label=item["name"],
                value=item["key"],
                description=f"{item['price']} монет",
            )
            for item in SHOP_ITEMS
        ]

        select = discord.ui.Select(
            placeholder="Выберите товар",
            min_values=1,
            max_values=1,
            options=options,
        )

        async def on_select(inter: discord.Interaction) -> None:
            key = select.values[0]
            item = next((i for i in SHOP_ITEMS if i["key"] == key), None)
            if item is None:
                await inter.response.send_message("Товар не найден.", ephemeral=True)
                return

            balance = await get_user_balance(inter.user.id)
            price = int(item["price"])

            if balance < price:
                await inter.response.send_message("Недостаточно средств.", ephemeral=True)
                return

            await set_user_balance(inter.user.id, balance - price)

            if settings.PURCHASE_LOG_CHANNEL:
                log_channel = self.bot.get_channel(settings.PURCHASE_LOG_CHANNEL)
                if log_channel:
                    await log_channel.send(
                        f"🛒 {inter.user.mention} купил(а) **{item['name']}** за {price} монет"
                    )

            await record_purchase(inter.user.id, item["key"], item["name"], price)

            result_msg = await self._process_purchase(inter, item)

            await inter.response.send_message(
                f"✅ Покупка успешна: **{item['name']}**\n{result_msg}",
                ephemeral=True,
            )

        select.callback = on_select
        view = discord.ui.View(timeout=60)
        view.add_item(select)

        embed = discord.Embed(
            title="🏪 Магазин",
            description="Выберите товар для покупки:",
            color=discord.Color.gold(),
        )

        for item in SHOP_ITEMS:
            embed.add_field(
                name=f"{item['name']} - {item['price']}💰",
                value=f"Тип: {self._get_item_type_name(item['type'])}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _get_item_type_name(self, item_type: str) -> str:
        type_names = {
            "role": "Роль",
            "channel_text": "Текстовый канал",
            "channel_voice": "Голосовой канал",
            "virtual": "Виртуальный товар",
        }
        return type_names.get(item_type, "Неизвестно")

    async def _process_purchase(self, interaction: discord.Interaction, item: dict) -> str:
        item_type = item.get("type", "virtual")
        duration_days = item.get("duration_days")
        duration_seconds = duration_days * 24 * 60 * 60 if duration_days else None

        if item_type == "role":
            member = interaction.user
            guild = interaction.guild
            if not guild or not isinstance(member, discord.Member):
                return "Ошибка: выдача роли доступна только на сервере."

            role_name = f"Custom Role - {member.display_name}"[:100]
            role = await guild.create_role(name=role_name, reason="Покупка в магазине")
            await member.add_roles(role, reason="Покупка в магазине")

            if duration_seconds:
                asyncio.create_task(self._schedule_role_expiration(member, role, duration_seconds))

            return f"Вам выдана роль {role.mention}."

        if item_type in {"channel_text", "channel_voice"}:
            guild = interaction.guild
            member = interaction.user
            if not guild or not isinstance(member, discord.Member):
                return "Ошибка: создание канала доступно только на сервере."

            member_overwrite = discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                manage_permissions=True,
            )
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: member_overwrite,
            }

            channel_name = f"private-{member.display_name}".lower().replace(" ", "-")[:95]
            reason = "Покупка приватного канала"

            if item_type == "channel_text":
                channel = await guild.create_text_channel(channel_name, overwrites=overwrites, reason=reason)
            else:
                member_overwrite.connect = True
                channel = await guild.create_voice_channel(channel_name, overwrites=overwrites, reason=reason)

            if duration_seconds:
                asyncio.create_task(self._schedule_channel_expiration(channel, duration_seconds))

            channel_type_name = "текстовый" if item_type == "channel_text" else "голосовой"
            return f"Создан приватный {channel_type_name} канал {channel.mention}."

        if item_type == "virtual":
            if item.get("key") == "warning_remove":
                return "Ваше предупреждение было снято."
            return "Спасибо за покупку!"

        return "Товар выдан."

    async def _schedule_role_expiration(self, member: discord.Member, role: discord.Role, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            await member.remove_roles(role, reason="Срок действия роли истек")
            await role.delete(reason="Срок действия роли истек")
        except Exception:
            pass

    async def _schedule_channel_expiration(self, channel: discord.abc.GuildChannel, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await channel.delete(reason="Срок действия приватного канала истек")
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Shop(bot))