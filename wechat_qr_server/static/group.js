function getGroupIdFromPath() {
  const parts = window.location.pathname.split("/");
  return parts[2] || "";
}

async function fetchGroupInfo(groupId) {
  const resp = await fetch(`/api/groups/${groupId}`);
  return await resp.json();
}

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  return Promise.resolve();
}

async function main() {
  const groupId = getGroupIdFromPath();
  const info = await fetchGroupInfo(groupId);
  document.getElementById("groupName").textContent = info.name || groupId;
  document.getElementById("groupId").textContent = groupId;
  const pgwWrap = document.getElementById("pgwMeta");
  const pgwName = (info.pgw_name || "").trim();
  const pgwEmail = (info.pgw_email || "").trim();
  if (pgwWrap && (pgwName || pgwEmail)) {
    pgwWrap.style.display = "block";
    const n = document.getElementById("pgwName");
    const e = document.getElementById("pgwEmail");
    if (n) n.textContent = pgwName || "-";
    if (e) e.textContent = pgwEmail || "-";
  }

  const frame = document.getElementById("boardFrame");
  frame.src = `/board?group_id=${encodeURIComponent(groupId)}`;

  const share = info.share_url || window.location.href;
  const shareBtn = document.getElementById("shareLink");
  shareBtn.href = share;
  shareBtn.onclick = async (e) => {
    e.preventDefault();
    await copyText(share);
    shareBtn.textContent = "已复制";
    setTimeout(() => (shareBtn.textContent = "复制分享链接"), 1200);
  };

  const csvBtn = document.getElementById("csvLink");
  if (csvBtn) {
    const kind = String(info.kind || "").toLowerCase();
    if (kind === "ttm_alipay") {
      csvBtn.href = `/api/groups/${encodeURIComponent(groupId)}/ttm_csv`;
      csvBtn.textContent = "下载TTM订单CSV";
    } else {
      csvBtn.href = `/api/groups/${encodeURIComponent(groupId)}/csv`;
      csvBtn.textContent = "下载CSV";
    }
  }
}

main();




