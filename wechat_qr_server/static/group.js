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
    csvBtn.href = `/api/groups/${encodeURIComponent(groupId)}/csv`;
  }
}

main();




