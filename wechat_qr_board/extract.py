from __future__ import annotations

import re
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_MD_URL_RE = re.compile(r"\((https?://[^\s)]+)\)")
EXIMBAY_QR_KEYWORD = "secureapi.ext.eximbay.com/servlet/QRCodeGenerator"
XBOT_QR_PREFIX = "https://api.xbotaio.com/api/v1/short-url/"


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


def extract_account_info_from_embeds(message, account_field_name_patterns: Sequence[str]) -> str:
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
    # 清理：去掉尾部常见标点（T-Splash 常见末尾有 '.'），并对密码做脱敏（只保留账号）
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


