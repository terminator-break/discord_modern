"""
Главная точка входа Discord-бота.
Загружает настройки, инициализирует БД, регистрирует коги и запускает бота.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import database
from config import Config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")

# Загружаем переменные окружения из .env
load_dotenv()


class DiscordBot(commands.Bot):
    """Основной класс бота с поддержкой слэш-команд."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=Config.PREFIX,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Вызывается при запуске — загружаем коги и синхронизируем команды."""
        # Инициализируем базу данных
        await database.init_db()
        logger.info("База данных инициализирована.")

        # Загружаем коги
        cogs = ["cogs.moderation", "cogs.games"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"Ког '{cog}' загружен.")
            except Exception as e:
                logger.error(f"Ошибка загрузки кога '{cog}': {e}")

        # Синхронизируем слэш-команды
        if Config.GUILD_ID:
            guild = discord.Object(id=Config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(f"Синхронизировано {len(synced)} команд для гильдии {Config.GUILD_ID}.")
        else:
            synced = await self.tree.sync()
            logger.info(f"Синхронизировано {len(synced)} глобальных команд.")

    async def on_ready(self):
        """Событие при успешном подключении бота."""
        logger.info(f"Бот запущен как {self.user} (ID: {self.user.id})")
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{Config.PREFIX}help | {len(self.guilds)} серверов"
        )
        await self.change_presence(activity=activity)

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        """Глобальный обработчик ошибок слэш-команд."""
        # Определяем тип ошибки и формируем понятное сообщение
        if isinstance(error, discord.app_commands.MissingPermissions):
            description = "❌ У вас недостаточно прав для выполнения этой команды."
        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            description = "❌ У бота недостаточно прав для выполнения этой команды."
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            description = f"⏳ Команда на перезарядке. Попробуйте через **{error.retry_after:.1f}** сек."
        elif isinstance(error, discord.app_commands.NoPrivateMessage):
            description = "❌ Эта команда доступна только на серверах."
        elif isinstance(error, discord.app_commands.CheckFailure):
            description = "❌ Вы не можете использовать эту команду."
        else:
            description = f"❌ Произошла непредвиденная ошибка: `{error}`"
            logger.error(f"Необработанная ошибка команды: {error}", exc_info=error)

        embed = discord.Embed(
            title="Ошибка",
            description=description,
            color=discord.Color.red(),
        )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e}")


async def main():
    """Точка входа — создаём и запускаем бота."""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("Переменная DISCORD_TOKEN не задана в .env!")
        return

    bot = DiscordBot()
    # Подключаем глобальный обработчик ошибок дерева команд
    bot.tree.on_error = bot.on_tree_error

    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
