let selectedSeatKey = null;
let isAdvancing = false;
let lastShownQrUrl = null;
let toastTimer = null;

function splitSeatLabel(label) {
  const s = (label || "").trim();
  // T-Splash: "20260213-001 지정석-..."
  const m = s.match(/^(\d{8}-\d+)\s+(.+)$/);
  if (m) return { top: m[1], bottom: m[2] };
  // Xbot: "20260130 sku ..."
  const m2 = s.match(/^(\d{8})\s+(.+)$/);
  if (m2) return { top: m2[1], bottom: m2[2] };
  return { top: s, bottom: "" };
}

function fmtDateTime(tsSeconds) {
  if (!tsSeconds) return "-";
  const d = new Date(tsSeconds * 1000);
  // 本地时间：YYYY-MM-DD HH:mm:ss
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtMMSS(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function pickNextSeatKey(state) {
  const pending = state.seats.filter((s) => s.pending_count > 0);
  return pending.length ? pending[0].seat_key : null;
}

function render(state) {
  const seatListEl = document.getElementById("seatList");
  const statsEl = document.getElementById("stats");

  const total = state.seats.length;
  const pending = state.seats.reduce((a, s) => a + s.pending_count, 0);
  const scannedSeats = state.seats.filter((s) => s.status === "scanned").length;
  statsEl.textContent = `待扫码 ${pending} | 已完成座位 ${scannedSeats}/${total}`;

  if (!selectedSeatKey || !state.seats.find((s) => s.seat_key === selectedSeatKey)) {
    selectedSeatKey = pickNextSeatKey(state) || (state.seats[0] ? state.seats[0].seat_key : null);
  }

  seatListEl.innerHTML = "";
  state.seats.forEach((seat) => {
    const item = document.createElement("div");
    let isExpired = false;
    item.className =
      "seat-item " +
      seat.status +
      (seat.seat_key === selectedSeatKey ? " selected" : "");
    item.onclick = () => {
      selectedSeatKey = seat.seat_key;
      render(state);
    };

    const name = document.createElement("div");
    name.className = "seat-name";
    const parts = splitSeatLabel(seat.seat_label);
    const line1 = document.createElement("div");
    line1.className = "seat-line seat-line-1";
    line1.textContent = parts.top || "-";
    name.appendChild(line1);
    if (parts.bottom) {
      const line2 = document.createElement("div");
      line2.className = "seat-line seat-line-2";
      line2.textContent = parts.bottom;
      name.appendChild(line2);
    }

    const status = document.createElement("div");
    status.className = "seat-status";
    const pill = document.createElement("span");
    pill.className = "pill " + seat.status;
    pill.textContent = seat.status === "pending" ? "未扫描" : seat.status === "scanned" ? "已扫描" : "空";
    status.appendChild(pill);

    const timer = document.createElement("div");
    timer.className = "seat-timer";
    if (seat.pending_count > 0 && seat.current && seat.current.expires_at) {
      const remaining = seat.current.expires_at - state.server_time;
      if (remaining <= 0) {
        isExpired = true;
        timer.textContent = "此购物车已过期";
      } else {
        timer.textContent = `倒计时 ${fmtMMSS(remaining)}`;
      }
    } else {
      timer.textContent = seat.status === "scanned" ? "已完成" : "等待中";
    }

    const right = document.createElement("div");
    right.style.textAlign = "right";
    right.style.fontSize = "12px";
    right.style.color = "rgba(231,238,252,0.7)";
    right.textContent = seat.pending_count > 0 ? `待扫码 ${seat.pending_count}` : `已扫 ${seat.scanned_count}`;

    item.appendChild(name);
    item.appendChild(status);
    item.appendChild(timer);
    item.appendChild(right);
    if (isExpired) item.classList.add("expired");
    seatListEl.appendChild(item);
  });

  const cur = state.seats.find((s) => s.seat_key === selectedSeatKey) || null;
  const curSeatEl = document.getElementById("curSeat");
  const curCapturedAtEl = document.getElementById("curCapturedAt");
  const curDateEl = document.getElementById("curDate");
  const curSeatDetailEl = document.getElementById("curSeatDetail");
  const curPriceEl = document.getElementById("curPrice");
  const curQtyEl = document.getElementById("curQty");
  const xbotDetailsEl = document.getElementById("xbotDetails");
  const curAccountEl = document.getElementById("curAccount");
  const curLinkEl = document.getElementById("curLink");
  const qrImgEl = document.getElementById("qrImg");
  const qrHintEl = document.getElementById("qrHint");
  const btnNextEl = document.getElementById("btnNext");
  const statusBannerEl = document.getElementById("statusBanner");

  if (!cur) {
    curSeatEl.textContent = "-";
    if (curCapturedAtEl) curCapturedAtEl.textContent = "-";
    if (curDateEl) curDateEl.textContent = "-";
    if (curSeatDetailEl) curSeatDetailEl.textContent = "-";
    if (curPriceEl) curPriceEl.textContent = "-";
    if (curQtyEl) curQtyEl.textContent = "-";
    if (xbotDetailsEl) xbotDetailsEl.style.display = "none";
    curAccountEl.textContent = "-";
    curLinkEl.textContent = "-";
    curLinkEl.href = "#";
    qrImgEl.style.display = "none";
    qrHintEl.textContent = "等待抓取…";
    btnNextEl.disabled = true;
    if (statusBannerEl) statusBannerEl.style.display = "none";
    return;
  }

  // 右侧位置也按两行显示（日期在上，座位在下）
  const curParts = splitSeatLabel(cur.seat_label);
  curSeatEl.textContent = curParts.bottom ? `${curParts.top}\n${curParts.bottom}` : curParts.top;
  curAccountEl.textContent = cur.account_info || "-";
  // 优先展示 current；若没有 current，则展示 last_scanned（防误点消失）
  const shown = cur.current || cur.last_scanned || null;
  if (curCapturedAtEl) {
    const ts = shown ? shown.captured_at : null;
    curCapturedAtEl.textContent = fmtDateTime(ts);
  }
  const meta = (shown && shown.meta) ? shown.meta : {};
  const isXbot = meta && (meta.source === "xbot" || meta.source === "spider");
  if (xbotDetailsEl) xbotDetailsEl.style.display = isXbot ? "block" : "none";
  if (isXbot) {
    if (curDateEl) curDateEl.textContent = meta.date || "-";
    if (curSeatDetailEl) curSeatDetailEl.textContent = meta.seat_detail || "-";
    if (curPriceEl) curPriceEl.textContent = meta.price ? String(meta.price) : "-";
    if (curQtyEl) curQtyEl.textContent = meta.quantity ? String(meta.quantity) : "-";
  } else {
    if (curDateEl) curDateEl.textContent = "-";
    if (curSeatDetailEl) curSeatDetailEl.textContent = "-";
    if (curPriceEl) curPriceEl.textContent = "-";
    if (curQtyEl) curQtyEl.textContent = "-";
  }
  if (statusBannerEl) {
    if (cur.status === "scanned" && cur.pending_count === 0) {
      statusBannerEl.textContent = "本位置已完成扫码付款";
      statusBannerEl.style.display = "block";
    } else {
      statusBannerEl.style.display = "none";
    }
  }

  if (shown && shown.message_link) {
    curLinkEl.textContent = "打开 Discord 消息";
    curLinkEl.href = shown.message_link;
  } else {
    curLinkEl.textContent = "-";
    curLinkEl.href = "#";
  }

  if (shown && shown.qr_url) {
    const nextUrl = shown.qr_url;
    const isChanged = lastShownQrUrl && lastShownQrUrl !== nextUrl;
    if (isChanged) {
      qrImgEl.classList.add("switching");
    }
    qrImgEl.src = nextUrl;
    qrImgEl.style.display = "block";
    qrHintEl.textContent = "";
    // 只有 pending 的 current 才允许 next；last_scanned 只保留显示
    btnNextEl.disabled = !(cur.current && cur.current.qr_url);
    qrImgEl.onload = () => {
      qrHintEl.textContent = "";
      qrImgEl.style.display = "block";
      qrImgEl.classList.remove("switching");
      lastShownQrUrl = nextUrl;
    };
    qrImgEl.onerror = () => {
      qrImgEl.style.display = "none";
      qrHintEl.textContent = "图片加载失败（可能链接不可访问/已过期）";
      btnNextEl.disabled = true;
      qrImgEl.classList.remove("switching");
    };
  } else {
    qrImgEl.style.display = "none";
    qrHintEl.textContent =
      cur.status === "scanned" && cur.pending_count === 0
        ? "本位置已完成扫码付款"
        : "该位置暂无二维码";
    btnNextEl.disabled = true;
  }

  // 如果正在展示的是 last_scanned（说明已点击过 next），给一个明确提示
  if (!cur.current && cur.last_scanned && qrHintEl && qrImgEl.style.display !== "none") {
    qrHintEl.textContent = "已扫描（保留显示，防误点）";
  }
}

async function fetchState() {
  const resp = await fetch("/api/state");
  if (!resp.ok) throw new Error("state failed");
  return await resp.json();
}

async function doNext() {
  if (!selectedSeatKey) return;
  const resp = await fetch("/api/scan_next", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ seat_key: selectedSeatKey })
  });
  if (!resp.ok) return;
  const data = await resp.json();
  if (data && data.next_seat_key) selectedSeatKey = data.next_seat_key;
}

