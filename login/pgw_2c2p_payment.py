"""
2C2P PGW 4.1 Payment API（与浏览器 curl 对齐）。

- ``data`` 中 ``MPaymentProcess.aspx?...`` 为 **入口**；支付宝收银台 URL 为跳转后的 **最终地址**。
- **requests**：跟 HTTP 重定向 / 表单（``resolve_mpayment_to_alipay_cashier_url``）。
- **Playwright**：打开入口页等 JS 跳转（与最初「能进到支付宝并抓图」的流程一致）；
  ``save_qr_from_pgw_response`` 在内存中截图并转 Base64（默认不落盘 PNG）；可选 ``out_path`` 才写文件。

Requires: pip install requests；抓图需 pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

PGW_PAYMENT_URL = "https://pgw.2c2p.com/payment/4.1/Payment"

DEFAULT_HEADERS = {
    "accept": "application/json",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
    "access-control-allow-origin": "*",
    "content-type": "application/json",
    "origin": "https://pgw-ui.2c2p.com",
    "priority": "u=1, i",
    "referer": "https://pgw-ui.2c2p.com/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
    ),
    "x-pgw-api-type": "UI",
    "x-pgw-client-additional-info": (
        '{"browserLanguage":"zh-CN","browserScreenWidth":2560,"browserScreenHeight":1440,'
        '"browserColorDepth":32,"browserTZ":-480,"browserJavaEnabled":false,'
        '"browserJavaScriptEnabled":true}'
    ),
    "x-pgw-client-os": "chrome 146.0.0-Windows 10",
    "x-pgw-client-type": "WEB",
    "x-pgw-client-version": "4.1",
}


def build_client_additional_info(
    *,
    lang: str = "zh-CN",
    width: int = 2560,
    height: int = 1440,
    tz_minutes: int = -480,
) -> str:
    payload = {
        "browserLanguage": lang,
        "browserScreenWidth": width,
        "browserScreenHeight": height,
        "browserColorDepth": 32,
        "browserTZ": tz_minutes,
        "browserJavaEnabled": False,
        "browserJavaScriptEnabled": True,
    }
    return json.dumps(payload, separators=(",", ":"))


def build_alipay_payment_body(
    *,
    payment_token: str,
    client_ip: str,
    client_id: str,
    email: str,
    name: str,
    mobile_no_prefix: str = "1",
    locale: str = "en",
    response_return_url: str = "https://pgw-ui.2c2p.com/payment/4.1/#/info/",
) -> dict[str, Any]:
    return {
        "paymentToken": payment_token,
        "clientIP": client_ip,
        "locale": locale,
        "responseReturnUrl": response_return_url,
        "clientID": client_id,
        "payment": {
            "code": {"channelCode": "ALIPAY"},
            "data": {
                "name": name,
                "isIppChosen": None,
                "cardDetails": {"email": email},
                "loyaltyPoints": [],
                "email": email,
                "mobileNoPrefix": mobile_no_prefix,
                "qrType": "URL",
            },
        },
    }


def extract_payment_token_from_url(url: str) -> str | None:
    raw = url.strip()
    p = urlparse(raw)
    frag = p.fragment or ""
    m = re.search(r"(?:^|/)token/([^?#&]+)", frag)
    if m:
        return unquote(m.group(1).strip())
    m = re.search(r"#/token/([^?#\"'\\s<>]+)", raw)
    if m:
        return unquote(m.group(1).strip())

    for part in (p.query, frag):
        if not part:
            continue
        qs = parse_qs(part)
        for key in ("paymentToken", "payment_token", "token", "jwt"):
            if qs.get(key) and qs[key][0]:
                return unquote(qs[key][0])
    m = re.search(r"paymentToken=([^&]+)", raw)
    if m:
        return unquote(m.group(1))
    return None


def _find_payment_expiry_in_obj(obj: Any, max_depth: int = 24) -> str | None:
    """在嵌套 dict/list 中查找 ``payment_expiry`` / ``paymentExpiry``。"""
    if max_depth <= 0:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).replace("-", "_").lower()
            if lk in ("payment_expiry", "paymentexpiry"):
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if v is not None and not isinstance(v, (dict, list)):
                    s = str(v).strip()
                    if s:
                        return s
            found = _find_payment_expiry_in_obj(v, max_depth - 1)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_payment_expiry_in_obj(it, max_depth - 1)
            if found:
                return found
    return None


def _try_decode_base64_json(s: str) -> Any | None:
    s = s.strip()
    if not s:
        return None
    pad = (-len(s)) % 4
    try:
        raw = base64.urlsafe_b64decode(s + "=" * pad)
    except Exception:
        try:
            raw = base64.b64decode(s + "=" * pad, validate=False)
        except Exception:
            return None
    try:
        t = raw.decode("utf-8")
    except Exception:
        return None
    try:
        return json.loads(t)
    except Exception:
        return None


def extract_payment_expiry(resp_json: Any) -> str | None:
    """
    从 PGW 响应 JSON 取支付截止时间。
    若顶层含 ``base``（常为 base64 的 JSON），会解码后再搜 ``payment_expiry``。
    """
    found = _find_payment_expiry_in_obj(resp_json)
    if found:
        return found
    if isinstance(resp_json, dict):
        b = resp_json.get("base")
        if isinstance(b, str) and b.strip():
            inner = _try_decode_base64_json(b)
            if inner is not None:
                return _find_payment_expiry_in_obj(inner)
    return None


# 收银台 / 支付跳转常见域名（用于链接判断，排除 gw.alipayobjects 等静态域）
ALIPAY_CASHIER_NETLOC_EXACT: frozenset[str] = frozenset(
    {
        "excashier.alipay.com",
        "render.alipay.com",
        "openapi.alipay.com",
        "global.alipay.com",
        "mapi.alipay.com",
        "unitradeprod.alipay.com",
        "payments.alipay.com",
    }
)


def is_alipay_cashier_url(url: str) -> bool:
    """
    是否为「支付宝收银台 / 支付授权页」类链接（旧版逻辑：白名单 host + 路径/参数特征）。
    通过此判断的 URL 才会作为最终收银台输出候选。
    """
    raw = (url or "").strip()
    if not raw:
        return False
    try:
        p = urlparse(raw)
        host = p.netloc.lower()
    except Exception:
        return False
    if not host or "alipay" not in host:
        return False

    if host in ALIPAY_CASHIER_NETLOC_EXACT:
        return True
    for suf in ALIPAY_CASHIER_NETLOC_EXACT:
        if host.endswith("." + suf):
            return True

    path = (p.path or "").lower()
    q = (p.query or "").lower()
    if host.endswith(".alipay.com") or host.endswith(".alipay.com.cn"):
        if "auth_order_id" in q or "/standard/auth" in path or "cashier" in path:
            return True
    return False


def alipay_cashier_link_kind(url: str) -> str:
    """通过判断后的粗分类，便于日志；未通过则为 ``none``。"""
    if not is_alipay_cashier_url(url):
        return "none"
    lo = url.lower()
    if "excashier.alipay.com" in lo:
        return "excashier"
    if "render.alipay.com" in lo:
        return "render"
    if "openapi.alipay.com" in lo:
        return "openapi"
    if "global.alipay.com" in lo:
        return "global"
    return "other_alipay"


MPAYMENT_FETCH_HEADERS = {
    "User-Agent": DEFAULT_HEADERS["user-agent"],
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": DEFAULT_HEADERS["accept-language"],
    "Referer": "https://pgw-ui.2c2p.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Upgrade-Insecure-Requests": "1",
}


def _meta_refresh_url(html: str) -> str | None:
    if not html:
        return None
    m = re.search(
        r'http-equiv\s*=\s*["\']?\s*refresh\s*["\']?[^>]+content\s*=\s*["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if not m:
        m = re.search(
            r'content\s*=\s*["\']([^"\']+)["\'][^>]+http-equiv\s*=\s*["\']?\s*refresh',
            html,
            re.I,
        )
    if not m:
        return None
    content = m.group(1).strip()
    um = re.search(r"url\s*=\s*([^;]+)", content, re.I)
    if not um:
        return None
    raw = um.group(1).strip().strip("'\"").strip()
    return unescape(raw) or None


def _denormalize_json_escapes_in_html(html: str) -> str:
    """把内嵌 JSON/JS 里的 ``https:\\/\\/`` 等还原，便于正则提取支付宝链接。"""
    if not html:
        return ""
    s = html
    s = s.replace("https:\\/\\/", "https://")
    s = s.replace("http:\\/\\/", "http://")
    return s


def _log_http_redirect_chain(resp: requests.Response) -> None:
    if not resp.history:
        return
    for rh in resp.history:
        loc = rh.headers.get("Location") or rh.headers.get("location") or ""
        print(f"http_redirect: {rh.status_code} {rh.url!r} Location={loc!r}", file=sys.stderr)
    print(f"http_redirect_final: {resp.status_code} {resp.url!r}", file=sys.stderr)


def _parse_form_inputs(form_inner: str) -> dict[str, str]:
    """解析 ``<form>`` 内 ``<input>``（含 hidden），用于自动 POST。"""
    out: dict[str, str] = {}
    for im in re.finditer(r"<input\b([^>]*)/?>", form_inner, re.I):
        tag = im.group(1)
        tym = re.search(r'type\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        typ = (tym.group(1).lower() if tym else "text").strip()
        if typ in ("image", "button", "reset"):
            continue
        nm = re.search(r'name\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        if not nm:
            continue
        name = nm.group(1)
        vm = re.search(r'value\s*=\s*"([^"]*)"', tag, re.I)
        if not vm:
            vm = re.search(r"value\s*=\s*'([^']*)'", tag, re.I)
        val = vm.group(1) if vm else ""
        out[name] = val
    return out


def _form_autopost_score(action_abs: str, field_count: int) -> int:
    s = action_abs.lower()
    score = field_count * 2
    if "alipay" in s:
        score += 80
    if "2c2p" in s:
        score += 60
    if "payment" in s or "acs" in s or "threed" in s or "secure" in s:
        score += 25
    return score


def _try_follow_autopost_form(
    sess: requests.Session,
    html: str,
    page_url: str,
    *,
    verify: bool,
    timeout: float,
) -> requests.Response | None:
    """
    许多网关返回 200 + 自动提交表单而非 302；浏览器会 POST 到 action，再跳到支付宝。
    """
    if not html or "<form" not in html.lower():
        return None
    if "2c2p.com" not in page_url.lower():
        return None
    best: tuple[int, str, dict[str, str]] | None = None
    for m in re.finditer(r"<form\b([^>]*)>", html, re.I):
        attrs = m.group(1)
        if re.search(r'method\s*=\s*["\']?\s*post\s*["\']?', attrs, re.I) is None:
            continue
        am = re.search(r'action\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
        if not am:
            am = re.search(r"action\s*=\s*([^\s>]+)", attrs, re.I)
        if not am:
            continue
        action = unescape(am.group(1).strip().strip('"').strip("'"))
        if not action:
            continue
        action_abs = urljoin(page_url, action)
        body_start = m.end()
        end_m = re.search(r"</form>", html[body_start:], re.I)
        form_inner = html[body_start : body_start + end_m.start()] if end_m else html[body_start:]
        data = _parse_form_inputs(form_inner)
        sc = _form_autopost_score(action_abs, len(data))
        if best is None or sc > best[0]:
            best = (sc, action_abs, data)
    if best is None:
        return None
    sc, action_abs, data = best
    low_a = action_abs.lower()
    if len(data) < 1 and not any(k in low_a for k in ("2c2p", "alipay")):
        return None
    origin = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    post_headers = {
        **MPAYMENT_FETCH_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": page_url,
        "Origin": origin,
    }
    try:
        pr = sess.post(
            action_abs,
            data=data,
            headers=post_headers,
            allow_redirects=True,
            verify=verify,
            timeout=timeout,
        )
        print(f"form_post: {action_abs} -> {pr.status_code} {pr.url!r}", file=sys.stderr)
        _log_http_redirect_chain(pr)
        return pr
    except requests.RequestException as exc:
        print(f"form_post failed: {exc}", file=sys.stderr)
        return None


def _extract_urls_from_js_redirects(html: str) -> list[str]:
    if not html:
        return []
    patterns = [
        r'(?:window\.)?location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)["\']',
        r'document\.location\s*=\s*["\'](https?://[^"\']+)["\']',
        r'top\.location(?:\.href)?\s*=\s*["\'](https?://[^"\']+)["\']',
        r'location\.replace\s*\(\s*["\'](https?://[^"\']+)["\']',
        r'location\.assign\s*\(\s*["\'](https?://[^"\']+)["\']',
    ]
    out: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, html, re.I):
            out.append(unescape(m.group(1).strip()))
    return out


def _pick_best_alipay_cashier_url(candidates: list[str]) -> str | None:
    """
    在多个 URL 中择优：仅保留通过 ``is_alipay_cashier_url`` 的候选（链接判断）。

    目标形态（2C2P → 支付宝）：
    ``https://excashier.alipay.com/standard/auth.htm?auth_order_id=exc_...``
    """
    judged = [u for u in candidates if is_alipay_cashier_url(u)]
    if not judged:
        return None
    # 越靠前越优先
    priority = (
        "excashier.alipay.com",
        "render.alipay.com",
        "openapi.alipay.com",
        "global.alipay.com",
        "alipay.com",
    )

    def score(u: str) -> tuple[int, int, int]:
        lo = u.lower()
        tier = len(priority)
        for i, p in enumerate(priority):
            if p in lo:
                tier = i
                break
        # 同 tier 时优先 standard/auth + auth_order_id
        generic = 0 if ("auth_order_id" in lo or "/standard/auth" in lo) else 1
        return (tier, generic, -len(u))

    return min(judged, key=score)


def _extract_alipay_cashier_url_from_html(html: str) -> str | None:
    """从 HTML 中挑最像支付宝收银台的 ``https`` 链接（非静态资源）。"""
    if not html or "alipay" not in html.lower():
        return None
    pat = re.compile(r"https?://[^\s\"'<>]+", re.I)
    skip_suffix = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".js", ".css", ".ico", ".svg")
    candidates: list[str] = []
    for m in pat.finditer(html):
        u = m.group(0).rstrip("\\,.);'\"")
        low = u.lower()
        if "alipay" not in low:
            continue
        if any(low.endswith(s) for s in skip_suffix):
            continue
        if not is_alipay_cashier_url(u):
            continue
        candidates.append(u)
    return _pick_best_alipay_cashier_url(candidates)


def resolve_mpayment_to_alipay_cashier_url(
    mpayment_url: str,
    *,
    session: requests.Session | None = None,
    verify: bool = True,
    timeout: float = 60.0,
    max_hops: int = 8,
) -> tuple[str, requests.Response | None]:
    """
    从 **入口** ``MPaymentProcess.aspx?...`` 尽力解析 **跳转后** 的收银台 URL（HTTP/表单/HTML）。
    若页面仅「请稍候」并由 JS 跳转，requests 往往仍停在 2c2p，需 ``playwright_resolve_mpayment_to_alipay_url``。
    """
    sess = session or requests.Session()
    current = mpayment_url.strip()
    seen: set[str] = set()
    last_r: requests.Response | None = None
    referer = "https://pgw-ui.2c2p.com/"

    for _ in range(max_hops):
        if current in seen:
            break
        seen.add(current)
        try:
            h_get = {**MPAYMENT_FETCH_HEADERS, "Referer": referer}
            last_r = sess.get(
                current,
                headers=h_get,
                allow_redirects=True,
                verify=verify,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            print(f"GET {current!r} failed: {exc}", file=sys.stderr)
            return current, last_r

        _log_http_redirect_chain(last_r)
        landed = last_r.url
        referer = landed
        if is_alipay_cashier_url(landed):
            return landed, last_r

        text = last_r.text or ""

        for _ft in range(4):
            form_r = _try_follow_autopost_form(
                sess, text, landed, verify=verify, timeout=timeout
            )
            if form_r is None:
                break
            last_r = form_r
            landed = last_r.url
            referer = landed
            if is_alipay_cashier_url(landed):
                return landed, last_r
            text = last_r.text or ""

        scan = text + "\n" + _denormalize_json_escapes_in_html(text)

        nxt = _meta_refresh_url(text)
        if nxt:
            abs_u = urljoin(landed, nxt)
            if abs_u != current:
                if is_alipay_cashier_url(abs_u):
                    return abs_u, last_r
                current = abs_u
                continue

        js_alipay = _extract_urls_from_js_redirects(scan)
        best_js = _pick_best_alipay_cashier_url(js_alipay)
        if best_js:
            return best_js, last_r

        embedded = _extract_alipay_cashier_url_from_html(scan)
        if embedded:
            return embedded, last_r

        return landed, last_r

    return current, last_r


def _playwright_cookie_list_from_session(
    sess: requests.Session | None, for_url: str
) -> list[dict[str, Any]]:
    """把 ``requests`` 里适用于 ``for_url`` 主机的 Cookie 转成 Playwright ``add_cookies`` 格式。"""
    if not sess:
        return []
    host = (urlparse(for_url).hostname or "").lower()
    rows: list[dict[str, Any]] = []
    for c in sess.cookies:
        dom = (c.domain or "").lstrip(".").lower()
        if not dom:
            dom = host
        if host != dom and not host.endswith("." + dom):
            continue
        row: dict[str, Any] = {
            "name": c.name,
            "value": c.value or "",
            "domain": dom,
            "path": c.path or "/",
        }
        if getattr(c, "secure", False):
            row["secure"] = True
        rows.append(row)
    return rows


def _playwright_wait_alipay_cashier(page: Any, timeout_sec: float) -> str:
    """在超时内轮询地址栏，直到 ``is_alipay_cashier_url`` 或时间用尽。"""
    deadline = time.time() + max(5.0, timeout_sec)
    alipay_re = re.compile(r"https?://[^/]*alipay", re.I)
    while time.time() < deadline:
        cur = page.url
        if is_alipay_cashier_url(cur):
            return cur
        try:
            page.wait_for_url(alipay_re, timeout=2_000)
        except Exception:
            pass
        time.sleep(0.35)
    time.sleep(1.2)
    return page.url


def _playwright_capture_qr_png_bytes(page: Any) -> bytes | None:
    """在支付宝收银台页截取二维码为 PNG **字节**（不写磁盘）。"""
    selectors = (
        "[class*='qrcode'] canvas",
        "canvas#qr",
        "canvas.qrcode",
        "#J_qrcode canvas",
        "img[src*='qr']",
        "img[alt*='二维码']",
        "img[alt*='QR']",
    )
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() == 0:
                continue
        except Exception:
            continue
        first = loc.first
        try:
            box = first.bounding_box()
            if box and box["width"] >= 64 and box["height"] >= 64:
                png = first.screenshot(type="png")
                if png:
                    print(f"qr_capture: selector={sel!r} ({len(png)} bytes)", file=sys.stderr)
                    return png
        except Exception:
            continue

    canvases = page.locator("canvas")
    try:
        n = canvases.count()
    except Exception:
        n = 0
    best_idx = -1
    best_area = 0.0
    for i in range(n):
        c = canvases.nth(i)
        try:
            box = c.bounding_box()
            if not box:
                continue
            a = box["width"] * box["height"]
            if a > best_area and box["width"] >= 64:
                best_area = a
                best_idx = i
        except Exception:
            continue
    if best_idx >= 0:
        try:
            png = canvases.nth(best_idx).screenshot(type="png")
            if png:
                print(f"qr_capture: largest canvas ({len(png)} bytes)", file=sys.stderr)
                return png
        except Exception:
            pass

    try:
        png = page.screenshot(full_page=True, type="png")
        if png:
            print(f"qr_capture: full_page fallback ({len(png)} bytes)", file=sys.stderr)
            return png
    except Exception as exc:
        print(f"qr_capture failed: {exc}", file=sys.stderr)
    return None


def playwright_resolve_mpayment_to_alipay_url(
    mpayment_url: str,
    *,
    session: requests.Session | None = None,
    verify: bool = True,
    timeout_sec: float = 90.0,
    headless: bool = True,
) -> str | None:
    """
    用 Chromium 打开 MPaymentProcess「请稍候」页，注入 ``session`` Cookie，等 JS 跳到支付宝。
    仅返回最终地址字符串（不关二维码文件）。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "未安装 playwright：pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return None

    u0 = mpayment_url.strip()
    deadline_ms = max(8_000, int(timeout_sec * 1000))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            ctx = browser.new_context(
                user_agent=MPAYMENT_FETCH_HEADERS["User-Agent"],
                ignore_https_errors=not verify,
                locale="zh-CN",
            )
            cookies = _playwright_cookie_list_from_session(session, u0)
            if cookies:
                ctx.add_cookies(cookies)
                print(f"playwright: injected {len(cookies)} cookie(s)", file=sys.stderr)
            page = ctx.new_page()
            page.goto(u0, wait_until="load", timeout=deadline_ms)
            end = _playwright_wait_alipay_cashier(page, timeout_sec)
            if is_alipay_cashier_url(end):
                print("playwright: 已到达支付宝收银台 URL", file=sys.stderr)
                return end
            print(
                f"playwright: 当前页 {end!r} 未通过收银台链接判断",
                file=sys.stderr,
            )
            return None
        finally:
            browser.close()


