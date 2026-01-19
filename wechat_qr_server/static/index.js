async function fetchGroups() {
  const resp = await fetch("/api/groups");
  return await resp.json();
}

async function doReset(password) {
  const resp = await fetch("/api/reset", {
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
    left.innerHTML = `<div class="gname">${g.name}</div><div class="gid">ID: ${g.group_id}</div>`;
    const a = document.createElement("a");
    a.className = "btn";
    a.href = `/g/${g.group_id}`;
    a.textContent = "进入";
    row.appendChild(left);
    row.appendChild(a);
    el.appendChild(row);
  });
  if ((data.groups || []).length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无分组，请先创建。";
    el.appendChild(empty);
  }
}

document.getElementById("createForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("groupName").value || "";
  const resp = await fetch("/api/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  const data = await resp.json();
  if (data && data.group_id) {
    window.location.href = `/g/${data.group_id}`;
  }
});

async function loop() {
  try {
    const data = await fetchGroups();
    renderGroups(data);
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
    renderGroups(data);
  } else if (resp.status === 403) {
    window.alert("密码错误");
  } else if (resp.status === 404) {
    window.alert("服务器未启用重置密码（reset_password 为空）");
  } else {
    window.alert("重置失败");
  }
});