async function loop() {
  try {
    const state = await fetchState();
    render(state);
  } catch (e) {
    // ignore
  } finally {
    setTimeout(loop, 1000);
  }
}

function showToast(message, kind) {
  const el = document.getElementById("toast");
  if (!el) return;
  if (toastTimer) clearTimeout(toastTimer);
  el.textContent = message;
  el.className = "toast show " + (kind || "ok");
  toastTimer = setTimeout(() => {
    el.className = "toast";
  }, 1200);
}

document.getElementById("btnNext").onclick = async () => {
  if (isAdvancing) return;
  const btn = document.getElementById("btnNext");
  const qrImgEl = document.getElementById("qrImg");

  isAdvancing = true;
  btn.classList.add("loading");
  btn.disabled = true;
  // 先做一个轻微淡出，增强“切换中”的感觉
  if (qrImgEl && qrImgEl.style.display !== "none") {
    qrImgEl.classList.add("switching");
  }

  try {
    await doNext();
    const state = await fetchState();
    render(state);
    showToast("已记录到 CSV", "ok");
  } catch (e) {
    showToast("操作失败，请重试", "err");
  } finally {
    btn.classList.remove("loading");
    isAdvancing = false;
    // render 会根据状态重新启用/禁用按钮
  }
};

loop();