def png_path_to_base64(path: Path) -> str:
    """PNG 文件 → 标准 Base64 字符串（无换行），便于 JSON / 其它系统再生成图片。"""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def png_path_to_data_uri(path: Path) -> str:
    """PNG → ``data:image/png;base64,...``，便于直接塞进 HTML ``<img src>``。"""
    return "data:image/png;base64," + png_path_to_base64(path)


def png_bytes_to_base64(png_bytes: bytes) -> str:
    """PNG 字节 → 标准 Base64（无换行）。"""
    return base64.b64encode(png_bytes).decode("ascii")


def png_bytes_to_data_uri(png_bytes: bytes) -> str:
    """PNG 字节 → ``data:image/png;base64,...``。"""
    return "data:image/png;base64," + png_bytes_to_base64(png_bytes)


def save_qr_from_pgw_response(
    resp: requests.Response,
    out_path: Path | None = None,
    *,
    session: requests.Session | None = None,
    verify: bool = True,
    timeout_sec: float = 120.0,
    headless: bool = True,
    qr_base64_as_data_uri: bool = False,
    qr_base64_out: Path | None = None,
) -> tuple[Path | None, str | None, str | None, bytes | None]:
    """
    解析 PGW JSON → Playwright 跟跳到支付宝 → **内存截图** PNG 字节（默认不写 ``.png``）。

    返回 ``(可选落盘的 png 路径, 收银台 URL, PGW payment_expiry, png 字节或 None)``。

    - ``out_path``：若提供，再把 PNG 字节写入该路径。
    - ``qr_base64_out``：将 Base64 或 data-uri **文本**写入该文件。
    """
    try:
        data = resp.json()
    except Exception:
        print("PGW 响应非 JSON", file=sys.stderr)
        return None, None, None, None

    mpayment = extract_pgw_data_url(data)
    exp = extract_payment_expiry(data)
    if not mpayment:
        print("PGW JSON 无 data URL", file=sys.stderr)
        return None, None, exp, None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "未安装 playwright：pip install playwright && playwright install chromium",
            file=sys.stderr,
        )
        return None, None, exp, None

    u0 = mpayment.strip()
    deadline_ms = max(8_000, int(timeout_sec * 1000))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            ctx = browser.new_context(
                user_agent=MPAYMENT_FETCH_HEADERS["User-Agent"],
                ignore_https_errors=not verify,
                locale="zh-CN",
                viewport={"width": 1280, "height": 900},
            )
            cookies = _playwright_cookie_list_from_session(session, u0)
            if cookies:
                ctx.add_cookies(cookies)
                print(f"playwright: injected {len(cookies)} cookie(s)", file=sys.stderr)
            page = ctx.new_page()
            print(f"mpayment_url: {u0}", file=sys.stderr)
            page.goto(u0, wait_until="load", timeout=deadline_ms)
            end = _playwright_wait_alipay_cashier(page, timeout_sec)
            if not is_alipay_cashier_url(end):
                print(f"未进入支付宝收银台，当前: {end!r}", file=sys.stderr)
                return None, None, exp, None
            print(f"alipay_cashier_url: {end}", file=sys.stderr)
            raw = _playwright_capture_qr_png_bytes(page)
            if raw is None:
                return None, end, exp, None
            png_path: Path | None = None
            if out_path is not None:
                try:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(raw)
                    png_path = out_path
                    print(f"qr_png_file: {out_path}", file=sys.stderr)
                except OSError as exc:
                    print(f"qr png file write failed: {exc}", file=sys.stderr)
            if qr_base64_out is not None:
                try:
                    payload = (
                        png_bytes_to_data_uri(raw)
                        if qr_base64_as_data_uri
                        else png_bytes_to_base64(raw)
                    )
                    qr_base64_out.parent.mkdir(parents=True, exist_ok=True)
                    qr_base64_out.write_text(payload, encoding="ascii")
                    print(f"qr_base64_file: {qr_base64_out}", file=sys.stderr)
                except OSError as exc:
                    print(f"qr base64 file write failed: {exc}", file=sys.stderr)
            return png_path, end, exp, raw
        finally:
            browser.close()


