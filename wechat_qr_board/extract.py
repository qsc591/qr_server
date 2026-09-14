from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_MD_URL_RE = re.compile(r"\((https?://[^\s)]+)\)")
EXIMBAY_QR_KEYWORD = "secureapi.ext.eximbay.com/servlet/QRCodeGenerator"
XBOT_QR_PREFIX = "https://api.xbotaio.com/api/v1/short-url/"
SPIDER_FOOTER_KEYWORD = "spider browser"
TSPLASH_FOOTER_KEYWORD = "t-splash"
_ALIPAY_CASHIER_RE = re.compile(
    r"https?://excashier\.alipay\.com/standard/auth\.htm\?[^\s<>()]+",
    re.IGNORECASE,
)


def message_text_raw(message) -> str:
    parts: List[str] = []
    content = getattr(message, "content", None)
    if isinstance(content, str) and content:
        parts.append(content)
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            parts.extend(_collect_text_from_embed_dict(em.to_dict()))
        except Exception:
            continue
    return "\n".join(parts)


def _extract_ttm_payload_from_text(text: str) -> Dict[str, str]:
    """
    从 message 的原始文本中提取 ThaiTicketMajor/支付宝收银台信息：
    - excashier url
    - qr_png_base64
    - product_title
    - order_id
    - payment_expiry
    """
    t = (text or "").strip()
    if not t:
        return {}
    out: Dict[str, str] = {}

    m = _ALIPAY_CASHIER_RE.search(t)
    if m:
        out["alipay_url"] = sanitize_url(m.group(0))

    m2 = re.search(r"\bqr_png_base64\s*=\s*([A-Za-z0-9+/=]{100,})", t)
    if m2:
        out["qr_png_base64"] = m2.group(1).strip()

    def _kv(key: str) -> str:
        mm = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", t, re.MULTILINE)
        return (mm.group(1).strip() if mm else "")

    out["product_title"] = _kv("product_title")
    out["order_id"] = _kv("order_id")
    out["payment_expiry"] = _kv("payment_expiry")
    return {k: v for k, v in out.items() if v}


def _parse_ttm_expiry_th_to_cn_epoch(exp_th: str) -> Tuple[float, str]:
    """
    输入：泰国时区字符串 "YYYY-MM-DD HH:MM:SS"
    输出：(expires_at_epoch_seconds, cn_string "YYYY-MM-DD HH:MM:SS")
    """
    dt = datetime.strptime(exp_th.strip(), "%Y-%m-%d %H:%M:%S")
    try:
        dt_th = dt.replace(tzinfo=ZoneInfo("Asia/Bangkok"))
        dt_cn = dt_th.astimezone(ZoneInfo("Asia/Shanghai"))
        return float(dt_cn.timestamp()), dt_cn.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # Windows 可能缺 tzdb；Bangkok UTC+7 -> Shanghai UTC+8
        from datetime import timedelta

        dt_cn = dt + timedelta(hours=1)
        return float(dt_cn.timestamp()), dt_cn.strftime("%Y-%m-%d %H:%M:%S")


def sanitize_url(url: str) -> str:
    """
    - 去掉 markdown/括号包裹
    - 去掉尾部常见标点
    """
    if not url:
        return ""
    url = url.strip()
    m = _MD_URL_RE.search(url)
    if m:
        url = m.group(1).strip()
    url = url.strip(" \t\r\n\"'<>")
    url = re.sub(r"[)\].,，。;；]+$", "", url)
    return url


def _collect_text_from_embed_dict(e: Dict) -> List[str]:
    out: List[str] = []
    for k in ("title", "description", "url"):
        v = e.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    author = e.get("author") or {}
    if isinstance(author, dict):
        for k in ("name", "url"):
            v = author.get(k)
            if isinstance(v, str) and v:
                out.append(v)
    footer = e.get("footer") or {}
    if isinstance(footer, dict):
        v = footer.get("text")
        if isinstance(v, str) and v:
            out.append(v)
    for f in (e.get("fields") or []):
        if not isinstance(f, dict):
            continue
        for k in ("name", "value"):
            v = f.get(k)
            if isinstance(v, str) and v:
                out.append(v)
    return out


def message_text_haystack(message) -> str:
    """
    兼容 discord.py 1.x/2.x 的 message 对象。
    """
    parts: List[str] = []
    content = getattr(message, "content", None)
    if isinstance(content, str) and content:
        parts.append(content)
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            parts.extend(_collect_text_from_embed_dict(em.to_dict()))
        except Exception:
            continue
    return "\n".join(parts).lower()


