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
    kind: str = "wechat"  # wechat | kakao | ttm_alipay
    password: str = ""  # non-empty => locked
    pgw_email: str = ""
    pgw_name: str = ""
    ttm_capture_qr: bool = True  # TTM only: whether to capture Alipay QR via Playwright

    @property
    def locked(self) -> bool:
        return bool(self.password)


class GroupManager:
    """
    - 分组完全在内存；启动时清空
    - 每个 group 有独立 Store（独立 CSV/状态）
    - 新入库的二维码条目按 group 轮询分发，保证“一个二维码只分配给一个分组”
    """

    def __init__(
        self,
        data_dir: str,
    ):
        self.data_dir = data_dir
        self.groups_dir = os.path.join(self.data_dir, "groups")
        self.groups: Dict[str, Group] = {}
        # 三套轮询：微信 / Kakao / ThaiTicketMajor(支付宝) 互不影响
        self._rr_keys_wechat: List[str] = []
        self._rr_keys_kakao: List[str] = []
        self._rr_keys_ttm: List[str] = []
        self._rr_i_wechat = 0
        self._rr_i_kakao = 0
        self._rr_i_ttm = 0
        # 无对应分组时先暂存，分组创建后再轮询分发（保持 seat/account 信息）
        self._backlog_wechat: List[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, Any]]]]] = []
        self._backlog_kakao: List[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, Any]]]]] = []
        self._backlog_ttm: List[Tuple[str, str, str, List[Tuple[str, str, float, float, Dict[str, Any]]]]] = []

    def reset_all_groups(self) -> None:
        self.groups.clear()
        self._rr_keys_wechat = []
        self._rr_keys_kakao = []
        self._rr_keys_ttm = []
        self._rr_i_wechat = 0
        self._rr_i_kakao = 0
        self._rr_i_ttm = 0
        self._backlog_wechat = []
        self._backlog_kakao = []
        self._backlog_ttm = []
        # 清空落盘目录（每次启动删除所有群组）
        if os.path.exists(self.groups_dir):
            shutil.rmtree(self.groups_dir, ignore_errors=True)
        os.makedirs(self.groups_dir, exist_ok=True)

    def create_group(
        self,
        name: str,
        *,
        kind: str = "wechat",
        password: str = "",
        pgw_email: str = "",
        pgw_name: str = "",
        ttm_capture_qr: bool = True,
    ) -> Group:
        kind = (kind or "wechat").strip().lower()
        if kind not in ("wechat", "kakao", "ttm_alipay"):
            kind = "wechat"
        password = (password or "").strip()
        if kind == "kakao" and not password:
            raise ValueError("kakao group requires password")

        gid = secrets.token_urlsafe(8)
        gid = gid.replace("-", "").replace("_", "")
        gid = gid[:10]
        gdir = os.path.join(self.groups_dir, gid)
        os.makedirs(gdir, exist_ok=True)
        store = Store(data_dir=gdir)
        group = Group(
            group_id=gid,
            name=name.strip() or gid,
            created_at=time.time(),
            store=store,
            kind=kind,
            password=password,
            pgw_email=(pgw_email or "").strip(),
            pgw_name=(pgw_name or "").strip(),
            ttm_capture_qr=bool(ttm_capture_qr) if kind == "ttm_alipay" else True,
        )
        self.groups[gid] = group
        if kind == "kakao":
            self._rr_keys_kakao.append(gid)
            self._flush_backlog_kakao()
        elif kind == "ttm_alipay":
            self._rr_keys_ttm.append(gid)
            self._flush_backlog_ttm()
        else:
            self._rr_keys_wechat.append(gid)
            self._flush_backlog_wechat()
        return group

    def get_group(self, group_id: str) -> Optional[Group]:
        return self.groups.get(group_id)

    def delete_group(self, group_id: str) -> bool:
        """
        删除单个分组：
        - 从 groups 移除
        - 从对应 kind 的 RR 列表移除，并修正 RR 指针
        - 删除其落盘目录 data_dir/groups/<gid>
        返回：是否真的删除了一个分组
        """
        gid = (group_id or "").strip()
        g = self.groups.get(gid)
        if not g:
            return False

        # 先从 rr 列表移除并修正指针，确保其它分组轮询不被打乱
        if getattr(g, "kind", "wechat") == "kakao":
            keys = self._rr_keys_kakao
            i = self._rr_i_kakao
            if gid in keys:
                idx = keys.index(gid)
                keys.pop(idx)
                if idx < i:
                    i -= 1
            if not keys:
                i = 0
            else:
                if i < 0:
                    i = 0
                if i >= len(keys):
                    i = i % len(keys)
            self._rr_keys_kakao = keys
            self._rr_i_kakao = i
        elif getattr(g, "kind", "wechat") == "ttm_alipay":
            keys = self._rr_keys_ttm
            i = self._rr_i_ttm
            if gid in keys:
                idx = keys.index(gid)
                keys.pop(idx)
                if idx < i:
                    i -= 1
            if not keys:
                i = 0
            else:
                if i < 0:
                    i = 0
                if i >= len(keys):
                    i = i % len(keys)
            self._rr_keys_ttm = keys
            self._rr_i_ttm = i
        else:
            keys = self._rr_keys_wechat
            i = self._rr_i_wechat
            if gid in keys:
                idx = keys.index(gid)
                keys.pop(idx)
                if idx < i:
                    i -= 1
            if not keys:
                i = 0
            else:
                if i < 0:
                    i = 0
                if i >= len(keys):
                    i = i % len(keys)
            self._rr_keys_wechat = keys
            self._rr_i_wechat = i

        # 从 groups 移除
        self.groups.pop(gid, None)

        # 删除落盘目录
        gdir = os.path.join(self.groups_dir, gid)
        if os.path.exists(gdir):
            shutil.rmtree(gdir, ignore_errors=True)
        return True

    def list_groups(self) -> List[Dict]:
        out = []
        for g in sorted(self.groups.values(), key=lambda x: x.created_at):
            out.append(
                {
                    "group_id": g.group_id,
                    "name": g.name,
                    "created_at": g.created_at,
                    "kind": g.kind,
                    "locked": bool(g.locked),
                }
            )
        return out

    def _pick_group_rr_wechat(self) -> Optional[Group]:
        if not self._rr_keys_wechat:
            return None
        if self._rr_i_wechat >= len(self._rr_keys_wechat):
            self._rr_i_wechat = 0
        gid = self._rr_keys_wechat[self._rr_i_wechat]
        self._rr_i_wechat = (self._rr_i_wechat + 1) % len(self._rr_keys_wechat)
        return self.groups.get(gid)

    def _pick_group_rr_kakao(self) -> Optional[Group]:
        if not self._rr_keys_kakao:
            return None
        if self._rr_i_kakao >= len(self._rr_keys_kakao):
            self._rr_i_kakao = 0
        gid = self._rr_keys_kakao[self._rr_i_kakao]
        self._rr_i_kakao = (self._rr_i_kakao + 1) % len(self._rr_keys_kakao)
        return self.groups.get(gid)

    def _pick_group_rr_ttm(self) -> Optional[Group]:
        if not self._rr_keys_ttm:
            return None
        if self._rr_i_ttm >= len(self._rr_keys_ttm):
            self._rr_i_ttm = 0
        gid = self._rr_keys_ttm[self._rr_i_ttm]
        self._rr_i_ttm = (self._rr_i_ttm + 1) % len(self._rr_keys_ttm)
        return self.groups.get(gid)

    def pick_ttm_group(self) -> Optional[Group]:
        """
        供 main.py 使用：选出一个 ttm_alipay 分组（RR），并返回该 Group（含 pgw_email/pgw_name）。
        """
        return self._pick_group_rr_ttm()

    def add_items_to_group(
        self,
        group_id: str,
        *,
        seat_key: str,
        seat_label: str,
        account_info: str,
        items: List[Tuple[str, str, float, float, Dict[str, Any]]],
    ) -> int:
        """
        将 items 直接写入指定 group（不做 RR），并自动处理 qr_png_base64 落盘。
        """
        gid = (group_id or "").strip()
        g = self.groups.get(gid)
        if not g:
            return 0
        n = 0
        for it in items:
            qr_url, message_link, captured_at, expires_at, meta = it
            meta = dict(meta or {})
            b64 = (meta.get("qr_png_base64") or "").strip() if isinstance(meta, dict) else ""
            if b64:
                try:
                    name = g.store.save_png_base64(b64)
                    qr_url = f"/api/groups/{g.group_id}/qr/{name}"
                    meta.pop("qr_png_base64", None)
                    meta["qr_saved"] = True
                except Exception:
                    pass
            g.store.add_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=[(qr_url, message_link, captured_at, expires_at, meta)],
            )
            n += 1
        return n

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
        if not self._rr_keys_wechat:
            # 暂存整批（保持原始 seat/account 信息）
            self._backlog_wechat.append((seat_key, seat_label, account_info, items))
            return 0

        for it in items:
            g = self._pick_group_rr_wechat()
            if not g:
                # 理论不会发生（有 rr_keys）
                self._backlog_wechat.append((seat_key, seat_label, account_info, [it]))
                continue
            qr_url, message_link, captured_at, expires_at, meta = it
            meta = dict(meta or {})
            # ThaiTicketMajor: 通过 base64 传图会导致 state.json 巨大，这里落盘为 PNG 并用短 URL 引用
            b64 = (meta.get("qr_png_base64") or "").strip() if isinstance(meta, dict) else ""
            if b64:
                try:
                    name = g.store.save_png_base64(b64)
                    qr_url = f"/api/groups/{g.group_id}/qr/{name}"
                    meta.pop("qr_png_base64", None)
                    meta["qr_saved"] = True
                except Exception:
                    # 保存失败则退回原样（可能仍可用 data URI 或外链）
                    pass
            g.store.add_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=[(qr_url, message_link, captured_at, expires_at, meta)],
            )
            n += 1
        return n

    def distribute_kakao_items(
        self,
        *,
        seat_key: str,
        seat_label: str,
        account_info: str,
        items: List[Tuple[str, str, float, float, Dict[str, Any]]],
    ) -> int:
        """
        Kakao 专用：只在 kakao 分组中轮询分发；没有 kakao 分组则暂存 backlog。
        """
        n = 0
        if not self._rr_keys_kakao:
            self._backlog_kakao.append((seat_key, seat_label, account_info, items))
            return 0
        for it in items:
            g = self._pick_group_rr_kakao()
            if not g:
                self._backlog_kakao.append((seat_key, seat_label, account_info, [it]))
                continue
            g.store.add_items(seat_key=seat_key, seat_label=seat_label, account_info=account_info, items=[it])
            n += 1
        return n

    def distribute_ttm_items(
        self,
        *,
        seat_key: str,
        seat_label: str,
        account_info: str,
        items: List[Tuple[str, str, float, float, Dict[str, Any]]],
    ) -> int:
        """
        ThaiTicketMajor(支付宝) 专用：只在 ttm_alipay 分组中轮询分发；无分组则暂存 backlog。
        """
        n = 0
        if not self._rr_keys_ttm:
            self._backlog_ttm.append((seat_key, seat_label, account_info, items))
            return 0
        for it in items:
            g = self._pick_group_rr_ttm()
            if not g:
                self._backlog_ttm.append((seat_key, seat_label, account_info, [it]))
                continue
            qr_url, message_link, captured_at, expires_at, meta = it
            meta = dict(meta or {})
            # 若包含 qr_png_base64，则落盘为 PNG 并改成短 URL
            b64 = (meta.get("qr_png_base64") or "").strip() if isinstance(meta, dict) else ""
            if b64:
                try:
                    name = g.store.save_png_base64(b64)
                    qr_url = f"/api/groups/{g.group_id}/qr/{name}"
                    meta.pop("qr_png_base64", None)
                    meta["qr_saved"] = True
                except Exception:
                    pass
            g.store.add_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=[(qr_url, message_link, captured_at, expires_at, meta)],
            )
            n += 1
        return n

    def _flush_backlog_wechat(self) -> None:
        if not self._rr_keys_wechat or not self._backlog_wechat:
            return
        # 简单策略：按追加顺序把 backlog 逐条轮询分发
        pending = self._backlog_wechat
        self._backlog_wechat = []
        for seat_key, seat_label, account_info, items in pending:
            self.distribute_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=items,
            )

    def _flush_backlog_kakao(self) -> None:
        if not self._rr_keys_kakao or not self._backlog_kakao:
            return
        pending = self._backlog_kakao
        self._backlog_kakao = []
        for seat_key, seat_label, account_info, items in pending:
            self.distribute_kakao_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=items,
            )

    def _flush_backlog_ttm(self) -> None:
        if not self._rr_keys_ttm or not self._backlog_ttm:
            return
        pending = self._backlog_ttm
        self._backlog_ttm = []
        for seat_key, seat_label, account_info, items in pending:
            self.distribute_ttm_items(
                seat_key=seat_key,
                seat_label=seat_label,
                account_info=account_info,
                items=items,
            )


