"""
Ког модерации: кик, бан, анбан, мут, анмут, очистка, предупреждения.
"""

import asyncio
import logging
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from config import Config

logger = logging.getLogger("moderation")


def guild_only():
    """Проверяет, что команда выполняется на сервере, а не в ЛС."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        return True
    return app_commands.check(predicate)


def parse_duration(text: str) -> int:
    """
    Конвертирует строку длительности в секунды.
    Примеры: '10m', '2h', '1d', '30s', '90' (по умолчанию секунды).
    """
    pattern = r"^(\d+)(s|m|h|d)?$"
    match = re.match(pattern, text.strip().lower())
    if not match:
        raise ValueError(f"Неверный формат длительности: '{text}'. Используйте: 30s, 10m, 2h, 1d")
    value, unit = int(match.group(1)), match.group(2) or "s"
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers[unit]


class Moderation(commands.Cog):
    """Команды модерации сервера."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Словарь активных задач мута: {(guild_id, user_id): asyncio.Task}
        self._mute_tasks: dict[tuple[int, int], asyncio.Task] = {}

    # ─────────────────── ВСПОМОГАТЕЛЬНЫЕ ───────────────────

    async def _get_or_create_muted_role(self, guild: discord.Guild) -> discord.Role:
        """Ищет роль Muted. Если не найдена — создаёт и настраивает права."""
        role = discord.utils.get(guild.roles, name="Muted")
        if role:
            return role

        # Создаём роль без цвета, ниже всех остальных
        role = await guild.create_role(
            name="Muted",
            reason="Автосоздание роли мута ботом",
        )

        # Запрещаем отправку сообщений во всех каналах
        for channel in guild.channels:
            try:
                overwrite = channel.overwrites_for(role)
                overwrite.send_messages = False
                overwrite.speak = False
                overwrite.add_reactions = False
                await channel.set_permissions(
                    role,
                    overwrite=overwrite,
                    reason="Настройка роли Muted",
                )
            except discord.Forbidden:
                pass  # Пропускаем каналы без прав

        logger.info(f"Роль Muted создана на сервере '{guild.name}'")
        return role

    async def _schedule_unmute(
        self,
        guild: discord.Guild,
        member: discord.Member,
        role: discord.Role,
        seconds: int,
    ) -> None:
        """Создаёт фоновую задачу автоснятия мута через заданное время."""
        key = (guild.id, member.id)

        # Отменяем предыдущую задачу если была
        if key in self._mute_tasks:
            self._mute_tasks[key].cancel()

        async def _unmute_after():
            await asyncio.sleep(seconds)
            try:
                if role in member.roles:
                    await member.remove_roles(role, reason="Автоснятие мута")
                    logger.info(f"Автоснят мут с {member} на '{guild.name}'")
            except Exception as e:
                logger.warning(f"Не удалось снять мут с {member}: {e}")
            finally:
                self._mute_tasks.pop(key, None)

        task = asyncio.create_task(_unmute_after())
        self._mute_tasks[key] = task

    # ─────────────────── КОМАНДЫ ───────────────────

    @app_commands.command(name="kick", description="Кикнуть участника с сервера")
    @app_commands.describe(member="Участник для кика", reason="Причина кика")
    @app_commands.default_permissions(kick_members=True)
    @guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = "Причина не указана",
    ):
        await interaction.response.defer(ephemeral=False)

        if member.top_role >= interaction.user.top_role:
            embed = discord.Embed(
                description="❌ Вы не можете кикнуть участника с ролью выше или равной вашей.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        try:
            await member.kick(reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            embed = discord.Embed(
                description="❌ У бота недостаточно прав для кика этого участника.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        embed = discord.Embed(
            title="👢 Участник кикнут",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
        logger.info(f"{interaction.user} кикнул {member} | Причина: {reason}")

    @app_commands.command(name="ban", description="Забанить участника сервера")
    @app_commands.describe(member="Участник для бана", reason="Причина бана")
    @app_commands.default_permissions(ban_members=True)
    @guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: Optional[str] = "Причина не указана",
    ):
        await interaction.response.defer()

        if member.top_role >= interaction.user.top_role:
            embed = discord.Embed(
                description="❌ Вы не можете забанить участника с ролью выше или равной вашей.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        # Пытаемся отправить ЛС до бана
        try:
            dm_embed = discord.Embed(
                title=f"🔨 Вы забанены на сервере **{interaction.guild.name}**",
                color=discord.Color.dark_red(),
            )
            dm_embed.add_field(name="Причина", value=reason)
            dm_embed.add_field(name="Модератор", value=str(interaction.user))
            await member.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass  # ЛС закрыты — не страшно

        try:
            await member.ban(reason=f"{interaction.user}: {reason}", delete_message_days=0)
        except discord.Forbidden:
            embed = discord.Embed(
                description="❌ У бота недостаточно прав для бана этого участника.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        embed = discord.Embed(
            title="🔨 Участник забанен",
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
        logger.info(f"{interaction.user} забанил {member} | Причина: {reason}")

    @app_commands.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.describe(user_id="ID пользователя для разбана", reason="Причина разбана")
    @app_commands.default_permissions(ban_members=True)
    @guild_only()
    async def unban(
        self,
        interaction: discord.Interaction,
        user_id: str,
        reason: Optional[str] = "Причина не указана",
    ):
        await interaction.response.defer()

        if not user_id.isdigit():
            embed = discord.Embed(
                description="❌ Некорректный ID пользователя. Укажите числовой ID.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        uid = int(user_id)
        try:
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
        except discord.NotFound:
            embed = discord.Embed(
                description=f"❌ Пользователь с ID `{uid}` не находится в бан-листе.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        await interaction.guild.unban(ban_entry.user, reason=f"{interaction.user}: {reason}")

        embed = discord.Embed(
            title="✅ Пользователь разбанен",
            color=discord.Color.green(),
        )
        embed.add_field(name="Пользователь", value=f"`{ban_entry.user}` (ID: {uid})", inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
        logger.info(f"{interaction.user} разбанил {ban_entry.user} | Причина: {reason}")

    @app_commands.command(name="mute", description="Выдать мут участнику")
    @app_commands.describe(
        member="Участник для мута",
        duration="Длительность (30s, 10m, 2h, 1d)",
        reason="Причина мута",
    )
    @app_commands.default_permissions(manage_roles=True)
    @guild_only()
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: Optional[str] = "Причина не указана",
    ):
        await interaction.response.defer()

        try:
            seconds = parse_duration(duration)
        except ValueError as e:
            embed = discord.Embed(description=f"❌ {e}", color=discord.Color.red())
            return await interaction.followup.send(embed=embed)

        role = await self._get_or_create_muted_role(interaction.guild)

        if role in member.roles:
            embed = discord.Embed(
                description="❌ У участника уже есть мут.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        try:
            await member.add_roles(role, reason=f"{interaction.user}: {reason}")
        except discord.Forbidden:
            embed = discord.Embed(
                description="❌ У бота недостаточно прав для выдачи роли.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        # Планируем автоснятие мута
        await self._schedule_unmute(interaction.guild, member, role, seconds)

        embed = discord.Embed(
            title="🔇 Участник получил мут",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Длительность", value=duration, inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
        logger.info(f"{interaction.user} замутил {member} на {duration} | Причина: {reason}")

    @app_commands.command(name="unmute", description="Снять мут с участника")
    @app_commands.describe(member="Участник для снятия мута")
    @app_commands.default_permissions(manage_roles=True)
    @guild_only()
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        await interaction.response.defer()

        role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not role or role not in member.roles:
            embed = discord.Embed(
                description="❌ У участника нет мута.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        # Отменяем авто-задачу если есть
        key = (interaction.guild.id, member.id)
        if key in self._mute_tasks:
            self._mute_tasks[key].cancel()
            del self._mute_tasks[key]

        await member.remove_roles(role, reason=f"{interaction.user}: ручное снятие мута")

        embed = discord.Embed(
            title="🔊 Мут снят",
            color=discord.Color.green(),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        await interaction.followup.send(embed=embed)
        logger.info(f"{interaction.user} снял мут с {member}")

    @app_commands.command(name="clear", description="Удалить последние N сообщений в канале")
    @app_commands.describe(amount="Количество сообщений (1–100, по умолчанию 10)")
    @app_commands.default_permissions(manage_messages=True)
    @guild_only()
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: Optional[int] = 10,
    ):
        await interaction.response.defer(ephemeral=True)

        amount = max(1, min(amount, 100))  # Ограничиваем 1–100

        try:
            deleted = await interaction.channel.purge(limit=amount)
        except discord.Forbidden:
            embed = discord.Embed(
                description="❌ У бота нет прав на удаление сообщений.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="🗑️ Очистка завершена",
            description=f"Удалено **{len(deleted)}** сообщений.",
            color=discord.Color.blue(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"{interaction.user} удалил {len(deleted)} сообщений в #{interaction.channel}")

    @app_commands.command(name="warn", description="Выдать предупреждение участнику")
    @app_commands.describe(member="Участник", reason="Причина предупреждения")
    @app_commands.default_permissions(manage_messages=True)
    @guild_only()
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ):
        await interaction.response.defer()

        if member.bot:
            embed = discord.Embed(
                description="❌ Нельзя выдать предупреждение боту.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        # Записываем предупреждение в БД
        warn_count = await database.add_warning(
            interaction.guild.id, member.id, interaction.user.id, reason
        )

        embed = discord.Embed(
            title="⚠️ Предупреждение выдано",
            color=discord.Color.yellow(),
        )
        embed.add_field(name="Участник", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(
            name="Предупреждения",
            value=f"**{warn_count}** / {Config.WARN_THRESHOLD}",
            inline=True,
        )

        await interaction.followup.send(embed=embed)

        # Автобан при достижении порога
        if warn_count >= Config.WARN_THRESHOLD:
            try:
                ban_embed = discord.Embed(
                    title=f"🔨 Автобан на **{interaction.guild.name}**",
                    color=discord.Color.dark_red(),
                )
                ban_embed.add_field(
                    name="Причина",
                    value=f"Достигнут лимит предупреждений ({Config.WARN_THRESHOLD})"
                )
                await member.send(embed=ban_embed)
            except (discord.Forbidden, discord.HTTPException):
                pass

            await member.ban(
                reason=f"Автобан: {Config.WARN_THRESHOLD} предупреждений"
            )
            await database.clear_warnings(interaction.guild.id, member.id)

            auto_embed = discord.Embed(
                title="🔨 Автобан",
                description=(
                    f"{member.mention} получил **{Config.WARN_THRESHOLD}** предупреждений "
                    f"и был автоматически забанен."
                ),
                color=discord.Color.dark_red(),
            )
            await interaction.channel.send(embed=auto_embed)
            logger.info(f"Автобан: {member} достиг {Config.WARN_THRESHOLD} предупреждений")

    @app_commands.command(name="warnings", description="Показать предупреждения участника")
    @app_commands.describe(member="Участник (по умолчанию — вы)")
    @app_commands.default_permissions(manage_messages=True)
    @guild_only()
    async def warnings(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer()

        target = member or interaction.user
        warns = await database.get_warnings(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"📋 Предупреждения: {target}",
            color=discord.Color.blue() if warns else discord.Color.green(),
        )

        if not warns:
            embed.description = "✅ Предупреждений нет."
        else:
            for i, w in enumerate(warns, 1):
                embed.add_field(
                    name=f"#{i} — {w['created_at'][:10]}",
                    value=f"**Причина:** {w['reason']}\n**Модератор:** <@{w['mod_id']}>",
                    inline=False,
                )
            embed.set_footer(text=f"Всего: {len(warns)} / {Config.WARN_THRESHOLD}")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