def match_all_keywords(haystack_lower: str, keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    return all((kw or "").lower() in haystack_lower for kw in keywords)


def extract_embed_image_urls(embed_dict: Dict) -> List[str]:
    urls: List[str] = []
    img = (embed_dict.get("image") or {}).get("url")
    if isinstance(img, str) and img:
        urls.append(sanitize_url(img))
    thumb = (embed_dict.get("thumbnail") or {}).get("url")
    if isinstance(thumb, str) and thumb:
        urls.append(sanitize_url(thumb))
    # 同时把 fields/description 里的 url 也抽出来（有些机器人把二维码当链接塞进 field）
    for txt in _collect_text_from_embed_dict(embed_dict):
        urls.extend([sanitize_url(u) for u in _URL_RE.findall(txt)])
    return urls


def _has_xbot_footer(embed_dict: Dict) -> bool:
    footer = embed_dict.get("footer") or {}
    if isinstance(footer, dict):
        txt = str(footer.get("text") or "")
        if "xbot" in txt.lower():
            return True
    title = str(embed_dict.get("title") or "")
    if "xbot" in title.lower():
        return True
    return False


def _has_spider_footer(embed_dict: Dict) -> bool:
    footer = embed_dict.get("footer") or {}
    if isinstance(footer, dict):
        txt = str(footer.get("text") or "")
        if SPIDER_FOOTER_KEYWORD in txt.lower():
            return True
    title = str(embed_dict.get("title") or "")
    if "spider" in title.lower():
        # 兜底：多数 spider 消息 title/description 也会带 spider
        return True
    return False


def _has_tsplash_footer(embed_dict: Dict) -> bool:
    footer = embed_dict.get("footer") or {}
    if isinstance(footer, dict):
        txt = str(footer.get("text") or "")
        if TSPLASH_FOOTER_KEYWORD in txt.lower():
            return True
    desc = str(embed_dict.get("description") or "")
    title = str(embed_dict.get("title") or "")
    if "payment exported" in desc.lower():
        return True
    if "exported link" in title.lower():
        return True
    return False


def _extract_tsplash_fields(message) -> Dict[str, str]:
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_tsplash_footer(d):
            continue
        out: Dict[str, str] = {}
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip()
            val = str(f.get("value") or "").strip()
            if name and val and name not in out:
                out[name] = val
        return out
    return {}


def _extract_tsplash_alipay_qr_url_from_embeds(message) -> Optional[str]:
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_tsplash_footer(d):
            continue
        paymethod = ""
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            n = str(f.get("name") or "").strip().lower()
            if n == "paymethod" or "paymethod" in n:
                paymethod = str(f.get("value") or "").replace("||", "").strip()
                break
        if paymethod.lower() != "alipay":
            continue
        img = (d.get("image") or {}).get("url")
        img = sanitize_url(str(img or ""))
        if img:
            return img
    return None


def _extract_spider_fields(message) -> Dict[str, str]:
    """
    Spider 的 embed.fields 按 name -> value 映射（取第一个 Spider embed）。
    """
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_spider_footer(d):
            continue
        out: Dict[str, str] = {}
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip()
            val = str(f.get("value") or "").strip()
            if name and val and name not in out:
                out[name] = val
        return out
    return {}


def _extract_spider_qr_url_from_embeds(message) -> Optional[str]:
    """
    Spider 的 WeChat 二维码通常在 fields 里：
    - name: Checkout Link(Wechat)
    - value: [Click](https://secureapi.ext.eximbay.com/servlet/QRCodeGenerator?...qrtxt=weixin://...)
    """
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_spider_footer(d):
            continue
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip().lower()
            if "checkout" in name and "wechat" in name:
                val = sanitize_url(str(f.get("value") or ""))
                if val and (EXIMBAY_QR_KEYWORD.lower() in val.lower()) and ("qrtxt=weixin://" in val.lower()):
                    return val
    return None


def _parse_spider_event_time(text: str) -> Dict[str, str]:
    """
    Event Time: 2026-04-16T10:30:00.000Z
    返回：
    - date_key: YYYYMMDD
    - show_time: YYYY-MM-DD HH:mm
    """
    out = {"date_key": "", "show_time": ""}
    t = (text or "").strip()
    if not t:
        return out
    try:
        # fromisoformat 不接受 'Z'，做替换
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # 展示用：按 UTC 输出（避免服务器时区不一致造成歧义）
        dt_utc = dt.astimezone(timezone.utc)
        ymd = dt_utc.strftime("%Y%m%d")
        out["date_key"] = ymd
        out["show_time"] = dt_utc.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # 兜底：仅提取日期
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
        if m:
            out["date_key"] = f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return out


def _parse_spider_timestamp_ms(text: str) -> Optional[float]:
    t = (text or "").strip()
    if not t:
        return None
    if not re.fullmatch(r"\d{10,16}", t):
        return None
    try:
        n = int(t)
        # 猜测：13 位为毫秒
        if n > 10_000_000_000:
            return float(n) / 1000.0
        return float(n)
    except Exception:
        return None


def _extract_xbot_qr_url_from_embeds(message) -> Optional[str]:
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_xbot_footer(d):
            continue
        img = (d.get("image") or {}).get("url")
        img = sanitize_url(str(img or ""))
        if img.startswith(XBOT_QR_PREFIX):
            return img
    return None


def _extract_xbot_fields(message) -> Dict[str, str]:
    """
    将 embed.fields 按 name -> value 映射（取第一个 Xbot embed）。
    """
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if not _has_xbot_footer(d):
            continue
        out: Dict[str, str] = {}
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "").strip()
            val = str(f.get("value") or "").strip()
            if name and val and name not in out:
                out[name] = val
        return out
    return {}


