from __future__ import annotations

import csv
import json
import os
import hashlib
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import QrItem, SeatState, seat_state_to_dict


class Store:
    """
    内存状态 + JSON/CSV 落盘。
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.state_path = os.path.join(self.data_dir, "state.json")
        self.csv_path = os.path.join(self.data_dir, "scan_log.csv")
        self.ttm_csv_path = os.path.join(self.data_dir, "ttm_orders.csv")
        self._lock = threading.Lock()

        self.seats: Dict[str, SeatState] = {}
        self._seen_item_keys: set[str] = set()
        self._seen_ttm_jump_keys: set[str] = set()

    def preload_seats(self, seat_labels: List[str]) -> None:
        with self._lock:
            for label in seat_labels:
                key = label.strip()
                if not key:
                    continue
                if key not in self.seats:
                    self.seats[key] = SeatState(seat_key=key, seat_label=label.strip())

    def _item_key(self, seat_key: str, qr_url: str, message_link: str) -> str:
        return f"{seat_key}||{qr_url}||{message_link}"

    def add_items(
        self,
        seat_key: str,
        seat_label: str,
        account_info: str,
        items: List[Tuple[str, str, float, float, Dict[str, Any]]],
    ) -> None:
        with self._lock:
            if seat_key not in self.seats:
                self.seats[seat_key] = SeatState(seat_key=seat_key, seat_label=seat_label)
            seat = self.seats[seat_key]

            if account_info:
                seat.account_info = account_info

            for qr_url, message_link, captured_at, expires_at, meta in items:
                k = self._item_key(seat_key, qr_url, message_link)
                if k in self._seen_item_keys:
                    continue
                self._seen_item_keys.add(k)
                seat.pending.append(
                    QrItem(
                        qr_url=qr_url,
                        message_link=message_link,
                        captured_at=captured_at,
                        expires_at=expires_at,
                        meta=meta or {},
                    )
                )

        self.save_state()

    def save_state(self) -> None:
        with self._lock:
            payload = {
                "updated_at": time.time(),
                "seats": {k: seat_state_to_dict(v) for k, v in self.seats.items()},
            }
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    def list_seats_for_ui(self) -> Dict:
        with self._lock:
            seats = list(self.seats.values())
        # 默认：pending 优先，其次按 label 排序
        seats.sort(key=lambda s: (0 if s.pending else 1, s.seat_label))
        return {
            "server_time": time.time(),
            "seats": [seat_state_to_dict(s) for s in seats],
        }

    def group_summary(self) -> Dict[str, int]:
        """
        给 server 首页用：返回该分组的简要统计信息。
        - pending_total: 待扫码二维码总数
        - completed_seats: 已完成(至少扫过一次且当前无 pending)的座位数
        - total_seats: 座位总数
        """
        with self._lock:
            seats = list(self.seats.values())
        pending_total = sum(len(s.pending) for s in seats)
        completed_seats = sum(1 for s in seats if (not s.pending) and bool(s.scanned))
        total_seats = len(seats)
        return {
            "pending_total": int(pending_total),
            "completed_seats": int(completed_seats),
            "total_seats": int(total_seats),
        }

    def scan_next(self, seat_key: str) -> Optional[str]:
        """
        将 seat 的当前二维码标记为 scanned，并写 CSV。
        返回：建议前端选中的下一个 seat_key（优先当前 seat 还有 pending，否则找下一个 pending seat）。
        """
        scanned_row: Optional[Tuple[str, str, str]] = None
        next_key: Optional[str] = None

        with self._lock:
            seat = self.seats.get(seat_key)
            if not seat or not seat.pending:
                # 找一个 pending seat
                next_key = self._find_next_pending_locked(None)
                return next_key

            item = seat.pending.pop(0)
            item.scanned_at = time.time()
            seat.scanned.append(item)
            scanned_row = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.scanned_at)),
                seat.seat_label,
                item.message_link or "",
            )

            # 决定下一个
            if seat.pending:
                next_key = seat.seat_key
            else:
                next_key = self._find_next_pending_locked(seat.seat_key)

        if scanned_row:
            self._append_csv(scanned_row)
        self.save_state()
        return next_key

    def _find_next_pending_locked(self, after_key: Optional[str]) -> Optional[str]:
        keys = list(self.seats.keys())
        # 尽量按 seat_label 排序稳定
        keys.sort(key=lambda k: self.seats[k].seat_label)
        if not keys:
            return None
        start_idx = 0
        if after_key and after_key in keys:
            start_idx = (keys.index(after_key) + 1) % len(keys)
        for i in range(len(keys)):
            k = keys[(start_idx + i) % len(keys)]
            if self.seats[k].pending:
                return k
        return None

    def _append_csv(self, row: Tuple[str, str, str]) -> None:
        file_exists = os.path.exists(self.csv_path)
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(["时间", "位置", "discord消息链接"])
            w.writerow(list(row))

    def ensure_csv_exists(self) -> None:
        """
        让“下载CSV”在未点击 Next 的情况下也能正常下载（至少包含表头）。
        """
        with self._lock:
            file_exists = os.path.exists(self.csv_path)
        if file_exists:
            return
        # 写一个只有表头的文件
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["时间", "位置", "discord消息链接"])

    def _append_ttm_csv(self, row: Tuple[str, str, str, str]) -> None:
        file_exists = os.path.exists(self.ttm_csv_path)
        with open(self.ttm_csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow(["时间", "位置", "订单号", "账号密码"])
            w.writerow(list(row))

    def ensure_ttm_csv_exists(self) -> None:
        file_exists = os.path.exists(self.ttm_csv_path)
        if file_exists:
            return
        with open(self.ttm_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["时间", "位置", "订单号", "账号密码"])

    def log_ttm_jump(self, seat_key: str) -> Dict[str, Any]:
        """
        TTM：点击“跳转到支付宝”后记录订单到 ttm_orders.csv，并在 meta 里打标记（持久化）。
        CSV 字段：时间、位置、订单号、账号密码
        """
        seat_key = (seat_key or "").strip()
        if not seat_key:
            return {"ok": False, "error": "missing seat_key"}

        row: Tuple[str, str, str, str] | None = None
        dedup = False
        with self._lock:
            seat = self.seats.get(seat_key)
            if not seat:
                return {"ok": False, "error": "seat not found"}
            item = seat.current()
            if not item:
                return {"ok": False, "error": "no current item"}
            meta = item.meta or {}
            source = str(meta.get("source") or "")
            if source not in ("ttm_alipay", "ttm_export"):
                return {"ok": False, "error": "not ttm"}

            order_id = str(meta.get("order_id") or "").strip()
            seat_label = seat.seat_label or seat.seat_key
            account = seat.account_info or ""
            jump_key = f"{seat_key}||{item.captured_at}||{order_id}||{account}"
            if meta.get("jump_logged_at") or (jump_key in self._seen_ttm_jump_keys):
                dedup = True
            else:
                self._seen_ttm_jump_keys.add(jump_key)
                now = time.time()
                meta["jumped_at"] = now
                meta["jump_logged_at"] = now
                item.meta = meta
                row = (
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                    seat_label,
                    order_id,
                    account,
                )

        if row and not dedup:
            self._append_ttm_csv(row)
            self.save_state()
        return {"ok": True, "dedup": dedup}

    def save_png_bytes(self, png_bytes: bytes) -> str:
        """
        保存 PNG 到 data_dir/qr/<sha1>.png，返回文件名（不包含路径）。
        用内容哈希去重，避免同一张图重复落盘。
        """
        if not png_bytes:
            raise ValueError("empty png bytes")
        qr_dir = os.path.join(self.data_dir, "qr")
        os.makedirs(qr_dir, exist_ok=True)
        h = hashlib.sha1(png_bytes).hexdigest()
        name = f"{h}.png"
        path = os.path.join(qr_dir, name)
        if not os.path.exists(path):
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(png_bytes)
            os.replace(tmp, path)
        return name

    def save_png_base64(self, b64: str) -> str:
        """
        解析 base64（不含 data: 前缀），保存为 PNG 文件，返回文件名。
        """
        import base64

        s = (b64 or "").strip()
        if not s:
            raise ValueError("empty base64")
        # 容错：如果是 data URI，剥离前缀
        if s.startswith("data:"):
            if "base64," in s:
                s = s.split("base64,", 1)[1].strip()
        try:
            png = base64.b64decode(s, validate=False)
        except Exception as e:
            raise ValueError("bad base64") from e
        return self.save_png_bytes(png)


