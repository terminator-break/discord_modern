"""
Конфигурация бота — загружает настройки из переменных окружения.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Токен бота Discord
    TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    # ID гильдии для мгновенной синхронизации команд (опционально)
    # Если не задан — команды синхронизируются глобально (до 1 часа)
    _guild_id = os.getenv("GUILD_ID", "")
    GUILD_ID: int | None = int(_guild_id) if _guild_id.isdigit() else None

    # Префикс для обычных команд (не слэш)
    PREFIX: str = os.getenv("PREFIX", "!")

    # Порог предупреждений для автобана
    WARN_THRESHOLD: int = int(os.getenv("WARN_THRESHOLD", "3"))

    # Начальный баланс новых игроков
    STARTING_BALANCE: int = int(os.getenv("STARTING_BALANCE", "100"))

    # Ежедневный бонус монет
    DAILY_REWARD: int = int(os.getenv("DAILY_REWARD", "100"))

    # Путь к файлу базы данных SQLite
    DB_PATH: str = os.getenv("DB_PATH", "bot.db")
