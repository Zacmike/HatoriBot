from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

def _get_env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    value = os.getenv(name, default)
    if required and (value is None or value == ''):
        raise RuntimeError(f"Переменная окружения {name} обязательно, но отсутсвует")
    return value

def _to_int(name: str, value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None or value == '':
        return default
    try:
        return int(value)
    except ValueError as e:
        raise RuntimeError(f"Переменная окружения {name} должна быть целым числом, получено: {value} ") from e
    
    
@dataclass(frozen=True)
class Settings:
    DISCORD_TOKEN: str
    GUILD_ID: Optional[int]
    ADMIN_ROLE_ID: Optional[int]
    CUSTOM_GAME_MANAGER_ROLE_ID: Optional[int]
    COMPLAINTS_CHANNEL_ID: Optional[int]
    BETS_CHANNEL_ID: Optional[int]
    PURCHASE_LOG_CHANNEL: Optional[int]
    ADMIN_ALERT_CHANNEL_ID: Optional[int]
    VOICE_REWARD_INTERVAL: int
    VOICE_REWARD_AMOUNT: int
    MESSAGE_REWARD_AMOUNT: int
    MESSAGE_COOLDOWN_MS: int
    DATABASE_URL: str
    KEEPALIVE_PORT: int
    ADMIN_NOTICE_COOLDOWN: int
    
def load_settings() -> Settings:
    token = _get_env("DISCORD_TOKEN", required=True)
    db_url = _get_env("DATABASE_URL", required=True)
    message_cooldown_raw = _get_env("MESSAGE_COOLDOWN_MS")
    if message_cooldown_raw in (None, ""):
        message_cooldown_raw = _get_env("MESSAGE_COOLDOWN")
    keepalive_port_raw = _get_env("PORT")
    admin_notice_cooldown_raw = _get_env("ADMIN_NOTICE_COOLDOWN")

    return Settings(
        DISCORD_TOKEN=token,
        DATABASE_URL=db_url,
        GUILD_ID = _to_int("GUILD_ID", _get_env("GUILD_ID")),
        ADMIN_ROLE_ID = _to_int("ADMIN_ROLE_ID", _get_env("ADMIN_ROLE_ID")),
        CUSTOM_GAME_MANAGER_ROLE_ID = _to_int("CUSTOM_GAME_MANAGER_ROLE_ID", _get_env("CUSTOM_GAME_MANAGER_ROLE_ID")),
        COMPLAINTS_CHANNEL_ID = _to_int("COMPLAINTS_CHANNEL_ID", _get_env("COMPLAINTS_CHANNEL_ID")),
        BETS_CHANNEL_ID = _to_int("BETS_CHANNEL_ID", _get_env("BETS_CHANNEL_ID")),
        PURCHASE_LOG_CHANNEL = _to_int("PURCHASE_LOG_CHANNEL", _get_env("PURCHASE_LOG_CHANNEL")),
        ADMIN_ALERT_CHANNEL_ID = _to_int("ADMIN_ALERT_CHANNEL_ID", _get_env("ADMIN_ALERT_CHANNEL_ID")),
        VOICE_REWARD_INTERVAL = _to_int("VOICE_REWARD_INTERVAL", _get_env("VOICE_REWARD_INTERVAL"), 60) or 60,
        VOICE_REWARD_AMOUNT = _to_int('VOICE_REWARD_AMOUNT', _get_env('VOICE_REWARD_AMOUNT'), 5) or 5,
        MESSAGE_REWARD_AMOUNT = _to_int("MESSAGE_REWARD_AMOUNT", _get_env("MESSAGE_REWARD_AMOUNT"), 1) or 1,
        MESSAGE_COOLDOWN_MS = _to_int("MESSAGE_COOLDOWN_MS", message_cooldown_raw, 15000) or 15000,
        KEEPALIVE_PORT = _to_int("PORT", keepalive_port_raw, 3000) or 3000,
        ADMIN_NOTICE_COOLDOWN = _to_int("ADMIN_NOTICE_COOLDOWN", admin_notice_cooldown_raw, 600) or 600,
    )
    
settings = load_settings()
