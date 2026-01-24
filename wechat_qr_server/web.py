from __future__ import annotations

import os
import secrets
from typing import Any, Dict

from aiohttp import web

from .groups import GroupManager


def create_app(groups: GroupManager, public_base_url: str, reset_password: str) -> web.Application:
    app = web.Application()
    # group password sessions: sid -> group_id
    group_sessions: Dict[str, str] = {}
    group_cookie_name = "g_sid"

    here = os.path.dirname(__file__)
    static_dir = os.path.join(here, "static")
    board_static_dir = os.path.join(here, "board_static")
    board_src_dir = os.path.join(os.path.dirname(here), "wechat_qr_board", "static")

    def _is_group_locked(gid: str) -> bool:
        g = groups.get_group(gid)
        return bool(g and getattr(g, "locked", False))

    def _has_group_auth(request: web.Request, gid: str) -> bool:
        sid = request.cookies.get(group_cookie_name, "")
        return bool(sid and group_sessions.get(sid) == gid)

    def _require_group_auth(request: web.Request, gid: str) -> None:
        if _is_group_locked(gid) and not _has_group_auth(request, gid):
            raise web.HTTPUnauthorized(text="group login required")

    async def handle_index(_: web.Request) -> web.StreamResponse:
        resp = web.FileResponse(os.path.join(static_dir, "index.html"))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def handle_group_page(_: web.Request) -> web.StreamResponse:
        resp = web.FileResponse(os.path.join(static_dir, "group.html"))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def handle_group_login_page(request: web.Request) -> web.StreamResponse:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        if not _is_group_locked(gid):
            raise web.HTTPNotFound()
        title = "Kakao Pay - 登录" if getattr(g, "kind", "") == "kakao" else "分组登录"
        heading = f"进入 {g.name}"
        desc = "此分组需要密码验证（创建分组时设置）。"
        body = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; background:#0b1220; color:#e5e7eb; display:flex; align-items:center; justify-content:center; min-height:100vh; padding:24px; }}
      .card {{ width: min(420px, 100%); background:#0f172a; border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:18px; }}
      h1 {{ margin:0 0 10px; font-size:18px; }}
      p {{ margin:0 0 14px; color:#9ca3af; font-size:13px; }}
      input {{ width:100%; box-sizing:border-box; padding:12px; border-radius:10px; border:1px solid rgba(255,255,255,.12); background:#0b1220; color:#e5e7eb; }}
      button {{ margin-top:10px; width:100%; padding:12px; border-radius:10px; border:0; background:#22c55e; color:#052e16; font-weight:700; cursor:pointer; }}
      .err {{ margin-top:10px; color:#fca5a5; font-size:13px; display:none; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>{heading}</h1>
      <p>{desc}</p>
      <input id="pw" type="password" placeholder="请输入密码" autofocus />
      <button id="btn">登录</button>
      <div id="err" class="err">密码错误</div>
    </div>
    <script>
      const gid = {gid!r};
      async function login() {{
        const pw = document.getElementById("pw").value || "";
        const resp = await fetch(`/api/groups/${{encodeURIComponent(gid)}}/login`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ password: pw }})
        }});
        if (resp.status === 200) {{
          window.location.href = `/g/${{encodeURIComponent(gid)}}`;
          return;
        }}
        document.getElementById("err").style.display = "block";
      }}
      document.getElementById("btn").addEventListener("click", login);
      document.getElementById("pw").addEventListener("keydown", (e) => {{
        if (e.key === "Enter") login();
      }});
    </script>
  </body>
</html>"""
        return web.Response(text=body, content_type="text/html")

    async def handle_board(request: web.Request) -> web.StreamResponse:
        # 直接复用本地版 UI（iframe），通过 query 参数注入 group_id
        # 注意：本地版资源路径是 /static/...，与 server 侧冲突，所以这里做一份“反向代理式”页面：
        group_id = (request.query.get("group_id") or "").strip()
        if not group_id or not groups.get_group(group_id):
            raise web.HTTPNotFound()
        _require_group_auth(request, group_id)
        # 复用 wechat_qr_board/static/index.html，但把 API 路径改为 group scoped
        # 为简化：输出一个最小 HTML，加载 wechat_qr_board 的 js/css，并在 window 注入 group_id
        body = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>WeChat QR Board - {group_id}</title>
    <link rel="stylesheet" href="/board_static/style.css" />
  </head>
  <body>
    <script>window.__GROUP_ID__ = "{group_id}";</script>
    <div id="root"></div>
    <iframe style="display:none"></iframe>
    <div id="app_mount"></div>
    <div id="app_container"></div>
    <div id="app"></div>
    <div id="container"></div>
    <div id="mount"></div>
    <!-- 直接复用现有 board html -->
    <div id="board_wrapper"></div>
    <script src="/board_static/boot.js?v=20260120_2"></script>
  </body>
</html>"""
        resp = web.Response(text=body, content_type="text/html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def handle_board_static(request: web.Request) -> web.StreamResponse:
        """
        /board_static 下的资源：
        - boot.js 来自 wechat_qr_server/board_static
        - 其他 index.html/app.js/style.css 直接复用 wechat_qr_board/static
        """
        name = request.match_info["name"]
        if name == "boot.js":
            p = os.path.join(board_static_dir, "boot.js")
        else:
            p = os.path.join(board_src_dir, name)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        resp = web.FileResponse(p)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def handle_static(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        p = os.path.join(static_dir, name)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        resp = web.FileResponse(p)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    async def api_groups(_: web.Request) -> web.Response:
        out = []
        for g in sorted(groups.groups.values(), key=lambda x: x.created_at):
            # 不依赖 Store 的新增方法：直接从 list_seats_for_ui() 计算，避免 server 端 wechat_qr_board 版本不一致导致 stats 恒为 0
            try:
                state = g.store.list_seats_for_ui()
                seats = state.get("seats") or []
                pending_total = sum(int(s.get("pending_count") or 0) for s in seats if isinstance(s, dict))
                total_seats = len(seats)
                completed_seats = sum(
                    1
                    for s in seats
                    if isinstance(s, dict) and (s.get("status") == "scanned") and int(s.get("pending_count") or 0) == 0
                )
                stats = {
                    "pending_total": int(pending_total),
                    "completed_seats": int(completed_seats),
                    "total_seats": int(total_seats),
                }
            except Exception:
                stats = {"pending_total": 0, "completed_seats": 0, "total_seats": 0}

            out.append(
                {
                    "group_id": g.group_id,
                    "name": g.name,
                    "created_at": g.created_at,
                    "kind": getattr(g, "kind", "wechat"),
                    "locked": bool(getattr(g, "locked", False)),
                    "stats": stats,
                }
            )
        return web.json_response({"groups": out})

    async def api_create_group(request: web.Request) -> web.Response:
        body: Dict[str, Any] = await request.json()
        name = str(body.get("name") or "").strip()
        kind = str(body.get("kind") or "wechat").strip().lower()
        password = str(body.get("password") or "").strip()
        admin_password = str(body.get("admin_password") or "").strip()

        # Kakao 组：不允许用户自定义密码；使用 reset_password 作为“初始化/重置密码”
        if kind == "kakao":
            if not reset_password:
                raise web.HTTPBadRequest(text="服务器未配置 reset_password，无法创建/绑定 Kakao 分组")
            if admin_password != reset_password:
                raise web.HTTPForbidden(text="重置密码错误")
            password = reset_password
        try:
            g = groups.create_group(name, kind=kind, password=password)
        except ValueError as e:
            raise web.HTTPBadRequest(text=str(e))
        share = ""
        if public_base_url:
            share = f"{public_base_url.rstrip('/')}/g/{g.group_id}"
        return web.json_response(
            {"group_id": g.group_id, "name": g.name, "share_url": share, "kind": g.kind, "locked": bool(g.locked)}
        )

    async def api_group_info(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        _require_group_auth(request, gid)
        share = ""
        if public_base_url:
            share = f"{public_base_url.rstrip('/')}/g/{g.group_id}"
        return web.json_response(
            {"group_id": g.group_id, "name": g.name, "share_url": share, "kind": g.kind, "locked": bool(g.locked)}
        )

    async def api_group_state(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        _require_group_auth(request, gid)
        return web.json_response(g.store.list_seats_for_ui())

    async def api_group_scan_next(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        _require_group_auth(request, gid)
        body: Dict[str, Any] = await request.json()
        seat_key = str(body.get("seat_key") or "").strip()
        next_key = g.store.scan_next(seat_key)
        return web.json_response({"ok": True, "next_seat_key": next_key})

    async def api_group_csv(request: web.Request) -> web.StreamResponse:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        _require_group_auth(request, gid)
        g.store.ensure_csv_exists()
        resp = web.FileResponse(g.store.csv_path)
        resp.content_type = "text/csv"
        resp.headers["Content-Disposition"] = f'attachment; filename="scan_log_{gid}.csv"'
        return resp

    async def api_group_login(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g or not _is_group_locked(gid):
            raise web.HTTPNotFound()
        body: Dict[str, Any] = await request.json()
        pw = str(body.get("password") or "")
        if pw != getattr(g, "password", ""):
            raise web.HTTPForbidden(text="bad password")
        sid = secrets.token_urlsafe(18)
        group_sessions[sid] = gid
        resp = web.json_response({"ok": True})
        resp.set_cookie(
            group_cookie_name,
            sid,
            httponly=True,
            samesite="Lax",
            secure=(request.scheme == "https"),
            path="/",
            max_age=3600 * 24,
        )
        return resp

    async def api_reset(request: web.Request) -> web.Response:
        if not reset_password:
            raise web.HTTPNotFound()
        body: Dict[str, Any] = await request.json()
        pw = str(body.get("password") or "")
        if pw != reset_password:
            raise web.HTTPForbidden(text="bad password")
        groups.reset_all_groups()
        return web.json_response({"ok": True})

    async def api_delete_group(request: web.Request) -> web.Response:
        """
        删除单个分组（需要 reset_password，避免误删）：
        POST /api/groups/{group_id}/delete  body: { password }
        """
        if not reset_password:
            raise web.HTTPNotFound()
        gid = request.match_info["group_id"]
        if not groups.get_group(gid):
            raise web.HTTPNotFound()
        body: Dict[str, Any] = await request.json()
        pw = str(body.get("password") or "")
        if pw != reset_password:
            raise web.HTTPForbidden(text="bad password")

        # 清理登录 session（避免删除后 cookie 仍指向不存在的组）
        try:
            dead_sids = [sid for sid, g2 in group_sessions.items() if g2 == gid]
            for sid in dead_sids:
                group_sessions.pop(sid, None)
        except Exception:
            pass

        ok = groups.delete_group(gid)
        if not ok:
            raise web.HTTPNotFound()
        return web.json_response({"ok": True})

    # routes
    app.router.add_get("/", handle_index)
    async def handle_group_entry(request: web.Request) -> web.StreamResponse:
        gid = request.match_info["group_id"]
        if not groups.get_group(gid):
            raise web.HTTPNotFound()
        if _is_group_locked(gid) and not _has_group_auth(request, gid):
            return await handle_group_login_page(request)
        return await handle_group_page(request)

    app.router.add_get("/g/{group_id}", handle_group_entry)
    app.router.add_get("/board", handle_board)
    app.router.add_get("/board_static/{name}", handle_board_static)
    app.router.add_get("/static/{name}", handle_static)

    # group apis
    app.router.add_get("/api/groups", api_groups)
    app.router.add_post("/api/groups", api_create_group)
    app.router.add_get("/api/groups/{group_id}", api_group_info)
    app.router.add_get("/api/groups/{group_id}/state", api_group_state)
    app.router.add_post("/api/groups/{group_id}/scan_next", api_group_scan_next)
    app.router.add_get("/api/groups/{group_id}/csv", api_group_csv)
    app.router.add_post("/api/groups/{group_id}/login", api_group_login)
    app.router.add_post("/api/groups/{group_id}/delete", api_delete_group)
    app.router.add_post("/api/reset", api_reset)

    return app


