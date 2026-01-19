from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class QrItem:
    qr_url: str
    message_link: str
    captured_at: float  # epoch seconds
    expires_at: float  # epoch seconds
    scanned_at: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SeatState:
    seat_key: str
    seat_label: str
    account_info: str = ""
    pending: List[QrItem] = field(default_factory=list)
    scanned: List[QrItem] = field(default_factory=list)

    def current(self) -> Optional[QrItem]:
        return self.pending[0] if self.pending else None

    def last_scanned(self) -> Optional[QrItem]:
        return self.scanned[-1] if self.scanned else None

    def status(self) -> str:
        if self.pending:
            return "pending"
        if self.scanned:
            return "scanned"
        return "empty"


def seat_state_to_dict(seat: SeatState) -> Dict:
    cur = seat.current()
    last = seat.last_scanned()
    return {
        "seat_key": seat.seat_key,
        "seat_label": seat.seat_label,
        "account_info": seat.account_info,
        "pending_count": len(seat.pending),
        "scanned_count": len(seat.scanned),
        "status": seat.status(),
        "current": None
        if not cur
        else {
            "qr_url": cur.qr_url,
            "message_link": cur.message_link,
            "captured_at": cur.captured_at,
            "expires_at": cur.expires_at,
            "meta": cur.meta or {},
        },
        "last_scanned": None
        if not last
        else {
            "qr_url": last.qr_url,
            "message_link": last.message_link,
            "captured_at": last.captured_at,
            "scanned_at": last.scanned_at,
            "meta": last.meta or {},
        },
    }