def extract_all_image_urls(message) -> List[str]:
    urls: List[str] = []
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            urls.extend(extract_embed_image_urls(em.to_dict()))
        except Exception:
            continue
    atts = getattr(message, "attachments", None) or []
    for a in atts:
        u = getattr(a, "url", None)
        if isinstance(u, str) and u:
            urls.append(sanitize_url(u))
    # 去重保持顺序
    seen = set()
    out: List[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _normalize_field(s: str) -> str:
    return (s or "").strip().lower()


def _pick_tsplash_seat_line(value: str) -> Optional[str]:
    """
    T-Splash 的 Seat Info value 通常包含多行：
    - 日期/订单号（如 20260213-001）
    - 真正座位/区域行（如 지정석-104... 104구역 2열-18）

    参考 itp_google.py：优先取 seat_info.split(" \\n")[1] 的逻辑，这里做更鲁棒的兜底。
    返回值要求：尽量拼成 “日期/订单号 + 空格 + 座位行”，确保完整可读。
    """
    if not value:
        return None
    v = value.replace("\r\n", "\n").replace("\r", "\n")
    v = v.strip()
    # itp_google 的分隔： " \n"
    if " \n" in v:
        parts = [p.strip() for p in v.split(" \n") if p.strip()]
        if parts:
            first = parts[0].splitlines()[0].strip()
            seat_line = parts[1].splitlines()[0].strip() if len(parts) >= 2 else ""
            if first and seat_line and first != seat_line:
                return f"{first} {seat_line}".strip()
            if seat_line:
                return seat_line
            return first
    lines = [ln.strip() for ln in v.splitlines() if ln.strip()]
    if not lines:
        return None

    first = lines[0].strip()

    # 含“구역/열/번/지정석”等关键词的行更像座位
    seat_line: Optional[str] = None
    for ln in lines:
        l = ln.lower()
        if any(k in ln for k in ("구역", "열", "번", "지정석")):
            seat_line = ln.strip()
            break
        if "-" in ln and any(ch.isdigit() for ch in ln):
            # 很多座位行是 数字/连字符混合
            seat_line = ln.strip()
            break

    # 兜底：如果有第二行，优先第二行（第一行常是订单号）
    if not seat_line:
        seat_line = (lines[1] if len(lines) >= 2 else lines[0]).strip()

    if first and seat_line and first != seat_line:
        return f"{first} {seat_line}".strip()
    return seat_line or first


def extract_seat_label_from_embeds(message, seat_field_name_patterns: Sequence[str]) -> Optional[str]:
    patterns = [_normalize_field(p) for p in seat_field_name_patterns if p]
    embeds = getattr(message, "embeds", None) or []
    # 1) fields 匹配 name
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = _normalize_field(str(f.get("name") or ""))
            if any(p in name for p in patterns):
                val = str(f.get("value") or "").strip()
                if val:
                    picked = _pick_tsplash_seat_line(val)
                    if picked:
                        return picked
    # 2) description 兜底：找包含 seat/位置 的行
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        desc = str(d.get("description") or "")
        for ln in desc.splitlines():
            lnl = ln.lower()
            if any(p in lnl for p in patterns):
                return ln.strip()
    return None


def extract_account_info_from_embeds(
    message,
    account_field_name_patterns: Sequence[str],
    *,
    mask_password: bool = True,
) -> str:
    patterns = [_normalize_field(p) for p in account_field_name_patterns if p]
    embeds = getattr(message, "embeds", None) or []
    hits: List[str] = []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        for f in (d.get("fields") or []):
            if not isinstance(f, dict):
                continue
            name = _normalize_field(str(f.get("name") or ""))
            if any(p in name for p in patterns):
                val = str(f.get("value") or "").strip()
                if val:
                    hits.append(val.replace("||", "").strip())
    # 若没匹配到字段名，尝试从文本里抓常见 "account:xxx" 形式
    if not hits:
        hay = message_text_haystack(message)
        m = re.search(r"(account|账号)\s*[:：]\s*([^\n\r]+)", hay, re.IGNORECASE)
        if m:
            hits.append(m.group(2).strip())
    # 清理：去掉尾部常见标点（T-Splash 常见末尾有 '.'）；默认对密码做脱敏（只保留账号）
    cleaned: List[str] = []
    for x in hits:
        x = x.replace("||", "").strip()
        x = re.sub(r"[。\.\s;；]+$", "", x)
        if not x:
            continue
        # 常见格式：
        # - email:password
        # - email/password
        # - email password
        if mask_password:
            m = re.match(r"^([^:\s/]+@[^:\s/]+)\s*[:/]\s*.+$", x)
            if m:
                cleaned.append(f"{m.group(1)}:****")
            else:
                # 若不是邮箱+密码结构，尝试只保留 ':' 或 '/' 前半段
                if ":" in x:
                    cleaned.append(x.split(":", 1)[0].strip())
                elif "/" in x:
                    cleaned.append(x.split("/", 1)[0].strip())
                else:
                    cleaned.append(x)
        else:
            cleaned.append(x)
    return " | ".join(cleaned)[:300]


def make_message_link(message) -> str:
    guild = getattr(message, "guild", None)
    guild_id = getattr(guild, "id", None) if guild else None
    channel = getattr(message, "channel", None)
    channel_id = getattr(channel, "id", None) if channel else None
    message_id = getattr(message, "id", None)
    if guild_id and channel_id and message_id:
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
    # fallback
    return ""


def choose_seat_key(seat_label: str) -> str:
    # seat_key 要稳定且适合作为前端 key
    seat_label = seat_label.strip()
    if not seat_label:
        return "unknown"
    # 删除过多空白，避免 key 变化
    seat_label = re.sub(r"\s+", " ", seat_label)
    return seat_label


def filter_qr_urls(urls: Iterable[str]) -> List[str]:
    """
    仅抓取 Eximbay 的微信二维码：
    https://secureapi.ext.eximbay.com/servlet/QRCodeGenerator?qrtxt=weixin://...
    """
    out: List[str] = []
    for u in urls:
        u = sanitize_url(u)
        if not u:
            continue
        ul = u.lower()
        if EXIMBAY_QR_KEYWORD.lower() in ul and "qrtxt=weixin://" in ul:
            out.append(u)
    # 去重
    seen = set()
    uniq: List[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def filter_kakao_qr_urls(urls: Iterable[str]) -> List[str]:
    """
    仅抓取 Kakao Pay 的二维码图片（T-Splash）：
    例如：
    https://kakaopayqr.s3.amazonaws.com/<hex>.png
    """
    out: List[str] = []
    for u in urls:
        u = sanitize_url(u)
        if not u:
            continue
        ul = u.lower()
        if "kakaopayqr.s3.amazonaws.com/" not in ul:
            continue
        if not (ul.endswith(".png") or ul.endswith(".jpg") or ul.endswith(".jpeg") or ul.endswith(".webp")):
            continue
        out.append(u)
    # 去重
    seen = set()
    uniq: List[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def _parse_discord_timestamp(text: str) -> Optional[float]:
    """
    解析 <t:1768810703:F> 这种格式，取第一个 timestamp。
    """
    m = re.search(r"<t:(\d+):[A-Za-z]>", text or "")
    if not m:
        return None
    try:
        return float(int(m.group(1)))
    except Exception:
        return None


def _parse_xbot_show_time(round_text: str) -> Dict[str, str]:
    """
    Round: "Show Time: 20260130 20:00"
    返回：
    - date_key: YYYYMMDD
    - show_time: YYYY-MM-DD HH:mm
    """
    out = {"date_key": "", "show_time": ""}
    m = re.search(r"(\d{8})\s+(\d{2}:\d{2})", round_text or "")
    if not m:
        return out
    ymd = m.group(1)
    hm = m.group(2)
    out["date_key"] = ymd
    out["show_time"] = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]} {hm}"
    return out


def _strip_codeblock(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```") and s.endswith("```"):
        s = s[3:-3].strip()
    return s.strip("`").strip()


def _parse_xbot_seat_price(seat_no_text: str) -> Dict[str, str]:
    """
    Seat No: ```... sku XXX price 899.00```
    """
    t = _strip_codeblock(seat_no_text)
    out = {"seat_detail": t, "price": ""}
    m_price = re.search(r"\bprice\b\s*([0-9]+(?:\.[0-9]+)?)", t, re.IGNORECASE)
    if m_price:
        out["price"] = m_price.group(1)
    # 尝试提取 sku 段作为更清晰的“座位/票种信息”
    m_sku = re.search(r"\bsku\b\s+(.*?)\s+\bprice\b", t, re.IGNORECASE)
    if m_sku:
        out["seat_detail"] = m_sku.group(1).strip()
    return out


def extract_wechat_qr_entries(
    message,
    *,
    keywords: Sequence[str],
    seat_field_name_patterns: Sequence[str],
    account_field_name_patterns: Sequence[str],
    countdown_seconds: int,
) -> Optional[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, str]]]]]:
    """
    返回：
    - seat_key
    - seat_label
    - account_info
    - items: [(qr_url, message_link, captured_at, expires_at, meta), ...]
    """
    # ===== T-Splash / AliPay（二维码在 embed.image.url，Paymethod=AliPay）=====
    ts_alipay_qr = _extract_tsplash_alipay_qr_url_from_embeds(message)
    if ts_alipay_qr:
        fields = _extract_tsplash_fields(message)
        seat_info_raw = (fields.get("Seat Info") or "").strip()
        account_info = extract_account_info_from_embeds(
            message, account_field_name_patterns, mask_password=False
        )
        link = make_message_link(message)
        now = time.time()
        # HKT / T-Splash AliPay：二维码通常仅 5 分钟有效
        expires_at = now + 300.0

        order_id = (fields.get("OrderId") or fields.get("OrderID") or fields.get("orderid") or "").replace("||", "").strip()

        alipay_jump = ""
        embeds = getattr(message, "embeds", None) or []
        for em in embeds:
            try:
                d = em.to_dict()
            except Exception:
                continue
            if not _has_tsplash_footer(d):
                continue
            u = sanitize_url(str(d.get("url") or ""))
            if u:
                alipay_jump = u
                break

        lines = [ln.strip() for ln in seat_info_raw.splitlines() if ln.strip()]
        show_time = lines[0] if len(lines) >= 1 else ""
        rest = lines[1:] if len(lines) >= 2 else []

        seat_lines = [ln for ln in rest if ("排" in ln or "号" in ln)]
        if not seat_lines and rest:
            seat_lines = rest[-2:] if len(rest) >= 2 else rest[-1:]

        ticket_lines = [ln for ln in rest if ln not in seat_lines]
        ticket = ticket_lines[0] if ticket_lines else ""
        if ticket and ticket_lines.count(ticket) > 1:
            ticket = ticket_lines[0]

        seat_detail = "\n".join(seat_lines).strip()

        seat_label_fallback = (f"{show_time} {seat_lines[0]}".strip() if (show_time and seat_lines) else (show_time or (seat_lines[0] if seat_lines else "AliPay")))
        seat_label = extract_seat_label_from_embeds(message, seat_field_name_patterns) or seat_label_fallback
        seat_key = f"{order_id} {seat_label}".strip() if order_id else choose_seat_key(seat_label)
        meta = {
            "source": "alipay_tsplash",
            "alipay_url": alipay_jump,
            "order_id": order_id,
            "site": (fields.get("Site") or "").strip(),
            "event_id": (fields.get("Event ID") or "").strip(),
            "quantity": (fields.get("Quantity") or "").strip(),
            "date": show_time,
            "seat_detail": seat_detail,
            "price": ticket,
            "seat_info": seat_info_raw,
            "paymethod": "AliPay",
            "qr_large": True,
        }
        items = [(ts_alipay_qr, link, now, float(expires_at), meta)]
        return seat_key, seat_label, account_info, items

    # ===== ThaiTicketMajor / 支付宝（二维码以 base64 形式提供）=====
    raw = message_text_raw(message)
    ttm = _extract_ttm_payload_from_text(raw)
    if ttm.get("alipay_url") and ttm.get("qr_png_base64"):
        seat_label = extract_seat_label_from_embeds(message, seat_field_name_patterns) or "TTM"
        account_info = extract_account_info_from_embeds(message, account_field_name_patterns)
        link = make_message_link(message)
        now = time.time()
        expires_at = now + 600.0
        payment_expiry_cn = ""
        exp_th = (ttm.get("payment_expiry") or "").strip()
        if exp_th:
            try:
                expires_at, payment_expiry_cn = _parse_ttm_expiry_th_to_cn_epoch(exp_th)
            except Exception:
                pass
        order_id = (ttm.get("order_id") or "").strip()
        if order_id:
            seat_key = f"{order_id} {seat_label}".strip()
        else:
            seat_key = choose_seat_key(seat_label)
        meta = {
            "source": "ttm_alipay",
            "alipay_url": ttm.get("alipay_url") or "",
            "product_title": ttm.get("product_title") or "",
            "order_id": order_id,
            "payment_expiry_th": exp_th,
            "payment_expiry_cn": payment_expiry_cn,
            "qr_png_base64": ttm.get("qr_png_base64") or "",
        }
        items = [("ttm", link, now, float(expires_at), meta)]
        return seat_key, seat_label, account_info, items

    # ===== Spider 分支（不与 T-Splash 混淆；二维码在字段里）=====
    spider_qr = _extract_spider_qr_url_from_embeds(message)
    if spider_qr:
        fields = _extract_spider_fields(message)
        seat_detail = (fields.get("Seat") or "").strip()
        price = (fields.get("Price") or "").strip()
        event_time = (fields.get("Event Time") or "").strip()
        task_id = (fields.get("Task Id") or "").strip()
        product_id = (fields.get("Product Id") or "").strip()
        product = (fields.get("Product") or "").strip()
        product_url = sanitize_url(fields.get("Product Url") or "")
        captured_at = _parse_spider_timestamp_ms(fields.get("Timestamp") or "") or time.time()

        time_info = _parse_spider_event_time(event_time)
        date_key = time_info.get("date_key") or ""
        seat_label = f"{date_key} {seat_detail}".strip() if date_key else (seat_detail or "Unknown")
        # seat_key 用 task_id（或 timestamp）做唯一性
        uniq = task_id or str(int(captured_at))
        seat_key = f"{uniq} {seat_label}".strip() if uniq else choose_seat_key(seat_label)

        account_info = extract_account_info_from_embeds(message, account_field_name_patterns)
        link = make_message_link(message)
        expires_at = float(captured_at) + float(countdown_seconds)

        meta = {
            "source": "spider",
            "seat_detail": seat_detail,
            "price": price,
            "date": time_info.get("show_time") or "",
            "task_id": task_id,
            "product_id": product_id,
            "product": product,
            "product_url": product_url,
        }
        items = [(spider_qr, link, float(captured_at), float(expires_at), meta)]
        return seat_key, seat_label, account_info, items

    # ===== Xbot 分支（不与 T-Splash 混淆）=====
    # 注意：Xbot 支付可能是 alipay 等，不一定包含 wechat/payment exported 等关键词，
    # 所以 Xbot 必须先判定，不能被 keywords 过滤挡掉。
    xbot_qr = _extract_xbot_qr_url_from_embeds(message)
    if xbot_qr:
        fields = _extract_xbot_fields(message)
        seat_no = fields.get("Seat No", "")
        qty = fields.get("Quantity", "")
        round_txt = fields.get("Round", "")
        order_no = fields.get("Order Number", "")
        expire_txt = fields.get("Order Expire", "")

        time_info = _parse_xbot_show_time(round_txt)
        seat_price = _parse_xbot_seat_price(seat_no)

        date_key = time_info.get("date_key") or ""
        seat_detail = seat_price.get("seat_detail") or ""
        # 左侧展示：日期在上，座位/票种在下
        seat_label = f"{date_key} {seat_detail}".strip() if date_key else (seat_detail or "Unknown")
        # seat_key 用订单号做唯一性（避免不同订单同座位被合并）
        seat_key = f"{order_no} {seat_label}".strip() if order_no else choose_seat_key(seat_label)

        account_info = extract_account_info_from_embeds(message, account_field_name_patterns)
        link = make_message_link(message)
        now = time.time()
        expires_at = _parse_discord_timestamp(expire_txt) or (now + float(countdown_seconds))

        meta = {
            "source": "xbot",
            "seat_detail": seat_detail,
            "price": seat_price.get("price") or "",
            "date": time_info.get("show_time") or "",
            "quantity": str(qty or "").strip(),
            "order_number": str(order_no or "").strip(),
        }
        items = [(xbot_qr, link, now, float(expires_at), meta)]
        return seat_key, seat_label, account_info, items

    # ===== 兜底：T-Splash/Eximbay 分支 =====
    hay = message_text_haystack(message)
    if not match_all_keywords(hay, keywords):
        return None
    seat_label = extract_seat_label_from_embeds(message, seat_field_name_patterns) or "Unknown"
    account_info = extract_account_info_from_embeds(message, account_field_name_patterns)
    link = make_message_link(message)

    urls = extract_all_image_urls(message)
    qr_urls = filter_qr_urls(urls)
    if not qr_urls:
        return None

    now = time.time()
    items = [(u, link, now, now + float(countdown_seconds), {"source": "eximbay"}) for u in qr_urls]
    seat_key = choose_seat_key(seat_label)
    return seat_key, seat_label, account_info, items


