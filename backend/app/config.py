"""Настройки приложения из окружения (.env в корне репозитория, в Docker — env_file compose)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://snab:snab@localhost:5433/snabzhenets"
    redis_url: str = "redis://localhost:6380/0"
    secret_key: str = "dev-secret-change-me"

    # Демо-режим: письма только на этот домен (CLAUDE.md, правило 1.6). Проверка — в порте почты
    demo_mode: bool = True
    demo_mail_domain: str = "demo.local"

    smtp_host: str = "localhost"
    smtp_port: int = 3025
    imap_host: str = "localhost"
    imap_port: int = 3143
    mailbox: str = "zakupki@demo.local"
    mailbox_password: str = "demo"

    storage_dir: str = "storage"  # доказательства (по sha256)
    replay_dir: str = "../data/replay"  # записанные открытые данные для офлайн-демо


settings = Settings()