def _find_data_http_url_in_obj(obj: Any, max_depth: int = 24) -> str | None:
    """在嵌套结构里找值为 ``http(s)`` 的 ``data`` 字段（与 PGW / ``base`` 内嵌 JSON 一致）。"""
    if max_depth <= 0:
        return None
    if isinstance(obj, dict):
        d = obj.get("data")
        if isinstance(d, str) and d.strip().lower().startswith("http"):
            return d.strip()
        for v in obj.values():
            found = _find_data_http_url_in_obj(v, max_depth - 1)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_data_http_url_in_obj(it, max_depth - 1)
            if found:
                return found
    return None


def extract_pgw_data_url(resp_json: Any) -> str | None:
    """响应 JSON 中 ``data`` 里的 ``http(s)`` URL（含顶层与解码 ``base`` 后的嵌套）。"""
    if not isinstance(resp_json, dict):
        return None
    found = _find_data_http_url_in_obj(resp_json)
    if found:
        return found
    b = resp_json.get("base")
    if isinstance(b, str) and b.strip():
        inner = _try_decode_base64_json(b)
        if isinstance(inner, dict):
            return _find_data_http_url_in_obj(inner)
    return None


def print_pgw_payment_summary(
    resp: requests.Response,
    *,
    dump_path: Path | None = None,
    session: requests.Session | None = None,
    verify: bool = True,
    follow_to_cashier: bool = True,
    fetch_timeout: float = 60.0,
    playwright_fallback: bool = False,
    print_payment_expiry_line: bool = True,
) -> None:
    """
    **stdout 第一行**：仅当解析到 **支付宝收银台 URL**（``is_alipay_cashier_url``）时打印；
    MPaymentProcess 入口只写在 stderr，避免与「跳转后的完整收银台链接」混淆。

    另打印 ``payment_expiry``（若 JSON 中存在）。可选 ``playwright_fallback`` 在 requests 不够时
    用浏览器等待 JS 跳转（仍不抓二维码）。
    """
    try:
        data = resp.json()
    except Exception:
        print("响应非 JSON，前 800 字符：", file=sys.stderr)
        print((resp.text or "")[:800], file=sys.stderr)
        return

    url = extract_pgw_data_url(data)
    exp = extract_payment_expiry(data)

    if url and follow_to_cashier:
        print(f"mpayment_url: {url}", file=sys.stderr)
        final, _page_r = resolve_mpayment_to_alipay_cashier_url(
            url,
            session=session,
            verify=verify,
            timeout=fetch_timeout,
        )
        if not is_alipay_cashier_url(final) and playwright_fallback:
            pw = playwright_resolve_mpayment_to_alipay_url(
                url,
                session=session,
                verify=verify,
                timeout_sec=fetch_timeout,
            )
            if pw:
                final = pw
        if is_alipay_cashier_url(final):
            print(final)
            print(f"alipay_link_judgment: {alipay_cashier_link_kind(final)}", file=sys.stderr)
        else:
            print("alipay_link_judgment: none", file=sys.stderr)
            print(
                "说明: ``data`` 里的链接是 2C2P 入口（见 mpayment_url），"
                "支付宝收银台完整 URL 须在该页跳转结束后的最终地址；"
                "纯 requests 常拿不到「请稍候」类 JS 跳转。请使用 --playwright "
                "或在浏览器中打开 mpayment_url。",
                file=sys.stderr,
            )
    elif url:
        print(url)
    else:
        print("data: <missing>", file=sys.stderr)

    if print_payment_expiry_line:
        if exp:
            print(f"payment_expiry = {exp}")
        else:
            print("payment_expiry: <missing>")

    if dump_path is not None:
        dump_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"(full JSON -> {dump_path})", file=sys.stderr)