def extract_kakao_pay_entries(
    message,
    *,
    keywords: Sequence[str] = ("payment exported", "kakao"),
    seat_field_name_patterns: Sequence[str],
    account_field_name_patterns: Sequence[str],
    countdown_seconds: int,
) -> Optional[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, str]]]]]:
    """
    Kakao Pay 专用（服务端固定分组用）：
    - 仅当 message 文本/embeds 命中所有 keywords（默认：payment exported + kakao）才返回
    - 不做 Eximbay/weixin 限制，直接提取消息里的图片 URL 作为二维码候选
    """
    hay = message_text_haystack(message)
    if not match_all_keywords(hay, keywords):
        return None

    seat_label = extract_seat_label_from_embeds(message, seat_field_name_patterns) or "Unknown"
    account_info = extract_account_info_from_embeds(message, account_field_name_patterns)
    link = make_message_link(message)

    urls = extract_all_image_urls(message)
    qr_urls = filter_kakao_qr_urls(urls)
    if not qr_urls:
        return None

    # 从 embed fields 读 Site，按站点决定 TTL（Melon 5 分 / ITP 7 分 / 其他默认 5 分）
    site = ""
    for _em in getattr(message, "embeds", None) or []:
        try:
            _d = _em.to_dict()
        except Exception:
            continue
        for _f in (_d.get("fields") or []):
            if isinstance(_f, dict) and _normalize_field(str(_f.get("name") or "")) == "site":
                site = str(_f.get("value") or "").strip()
                break
        if site:
            break

    now = time.time()
    kakao_ttl = _ttl_by_site(site, 5 * 60.0)
    items = [(u, link, now, now + kakao_ttl, {"source": "kakao_tsplash", "site": site}) for u in qr_urls]
    seat_key = choose_seat_key(seat_label)
    return seat_key, seat_label, account_info, items


