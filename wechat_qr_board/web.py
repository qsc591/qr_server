from __future__ import annotations

import json
import os
from typing import Any, Dict

from aiohttp import web

from .store import Store


def create_app(store: Store) -> web.Application:
    app = web.Application()

    async def handle_index(_: web.Request) -> web.StreamResponse:
        here = os.path.dirname(__file__)
        p = os.path.join(here, "static", "index.html")
        return web.FileResponse(p)

    async def handle_static(request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        here = os.path.dirname(__file__)
        p = os.path.join(here, "static", name)
        if not os.path.exists(p):
            raise web.HTTPNotFound()
        return web.FileResponse(p)

    async def api_state(_: web.Request) -> web.Response:
        return web.json_response(store.list_seats_for_ui())

    async def api_scan_next(request: web.Request) -> web.Response:
        body: Dict[str, Any] = await request.json()
        seat_key = str(body.get("seat_key") or "").strip()
        next_key = store.scan_next(seat_key)
        return web.json_response({"ok": True, "next_seat_key": next_key})

    app.router.add_get("/", handle_index)
    app.router.add_get("/static/{name}", handle_static)
    app.router.add_get("/api/state", api_state)
    app.router.add_post("/api/scan_next", api_scan_next)
    async def api_csv(_: web.Request) -> web.StreamResponse:
        store.ensure_csv_exists()
        resp = web.FileResponse(store.csv_path)
        resp.content_type = "text/csv"
        resp.headers["Content-Disposition"] = 'attachment; filename="scan_log.csv"'
        return resp

    app.router.add_get("/api/csv", api_csv)
    return app


