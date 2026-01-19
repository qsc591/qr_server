from __future__ import annotations

import os
from typing import Any, Dict

from aiohttp import web

from .groups import GroupManager


def create_app(groups: GroupManager, public_base_url: str, reset_password: str) -> web.Application:
    app = web.Application()

    here = os.path.dirname(__file__)
    static_dir = os.path.join(here, "static")
    board_static_dir = os.path.join(here, "board_static")
    board_src_dir = os.path.join(os.path.dirname(here), "wechat_qr_board", "static")

    async def handle_index(_: web.Request) -> web.StreamResponse:
        return web.FileResponse(os.path.join(static_dir, "index.html"))

    async def handle_group_page(_: web.Request) -> web.StreamResponse:
        return web.FileResponse(os.path.join(static_dir, "group.html"))

    async def handle_board(request: web.Request) -> web.StreamResponse:
        # 直接复用本地版 UI（iframe），通过 query 参数注入 group_id
        # 注意：本地版资源路径是 /static/...，与 server 侧冲突，所以这里做一份“反向代理式”页面：
        group_id = (request.query.get("group_id") or "").strip()
        if not group_id or not groups.get_group(group_id):
            raise web.HTTPNotFound()
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
    <script src="/board_static/boot.js"></script>
  </body>
</html>"""
        return web.Response(text=body, content_type="text/html")

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
        return web.FileResponse(p)

    async def handle_static(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        p = os.path.join(static_dir, name)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    async def api_groups(_: web.Request) -> web.Response:
        return web.json_response({"groups": groups.list_groups()})

    async def api_create_group(request: web.Request) -> web.Response:
        body: Dict[str, Any] = await request.json()
        name = str(body.get("name") or "").strip()
        g = groups.create_group(name)
        share = ""
        if public_base_url:
            share = f"{public_base_url.rstrip('/')}/g/{g.group_id}"
        return web.json_response({"group_id": g.group_id, "name": g.name, "share_url": share})

    async def api_group_info(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        share = ""
        if public_base_url:
            share = f"{public_base_url.rstrip('/')}/g/{g.group_id}"
        return web.json_response({"group_id": g.group_id, "name": g.name, "share_url": share})

    async def api_group_state(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        return web.json_response(g.store.list_seats_for_ui())

    async def api_group_scan_next(request: web.Request) -> web.Response:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        body: Dict[str, Any] = await request.json()
        seat_key = str(body.get("seat_key") or "").strip()
        next_key = g.store.scan_next(seat_key)
        return web.json_response({"ok": True, "next_seat_key": next_key})

    async def api_group_csv(request: web.Request) -> web.StreamResponse:
        gid = request.match_info["group_id"]
        g = groups.get_group(gid)
        if not g:
            raise web.HTTPNotFound()
        g.store.ensure_csv_exists()
        resp = web.FileResponse(g.store.csv_path)
        resp.content_type = "text/csv"
        resp.headers["Content-Disposition"] = f'attachment; filename="scan_log_{gid}.csv"'
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

    # routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/g/{group_id}", handle_group_page)
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
    app.router.add_post("/api/reset", api_reset)

    return app


