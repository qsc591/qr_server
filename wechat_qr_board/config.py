from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 17888


@dataclass
class DiscordConfig:
    token: str = ""
    use_user_token: bool = True
    source_channel_ids: List[int] = None  # type: ignore[assignment]


@dataclass
class AppConfig:
    discord: DiscordConfig
    keywords: List[str]
    countdown_seconds: int = 415
    seat_field_name_patterns: List[str] = None  # type: ignore[assignment]
    account_field_name_patterns: List[str] = None  # type: ignore[assignment]
    seats: List[str] = None  # type: ignore[assignment]
    web: WebConfig = field(default_factory=WebConfig)


def load_config(config_path: str) -> AppConfig:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    discord_raw = raw.get("discord") or {}
    token = str(discord_raw.get("token") or "").strip()
    # 允许用环境变量覆盖
    env_token = os.environ.get("DISCORD_TOKEN", "").strip()
    if env_token:
        token = env_token

    discord_cfg = DiscordConfig(
        token=token,
        use_user_token=bool(discord_raw.get("use_user_token", True)),
        source_channel_ids=[int(x) for x in (discord_raw.get("source_channel_ids") or [])],
    )

    web_raw = raw.get("web") or {}
    web_cfg = WebConfig(
        host=str(web_raw.get("host") or "127.0.0.1"),
        port=int(web_raw.get("port") or 17888),
    )

    return AppConfig(
        discord=discord_cfg,
        keywords=[str(x) for x in (raw.get("keywords") or [])],
        countdown_seconds=int(raw.get("countdown_seconds") or 415),
        seat_field_name_patterns=[str(x).lower() for x in (raw.get("seat_field_name_patterns") or ["seat info", "seat", "位置", "座位"])],
        account_field_name_patterns=[str(x).lower() for x in (raw.get("account_field_name_patterns") or ["account", "账号", "login", "id", "password", "pass"])],
        seats=[str(x) for x in (raw.get("seats") or [])],
        web=web_cfg,
    )


def default_config_path() -> Optional[str]:
    here = os.path.dirname(__file__)
    p = os.path.join(here, "config.json")
    return p if os.path.exists(p) else None


