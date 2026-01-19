from __future__ import annotations

import os
import secrets
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from wechat_qr_board.store import Store


@dataclass
class Group:
    group_id: str
    name: str
    created_at: float
    store: Store


class GroupManager:
    """
    - 分组完全在内存；启动时清空
    - 每个 group 有独立 Store（独立 CSV/状态）
    - 新入库的二维码条目按 group 轮询分发，保证“一个二维码只分配给一个分组”
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.groups_dir = os.path.join(self.data_dir, "groups")
        self.groups: Dict[str, Group] = {}
        self._rr_keys: List[str] = []
        self._rr_i = 0
        # 无分组时先暂存，分组创建后再轮询分发
        self._backlog: List[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, Any]]]]] = []

    def reset_all_groups(self) -> None:
        self.groups.clear()
        self._rr_keys = []
        self._rr_i = 0
        self._backlog = []
        # 清空落盘目录（每次启动删除所有群组）
        if os.path.exists(self.groups_dir):
            shutil.rmtree(self.groups_dir, ignore_errors=True)
        os.makedirs(self.groups_dir, exist_ok=True)

    def create_group(self, name: str) -> Group:
        gid = secrets.token_urlsafe(8)
        gid = gid.replace("-", "").replace("_", "")
        gid = gid[:10]
        gdir = os.path.join(self.groups_dir, gid)
        os.makedirs(gdir, exist_ok=True)
        store = Store(data_dir=gdir)
        group = Group(group_id=gid, name=name.strip() or gid, created_at=time.time(), store=store)
        self.groups[gid] = group
        self._rr_keys.append(gid)
        # 新建分组后尝试分发 backlog
        self._flush_backlog()
        return group

    def get_group(self, group_id: str) -> Optional[Group]:
        return self.groups.get(group_id)

    def list_groups(self) -> List[Dict]:
        out = []
        for g in sorted(self.groups.values(), key=lambda x: x.created_at):
            out.append(
                {
                    "group_id": g.group_id,
                    "name": g.name,
                    "created_at": g.created_at,
                }
            )
        return out

    def _pick_group_rr(self) -> Optional[Group]:
        if not self._rr_keys:
            return None
        if self._rr_i >= len(self._rr_keys):
            self._rr_i = 0
        gid = self._rr_keys[self._rr_i]
        self._rr_i = (self._rr_i + 1) % len(self._rr_keys)
        return self.groups.get(gid)

    def distribute_items(
        self,
        *,
        seat_key: str,
        seat_label: str,
        account_info: str,
        items: List[Tuple[str, str, float, float, Dict[str, Any]]],
    ) -> int:
        """
        将 items 轮询分配给现有分组。
        返回：成功分配的条目数
        """
        n = 0
        if not self._rr_keys:
            # 暂存整批（保持原始 seat/account 信息）
            self._backlog.append((seat_key, seat_label, account_info, items))
            return 0

        for it in items:
            g = self._pick_group_rr()
            if not g:
                # 理论不会发生（有 rr_keys）
                self._backlog.append((seat_key, seat_label, account_info, [it]))
                continue
            g.store.add_items(seat_key=seat_key, seat_label=seat_label, account_info=account_info, items=[it])
            n += 1
        return n

    def _flush_backlog(self) -> None:
        if not self._rr_keys or not self._backlog:
            return
        # 简单策略：按追加顺序把 backlog 逐条轮询分发
        pending = self._backlog
        self._backlog = []
        for seat_key, seat_label, account_info, items in pending:
            self.distribute_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=items,
            )


