from __future__ import annotations

import csv
import json
import os
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
        self._lock = threading.Lock()

        self.seats: Dict[str, SeatState] = {}
        self._seen_item_keys: set[str] = set()

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


