"""
Ког мини-игр с встроенной экономикой.
Команды: /daily, /balance, /pay, /coinflip, /roll, /rps, /top
"""

import datetime
import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database
from config import Config

logger = logging.getLogger("games")

# Эмодзи для камень-ножницы-бумага
RPS_EMOJIS = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
RPS_WINS = {
    "rock": "scissors",
    "scissors": "paper",
    "paper": "rock",
}
RPS_RU = {"rock": "камень", "scissors": "ножницы", "paper": "бумага"}


def guild_only():
    """Проверяет, что команда выполняется на сервере."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()
        return True
    return app_commands.check(predicate)


class Games(commands.Cog):
    """Мини-игры и экономика сервера."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ─────────────────── ЭКОНОМИКА ───────────────────

    @app_commands.command(name="daily", description="Получить ежедневный бонус")
    @guild_only()
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild_id = interaction.guild.id
        user_id = interaction.user.id

        last = await database.get_last_daily(guild_id, user_id)
        now = datetime.datetime.utcnow()

        if last:
            delta = now - last
            if delta.total_seconds() < 86400:  # 24 часа
                remaining = 86400 - delta.total_seconds()
                hours, rem = divmod(int(remaining), 3600)
                minutes = rem // 60
                embed = discord.Embed(
                    title="⏳ Ежедневный бонус",
                    description=(
                        f"Вы уже получали бонус сегодня!\n"
                        f"Следующий через: **{hours}ч {minutes}м**"
                    ),
                    color=discord.Color.red(),
                )
                return await interaction.followup.send(embed=embed)

        # Выдаём бонус
        await database.set_last_daily(guild_id, user_id)
        new_balance = await database.update_balance(guild_id, user_id, Config.DAILY_REWARD)

        embed = discord.Embed(
            title="🎁 Ежедневный бонус получен!",
            description=f"Вы получили **{Config.DAILY_REWARD}** монет.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Новый баланс", value=f"💰 {new_balance}")
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="balance", description="Показать баланс")
    @app_commands.describe(member="Участник (по умолчанию — вы)")
    @guild_only()
    async def balance(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        await interaction.response.defer()

        target = member or interaction.user
        bal = await database.get_balance(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"💰 Баланс: {target.display_name}",
            description=f"**{bal}** монет",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pay", description="Перевести монеты другому участнику")
    @app_commands.describe(member="Получатель", amount="Сумма перевода")
    @guild_only()
    async def pay(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
    ):
        await interaction.response.defer()

        if member.id == interaction.user.id:
            embed = discord.Embed(
                description="❌ Нельзя переводить монеты самому себе.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        if member.bot:
            embed = discord.Embed(
                description="❌ Нельзя переводить монеты ботам.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        if amount <= 0:
            embed = discord.Embed(
                description="❌ Сумма перевода должна быть больше нуля.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        sender_bal = await database.get_balance(interaction.guild.id, interaction.user.id)
        if sender_bal < amount:
            embed = discord.Embed(
                description=f"❌ Недостаточно монет. Ваш баланс: **{sender_bal}**.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        await database.update_balance(interaction.guild.id, interaction.user.id, -amount)
        new_receiver = await database.update_balance(interaction.guild.id, member.id, amount)

        embed = discord.Embed(
            title="💸 Перевод выполнен",
            color=discord.Color.green(),
        )
        embed.add_field(name="От", value=interaction.user.mention, inline=True)
        embed.add_field(name="Кому", value=member.mention, inline=True)
        embed.add_field(name="Сумма", value=f"**{amount}** монет", inline=True)
        embed.add_field(name="Новый баланс получателя", value=f"💰 {new_receiver}", inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="top", description="Топ-10 богатейших игроков сервера")
    @guild_only()
    async def top(self, interaction: discord.Interaction):
        await interaction.response.defer()

        leaders = await database.get_top(interaction.guild.id, limit=10)

        if not leaders:
            embed = discord.Embed(
                description="Список пуст. Станьте первым!",
                color=discord.Color.blue(),
            )
            return await interaction.followup.send(embed=embed)

        embed = discord.Embed(
            title=f"🏆 Топ игроков — {interaction.guild.name}",
            color=discord.Color.gold(),
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, entry in enumerate(leaders):
            medal = medals[i] if i < 3 else f"**{i + 1}.**"
            user = interaction.guild.get_member(entry["user_id"])
            name = user.display_name if user else f"<@{entry['user_id']}>"
            lines.append(f"{medal} {name} — **{entry['balance']}** монет")

        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ─────────────────── ИГРЫ ───────────────────

    @app_commands.command(name="coinflip", description="Бросить монетку (шанс 50/50, х2)")
    @app_commands.describe(bet="Ставка", choice="Ваш выбор: орёл или решка")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Орёл", value="heads"),
        app_commands.Choice(name="Решка", value="tails"),
    ])
    @guild_only()
    async def coinflip(
        self,
        interaction: discord.Interaction,
        bet: int,
        choice: str,
    ):
        await interaction.response.defer()

        if bet <= 0:
            embed = discord.Embed(description="❌ Ставка должна быть больше нуля.", color=discord.Color.red())
            return await interaction.followup.send(embed=embed)

        balance = await database.get_balance(interaction.guild.id, interaction.user.id)
        if balance < bet:
            embed = discord.Embed(
                description=f"❌ Недостаточно монет. Ваш баланс: **{balance}**.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        result = random.choice(["heads", "tails"])
        won = result == choice

        choice_name = "орёл" if choice == "heads" else "решка"
        result_name = "орёл" if result == "heads" else "решка"
        result_emoji = "🦅" if result == "heads" else "🪙"

        if won:
            delta = bet  # выигрыш: +ставка (итого х2)
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, delta)
            embed = discord.Embed(
                title=f"🎉 Победа! {result_emoji}",
                description=(
                    f"Выпало: **{result_name}** | Ваш выбор: **{choice_name}**\n"
                    f"Вы выиграли **{bet}** монет!"
                ),
                color=discord.Color.green(),
            )
        else:
            delta = -bet
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, delta)
            embed = discord.Embed(
                title=f"😢 Проигрыш! {result_emoji}",
                description=(
                    f"Выпало: **{result_name}** | Ваш выбор: **{choice_name}**\n"
                    f"Вы потеряли **{bet}** монет."
                ),
                color=discord.Color.red(),
            )

        embed.add_field(name="Баланс", value=f"💰 {new_bal}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="roll", description="Угадай число от 1 до 6 (при победе х3)")
    @app_commands.describe(bet="Ставка", guess="Ваше число (1–6)")
    @guild_only()
    async def roll(
        self,
        interaction: discord.Interaction,
        bet: int,
        guess: int,
    ):
        await interaction.response.defer()

        if bet <= 0:
            embed = discord.Embed(description="❌ Ставка должна быть больше нуля.", color=discord.Color.red())
            return await interaction.followup.send(embed=embed)

        if not 1 <= guess <= 6:
            embed = discord.Embed(description="❌ Число должно быть от 1 до 6.", color=discord.Color.red())
            return await interaction.followup.send(embed=embed)

        balance = await database.get_balance(interaction.guild.id, interaction.user.id)
        if balance < bet:
            embed = discord.Embed(
                description=f"❌ Недостаточно монет. Баланс: **{balance}**.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        result = random.randint(1, 6)
        dice_emojis = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]

        if result == guess:
            winnings = bet * 2  # выигрыш: ставка сохраняется + х2 сверху = итого х3
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, winnings)
            embed = discord.Embed(
                title=f"🎲 Победа! {dice_emojis[result - 1]}",
                description=(
                    f"Выпало: **{result}** | Ваш выбор: **{guess}**\n"
                    f"Вы выиграли **{winnings}** монет (x3)!"
                ),
                color=discord.Color.green(),
            )
        else:
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, -bet)
            embed = discord.Embed(
                title=f"🎲 Проигрыш! {dice_emojis[result - 1]}",
                description=(
                    f"Выпало: **{result}** | Ваш выбор: **{guess}**\n"
                    f"Вы потеряли **{bet}** монет."
                ),
                color=discord.Color.red(),
            )

        embed.add_field(name="Баланс", value=f"💰 {new_bal}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="rps", description="Камень-ножницы-бумага против бота")
    @app_commands.describe(bet="Ставка", choice="Ваш выбор")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🪨 Камень", value="rock"),
        app_commands.Choice(name="✂️ Ножницы", value="scissors"),
        app_commands.Choice(name="📄 Бумага", value="paper"),
    ])
    @guild_only()
    async def rps(
        self,
        interaction: discord.Interaction,
        bet: int,
        choice: str,
    ):
        await interaction.response.defer()

        if bet <= 0:
            embed = discord.Embed(description="❌ Ставка должна быть больше нуля.", color=discord.Color.red())
            return await interaction.followup.send(embed=embed)

        balance = await database.get_balance(interaction.guild.id, interaction.user.id)
        if balance < bet:
            embed = discord.Embed(
                description=f"❌ Недостаточно монет. Баланс: **{balance}**.",
                color=discord.Color.red(),
            )
            return await interaction.followup.send(embed=embed)

        bot_choice = random.choice(list(RPS_WINS.keys()))

        # Определяем исход
        if choice == bot_choice:
            outcome = "draw"
        elif RPS_WINS[choice] == bot_choice:
            outcome = "win"
        else:
            outcome = "lose"

        user_label = f"{RPS_EMOJIS[choice]} {RPS_RU[choice]}"
        bot_label = f"{RPS_EMOJIS[bot_choice]} {RPS_RU[bot_choice]}"

        if outcome == "win":
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, bet)
            embed = discord.Embed(
                title="🎉 Вы победили!",
                description=f"Вы: **{user_label}** | Бот: **{bot_label}**\nВы выиграли **{bet}** монет!",
                color=discord.Color.green(),
            )
        elif outcome == "lose":
            new_bal = await database.update_balance(interaction.guild.id, interaction.user.id, -bet)
            embed = discord.Embed(
                title="😢 Вы проиграли!",
                description=f"Вы: **{user_label}** | Бот: **{bot_label}**\nВы потеряли **{bet}** монет.",
                color=discord.Color.red(),
            )
        else:
            new_bal = balance  # ничья — ставка возвращается
            embed = discord.Embed(
                title="🤝 Ничья!",
                description=f"Вы: **{user_label}** | Бот: **{bot_label}**\nСтавка возвращена.",
                color=discord.Color.blue(),
            )

        embed.add_field(name="Баланс", value=f"💰 {new_bal}")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
