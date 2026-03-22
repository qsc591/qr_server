from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from typing import Optional

import discord
from aiohttp import web

from wechat_qr_board.extract import (
    extract_account_info_from_embeds,
    extract_kakao_pay_entries,
    extract_seat_label_from_embeds,
    extract_wechat_qr_entries,
    make_message_link,
    message_text_haystack,
    sanitize_url,
)

from .config import default_config_path, load_config
from .groups import GroupManager
from .web import create_app


PGW_CLIENT_ID_FIXED = "6940c10b-6860-4233-be3e-b935c44d9fbb"


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


async def _run_blocking(func, /, *args, **kwargs):
    """
    Run blocking CPU/IO (requests/playwright sync) off the asyncio loop thread.
    This avoids Playwright Sync API errors inside an active event loop.
    """
    if hasattr(asyncio, "to_thread"):
        return await asyncio.to_thread(func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


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

    groups = GroupManager(
        data_dir=data_dir,
    )
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

        # ===== ThaiTicketMajor (支付宝) 专用：Payment Exported + thaiticketmajor =====
        try:
            hay = message_text_haystack(message)
        except Exception:
            hay = ""
        if ("payment exported" in hay) and ("thaiticket" in hay):
            # 如果没有 TTM 分组，直接忽略（避免无意义的网络请求）
            g = groups.pick_ttm_group()
            if g:
                # 1) 只使用 embed.url（对应 itp_google.py 的 data['url']）
                check_url = ""
                embeds = getattr(message, "embeds", None) or []
                for em in embeds:
                    try:
                        u = getattr(em, "url", None)
                        if isinstance(u, str) and u.strip():
                            check_url = u.strip()
                            break
                    except Exception:
                        continue
                check_url = sanitize_url(str(check_url or "").replace("\n", ""))

                export_url = ""
                tsx = None
                if check_url:
                    try:
                        from login import tsplash_export as tsx  # lazy import

                        export_url = tsx.resolve_export_url(check_url, requests_verify=True)
                    except Exception:
                        export_url = ""

                seat_label = (
                    extract_seat_label_from_embeds(message, cfg.seat_field_name_patterns)
                    or "TTM"
                )
                # TTM：账号密码不脱敏
                account_info = extract_account_info_from_embeds(
                    message,
                    cfg.account_field_name_patterns,
                    mask_password=False,
                )
                msg_link = make_message_link(message)
                captured_at = time.time()

                def _compute_expiry_cn(exp_str: str) -> tuple[float, str]:
                    """
                    exp_str: 泰国时区 "YYYY-MM-DD HH:MM:SS"
                    返回：(expires_at_epoch_seconds, cn_string)
                    """
                    from datetime import datetime, timedelta

                    dt = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
                    # Windows 上可能缺 IANA tzdb（ZoneInfoNotFoundError），这里做稳定兜底：
                    # Bangkok UTC+7, Shanghai UTC+8（无 DST），北京时间 = 泰国时间 + 1 小时
                    try:
                        from zoneinfo import ZoneInfo

                        dt_th = dt.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
                        dt_cn = dt_th.astimezone(ZoneInfo("Asia/Shanghai"))
                        return float(dt_cn.timestamp()), dt_cn.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        dt_cn = dt + timedelta(hours=1)
                        # 以本地时区无关的“朴素时间”展示：YYYY-MM-DD HH:MM:SS（北京时间）
                        return float(dt_cn.timestamp()), dt_cn.strftime("%Y-%m-%d %H:%M:%S")

                # 2) 尝试解析订单字段（无论能否生成二维码）
                product_title = ""
                order_id = ""
                exp_th = ""
                payment_expiry_cn = ""
                expires_at = captured_at + 600.0
                if export_url and tsx:
                    try:
                        payload = tsx.parse_tsplash_export_url(export_url)
                        meta0 = tsx.extract_redirectv3_payment_meta(payload)
                        product_title = (
                            tsx.format_product_title_from_payment_description(meta0.get("payment_description"))
                            or (meta0.get("payment_description") or "")
                        ).strip()
                        order_id = (meta0.get("order_id") or "").strip()
                        exp_th = (meta0.get("payment_expiry") or "").strip()
                    except Exception:
                        pass

                if exp_th:
                    try:
                        expires_at, payment_expiry_cn = _compute_expiry_cn(exp_th)
                    except Exception:
                        pass

                seat_key = f"{order_id} {seat_label}".strip() if order_id else seat_label.strip()

                # 3) 做转换拿到二维码（PGW_EMAIL/PGW_NAME 允许为空：按空值传入，不影响流程）
                qr_b64 = ""
                alipay_url = ""
                mpayment_url = ""
                convert_error = ""
                qr_error = ""
                capture_qr = bool(getattr(g, "ttm_capture_qr", True))
                if export_url and tsx:
                    try:
                        out = await _run_blocking(
                            tsx.export_to_alipay_qr_payload,
                            export_url,
                            pgw_email=g.pgw_email,
                            pgw_name=g.pgw_name,
                            pgw_client_id=PGW_CLIENT_ID_FIXED,
                            pgw_client_ip="127.0.0.1",
                            referer=tsx.DEFAULT_2C2P_REFERER,
                            requests_verify=True,
                            fetch_timeout=120.0,
                            capture_qr=capture_qr,
                        )
                        mpayment_url = (out.get("mpayment_url") or "").strip()
                        # 关闭“读取二维码”时：只提供 MPaymentProcess 链接作为跳转入口，不展示二维码/最终收银台
                        if capture_qr:
                            alipay_url = (out.get("alipay_url") or "").strip()
                            qr_b64 = (out.get("qr_png_base64") or "").strip()
                            qr_error = (out.get("qr_error") or "").strip()
                        else:
                            alipay_url = ""
                            qr_b64 = ""
                            qr_error = ""
                        # 以转换结果为准（有时更完整）
                        if out.get("product_title"):
                            product_title = str(out.get("product_title") or "").strip()
                        if out.get("order_id"):
                            order_id = str(out.get("order_id") or "").strip()
                        if out.get("payment_expiry"):
                            exp_th = str(out.get("payment_expiry") or "").strip()
                            # 重要：转换结果里可能才有 payment_expiry，需要重新换算北京时间并刷新倒计时基准
                            try:
                                expires_at, payment_expiry_cn = _compute_expiry_cn(exp_th)
                            except Exception:
                                pass
                    except Exception as e:
                        convert_error = f"{type(e).__name__}: {e}"
                        try:
                            import traceback

                            print(f"[TTM] convert failed: {check_url!r} -> {export_url!r}", flush=True)
                            traceback.print_exc()
                        except Exception:
                            pass

                meta = {
                    "source": "ttm_alipay" if (alipay_url or mpayment_url) else "ttm_export",
                    "check_url": check_url,
                    "export_url": export_url,
                    "product_title": product_title,
                    "order_id": order_id,
                    "payment_expiry_th": exp_th,
                    "payment_expiry_cn": payment_expiry_cn,
                    "alipay_url": alipay_url,
                    "mpayment_url": mpayment_url,
                    "qr_png_base64": qr_b64,
                    "convert_error": convert_error,
                    "qr_error": qr_error,
                    "ttm_capture_qr": capture_qr,
                }
                # qr_url：若未转换成功保持为空，面板会显示“暂无二维码”，但倒计时仍可用
                items = [("", msg_link, captured_at, expires_at, meta)]
                groups.add_items_to_group(
                    g.group_id,
                    seat_key=seat_key,
                    seat_label=seat_label,
                    account_info=account_info,
                    items=items,
                )
                return

        if getattr(cfg, "kakao_group_enabled", True):
            kakao_result = extract_kakao_pay_entries(
                message,
                seat_field_name_patterns=cfg.seat_field_name_patterns,
                account_field_name_patterns=cfg.account_field_name_patterns,
                countdown_seconds=cfg.countdown_seconds,
            )
            if kakao_result:
                seat_key, seat_label, account_info, items = kakao_result
                groups.distribute_kakao_items(
                    seat_key=seat_key,
                    seat_label=seat_label,
                    account_info=account_info,
                    items=items,
                )
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


