from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 17889
    public_base_url: str = ""  # 可选：用于生成分享链接


@dataclass
class DiscordConfig:
    token: str = ""
    use_user_token: bool = True
    source_channel_ids: List[int] = None  # type: ignore[assignment]


@dataclass
class AppConfig:
    discord: DiscordConfig
    keywords: List[str]
    kakao_group_enabled: bool = True
    kakao_group_id: str = "kakao"
    kakao_group_name: str = "Kakao Pay"
    kakao_group_password: str = ""
    countdown_seconds: int = 415
    seat_field_name_patterns: List[str] = None  # type: ignore[assignment]
    account_field_name_patterns: List[str] = None  # type: ignore[assignment]
    web: WebConfig = field(default_factory=WebConfig)
    reset_password: str = ""
    data_dir: str = "wechat_qr_server/data"


def load_config(config_path: str) -> AppConfig:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    discord_raw = raw.get("discord") or {}
    token = str(discord_raw.get("token") or "").strip()
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
        host=str(web_raw.get("host") or "0.0.0.0"),
        port=int(web_raw.get("port") or 17889),
        public_base_url=str(web_raw.get("public_base_url") or "").strip(),
    )

    return AppConfig(
        discord=discord_cfg,
        keywords=[str(x) for x in (raw.get("keywords") or [])],
        kakao_group_enabled=bool(raw.get("kakao_group_enabled", True)),
        kakao_group_id=str(raw.get("kakao_group_id") or "kakao").strip() or "kakao",
        kakao_group_name=str(raw.get("kakao_group_name") or "Kakao Pay").strip() or "Kakao Pay",
        kakao_group_password=str(raw.get("kakao_group_password") or "").strip(),
        countdown_seconds=int(raw.get("countdown_seconds") or 415),
        seat_field_name_patterns=[str(x).lower() for x in (raw.get("seat_field_name_patterns") or ["seat info", "seat", "位置", "座位"])],
        account_field_name_patterns=[str(x).lower() for x in (raw.get("account_field_name_patterns") or ["account", "账号", "login", "id", "password", "pass"])],
        web=web_cfg,
        reset_password=str(raw.get("reset_password") or "").strip(),
        data_dir=str(raw.get("data_dir") or "wechat_qr_server/data"),
    )


def default_config_path() -> Optional[str]:
    here = os.path.dirname(__file__)
    p = os.path.join(here, "config.json")
    return p if os.path.exists(p) else None


