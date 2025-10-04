from __future__ import annotations

import math
import time
from typing import Dict, Tuple

import discord

from HatoriBotPy.config import settings



_action_cooldowns: Dict[Tuple[int, str], float] = {}


async def _send_admin_alert(client: discord.Client, embed: discord.Embed, *, content: str | None = None) -> None:
    cid = settings.ADMIN_ALERT_CHANNEL_ID
    if not cid:
        return
    channel = client.get_channel(cid)
    if channel is None:
        try:
            channel = await client.fetch_channel(cid)
        except Exception:
            return
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(content=content, embed=embed.copy())
        except Exception:
            pass


def _check_cooldown(user_id: int, action: str) -> tuple[bool, float]:
    now = time.monotonic()
    cooldown = settings.ADMIN_NOTICE_COOLDOWN
    key = (user_id, action)
    last = _action_cooldowns.get(key)
    if last is not None and now - last < cooldown:
        return False, cooldown - (now - last)
    _action_cooldowns[key] = now
    return True, 0.0


class ComplaintModal(discord.ui.Modal):
    def __init__(self):
        super().__init__( title='Жалоба')
        self.details = discord.ui.TextInput(
            label = 'Опишите вашу жалобу',
            style = discord.TextStyle.long,
            required = True,
            max_length = 1000
            
        )
        self.add_item(self.details)
        
        
    async def on_submit(self, interaction: discord.Interaction):
        cid = settings.COMPLAINTS_CHANNEL_ID
        if not cid:
            await interaction.response.send_message('Канал для жалоб не настроен.', ephemeral = True)
            return
        
        channel = interaction.client.get_channel(cid)
        if channel is None:
            await interaction.response.send_message('Канал для жалоб не найден.', ephemeral = True)
            return
        
        embed = discord.Embed(
            title = 'Новая жалоба.',
            description = self.details.value,
            color = discord.Color.orange()
        )
        
        embed.set_author(
            name = str(interaction.user),
            icon_url = interaction.user.display_avatar.url
        )
        
        await channel.send(embed = embed)
        await _send_admin_alert(interaction.client, embed)
        await interaction.response.send_message("✅ Жалоба отправлена администрации.", ephemeral=True)
        
        
class VoiceWelcomeView(discord.ui.View):
    def __init__(self, *, timeout: float | None = 180):
        super().__init__(timeout = timeout)
        
    @discord.ui.button(label = 'Вызвать администрацию', style = discord.ButtonStyle.danger)
    async def call_admins(self, interaction: discord.Interaction, button: discord.ui.Button):
        rid = settings.ADMIN_ROLE_ID
        if not rid:
            await interaction.response.send_message('Роль администраторов не настроена', ephemeral = True)
            return
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message('Эта команда доступна только на сервере', ephemeral = True)
            return
        
        role = guild.get_role(rid)
        if not role:
            await interaction.response.send_message('Роль администраторов не найдена.', ephemeral = True)
            return
        
        allowed, remaining = _check_cooldown(interaction.user.id, "call_admins")
        if not allowed:
            await interaction.response.send_message(
                f'Эту кнопку можно использовать снова через {math.ceil(remaining)} секунд.',
                ephemeral=True,
            )
            return

        #Уведомление администрации
        admin_mention = role.mention
        embed = discord.Embed(
            title="🚨 Вызов администрации",
            description=f"Пользователь {interaction.user.mention} запросил помощь в голосовом канале!",
            color=discord.Color.red()
        )
        
        voice_channel = getattr(interaction.user.voice, "channel", None)
        if voice_channel:
            embed.add_field(
                name="Голосовой канал",
                value=f"{voice_channel.name} ({voice_channel.id})",
                inline=False,
            )

        try:
            await interaction.channel.send(f'{admin_mention}', embed = embed)
            await interaction.response.send_message("✅ Администрация уведомлена.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ Не удалось уведомить администрацию.", ephemeral=True)

        for member in role.members:
            if member.bot:
                continue
            try:
                dm_embed = embed.copy()
                if voice_channel:
                    dm_embed.description = (
                        f"Пользователь {interaction.user.mention} запросил помощь."
                        f"\nКанал: {voice_channel.name} ({voice_channel.id})"
                    )
                await member.send(embed=dm_embed)
            except Exception:
                continue

        await _send_admin_alert(interaction.client, embed, content=admin_mention)
            
    @discord.ui.button(label = 'Подать жалобу', style = discord.ButtonStyle.primary)
    async def complaint(self, interaction: discord.Interaction, button: discord.ui.Button):
        allowed, remaining = _check_cooldown(interaction.user.id, "complaint")
        if not allowed:
            await interaction.response.send_message(
                f'Эту кнопку можно использовать снова через {math.ceil(remaining)} секунд.',
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(ComplaintModal())
        