def post_pgw_payment(
    body: dict[str, Any],
    *,
    session: requests.Session | None = None,
    verify: bool = True,
    timeout: float = 60.0,
    extra_headers: dict[str, str] | None = None,
) -> requests.Response:
    sess = session or requests.Session()
    h = {**DEFAULT_HEADERS, **(extra_headers or {})}
    return sess.post(
        PGW_PAYMENT_URL,
        headers=h,
        json=body,
        timeout=timeout,
        verify=verify,
    )


# =============================================================================
# PyCharm：填下面变量后 Run
# =============================================================================
PAYMENT_TOKEN = ""
CLIENT_ID = ""
CLIENT_IP = "127.0.0.1"
PAYER_EMAIL = ""
PAYER_NAME = ""
REQUESTS_VERIFY = True
DUMP_PGW_JSON: Path | None = None  # 设为 Path("pgw_response.json") 可保存完整响应
PLAYWRIGHT_FALLBACK = False  # True：requests 未跳到支付宝时用 Playwright 跟跳（不抓图）
# 抓二维码：默认只内存截图并 stdout 输出 Base64；若要另存 PNG 设 PGW_QR_OUT
PGW_QR_OUT: Path | None = None  # 例如 Path("alipay_qr.png")；None 则不写 PNG
PGW_PRINT_QR_BASE64 = True  # True：stdout 一行 qr_png_base64=...（或 data URI）
PGW_QR_BASE64_AS_DATA_URI = False  # True：qr_png_data_uri=data:image/png;base64,...
PGW_QR_BASE64_OUT: Path | None = None  # 可选：把 base64/data-uri 文本写入文件


