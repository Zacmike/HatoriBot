from __future__ import annotations

_TEAM_NAME_MAP = {
    "valorant": ["Атака", "Защита"],
    "dota 2": ["Тьма", "Свет"],
    "league of legends": ["Синие", "Красные"],
    "cs": ["CT", "T"],
}


def _normalize(name: str | None) -> str:
    return (name or "").strip()


def get_team_names(game: str | None) -> list[str]:
    return _TEAM_NAME_MAP.get(_normalize(game).lower(), ["Команда 1", "Команда 2"])


def format_currency(amount: int) -> str:
    return f"{amount}💰"