let selectedSeatKey = null;
let isAdvancing = false;
let lastShownQrUrl = null;
let toastTimer = null;
let ttmJumped = {}; // seat_key -> true (unlock Next after jumping to Alipay)
let scannedCollapsed = true; // 左侧「已扫描」子分组默认折叠
let expiredCollapsed = true; // 左侧「已过期」子分组默认折叠

async function logTtmJump(seatKey) {
  const k = String(seatKey || "").trim();
  if (!k) return;
  try {
    await fetch("/api/ttm_jump", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seat_key: k }),
    });
  } catch (e) {
    // ignore
  }
}

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

  const buildSeatItem = (seat) => {
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
    const seqN =
      (seat.current && seat.current.seq) ||
      (seat.last_scanned && seat.last_scanned.seq) ||
      0;
    const srcHere =
      (seat.current && seat.current.meta && seat.current.meta.source) ||
      (seat.last_scanned && seat.last_scanned.meta && seat.last_scanned.meta.source) ||
      "";
    // KB Pay：座位加粗在上、日期小字在下（座位是每张票的关键信息）
    const kbSwap = srcHere === "kbpay" && parts.bottom;
    const topText = kbSwap ? parts.bottom : (parts.top || "-");
    const bottomText = kbSwap ? parts.top : parts.bottom;

    const topline = document.createElement("div");
    topline.className = "seat-topline";
    if (seqN) {
      const badge = document.createElement("span");
      badge.className = "seq-badge";
      badge.textContent = "#" + seqN;
      topline.appendChild(badge);
    }
    const line1 = document.createElement("div");
    line1.className = "seat-line seat-line-1";
    line1.textContent = topText;
    topline.appendChild(line1);
    name.appendChild(topline);
    if (bottomText) {
      const line2 = document.createElement("div");
      line2.className = "seat-line seat-line-2";
      line2.textContent = bottomText;
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
    return item;
  };

  const buildGroupHead = (label, count, kind, collapsed) => {
    // kind: "" | "expired" | "scanned"
    const cls = ["group-head"];
    if (kind === "scanned") cls.push("scanned");
    else if (kind === "expired") cls.push("expired");
    if (kind) cls.push("collapsible");
    const head = document.createElement("div");
    head.className = cls.join(" ");
    let inner = "";
    if (kind) inner += `<span class="caret">${collapsed ? "▸" : "▾"}</span>`;
    inner += `<span>${label}</span><span class="cnt">${count}</span><span class="line"></span>`;
    head.innerHTML = inner;
    return head;
  };

  const isSeatExpired = (s) =>
    s.status !== "scanned" &&
    s.current &&
    s.current.expires_at &&
    s.current.expires_at - state.server_time <= 0;

  const activeSeats = state.seats.filter((s) => s.status !== "scanned" && !isSeatExpired(s));
  const expiredSeats = state.seats.filter((s) => isSeatExpired(s));
  const doneSeats = state.seats.filter((s) => s.status === "scanned");

  const buildSection = (label, kind, seats, collapsed, onToggle) => {
    const wrap = document.createElement("div");
    wrap.className = "seat-section" + (kind ? " " + kind : "");
    const head = buildGroupHead(label, seats.length, kind, collapsed);
    if (onToggle) head.onclick = onToggle;
    wrap.appendChild(head);
    const items = document.createElement("div");
    items.className = "seat-items";
    if (!collapsed || !kind) {
      seats.forEach((s) => items.appendChild(buildSeatItem(s)));
    }
    wrap.appendChild(items);
    return wrap;
  };

  seatListEl.appendChild(buildSection("未扫描", "", activeSeats, false, null));
  seatListEl.appendChild(buildSection(
    "已扫描", "scanned", doneSeats, scannedCollapsed,
    () => { scannedCollapsed = !scannedCollapsed; render(state); }
  ));
  seatListEl.appendChild(buildSection(
    "已过期", "expired", expiredSeats, expiredCollapsed,
    () => { expiredCollapsed = !expiredCollapsed; render(state); }
  ));

  const cur = state.seats.find((s) => s.seat_key === selectedSeatKey) || null;
  const curSeatEl = document.getElementById("curSeat");
  const curCapturedAtEl = document.getElementById("curCapturedAt");
  const curDateEl = document.getElementById("curDate");
  const curSeatDetailEl = document.getElementById("curSeatDetail");
  const curPriceEl = document.getElementById("curPrice");
  const curQtyEl = document.getElementById("curQty");
  const xbotDetailsEl = document.getElementById("xbotDetails");
  const ttmDetailsEl = document.getElementById("ttmDetails");
  const ttmTitleEl = document.getElementById("ttmTitle");
  const ttmOrderIdEl = document.getElementById("ttmOrderId");
  const ttmExpiryCnEl = document.getElementById("ttmExpiryCn");
  const curAccountEl = document.getElementById("curAccount");
  const curLinkEl = document.getElementById("curLink");
  const qrImgEl = document.getElementById("qrImg");
  const qrHintEl = document.getElementById("qrHint");
  const btnNextEl = document.getElementById("btnNext");
  const btnAlipayJumpEl = document.getElementById("btnAlipayJump");
  const btnDownloadCsvEl = document.getElementById("btnDownloadCsv");
  const btnDownloadTtmCsvEl = document.getElementById("btnDownloadTtmCsv");
  const statusBannerEl = document.getElementById("statusBanner");
  const genericMetaEl = document.getElementById("genericMeta");
  const genericQrEl = document.getElementById("genericQr");
  const kbpayCardEl = document.getElementById("kbpayCard");
  const kbSeqEl = document.getElementById("kbSeq");
  const kbSiteEl = document.getElementById("kbSite");
  const kbTitleEl = document.getElementById("kbTitle");
  const kbBannerEl = document.getElementById("kbBanner");
  const kbQrImgEl = document.getElementById("kbQrImg");
  const kbCodeEl = document.getElementById("kbCode");
  const kbCopyEl = document.getElementById("kbCopy");
  const kbPayMEl = document.getElementById("kbPayM");
  const kbExpEl = document.getElementById("kbExp");
  const kbCdEl = document.getElementById("kbCd");
  const kbStateEl = document.getElementById("kbState");
  const kbEventEl = document.getElementById("kbEvent");
  const kbDateEl = document.getElementById("kbDate");
  const kbSeatEl = document.getElementById("kbSeat");
  const kbPriceEl = document.getElementById("kbPrice");
  const kbQtyEl = document.getElementById("kbQty");
  const kbCapEl = document.getElementById("kbCap");
  const kbStepsBodyEl = document.getElementById("kbStepsBody");
  const kbLinkEl = document.getElementById("kbLink");
  const seqRowEl = document.getElementById("seqRow");
  const curSeqEl = document.getElementById("curSeq");

  if (!cur) {
    curSeatEl.textContent = "-";
    if (curCapturedAtEl) curCapturedAtEl.textContent = "-";
    if (curDateEl) curDateEl.textContent = "-";
    if (curSeatDetailEl) curSeatDetailEl.textContent = "-";
    if (curPriceEl) curPriceEl.textContent = "-";
    if (curQtyEl) curQtyEl.textContent = "-";
    if (xbotDetailsEl) xbotDetailsEl.style.display = "none";
    if (ttmDetailsEl) ttmDetailsEl.style.display = "none";
    if (kbpayCardEl) kbpayCardEl.style.display = "none";
    if (genericMetaEl) genericMetaEl.style.display = "";
    if (genericQrEl) genericQrEl.style.display = "";
    if (seqRowEl) seqRowEl.style.display = "none";
    if (btnAlipayJumpEl) {
      btnAlipayJumpEl.style.display = "none";
      btnAlipayJumpEl.href = "#";
    }
    if (curAccountEl) curAccountEl.textContent = "-";
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
  if (curAccountEl) curAccountEl.textContent = cur.account_info || "-";
  // 优先展示 current；若没有 current，则展示 last_scanned（防误点消失）
  const shown = cur.current || cur.last_scanned || null;
  if (curCapturedAtEl) {
    const ts = shown ? shown.captured_at : null;
    curCapturedAtEl.textContent = fmtDateTime(ts);
  }
  const meta = (shown && shown.meta) ? shown.meta : {};
  const source = meta && meta.source ? String(meta.source) : "";
  const isKbpay = source === "kbpay";
  const isXbot = source === "xbot" || source === "spider" || source === "alipay_tsplash";
  const isTtm = source === "ttm_alipay" || source === "ttm_export";
  const isAliPayImg = source === "alipay_tsplash";

  // KB Pay 用独立卡片布局；其它来源用通用布局
  if (kbpayCardEl) kbpayCardEl.style.display = isKbpay ? "flex" : "none";
  if (genericMetaEl) genericMetaEl.style.display = isKbpay ? "none" : "";
  if (genericQrEl) genericQrEl.style.display = isKbpay ? "none" : "";

  if (xbotDetailsEl) xbotDetailsEl.style.display = isXbot ? "block" : "none";
  if (ttmDetailsEl) ttmDetailsEl.style.display = isTtm ? "block" : "none";

  // 序号（通用布局用；KB Pay 的序号在卡片头部单独展示）
  const seqN = shown && shown.seq ? shown.seq : 0;
  if (seqRowEl && curSeqEl) {
    if (seqN && !isKbpay) {
      curSeqEl.textContent = "#" + seqN;
      seqRowEl.style.display = "";
    } else {
      seqRowEl.style.display = "none";
    }
  }

  if (isKbpay) {
    const isDone = cur.status === "scanned" && cur.pending_count === 0;
    const _expTs = shown && shown.expires_at ? shown.expires_at : 0;
    const _rem = _expTs ? _expTs - state.server_time : 0;
    const isKbExpired = !isDone && _expTs && _rem <= 0;
    if (kbSeqEl) kbSeqEl.textContent = seqN ? "#" + seqN : "#-";
    if (kbSiteEl) kbSiteEl.textContent = meta.site || "KB Pay";
    if (kbTitleEl) {
      kbTitleEl.classList.remove("dead");
      if (isDone) {
        kbTitleEl.innerHTML = "Payment done";
      } else if (isKbExpired) {
        kbTitleEl.innerHTML = "已过期 · 请忽略此码";
        kbTitleEl.classList.add("dead");
      } else {
        kbTitleEl.innerHTML = '<span class="dot"></span>Waiting for payment';
      }
    }
    if (kbBannerEl) {
      kbBannerEl.style.display = isDone ? "block" : "none";
      if (isDone) kbBannerEl.textContent = "本位置已完成扫码付款";
    }
    if (kbCodeEl) kbCodeEl.textContent = meta.settle_code || "-";
    if (kbPayMEl) kbPayMEl.textContent = meta.pay_method || "-";
    if (kbEventEl) {
      kbEventEl.textContent = meta.event || "-";
      kbEventEl.href = meta.event_url || "#";
    }
    if (kbDateEl) kbDateEl.textContent = meta.date || "-";
    if (kbSeatEl) kbSeatEl.textContent = meta.seat_detail || "-";
    if (kbPriceEl) kbPriceEl.textContent = meta.price ? String(meta.price) : "-";
    if (kbQtyEl) kbQtyEl.textContent = meta.quantity ? String(meta.quantity) : "-";
    if (kbCapEl) kbCapEl.textContent = shown ? fmtDateTime(shown.captured_at) : "-";
    if (kbStepsBodyEl) kbStepsBodyEl.textContent = meta.steps || "-";
    if (kbLinkEl) {
      if (shown && shown.message_link) {
        kbLinkEl.href = shown.message_link;
        kbLinkEl.textContent = "打开 Discord 消息";
      } else {
        kbLinkEl.href = "#";
        kbLinkEl.textContent = "-";
      }
    }
    if (kbQrImgEl) {
      if (shown && shown.qr_url) {
        if (kbQrImgEl.getAttribute("src") !== shown.qr_url) kbQrImgEl.src = shown.qr_url;
        kbQrImgEl.style.display = "block";
      } else {
        kbQrImgEl.removeAttribute("src");
        kbQrImgEl.style.display = "none";
      }
    }
    if (kbCopyEl) {
      kbCopyEl.onclick = () => {
        const code = meta.settle_code || "";
        if (!code) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(() => showToast("已复制结算码 " + code, "ok")).catch(() => {});
        } else {
          showToast("结算码 " + code, "ok");
        }
      };
    }
    if (kbExpEl && kbCdEl && kbStateEl) {
      const exp = shown && shown.expires_at ? shown.expires_at : 0;
      const remaining = exp ? exp - state.server_time : 0;
      kbExpEl.className = "expiry";
      if (isDone) {
        kbCdEl.textContent = "--:--";
        kbStateEl.textContent = "已完成付款";
        kbExpEl.classList.add("ok");
      } else if (!exp) {
        kbCdEl.textContent = "--:--";
        kbStateEl.textContent = "-";
      } else if (remaining <= 0) {
        kbCdEl.textContent = "00:00";
        kbStateEl.textContent = "已过期 · 请忽略此码";
        kbExpEl.classList.add("dead");
      } else if (remaining <= 60) {
        kbCdEl.textContent = fmtMMSS(remaining);
        kbStateEl.textContent = "即将过期";
        kbExpEl.classList.add("warn");
      } else {
        kbCdEl.textContent = fmtMMSS(remaining);
        kbStateEl.textContent = "有效 · 等待付款";
        kbExpEl.classList.add("ok");
      }
    }
  }

  if (isXbot) {
    if (curDateEl) curDateEl.textContent = meta.date || "-";
    if (curSeatDetailEl) {
      const seatTxt = meta.seat_detail || "-";
      curSeatDetailEl.textContent = seatTxt;
      if (source === "alipay_tsplash") curSeatDetailEl.classList.add("preline");
      else curSeatDetailEl.classList.remove("preline");
    }
    if (curPriceEl) curPriceEl.textContent = meta.price ? String(meta.price) : "-";
    if (curQtyEl) curQtyEl.textContent = meta.quantity ? String(meta.quantity) : "-";
  } else {
    if (curDateEl) curDateEl.textContent = "-";
    if (curSeatDetailEl) curSeatDetailEl.textContent = "-";
    if (curSeatDetailEl) curSeatDetailEl.classList.remove("preline");
    if (curPriceEl) curPriceEl.textContent = "-";
    if (curQtyEl) curQtyEl.textContent = "-";
  }

  if (isTtm) {
    if (ttmTitleEl) ttmTitleEl.textContent = meta.product_title || "-";
    if (ttmOrderIdEl) {
      const oid = (meta.order_id || "").trim();
      ttmOrderIdEl.textContent = oid ? oid.slice(0, 7) : "-";
    }
    if (ttmExpiryCnEl) {
      // 兜底：若后端没填 payment_expiry_cn，用 expires_at（浏览器本地时区）显示
      const s = (meta.payment_expiry_cn || "").trim();
      const expTs = (shown && shown.expires_at) ? shown.expires_at : null;
      ttmExpiryCnEl.textContent = s || (expTs ? fmtDateTime(expTs) : "-");
    }
  } else {
    if (ttmTitleEl) ttmTitleEl.textContent = "-";
    if (ttmOrderIdEl) ttmOrderIdEl.textContent = "-";
    if (ttmExpiryCnEl) ttmExpiryCnEl.textContent = "-";
  }

  if (btnAlipayJumpEl) {
    const u = (meta && meta.alipay_url) ? String(meta.alipay_url) : "";
    const m = (meta && meta.mpayment_url) ? String(meta.mpayment_url) : "";
    const jump = (u || m).trim();
    if (jump) {
      btnAlipayJumpEl.href = jump;
      btnAlipayJumpEl.style.display = "inline-block";
      btnAlipayJumpEl.onclick = () => {
        if (isTtm && cur && cur.seat_key) {
          ttmJumped[cur.seat_key] = true;
          logTtmJump(cur.seat_key);
          // 点击跳转后允许 Next（即使没有二维码）
          if (btnNextEl) btnNextEl.disabled = !(cur.current);
        }
      };
    } else {
      btnAlipayJumpEl.href = "#";
      btnAlipayJumpEl.style.display = "none";
      btnAlipayJumpEl.onclick = null;
    }
  }

  // 下载按钮：按“当前订单类型”切换显示
  if (btnDownloadCsvEl && btnDownloadTtmCsvEl) {
    if (isTtm) {
      btnDownloadCsvEl.style.display = "none";
      btnDownloadTtmCsvEl.style.display = "inline-flex";
    } else {
      btnDownloadCsvEl.style.display = "inline-flex";
      btnDownloadTtmCsvEl.style.display = "none";
    }
  }
  if (statusBannerEl) {
    if (cur.status === "scanned" && cur.pending_count === 0) {
      statusBannerEl.textContent = "本位置已完成扫码付款";
      statusBannerEl.style.display = "block";
    } else {
      statusBannerEl.style.display = "none";
    }
  }

  // “消息”固定为 Discord（避免与下方“点击跳转到支付宝”冲突）
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
    if (isAliPayImg || meta.qr_large) qrImgEl.classList.add("qr-large");
    else qrImgEl.classList.remove("qr-large");
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
    const u = (meta && meta.alipay_url) ? String(meta.alipay_url) : "";
    const m = (meta && meta.mpayment_url) ? String(meta.mpayment_url) : "";
    const jump = (u || m).trim();
    const allowNextByJump = !!(
      isTtm &&
      jump &&
      cur.current &&
      (ttmJumped[cur.seat_key] || (meta && meta.jumped_at))
    );
    qrHintEl.textContent =
      cur.status === "scanned" && cur.pending_count === 0
        ? "本位置已完成扫码付款"
        : (isTtm && jump)
          ? "该位置暂无二维码，请先点击下方“点击跳转到支付宝”后再点 Next"
          : "该位置暂无二维码";
    btnNextEl.disabled = !(cur.current && (allowNextByJump));
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