def _run_ide() -> None:
    if not PAYMENT_TOKEN.strip():
        print("设置 PAYMENT_TOKEN（及 CLIENT_ID、邮箱等）", file=sys.stderr)
        raise SystemExit(1)
    body = build_alipay_payment_body(
        payment_token=PAYMENT_TOKEN.strip(),
        client_ip=CLIENT_IP.strip(),
        client_id=CLIENT_ID.strip(),
        email=PAYER_EMAIL.strip(),
        name=PAYER_NAME.strip(),
    )
    sess = requests.Session()
    r = post_pgw_payment(body, session=sess, verify=REQUESTS_VERIFY)
    print(r.status_code, r.headers.get("Content-Type", ""), file=sys.stderr)
    if PGW_QR_OUT is not None or PGW_PRINT_QR_BASE64:
        _png, cashier, exp, raw = save_qr_from_pgw_response(
            r,
            PGW_QR_OUT,
            session=sess,
            verify=REQUESTS_VERIFY,
            qr_base64_as_data_uri=PGW_QR_BASE64_AS_DATA_URI,
            qr_base64_out=PGW_QR_BASE64_OUT,
        )
        if cashier:
            print(cashier)
        if PGW_PRINT_QR_BASE64 and raw is not None:
            payload = (
                png_bytes_to_data_uri(raw)
                if PGW_QR_BASE64_AS_DATA_URI
                else png_bytes_to_base64(raw)
            )
            key = "qr_png_data_uri" if PGW_QR_BASE64_AS_DATA_URI else "qr_png_base64"
            print(f"{key}={payload}")
        if exp:
            print(f"payment_expiry = {exp}")
        else:
            print("payment_expiry: <missing>")
        if DUMP_PGW_JSON is not None:
            try:
                DUMP_PGW_JSON.write_text(
                    json.dumps(r.json(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"(full JSON -> {DUMP_PGW_JSON})", file=sys.stderr)
            except Exception:
                pass
    else:
        print_pgw_payment_summary(
            r,
            dump_path=DUMP_PGW_JSON,
            session=sess,
            verify=REQUESTS_VERIFY,
            playwright_fallback=PLAYWRIGHT_FALLBACK,
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="2C2P PGW 4.1 Payment — print final Alipay cashier URL & payment_expiry"
    )
    p.add_argument("--token", help="paymentToken (or pass full pgw URL to --from-url)")
    p.add_argument("--from-url", dest="from_url", help="page URL containing paymentToken")
    p.add_argument("--client-id", required=True, help="X-PGW clientID (UUID from browser)")
    p.add_argument("--client-ip", default="127.0.0.1")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--dump-json", type=Path, default=None, help="write full response JSON to this path")
    p.add_argument(
        "--no-follow",
        action="store_true",
        help="only print PGW data URL (MPaymentProcess), do not resolve to Alipay cashier",
    )
    p.add_argument(
        "--playwright",
        action="store_true",
        help="if requests cannot reach alipay, use headless Chromium to wait for JS redirect (no QR)",
    )
    p.add_argument(
        "--qr-out",
        type=Path,
        default=None,
        help="optional: also write PNG to this path (capture is in-memory by default)",
    )
    p.add_argument(
        "--print-qr-base64",
        action="store_true",
        help="capture QR in Playwright (no PNG file unless --qr-out) and print qr_png_base64=... on stdout",
    )
    p.add_argument(
        "--qr-base64-data-uri",
        action="store_true",
        help="with --print-qr-base64, use prefix data:image/png;base64,... (key qr_png_data_uri)",
    )
    p.add_argument(
        "--qr-base64-out",
        type=Path,
        default=None,
        help="write raw base64 or data-uri string to this file (no key prefix)",
    )
    p.add_argument("--insecure", action="store_true")
    args = p.parse_args()

    token = args.token
    if args.from_url:
        token = extract_payment_token_from_url(args.from_url) or token
    if not token:
        p.error("need --token or --from-url with paymentToken")

    body = build_alipay_payment_body(
        payment_token=token,
        client_ip=args.client_ip,
        client_id=args.client_id,
        email=args.email,
        name=args.name,
    )
    verify = not args.insecure
    if not verify:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    sess = requests.Session()
    r = post_pgw_payment(body, session=sess, verify=verify)
    print(r.status_code, file=sys.stderr)
    if args.qr_out is not None or args.print_qr_base64:
        _png, cashier, exp, raw = save_qr_from_pgw_response(
            r,
            args.qr_out,
            session=sess,
            verify=verify,
            qr_base64_as_data_uri=args.qr_base64_data_uri,
            qr_base64_out=args.qr_base64_out,
        )
        if cashier:
            print(cashier)
        if args.print_qr_base64 and raw is not None:
            payload = (
                png_bytes_to_data_uri(raw)
                if args.qr_base64_data_uri
                else png_bytes_to_base64(raw)
            )
            key = "qr_png_data_uri" if args.qr_base64_data_uri else "qr_png_base64"
            print(f"{key}={payload}")
        if exp:
            print(f"payment_expiry = {exp}")
        else:
            print("payment_expiry: <missing>")
        if args.dump_json is not None:
            try:
                args.dump_json.write_text(
                    json.dumps(r.json(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"(full JSON -> {args.dump_json})", file=sys.stderr)
            except Exception:
                pass
    else:
        print_pgw_payment_summary(
            r,
            dump_path=args.dump_json,
            session=sess,
            verify=verify,
            follow_to_cashier=not args.no_follow,
            playwright_fallback=args.playwright,
        )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        _run_ide()
