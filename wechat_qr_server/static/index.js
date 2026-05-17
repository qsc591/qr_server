async function fetchGroups() {
  const resp = await fetch("/api/groups");
  return await resp.json();
}

let lastGroupsSig = "";

async function doReset(password) {
  const resp = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password })
  });
  return resp;
}

async function createGroup({ name, kind, password, pgwEmail, pgwName, ttmCaptureQr }) {
  const resp = await fetch("/api/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      kind,
      password,
      pgw_email: pgwEmail || "",
      pgw_name: pgwName || "",
      ttm_capture_qr: (kind || "").toLowerCase() === "ttm_alipay" ? !!ttmCaptureQr : true
    })
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(txt || "创建失败");
  }
  return await resp.json();
}

async function createKakaoGroupWithAdminPassword({ name, adminPassword }) {
  const resp = await fetch("/api/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, kind: "kakao", admin_password: adminPassword })
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(txt || "创建失败");
  }
  return await resp.json();
}

async function deleteGroup({ groupId, password }) {
  const resp = await fetch(`/api/groups/${encodeURIComponent(groupId)}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password })
  });
  return resp;
}

function renderGroups(data) {
  const el = document.getElementById("groups");
  el.innerHTML = "";
  (data.groups || []).forEach((g) => {
    const row = document.createElement("div");
    row.className = "group-row";
    const left = document.createElement("div");
    const tags = [];
    const kind0 = (g.kind || "wechat").toLowerCase();
    if (kind0 === "kakao") tags.push("KAKAO");
    else if (kind0 === "ttm_alipay") tags.push("TTM");
    else tags.push("WECHAT");
    if (g.locked) tags.push("LOCK");
    const tagHtml = tags.length ? `<div class="gtags">${tags.map((t) => `<span class="tag">${t}</span>`).join("")}</div>` : "";
    const st = g.stats || {};
    const pendingTotal = Number(st.pending_total || 0);
    const completedSeats = Number(st.completed_seats || 0);
    const totalSeats = Number(st.total_seats || 0);
    const statsLine = `待扫码 ${pendingTotal} | 已完成座位 ${completedSeats}/${totalSeats}`;
    left.innerHTML = `<div class="gname">${g.name}${tagHtml}</div><div class="gid">ID: ${g.group_id}</div><div class="gstats">${statsLine}</div>`;

    const icon = document.createElement("div");
    icon.className = "gicon";
    const img = document.createElement("img");
    const kind = kind0;
    img.src = kind === "kakao" ? "/static/icon_kakao.svg" : (kind === "ttm_alipay" ? "/static/icon_ttm.png" : "/static/icon_wechat.svg");
    img.alt = kind === "kakao" ? "Kakao" : (kind === "ttm_alipay" ? "ThaiTicketMajor" : "WeChat");
    if (kind === "ttm_alipay") img.className = "ttm-logo";
    icon.appendChild(img);

    const actions = document.createElement("div");
    actions.className = "gactions";

    const enter = document.createElement("a");
    enter.className = "btn primary";
    enter.href = `/g/${g.group_id}`;
    enter.textContent = "进入";

    const del = document.createElement("button");
    del.className = "btn danger";
    del.type = "button";
    del.textContent = "删除";
    del.addEventListener("click", async () => {
      const pw = window.prompt("请输入重置密码（reset_password）以删除该分组");
      if (pw === null) return;
      const confirm2 = window.confirm(`确认删除分组：${g.name}（ID: ${g.group_id}）？\n该操作不可恢复。`);
      if (!confirm2) return;
      const resp = await deleteGroup({ groupId: g.group_id, password: pw });
      if (resp.status === 200) {
        try {
          const d2 = await fetchGroups();
          lastGroupsSig = signatureForGroups(d2);
          renderGroups(d2);
        } catch (e) {}
        window.alert("已删除分组");
      } else if (resp.status === 403) {
        window.alert("密码错误");
      } else if (resp.status === 404) {
        window.alert("服务器未启用重置密码（reset_password 为空）");
      } else {
        const txt = await resp.text();
        window.alert(txt || "删除失败");
      }
    });

    actions.appendChild(enter);
    actions.appendChild(del);
    row.appendChild(left);
    row.appendChild(icon);
    row.appendChild(actions);
    el.appendChild(row);
  });
  if ((data.groups || []).length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无分组，请先创建。";
    el.appendChild(empty);
  }
}

function signatureForGroups(data) {
  try {
    const gs = (data && data.groups) ? data.groups : [];
    return JSON.stringify(
      (gs || []).map((g) => ({
        group_id: g.group_id,
        name: g.name,
        kind: g.kind,
        locked: !!g.locked,
        stats: {
          pending_total: (g.stats && g.stats.pending_total) || 0,
          completed_seats: (g.stats && g.stats.completed_seats) || 0,
          total_seats: (g.stats && g.stats.total_seats) || 0,
        },
      }))
    );
  } catch (e) {
    return "";
  }
}

function openKindModal() {
  const modal = document.getElementById("kindModal");
  if (modal) modal.style.display = "flex";
  const wrap = document.getElementById("kakaoPwWrap");
  const ttmWrap = document.getElementById("ttmPgwWrap");
  const actionsDefault = document.getElementById("modalActionsDefault");
  if (wrap) wrap.style.display = "none";
  if (ttmWrap) ttmWrap.style.display = "none";
  if (actionsDefault) actionsDefault.style.display = "flex";
  const pw = document.getElementById("kakaoPassword");
  if (pw) pw.value = "";
  const te = document.getElementById("ttmPgwEmail");
  const tn = document.getElementById("ttmPgwName");
  if (te) te.value = "";
  if (tn) tn.value = "";
  const tc = document.getElementById("ttmCaptureQr");
  if (tc) tc.checked = true;
}

function closeKindModal() {
  const modal = document.getElementById("kindModal");
  if (modal) modal.style.display = "none";
  const wrap = document.getElementById("kakaoPwWrap");
  const ttmWrap = document.getElementById("ttmPgwWrap");
  const actionsDefault = document.getElementById("modalActionsDefault");
  if (wrap) wrap.style.display = "none";
  if (ttmWrap) ttmWrap.style.display = "none";
  if (actionsDefault) actionsDefault.style.display = "flex";
}

document.getElementById("createForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  openKindModal();
});

async function loop() {
  try {
    const data = await fetchGroups();
    const sig = signatureForGroups(data);
    if (sig !== lastGroupsSig) {
      lastGroupsSig = sig;
      renderGroups(data);
    }
  } catch (e) {}
  setTimeout(loop, 2000);
}

loop();

document.getElementById("btnReset").addEventListener("click", async () => {
  const pw = window.prompt("请输入重置密码（确认后会删除所有分组）");
  if (pw === null) return;
  const confirm2 = window.confirm("确认初始化分组？所有分组与数据将被删除。");
  if (!confirm2) return;

  const resp = await doReset(pw);
  if (resp.status === 200) {
    window.alert("已清空所有分组");
    const data = await fetchGroups();
    lastGroupsSig = signatureForGroups(data);
    renderGroups(data);
  } else if (resp.status === 403) {
    window.alert("密码错误");
  } else if (resp.status === 404) {
    window.alert("服务器未启用重置密码（reset_password 为空）");
  } else {
    window.alert("重置失败");
  }
});

function setupModalHandlers() {
  const pickWechat = document.getElementById("pickWechat");
  const pickKakao = document.getElementById("pickKakao");
  const pickTtm = document.getElementById("pickTtm");
  const wrap = document.getElementById("kakaoPwWrap");
  const ttmWrap = document.getElementById("ttmPgwWrap");
  const actionsDefault = document.getElementById("modalActionsDefault");
  const btnClose = document.getElementById("btnClose");
  const btnCancel = document.getElementById("btnCancel");
  const btnCreateKakao = document.getElementById("btnCreateKakao");
  const pw = document.getElementById("kakaoPassword");
  const ttmEmail = document.getElementById("ttmPgwEmail");
  const ttmName = document.getElementById("ttmPgwName");
  const ttmCaptureQr = document.getElementById("ttmCaptureQr");
  const btnCancelTtm = document.getElementById("btnCancelTtm");
  const btnCreateTtm = document.getElementById("btnCreateTtm");
  const mask = document.querySelector("#kindModal .modal-mask");

  function getName() {
    return (document.getElementById("groupName").value || "").trim();
  }

  if (btnClose) btnClose.addEventListener("click", closeKindModal);
  if (btnCancel) btnCancel.addEventListener("click", closeKindModal);
  if (btnCancelTtm) btnCancelTtm.addEventListener("click", closeKindModal);
  if (mask) mask.addEventListener("click", closeKindModal);

  if (pickWechat) {
    pickWechat.addEventListener("click", async () => {
      const name = getName();
      try {
        const data = await createGroup({
          name,
          kind: "wechat",
          password: "",
          pgwEmail: "",
          pgwName: ""
        });
        if (data && data.group_id) window.location.href = `/g/${data.group_id}`;
      } catch (e) {
        window.alert(String(e && e.message ? e.message : e));
      }
    });
  }

  if (pickTtm) {
    pickTtm.addEventListener("click", () => {
      if (ttmWrap) ttmWrap.style.display = "block";
      if (actionsDefault) actionsDefault.style.display = "none";
      if (ttmEmail) ttmEmail.focus();
    });
  }

  if (pickKakao) {
    pickKakao.addEventListener("click", () => {
      if (wrap) wrap.style.display = "block";
      if (ttmWrap) ttmWrap.style.display = "none";
      if (actionsDefault) actionsDefault.style.display = "none";
      if (pw) pw.focus();
    });
  }

  async function doCreateTtm() {
    const name = getName();
    const email = (ttmEmail?.value || "").trim();
    const nm = (ttmName?.value || "").trim();
    const cap = !!(ttmCaptureQr && ttmCaptureQr.checked);
    try {
      const data = await createGroup({
        name: name || "ThaiTicketMajor (支付宝)",
        kind: "ttm_alipay",
        password: "",
        pgwEmail: email,
        pgwName: nm,
        ttmCaptureQr: cap
      });
      if (data && data.group_id) window.location.href = `/g/${data.group_id}`;
    } catch (e) {
      window.alert(String(e && e.message ? e.message : e));
    }
  }

  async function doCreateKakao() {
    const name = getName();
    const adminPassword = (pw?.value || "").trim();
    if (!adminPassword) {
      window.alert("请输入重置分组密码（reset_password）");
      return;
    }
    try {
      const data = await createKakaoGroupWithAdminPassword({ name, adminPassword });
      // Kakao 创建后不自动进入：停留主页，避免误操作
      closeKindModal();
      try {
        const d2 = await fetchGroups();
        lastGroupsSig = signatureForGroups(d2);
        renderGroups(d2);
      } catch (e) {}
      if (data && data.group_id) {
        window.alert(`Kakao 分组已创建：${data.group_id}\n请在“已有分组”列表点击进入。`);
      } else {
        window.alert("Kakao 分组已创建，请在“已有分组”列表点击进入。");
      }
    } catch (e) {
      window.alert(String(e && e.message ? e.message : e));
    }
  }

  if (btnCreateTtm) btnCreateTtm.addEventListener("click", doCreateTtm);
  if (ttmName) {
    ttmName.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doCreateTtm();
    });
  }

  if (btnCreateKakao) btnCreateKakao.addEventListener("click", doCreateKakao);
  if (pw) {
    pw.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doCreateKakao();
    });
  }
}

setupModalHandlers();