# ===================== KB Pay (KB국민카드 · Melon KR) =====================

def _embed_field_map(embed_dict: Dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in (embed_dict.get("fields") or []):
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "").strip()
        val = str(f.get("value") or "").strip()
        if name and val and name not in out:
            out[name] = val
    return out


def _ttl_by_site(site_or_url: str, default_ttl: float) -> float:
    """
    根据站点判断二维码/订单有效期（服务端没给过期字段时的兜底）：
    - Melon KR (ticket.melon.com / melon.co.kr): 5 分钟
    - Interpark (interpark.com): 7 分钟
    - 其他: default_ttl
    """
    u = (site_or_url or "").lower()
    if ("melon.com" in u) or ("melon.co.kr" in u):
        return 5 * 60.0
    if "interpark.com" in u:
        return 7 * 60.0
    return float(default_ttl)


def _kb_field_get(fields: Dict[str, str], *contains: str) -> str:
    """按字段名包含关系取值（大小写不敏感；中韩文按原样匹配）。"""
    for k, v in fields.items():
        kl = (k or "").strip().lower()
        for c in contains:
            if c and c.lower() in kl:
                return v
    return ""


def _is_kbpay_embed(embed_dict: Dict) -> bool:
    """
    判定 KB Pay 消息，兼容三种字段命名：
    - Xbot: 「支付方式」/ 「Pay Type」，value 含 'KB Pay' / 'KBPay'
    - T-Splash: 「Paymethod」，value 'KBPay'
    """
    for f in (embed_dict.get("fields") or []):
        if not isinstance(f, dict):
            continue
        name = _normalize_field(str(f.get("name") or ""))
        if ("支付方式" in name) or ("pay type" in name) or (name == "paymethod"):
            v = str(f.get("value") or "").lower().replace("||", "").strip()
            if ("kb pay" in v) or ("kbpay" in v.replace(" ", "")):
                return True
    return False


