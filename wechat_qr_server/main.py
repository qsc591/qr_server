from __future__ import annotations

import asyncio
import inspect
import os
from typing import Optional

import discord
from aiohttp import web

from wechat_qr_board.extract import choose_seat_key, extract_wechat_qr_entries

from .config import default_config_path, load_config
from .groups import GroupManager
from .web import create_app


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.messages = True
    try:
        intents.message_content = True
    except Exception:
        pass
    return intents


async def _start_web(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    return runner


def _call_discord_start(client: discord.Client, token: str, use_user_token: bool) -> asyncio.Future:
    start = getattr(client, "start")
    sig = inspect.signature(start)
    kwargs = {}
    if "reconnect" in sig.parameters:
        kwargs["reconnect"] = True
    if use_user_token and "bot" in sig.parameters:
        kwargs["bot"] = False
    return asyncio.create_task(start(token, **kwargs))


async def main_async() -> None:
    here = os.path.dirname(__file__)
    cfg_path = default_config_path() or os.path.join(here, "config.example.json")
    if cfg_path.endswith("config.example.json"):
        print("[WARN] 未找到 wechat_qr_server/config.json，当前使用 config.example.json（需要你填写频道ID）")

    cfg = load_config(cfg_path)
    if not cfg.discord.token:
        raise RuntimeError("缺少 DISCORD_TOKEN（请设置环境变量 DISCORD_TOKEN 或在 config.json 里填写 discord.token）")
    if not cfg.discord.source_channel_ids:
        raise RuntimeError("discord.source_channel_ids 为空：请在 wechat_qr_server/config.json 填写频道ID列表")

    data_dir = cfg.data_dir
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), data_dir)

    groups = GroupManager(data_dir=data_dir)
    groups.reset_all_groups()

    app = create_app(groups, cfg.web.public_base_url, cfg.reset_password)
    runner = await _start_web(app, cfg.web.host, cfg.web.port)

    intents = _build_intents()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"[OK] Discord logged in as {client.user}")
        print(f"[OK] Listening channel_ids={cfg.discord.source_channel_ids}")
        print(f"[OK] Server: http://{cfg.web.host}:{cfg.web.port}/")
        print("[OK] Groups reset on startup; create groups at /")

    @client.event
    async def on_message(message):
        ch = getattr(message, "channel", None)
        ch_id = getattr(ch, "id", None)
        if ch_id not in cfg.discord.source_channel_ids:
            return

        result = extract_wechat_qr_entries(
            message,
            keywords=cfg.keywords,
            seat_field_name_patterns=cfg.seat_field_name_patterns,
            account_field_name_patterns=cfg.account_field_name_patterns,
            countdown_seconds=cfg.countdown_seconds,
        )
        if not result:
            return

        seat_key, seat_label, account_info, items = result
        groups.distribute_items(seat_key=seat_key, seat_label=seat_label, account_info=account_info, items=items)

    try:
        await _call_discord_start(client, cfg.discord.token, cfg.discord.use_user_token)
    finally:
        await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[STOP] bye")


if __name__ == "__main__":
    main()


