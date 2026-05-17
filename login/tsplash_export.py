"""
Parse T-Splash export links (export.tsplash.com/?data=...) and reproduce the
extension flow: decode payload, optional cookie map, and POST form to 2C2P.

Mirrors background.js: Base64 JSON, cookies as URL -> "a=b; c=d", formObj split
by &, value handling decodeURIComponent then '+' -> space.

PyCharm: ``EXPORT_URL`` + optional PGW：请求头/JSON 结构与抓包 curl 一致，仅 ``PGW_NAME`` /
``PGW_EMAIL`` 由你填写；``paymentToken`` / ``clientID`` 与 curl 中字段一致（见底部常量）。

Functions: ``run_pgw_print_payment_redirect``, ``run_tsplash_export_with_redirect_response``, etc.

Security: export URLs contain session cookies and payment tokens — treat as secrets.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

# Thai Ticket Major: extension sets Referer to booking origin for main_frame (DNR rule).
DEFAULT_2C2P_REFERER = "https://booking.thaiticketmajor.com/"

_SHORTLINK_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _import_pgw():
    """
    Support both:
    - import as package: `import login.tsplash_export` (preferred by server)
    - run as script: `python login/tsplash_export.py` (legacy)
    """
    try:
        from . import pgw_2c2p_payment as pgw  # type: ignore

        return pgw
    except Exception:
        import pgw_2c2p_payment as pgw  # type: ignore

        return pgw


def _is_tsplash_export_with_data(url: str) -> bool:
    p = urlparse(url.strip())
    if (p.hostname or "").lower() != "export.tsplash.com":
        return False
    qs = parse_qs(p.query)
    return bool(qs.get("data"))


def _configure_requests_verify(verify: bool | str) -> bool | str:
    """If TLS verify is off, silence urllib3 warning spam."""
    if verify is False:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return verify


def expand_shortlink_to_tsplash(
    url: str,
    *,
    timeout: float = 20.0,
    verify: bool | str = True,
    max_redirects: int = 15,
) -> str:
    """
    Follow redirects (e.g. short.gy) until we get ``export.tsplash.com/?data=...``.

    Uses **manual** redirects: if ``Location`` already points at a full export URL, we
    return it **without** connecting to ``export.tsplash.com``. That avoids Python
    TLS errors (e.g. ``TLSV1_UNRECOGNIZED_NAME``) on that host while still resolving
    short links.

    If the last response is 200 HTML, try to extract the export URL from the body.
    """
    import requests

    verify = _configure_requests_verify(verify)
    headers = {
        "User-Agent": _SHORTLINK_BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    session = requests.Session()
    current = url.strip()

    for _ in range(max_redirects):
        if _is_tsplash_export_with_data(current):
            return current

        r = session.get(
            current,
            allow_redirects=False,
            timeout=timeout,
            headers=headers,
            verify=verify,
        )
        loc = r.headers.get("Location") or r.headers.get("location")
        if loc and r.status_code in (301, 302, 303, 307, 308):
            nxt = urljoin(current, loc.strip())
            if _is_tsplash_export_with_data(nxt):
                return nxt
            current = nxt
            continue

        final = (getattr(r, "url", None) or current).strip()
        if _is_tsplash_export_with_data(final):
            return final

        body = r.text or ""
        m = re.search(r"https?://export\.tsplash\.com/\?[^\s\"'<>]+", body, re.I)
        if m and _is_tsplash_export_with_data(m.group(0)):
            return m.group(0).rstrip("&).,]")
        raise ValueError(
            "短链跟跳后仍未得到 export.tsplash.com/?data=...，最后请求 "
            f"{final[:120] if final else '(?)'} HTTP {r.status_code}"
        )

    raise ValueError(f"短链重定向超过 {max_redirects} 次")


def _b64decode_data_param(raw: str) -> bytes:
    s = raw.replace(" ", "+")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return base64.b64decode(s, validate=False)


def parse_tsplash_export_url(export_url: str) -> dict[str, Any]:
    """Decode the `data` query parameter to the same JSON object the extension uses."""
    parsed = urlparse(export_url.strip())
    if not parsed.query:
        raise ValueError("URL has no query string")
    qs = parse_qs(parsed.query)
    if "data" not in qs or not qs["data"]:
        raise ValueError("Missing `data` query parameter")
    raw = qs["data"][0]
    return json.loads(_b64decode_data_param(raw).decode("utf-8"))


def decode_form_field_value(encoded: str) -> str:
    """Match extension: decodeURIComponent(value), then replace '+' with space."""
    return unquote(encoded).replace("+", " ")


def form_string_to_tuples(form: str) -> list[tuple[str, str]]:
    """
    Parse formObj['form'] like the extension (split on &, first '=' separates name/value).
    """
    out: list[tuple[str, str]] = []
    for pair in form.split("&"):
        if not pair:
            continue
        if "=" not in pair:
            out.append((pair, ""))
            continue
        name, value = pair.split("=", 1)
        out.append((name, decode_form_field_value(value)))
    return out


def form_obj_to_post_data(form_obj: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    """Returns (action_url, method, data_dict) for requests or printing."""
    method = form_obj.get("method", "POST").upper()
    action = form_obj["action"]
    form = form_obj["form"]
    if not isinstance(form, str):
        raise TypeError("formObj.form must be a string")
    pairs = form_string_to_tuples(form)
    return action, method, dict(pairs)


def extract_redirectv3_payment_meta(payload: dict[str, Any]) -> dict[str, str | None]:
    """
    从 T-Splash 解码后的整包 JSON（含 ``formObj``）或单独的 ``formObj`` 字典中，
    取出 RedirectV3 表单里的 ``payment_description`` / ``order_id`` / ``payment_expiry``。
    """
    form_obj: dict[str, Any] | None = None
    if isinstance(payload.get("formObj"), dict):
        form_obj = payload["formObj"]
    elif "form" in payload and "action" in payload:
        form_obj = payload
    if not form_obj:
        return {"payment_description": None, "order_id": None, "payment_expiry": None}
    try:
        _, _, data = form_obj_to_post_data(form_obj)
    except Exception:
        return {"payment_description": None, "order_id": None, "payment_expiry": None}
    return {
        "payment_description": data.get("payment_description"),
        "order_id": data.get("order_id"),
        "payment_expiry": data.get("payment_expiry"),
    }


def format_product_title_from_payment_description(payment_description: str | None) -> str | None:
    """去掉常见 ``Product Description :`` 前缀，得到可读产品标题。"""
    if not payment_description or not str(payment_description).strip():
        return None
    s = str(payment_description).strip()
    low = s.lower()
    for pref in ("product description :", "product description:"):
        if low.startswith(pref):
            return s[len(pref) :].strip()
    return s


def print_redirectv3_order_summary_lines(
    meta: dict[str, str | None],
    *,
    pgw_payment_expiry: str | None = None,
) -> None:
    """在 stdout 打印 ``product_title`` / ``order_id`` / ``payment_expiry``（合并 PGW JSON 里的截止时间）。"""
    pd = meta.get("payment_description")
    if pd:
        title = format_product_title_from_payment_description(pd) or pd
        print(f"product_title = {title}")
    oid = meta.get("order_id")
    if oid:
        print(f"order_id = {oid}")
    exp = (meta.get("payment_expiry") or "").strip() if meta.get("payment_expiry") else None
    if not exp:
        exp = pgw_payment_expiry
    if exp:
        print(f"payment_expiry = {exp}")
    else:
        print("payment_expiry: <missing>")


def build_auto_post_html(form_obj: dict[str, Any]) -> str:
    """
    Same mechanism as the extension: a minimal page that builds a hidden form and submits.
    Values are passed through decode_form_field_value when building the dict in Python;
    for HTML we embed already-decoded values escaped for JS strings.
    """
    action, method, fields = form_obj_to_post_data(form_obj)
    inputs_json = json.dumps(
        [{"name": k, "value": v} for k, v in fields.items()],
        ensure_ascii=False,
    )
    # Keep script compact like minified background.js source.
    post_js = (
        "function post(action,method,inputs){"
        "var f=document.createElement('form');"
        "f.action=action;f.method=method||'POST';"
        "for(var i=0;i<inputs.length;i++){"
        "var el=document.createElement('input');"
        "el.type='hidden';el.name=inputs[i].name;el.value=inputs[i].value;"
        "f.appendChild(el);"
        "}"
        "document.body.appendChild(f);f.submit();}"
    )
    # JSON in script: safe because json.dumps escapes quotes; inputs are our own structure.
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Redirect…</title></head>"
        f"<body><script>{post_js}post({json.dumps(action)},{json.dumps(method)},"
        f"{inputs_json});</script></body></html>"
    )


def print_curl(action: str, data: dict[str, str], referer: str | None = None) -> None:
    """Print an approximate curl for debugging (long values truncated in display)."""
    import shlex

    parts = ["curl", "-X", "POST", shlex.quote(action)]
    if referer:
        parts.extend(["-H", shlex.quote(f"Referer: {referer}")])
    parts.append("-H")
    parts.append(shlex.quote("Content-Type: application/x-www-form-urlencoded"))
    for k, v in data.items():
        parts.extend(["--data-urlencode", f"{k}={v}"])
    print(" \\\n  ".join(parts))


def post_with_requests(
    form_obj: dict[str, Any],
    *,
    referer: str = DEFAULT_2C2P_REFERER,
    timeout: float = 60.0,
    verify: bool | str = True,
):
    """POST payment form; follows redirects like a browser."""
    import requests

    verify = _configure_requests_verify(verify)
    action, method, data = form_obj_to_post_data(form_obj)
    if method != "POST":
        raise ValueError(f"Unsupported method: {method}")
    headers = {
        "Referer": referer,
        "Origin": urlparse(action).scheme + "://" + urlparse(action).netloc,
    }
    return requests.post(
        action,
        data=data,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        verify=verify,
    )


def post_2c2p_payment_from_export_url(
    export_url: str,
    *,
    referer: str = DEFAULT_2C2P_REFERER,
    timeout: float = 60.0,
    requests_verify: bool | str = True,
):
    """
    Decode a T-Splash export link (full ``export.tsplash.com/?data=...`` or a short
    redirect URL) and POST the same
    fields as the extension's hidden form: ``application/x-www-form-urlencoded``
    to ``formObj.action`` (typically ``https://t.2c2p.com/RedirectV3/payment``),
    with Referer set like the extension's DNR rule for Thai Ticket Major.

    Requires: ``pip install requests``

    Example::

        from tsplash_export import post_2c2p_payment_from_export_url

        r = post_2c2p_payment_from_export_url(EXPORT_URL)
        print(r.status_code, r.url)
        # r.history: redirects; r.text: final HTML if any
    """
    export_url = resolve_export_url(export_url, requests_verify=requests_verify)
    obj = parse_tsplash_export_url(export_url)
    form_obj = obj.get("formObj")
    if not form_obj:
        raise ValueError("No formObj in export payload (nothing to POST to 2C2P)")
    return post_with_requests(
        form_obj, referer=referer, timeout=timeout, verify=requests_verify
    )


def resolve_export_url(
    raw: str,
    *,
    short_link_timeout: float = 20.0,
    requests_verify: bool | str = True,
) -> str:
    """
    Normalize input to a full ``export.tsplash.com/?data=...`` URL.

    - If ``raw`` is a file path: read first matching URL from file (export or any http(s) link),
      then resolve short links if needed.
    - If ``raw`` is already a tsplash export URL with ``data``, return as-is.
    - Otherwise treat ``raw`` as a short link (e.g. ``short.gy/...``): follow ``Location``
      headers until an export URL appears (see ``expand_shortlink_to_tsplash``).
    """
    raw = raw.strip()
    if Path(raw).is_file():
        text = Path(raw).read_text(encoding="utf-8", errors="replace")
        m = re.search(r"https?://export\.tsplash\.com/\?[^\s\"']+", text)
        if m:
            return resolve_export_url(
                m.group(0).strip(),
                short_link_timeout=short_link_timeout,
                requests_verify=requests_verify,
            )
        m2 = re.search(r"https?://[^\s\"']+", text)
        if not m2:
            raise ValueError("文件中未找到 http(s) 链接")
        return resolve_export_url(
            m2.group(0).strip(),
            short_link_timeout=short_link_timeout,
            requests_verify=requests_verify,
        )
    if _is_tsplash_export_with_data(raw):
        return raw
    return expand_shortlink_to_tsplash(
        raw, timeout=short_link_timeout, verify=requests_verify
    )


def extract_payment_token_from_html(html: str | None) -> str | None:
    """Best-effort: pgw-ui ``#/token/...``, JSON paymentToken, or query-style."""
    if not html:
        return None
    for pattern in (
        r"#/token/([^\"'\\s<>]+)",
        r'["\']#/token/([^"\']+)',
        r'"paymentToken"\s*:\s*"([^"]+)"',
        r"'paymentToken'\s*:\s*'([^']+)'",
        r"paymentToken=([A-Za-z0-9+/=%]+)",
    ):
        m = re.search(pattern, html)
        if m:
            return unquote(m.group(1).strip())
    return None


def resolve_pgw_payment_token_from_redirect(redirect_r: Any, *, manual_override: str = "") -> str | None:
    """
    Prefer ``manual_override``: if it looks like a pgw-ui URL with ``#/token/...``,
    extract the token; otherwise use the string as raw token. Else parse redirect
    URL / history / HTML.
    """
    pgw = _import_pgw()

    mo = (manual_override or "").strip()
    if mo:
        t = pgw.extract_payment_token_from_url(mo)
        if t:
            return t
        return mo

    if redirect_r is None:
        return None
    urls: list[str] = []
    for h in getattr(redirect_r, "history", None) or []:
        loc = h.headers.get("Location") or h.headers.get("location")
        if loc:
            urls.append(urljoin(getattr(h, "url", "") or "", loc.strip()))
        hu = getattr(h, "url", None)
        if hu:
            urls.append(hu)
    fu = getattr(redirect_r, "url", None)
    if fu:
        urls.append(fu)
    seen: set[str] = set()
    for u in urls:
        if not u or u in seen:
            continue
        seen.add(u)
        tok = pgw.extract_payment_token_from_url(u)
        if tok:
            return tok
    return extract_payment_token_from_html(getattr(redirect_r, "text", None))


def run_pgw_print_payment_redirect(
    payment_token: str,
    client_id: str,
    *,
    client_ip: str,
    email: str,
    name: str,
    verify: bool | str = True,
    dump_json: Path | None = None,
    follow_to_cashier: bool = True,
    fetch_timeout: float = 60.0,
    playwright_fallback: bool = False,
    tsplash_export_payload: dict[str, Any] | None = None,
) -> None:
    """
    POST PGW 4.1 ``/payment/4.1/Payment``（与浏览器 curl 一致）。

    - **stdout**：收银台 URL；若提供 ``tsplash_export_payload``，另打印 RedirectV3 里的
      ``product_title`` / ``order_id`` / ``payment_expiry``（与最初抓包字段一致）。
    - ``playwright_fallback``：requests 未跳到支付宝时用 Playwright。
    """
    import requests

    pgw = _import_pgw()

    body = pgw.build_alipay_payment_body(
        payment_token=payment_token.strip(),
        client_ip=client_ip.strip(),
        client_id=client_id.strip(),
        email=email.strip(),
        name=name.strip(),
    )
    sess = requests.Session()
    r = pgw.post_pgw_payment(body, session=sess, verify=verify)
    print("PGW Payment", r.status_code, r.headers.get("Content-Type", ""), file=sys.stderr)
    exp_pgw: str | None = None
    try:
        exp_pgw = pgw.extract_payment_expiry(r.json())
    except Exception:
        pass
    meta = (
        extract_redirectv3_payment_meta(tsplash_export_payload)
        if tsplash_export_payload
        else {"payment_description": None, "order_id": None, "payment_expiry": None}
    )
    pgw.print_pgw_payment_summary(
        r,
        dump_path=dump_json,
        session=sess,
        verify=verify,
        follow_to_cashier=follow_to_cashier,
        fetch_timeout=fetch_timeout,
        playwright_fallback=playwright_fallback,
        print_payment_expiry_line=not tsplash_export_payload,
    )
    if tsplash_export_payload:
        print_redirectv3_order_summary_lines(meta, pgw_payment_expiry=exp_pgw)


def run_pgw_alipay_save_qr(
    payment_token: str,
    client_id: str,
    *,
    client_ip: str,
    email: str,
    name: str,
    out_path: Path | None = None,
    verify: bool | str = True,
    playwright_fallback: bool = False,  # 本函数以 Playwright 抓图为主，此项仅作预留
    dump_json: Path | None = None,
    follow_to_cashier: bool = True,  # 预留；抓图流程内始终跟跳到支付宝
    fetch_timeout: float = 120.0,
    tsplash_export_payload: dict[str, Any] | None = None,
    print_qr_base64: bool = True,
    qr_base64_as_data_uri: bool = False,
    qr_base64_out: Path | None = None,
) -> None:
    """
    POST PGW → Playwright 跟跳到支付宝 → **内存截图**（默认不写 PNG），stdout 打印收银台 URL。

    ``print_qr_base64=True``（默认）时再打印 ``qr_png_base64=...`` 或 data URI。
    ``out_path`` 非空时额外把同一张图写入该路径。

    若传入 ``tsplash_export_payload``，另打印 RedirectV3 的 ``product_title`` / ``order_id`` / ``payment_expiry``。
    """
    _ = playwright_fallback, follow_to_cashier
    import requests

    pgw = _import_pgw()

    body = pgw.build_alipay_payment_body(
        payment_token=payment_token.strip(),
        client_ip=client_ip.strip(),
        client_id=client_id.strip(),
        email=email.strip(),
        name=name.strip(),
    )
    sess = requests.Session()
    r = pgw.post_pgw_payment(body, session=sess, verify=verify)
    print("PGW Payment", r.status_code, r.headers.get("Content-Type", ""), file=sys.stderr)
    _, cashier, exp, qr_bytes = pgw.save_qr_from_pgw_response(
        r,
        out_path,
        session=sess,
        verify=verify,
        timeout_sec=fetch_timeout,
        qr_base64_as_data_uri=qr_base64_as_data_uri,
        qr_base64_out=qr_base64_out,
    )
    if cashier:
        print(cashier)
    if print_qr_base64 and qr_bytes is not None:
        payload = (
            pgw.png_bytes_to_data_uri(qr_bytes)
            if qr_base64_as_data_uri
            else pgw.png_bytes_to_base64(qr_bytes)
        )
        key = "qr_png_data_uri" if qr_base64_as_data_uri else "qr_png_base64"
        print(f"{key}={payload}")
    meta = (
        extract_redirectv3_payment_meta(tsplash_export_payload)
        if tsplash_export_payload
        else {"payment_description": None, "order_id": None, "payment_expiry": None}
    )
    print_redirectv3_order_summary_lines(meta, pgw_payment_expiry=exp)
    if dump_json is not None:
        try:
            dump_json.write_text(
                json.dumps(r.json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"(full JSON -> {dump_json})", file=sys.stderr)
        except Exception:
            pass


def _run_tsplash_export_impl(
    export_url: str,
    *,
    print_json_redacted: bool = False,
    print_fields: bool = True,
    print_curl_cmd: bool = False,
    html_out: Path | None = None,
    open_html_in_browser: bool = False,
    post_with_requests_flag: bool = False,
    referer: str = DEFAULT_2C2P_REFERER,
    requests_verify: bool | str = True,
) -> tuple[dict[str, Any], Any]:
    """
    Like ``run_tsplash_export`` but also returns the ``requests.Response`` from RedirectV3
    POST when ``post_with_requests_flag`` is True (else second value is None).
    """
    export_url = resolve_export_url(export_url, requests_verify=requests_verify)
    obj = parse_tsplash_export_url(export_url)

    if print_json_redacted:
        redacted = json.loads(json.dumps(obj))
        if isinstance(redacted.get("cookies"), dict):
            for k in list(redacted["cookies"].keys()):
                redacted["cookies"][k] = "<redacted>"
        print(json.dumps(redacted, ensure_ascii=False, indent=2))

    form_obj = obj.get("formObj")
    if not form_obj:
        raise ValueError("No formObj in payload (nothing to POST)")

    action, method, data = form_obj_to_post_data(form_obj)

    if print_fields:
        print(f"{method} {action}")
        for k, v in data.items():
            print(f"  {k} = {v}")

    if print_curl_cmd:
        print_curl(action, data, referer=referer)

    html = build_auto_post_html(form_obj)
    if html_out is not None:
        html_out.write_text(html, encoding="utf-8")
        print(f"Wrote {html_out}")

    if open_html_in_browser:
        out = Path.cwd() / "_tsplash_auto_post.html"
        out.write_text(html, encoding="utf-8")
        webbrowser.open(out.resolve().as_uri())
        print(f"Opened {out}")

    redirect_response = None
    if post_with_requests_flag:
        redirect_response = post_with_requests(
            form_obj, referer=referer, verify=requests_verify
        )
        # print(redirect_response.status_code, redirect_response.url)
        # print(
        #     (redirect_response.text or "")[:2000]
        #     if redirect_response.text
        #     else "(empty body)"
        # )

    return obj, redirect_response


def run_tsplash_export_with_redirect_response(
    export_url: str,
    **kwargs: Any,
) -> tuple[dict[str, Any], Any]:
    """Same as ``_run_tsplash_export_impl`` — public name for use from other modules."""
    return _run_tsplash_export_impl(export_url, **kwargs)


def run_tsplash_export(
    export_url: str,
    *,
    print_json_redacted: bool = False,
    print_fields: bool = True,
    print_curl_cmd: bool = False,
    html_out: Path | None = None,
    open_html_in_browser: bool = False,
    post_with_requests_flag: bool = False,
    referer: str = DEFAULT_2C2P_REFERER,
    requests_verify: bool | str = True,
) -> dict[str, Any]:
    """
    Decode export link and optionally print / write HTML / POST.
    Returns the parsed top-level JSON object.
    """
    obj, _ = _run_tsplash_export_impl(
        export_url,
        print_json_redacted=print_json_redacted,
        print_fields=print_fields,
        print_curl_cmd=print_curl_cmd,
        html_out=html_out,
        open_html_in_browser=open_html_in_browser,
        post_with_requests_flag=post_with_requests_flag,
        referer=referer,
        requests_verify=requests_verify,
    )
    return obj


def export_to_alipay_qr_payload(
    export_url: str,
    *,
    pgw_email: str,
    pgw_name: str,
    pgw_client_id: str,
    pgw_client_ip: str = "127.0.0.1",
    referer: str = DEFAULT_2C2P_REFERER,
    requests_verify: bool | str = True,
    fetch_timeout: float = 120.0,
    payment_token_override: str = "",
    capture_qr: bool = True,
) -> dict[str, str]:
    """
    给“面板程序/上层调用”用：输入 export.tsplash.com/?data=... + PGW 账号信息，
    返回支付宝收银台 URL + 二维码 PNG 的 base64 + 订单关键字段。

    返回字段（尽量与现有 stdout 输出保持一致）：
    - alipay_url
    - qr_png_base64
    - product_title
    - order_id
    - payment_expiry
    """
    import requests

    pgw = _import_pgw()

    export_url = resolve_export_url(export_url, requests_verify=requests_verify)
    obj, redirect_r = _run_tsplash_export_impl(
        export_url,
        print_json_redacted=False,
        print_fields=False,
        print_curl_cmd=False,
        html_out=None,
        open_html_in_browser=False,
        post_with_requests_flag=True,
        referer=referer,
        requests_verify=requests_verify,
    )

    token = resolve_pgw_payment_token_from_redirect(
        redirect_r, manual_override=payment_token_override
    )
    if not token:
        raise ValueError("failed to resolve paymentToken from redirect/html; provide payment_token_override")

    body = pgw.build_alipay_payment_body(
        payment_token=token.strip(),
        client_ip=(pgw_client_ip or "").strip(),
        client_id=(pgw_client_id or "").strip(),
        email=(pgw_email or "").strip(),
        name=(pgw_name or "").strip(),
    )
    sess = requests.Session()
    r = pgw.post_pgw_payment(body, session=sess, verify=requests_verify)
    if getattr(r, "status_code", 0) >= 400:
        # 让上层能看到具体失败原因（PGW 可能返回错误 JSON/HTML）
        ct = str(r.headers.get("Content-Type", "") or "")
        txt = ""
        try:
            txt = (r.text or "")[:800]
        except Exception:
            pass
        raise RuntimeError(f"PGW /payment 失败 HTTP {r.status_code} ({ct}) {txt!r}")
    # 先用 requests 尽力解析收银台 URL（即使没装 playwright，也要给出备用跳转链接）
    cashier = ""
    exp_pgw = ""
    qr_bytes = None
    mpayment_url = ""
    qr_error = ""
    alipay_resolve_error = ""

    # 如果未安装 Playwright：即便 capture_qr=True，也直接降级为“只输出 mpayment_url”
    # 避免在服务器上因缺依赖/缺浏览器导致转换失败或卡住。
    playwright_ok = False
    if capture_qr:
        try:
            import playwright.sync_api  # type: ignore

            playwright_ok = True
        except Exception:
            capture_qr = False
            qr_error = (
                "Playwright not installed; fallback to mpayment_url only. "
                "Install: pip install playwright && python -m playwright install chromium"
            )
    try:
        data = r.json()
    except Exception:
        data = None
    try:
        exp_pgw = str(pgw.extract_payment_expiry(data) or "").strip() if data is not None else ""
    except Exception:
        exp_pgw = ""
    try:
        mpayment = pgw.extract_pgw_data_url(data) if data is not None else None
        if mpayment:
            mpayment_url = str(mpayment).strip()
            resolved, _page_r = pgw.resolve_mpayment_to_alipay_cashier_url(
                mpayment,
                session=sess,
                verify=bool(requests_verify),
                timeout=float(fetch_timeout),
            )
            if pgw.is_alipay_cashier_url(resolved):
                cashier = resolved.strip()
    except Exception:
        pass

    # 若 requests 无法拿到最终收银台（常见：JS 跳转），且允许使用 Playwright，则仅解析 URL 兜底
    if capture_qr and playwright_ok and (not cashier) and mpayment_url:
        try:
            pw = pgw.playwright_resolve_mpayment_to_alipay_url(
                mpayment_url,
                session=sess,
                verify=bool(requests_verify),
                timeout_sec=float(fetch_timeout),
            )
            if pw and pgw.is_alipay_cashier_url(pw):
                cashier = pw.strip()
        except Exception as e:
            alipay_resolve_error = f"{type(e).__name__}: {e}"

    # 再尝试用 Playwright 抓二维码（安装了才会生效）；若失败，仍保留 cashier 作为备用
    if capture_qr and playwright_ok:
        try:
            _png_path, cashier2, exp2, qr2 = pgw.save_qr_from_pgw_response(
                r,
                out_path=None,
                session=sess,
                verify=bool(requests_verify),
                timeout_sec=float(fetch_timeout),
                qr_base64_as_data_uri=False,
                qr_base64_out=None,
            )
            if cashier2 and pgw.is_alipay_cashier_url(cashier2):
                cashier = cashier2.strip()
            if exp2 and not exp_pgw:
                exp_pgw = str(exp2).strip()
            if qr2:
                qr_bytes = qr2
        except Exception as e:
            # 未安装 playwright 或运行失败：保留错误信息，方便面板/日志定位
            qr_error = f"{type(e).__name__}: {e}"

    # 若 Playwright 不可用：按需求只输出 mpayment_url（即使 requests 解析到了收银台链接也不优先用它）
    if not playwright_ok:
        cashier = ""

    # 若仍拿不到收银台 URL：返回 mpayment_url 作为备用入口（至少可在浏览器里继续跳转）
    if not cashier:
        cashier = ""

    meta = extract_redirectv3_payment_meta(obj)
    title = (
        format_product_title_from_payment_description(meta.get("payment_description"))
        or (meta.get("payment_description") or "")
    ).strip()
    order_id = (meta.get("order_id") or "").strip()
    payment_expiry = (meta.get("payment_expiry") or "").strip() or (exp_pgw or "").strip()

    return {
        "alipay_url": cashier.strip(),
        "mpayment_url": mpayment_url,
        "qr_png_base64": (pgw.png_bytes_to_base64(qr_bytes) if qr_bytes else ""),
        "product_title": title,
        "order_id": order_id,
        "payment_expiry": payment_expiry,
        "qr_error": qr_error,
        "alipay_resolve_error": alipay_resolve_error,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="T-Splash export URL -> POST / HTML / curl")
    p.add_argument("url_or_path", nargs="?", help="export.tsplash.com URL or path to file containing it")
    p.add_argument("--print-json", action="store_true", help="print decoded JSON (omit sensitive in public logs)")
    p.add_argument("--print-fields", action="store_true", help="print POST field names and decoded values")
    p.add_argument("--curl", action="store_true", help="print curl command")
    p.add_argument("--html-out", type=Path, help="write auto-submit HTML to this path")
    p.add_argument("--open-html", action="store_true", help="write temp HTML and open in default browser")
    p.add_argument("--post", action="store_true", help="send POST via requests (needs: pip install requests)")
    p.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS certificate verification (short link + 2C2P POST)",
    )
    p.add_argument("--referer", default=DEFAULT_2C2P_REFERER, help="Referer for POST/curl")
    args = p.parse_args()

    if not args.url_or_path:
        p.print_help()
        return

    run_tsplash_export(
        args.url_or_path,
        print_json_redacted=args.print_json,
        print_fields=args.print_fields,
        print_curl_cmd=args.curl,
        html_out=args.html_out,
        open_html_in_browser=args.open_html,
        post_with_requests_flag=args.post,
        referer=args.referer,
        requests_verify=not args.insecure,
    )


# =============================================================================
# PyCharm：EXPORT_URL → Run → POST RedirectV3。
# 若填写 PGW_EMAIL、PGW_NAME：再 POST PGW。paymentToken 默认从跳转结果里取：
#   pgw-ui 链接 ``#/token/<token>``（含 URL 编码）；也可手动填 PGW_PAYMENT_TOKEN 覆盖。
# clientID 与 curl 一致；PGW_CLIENT_IP 固定 127.0.0.1。
# 说明：requests 有时拿不到地址栏里的 # 片段，若解析失败请把完整跳转 URL 填到 PGW_PAYMENT_TOKEN。
# =============================================================================
EXPORT_URL ="https://export.tsplash.com/?data=eyJjb29raWVzIjp7Imh0dHBzOi8vYm9va2luZy50aGFpdGlja2V0bWFqb3IuY29tIjoiUEhQU0VTU0lEPWQ2MmU0MjMxZjljYmMzMmQxYmZmMTU2ZGM0NjRhODZmO0hXV0FGU0VTSUQ9MWVkY2M5YWRhZjQ3YmU4YmQ2O0hXV0FGU0VTVElNRT0xNzc0MTYzMjM4NzU2O3R0a25hbWU9JUUwJUI4JTlCJUUwJUI4JUEzJUUwJUI4JUI1JUUwJUI4JThBJUUwJUI4JUIyKyVFMCVCOCVBMyVFMCVCOCVCOCVFMCVCOSU4OCVFMCVCOCU4NyVFMCVCOCVBOCVFMCVCOCVCNCVFMCVCOCVBMyVFMCVCOCVCNDt0dGtlbWFpbD1uZXcxeHFsYTY2a24lNDBnbWFpbC5jb207dGl4aWQ9bmV3MXhxbGE2NmtuJTQwZ21haWwuY29tO3RpeHU9NGFlMmJjNzlkZWJjODNmOTM3OWE2NGE3Y2FhNDI5ZjY7Y2RubmFtZT0lRTAlQjglOUIlRTAlQjglQTMlRTAlQjglQjUlRTAlQjglOEElRTAlQjglQjIrJUUwJUI4JUEzJUUwJUI4JUI4JUUwJUI5JTg4JUUwJUI4JTg3JUUwJUI4JUE4JUUwJUI4JUI0JUUwJUI4JUEzJUUwJUI4JUI0O3R0a25hbWU9JUUwJUI4JTlCJUUwJUI4JUEzJUUwJUI4JUI1JUUwJUI4JThBJUUwJUI4JUIyKyVFMCVCOCVBMyVFMCVCOCVCOCVFMCVCOSU4OCVFMCVCOCU4NyVFMCVCOCVBOCVFMCVCOCVCNCVFMCVCOCVBMyVFMCVCOCVCNDt0dGtlbWFpbD1uZXcxeHFsYTY2a24lNDBnbWFpbC5jb207In0sInVybCI6Imh0dHBzOi8vYm9va2luZy50aGFpdGlja2V0bWFqb3IuY29tL2Jvb2tpbmcvM20vcGF5Y2ZtYWxsLnBocD9rPTYzNmZkMDRlYmU4MWM2MTE4YjQzYzg4ZGJhODhiM2FmMzRiYTRjMTIiLCJmb3JtT2JqIjp7Im1ldGhvZCI6IlBPU1QiLCJhY3Rpb24iOiJodHRwczovL3QuMmMycC5jb20vUmVkaXJlY3RWMy9wYXltZW50IiwiZm9ybSI6InZlcnNpb249OC41Jm1lcmNoYW50X2lkPTc2NDc2NDAwMDAwMTE4NCZjdXJyZW5jeT03NjQmcmVzdWx0X3VybF8xPWh0dHBzJTNBJTJGJTJGd3d3LnRoYWl0aWNrZXRtYWpvci5jb20lMkZib29raW5nJTJGM20lMkYyYzJwX2xhbmRpbmcucGhwJTNGb3JkZXJubyUzRDM1MDgyNDcmcmVzdWx0X3VybF8yPWh0dHBzJTNBJTJGJTJGcGF5bWVudC50aGFpdGlja2V0bWFqb3IuY29tJTJGcGF5bWVudCUyRjJjMnAlMkYyYzJwX3Jlc3BvbnNlLnBocCZwYXltZW50X29wdGlvbj1BTElQQVklMkNXRUNIQVQmaGFzaF92YWx1ZT1kYjk5OGY0MWI5NmFkYWMxMGNlZDk0NzQ3ODE3MDI3ZjcwM2Y4ODNhZTZmNTNlNWM4ZjY5M2Q0YjIxODJiN2M3JnBheW1lbnRfZGVzY3JpcHRpb249UHJvZHVjdCtEZXNjcmlwdGlvbislM0ErK0JST0tFTisoT2YpK0xPVkUrK0ZyaSsyNy0wMy0yMDI2KzE5JTNBMDAmb3JkZXJfaWQ9MzUwODI0NzIwMTAwMTk3NjMmYW1vdW50PTAwMDAwMDIwOTAwMCZwYXltZW50X2V4cGlyeT0yMDI2LTAzLTIyKzE0JTNBMTclM0E1NSJ9fQ=="
IDE_REQUESTS_VERIFY = True
IDE_PRINT_JSON_REDACTED = False
IDE_PRINT_FIELDS = True
IDE_PRINT_CURL = False
IDE_HTML_OUT: Path | None = None
IDE_OPEN_HTML_IN_BROWSER = False
IDE_REFERER = DEFAULT_2C2P_REFERER

PGW_PAYMENT_TOKEN = ""
PGW_CLIENT_ID = "6940c10b-6860-4233-be3e-b935c44d9fbb"
PGW_CLIENT_IP = "127.0.0.1"
PGW_EMAIL = "qsc360520420@gmail.com"
PGW_NAME = "WENJI Z"
PGW_DUMP_JSON: Path | None = None  # 设为 Path("pgw_response.json") 可保存完整 PGW JSON
PGW_QR_OUT: Path | None = None  # 可选写 PNG；None 则只内存截图 + Base64
PGW_PRINT_QR_BASE64 = True  # stdout 一行 qr_png_base64=...（或 data URI）
PGW_QR_BASE64_AS_DATA_URI = False  # True 则用 qr_png_data_uri=data:image/png;base64,...
PGW_QR_BASE64_OUT: Path | None = None  # 可选：只把 base64/data-uri 文本写入文件


def _run_from_pycharm() -> None:
    if not EXPORT_URL.strip():
        print(
            "请在 tsplash_export.py 文件最下方设置 EXPORT_URL = \"https://export.tsplash.com/?data=...\"",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not (PGW_EMAIL or "").strip() or not (PGW_NAME or "").strip():
        # 仅解析 export 内容（不打 PGW）
        run_tsplash_export(
            EXPORT_URL,
            print_json_redacted=IDE_PRINT_JSON_REDACTED,
            print_fields=IDE_PRINT_FIELDS,
            print_curl_cmd=IDE_PRINT_CURL,
            html_out=IDE_HTML_OUT,
            open_html_in_browser=IDE_OPEN_HTML_IN_BROWSER,
            post_with_requests_flag=False,
            referer=IDE_REFERER,
            requests_verify=IDE_REQUESTS_VERIFY,
        )
        return

    try:
        payload = export_to_alipay_qr_payload(
            EXPORT_URL,
            pgw_email=PGW_EMAIL,
            pgw_name=PGW_NAME,
            pgw_client_id=PGW_CLIENT_ID,
            pgw_client_ip=PGW_CLIENT_IP,
            referer=IDE_REFERER,
            requests_verify=IDE_REQUESTS_VERIFY,
            fetch_timeout=120.0,
            payment_token_override=PGW_PAYMENT_TOKEN,
        )
    except ModuleNotFoundError as e:
        if getattr(e, "name", None) == "requests":
            print("缺少 requests：在 PyCharm 所用解释器里执行  pip install requests", file=sys.stderr)
            raise SystemExit(1) from e
        raise
    except Exception as e:
        print(f"失败：{e}", file=sys.stderr)
        raise SystemExit(1)

    print(payload["alipay_url"])
    print(f"qr_png_base64={payload['qr_png_base64']}")
    if payload.get("product_title"):
        print(f"product_title = {payload['product_title']}")
    if payload.get("order_id"):
        print(f"order_id = {payload['order_id']}")
    if payload.get("payment_expiry"):
        print(f"payment_expiry = {payload['payment_expiry']}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        _run_from_pycharm()