def _extract_kbpay_embed_dict(message) -> Optional[Dict]:
    embeds = getattr(message, "embeds", None) or []
    for em in embeds:
        try:
            d = em.to_dict()
        except Exception:
            continue
        if _is_kbpay_embed(d):
            return d
    return None


def _parse_kbpay_show_time(round_text: str) -> Dict[str, str]:
    """
    Round: "Show Time: 20270123 1800"（也兼容 20270123 18:00）
    返回 date_key=YYYYMMDD, show_time=YYYY-MM-DD HH:MM
    """
    out = {"date_key": "", "show_time": ""}
    m = re.search(r"(\d{8})\s+(\d{2}):?(\d{2})", round_text or "")
    if not m:
        return out
    ymd, hh, mm = m.group(1), m.group(2), m.group(3)
    out["date_key"] = ymd
    out["show_time"] = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]} {hh}:{mm}"
    return out


def _parse_kbpay_seat(seat_no_text: str) -> Dict[str, str]:
    """
    Seat No: ```전 floor  row 15 seat 7 price 135000```
    → seat_detail="전 floor row 15 seat 7", price="135000"
    """
    t = _strip_codeblock(seat_no_text)
    out = {"seat_detail": t, "price": ""}
    m = re.search(r"\bprice\b\s*([0-9]+(?:\.[0-9]+)?)", t, re.IGNORECASE)
    if m:
        out["price"] = m.group(1)
        out["seat_detail"] = t[: m.start()].strip()
    out["seat_detail"] = re.sub(r"\s+", " ", out["seat_detail"]).strip()
    return out


def _parse_tsplash_kbpay_seat_info(text: str) -> Dict[str, str]:
    """
    T-Splash Seat Info：
    "20261106\\n2-층-A-구역-6-열-36-번--R석-203_346"
    返回 date_key、show_time、zone、seat_detail
    """
    out = {"date_key": "", "show_time": "", "zone": "", "seat_detail": ""}
    if not text:
        return out
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return out
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", lines[0])
    if m:
        out["date_key"] = lines[0][:8]
        out["show_time"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if len(lines) >= 2:
        seat = lines[1]
        mz = re.search(r"([A-Za-z0-9]+)-?구역", seat)
        if mz:
            out["zone"] = mz.group(1)
        s = re.sub(r"-+", " ", seat).strip()
        # 去掉末尾的编号/席位价 (如 "203_346")
        s = re.sub(r"\s+\d+_\d+\s*$", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        out["seat_detail"] = s
    return out


def _parse_kbpay_event(value: str) -> Tuple[str, str]:
    """Event 字段：优先 markdown 链接 [名称](url)。返回 (event_name, event_url)。"""
    v = value or ""
    m = re.search(r"\[([^\]]+)\]\((https?://[^)]+)\)", v)
    if m:
        return m.group(1).strip(), sanitize_url(m.group(2))
    name = ""
    for ln in v.splitlines():
        ln = ln.strip().strip("`").strip()
        if ln:
            name = ln
            break
    url = ""
    mu = _URL_RE.search(v)
    if mu:
        url = sanitize_url(mu.group(0))
    return name, url


def extract_kbpay_entries(
    message,
    *,
    seat_field_name_patterns: Sequence[str],
    account_field_name_patterns: Sequence[str],
    countdown_seconds: int,
) -> Optional[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, str]]]]]:
    """
    KB Pay（KB국민카드 · Melon KR 等）专用：
    - 识别：embed 里「支付方式 / Pay Type」字段值含 'KB Pay'
    - 二维码：embed.image.url（如 api.qrserver.com/...?data=<결제코드>）
    - 结算码：결제코드 / 结算码 字段
    - 过期：Order Expire 里的 <t:...>
    """
    d = _extract_kbpay_embed_dict(message)
    if not d:
        return None

    qr_url = sanitize_url(str((d.get("image") or {}).get("url") or ""))
    if not qr_url:
        return None

    fields = _embed_field_map(d)

    # 数据源判定：T-Splash 用 kakaopayqr S3 图；Xbot 用 api.qrserver.com
    is_tsplash = "kakaopayqr.s3.amazonaws.com" in qr_url.lower()

    settle_code = _kb_field_get(fields, "결제코드", "结算码", "결제 코드").replace("||", "").strip()
    if not settle_code:
        m = re.search(r"[?&]data=([^&#]+)", qr_url)
        if m:
            settle_code = m.group(1).strip()
    # T-Splash 没独立结算码字段，回退 OrderId 当参考号（去 spoiler ||…||）
    order_id = (fields.get("OrderId") or fields.get("Order Id") or "").replace("||", "").strip()
    if not settle_code and order_id:
        settle_code = order_id

    # 优先「支付方式」字段（앱카드…），其次 Pay Type，再回退 Paymethod（T-Splash）
    pay_method = (
        _kb_field_get(fields, "支付方式")
        or _kb_field_get(fields, "pay type")
        or _kb_field_get(fields, "paymethod")
    ).replace("||", "").strip()
    if is_tsplash and pay_method.lower() in ("kbpay", "kb pay"):
        pay_method = "KB Pay"

    site = (fields.get("Site") or "").strip()
    zone = (fields.get("Zone") or "").replace("||", "").strip()
    qty = (fields.get("Quantity") or "").strip()
    steps = _kb_field_get(fields, "扫码步骤", "扫码").strip()
    round_txt = fields.get("Round", "")
    seat_no = fields.get("Seat No", "")
    expire_txt = fields.get("Order Expire", "")

    event_name, event_url = _parse_kbpay_event(fields.get("Event", "") or site)
    time_info = _parse_kbpay_show_time(round_txt)
    seat_price = _parse_kbpay_seat(seat_no) if seat_no else {"seat_detail": "", "price": ""}

    # T-Splash 分支：从 Seat Info 取日期/zone/座位；给个默认扫码步骤
    if is_tsplash and not seat_price.get("seat_detail"):
        ts_seat = _parse_tsplash_kbpay_seat_info(fields.get("Seat Info", ""))
        seat_price["seat_detail"] = ts_seat.get("seat_detail", "")
        if not zone:
            zone = ts_seat.get("zone", "")
        if not time_info.get("date_key"):
            time_info["date_key"] = ts_seat.get("date_key", "")
            time_info["show_time"] = ts_seat.get("show_time", "")
    if is_tsplash and not steps:
        steps = "1️⃣ 打开 KB Pay App（KB국민카드）\n2️⃣ 选「결제코드 / QR결제」\n3️⃣ 扫上方二维码"

    date_key = time_info.get("date_key") or ""
    seat_detail = seat_price.get("seat_detail") or ""
    # 完整座位 = zone + 座位段（例：X 전 floor row 15 seat 7）
    # T-Splash 的 seat_detail 已含 zone（"A 구역"），不再前置避免重复
    if zone and seat_detail and not is_tsplash:
        seat_detail = f"{zone} {seat_detail}"
    elif zone and not seat_detail:
        seat_detail = zone
    # 左侧展示：日期在上、座位在下
    seat_label = f"{date_key} {seat_detail}".strip() if date_key else (seat_detail or "KB Pay")
    # seat_key 用결제코드做唯一性（不同订单不合并）
    seat_key = f"{settle_code} {seat_label}".strip() if settle_code else choose_seat_key(seat_label)

    account_info = extract_account_info_from_embeds(
        message, account_field_name_patterns, mask_password=False
    )
    link = make_message_link(message)
    now = time.time()
    # 优先用 Order Expire 里的真实 <t:...> 时间戳；否则按站点定 TTL：
    # Melon KR 5 分 / Interpark 7 分 / 其他 T-Splash 默认 5 分 / 其他 Xbot 走 countdown_seconds
    _fallback_ttl = _ttl_by_site(site, (5 * 60.0) if is_tsplash else float(countdown_seconds))
    expires_at = _parse_discord_timestamp(expire_txt) or (now + _fallback_ttl)

    meta = {
        "source": "kbpay",
        "settle_code": settle_code,
        "order_id": order_id,
        "pay_method": pay_method,
        "site": site,
        "zone": zone,
        "seat_detail": seat_detail,
        "price": seat_price.get("price") or "",
        "date": time_info.get("show_time") or "",
        "quantity": str(qty or "").strip(),
        "event": event_name,
        "event_url": event_url,
        "steps": steps,
        "qr_large": True,
    }
    items = [(qr_url, link, now, float(expires_at), meta)]
    return seat_key, seat_label, account_info, items


