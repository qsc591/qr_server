// 复用 wechat_qr_board 的 UI，但把 API 路径改成 group scoped。
// 这里不直接 import（为了零构建），而是动态拉取原来的静态资源并“包一层” API 前缀。

async function loadText(url) {
  const resp = await fetch(url, { cache: "no-store" });
  return await resp.text();
}

function injectCss(cssText) {
  const s = document.createElement("style");
  s.textContent = cssText;
  document.head.appendChild(s);
}

function injectHtml(htmlText) {
  // 把 body 内容塞进当前页面
  const parser = new DOMParser();
  const doc = parser.parseFromString(htmlText, "text/html");
  const app = doc.body.querySelector(".app");
  if (app) document.body.prepend(app);
  const toast = doc.getElementById("toast");
  if (toast) document.body.appendChild(toast);
}

function injectCssText(cssText) {
  const s = document.createElement("style");
  s.textContent = cssText;
  document.head.appendChild(s);
}

function setupServerOnlyUi(gid) {
  // 仅在 server 的 /board 页面生效（boot.js 只在 server 的 /board_static/boot.js 使用）
  document.documentElement.classList.add("server-board");
  document.body.classList.add("server-board");

  // 1) 位置列表右侧：返回按钮
  const header = document.querySelector(".left .left-header");
  if (header && !header.querySelector("#btnBack")) {
    const title = header.querySelector(".title");
    const subtitle = header.querySelector(".subtitle");

    // 将原本 title/subtitle 包到一个容器里，避免 flex 打散布局
    const main = document.createElement("div");
    main.className = "left-header-main";
    if (title) main.appendChild(title);
    if (subtitle) main.appendChild(subtitle);
    header.prepend(main);

    const actions = document.createElement("div");
    actions.className = "left-header-actions";

    const backBtn = document.createElement("button");
    backBtn.id = "btnBack";
    backBtn.className = "btn";
    backBtn.type = "button";
    backBtn.setAttribute("aria-label", "返回");
    backBtn.innerHTML = `<img src="/static/icon_back.svg" alt="返回" />`;
    backBtn.onclick = () => {
      // iframe 内返回到 server 首页（分组创建/列表页）
      try {
        window.top.location.href = "/";
      } catch (e) {
        window.location.href = "/";
      }
    };

    actions.appendChild(backBtn);
    header.appendChild(actions);
  }

  // 2) 删除 board 内部的 CSV 按钮（已挪到顶栏）
  const csvBtn = document.querySelector('a[href="/api/csv"]');
  if (csvBtn) csvBtn.remove();

  // 3) server-only 样式覆盖：二维码区更紧凑、Next 按钮一整行更醒目
  injectCssText(`
    /* 不依赖外层 class，避免因缓存/注入时机导致不生效 */
    .left .left-header{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
    }
    .left-header-main{ min-width:0; }
    .left-header-actions{
      display:flex;
      align-items:flex-start;
      gap:10px;
    }
    #btnBack{
      padding:8px 10px;
      min-width:auto;
      border-radius:10px;
      font-weight:900;
      display:inline-flex;
      align-items:center;
      justify-content:center;
    }
    #btnBack img{
      width:34px;
      height:34px;
      display:block;
    }
    .right{ padding:14px; }
    .card{ max-width:980px; height:calc(100vh - 28px); }
    .qr{
      flex:0 0 auto;
      padding:10px;
      min-height:240px;
    }
    .qr img{
      max-height:360px;
      width:auto;
      max-width:100%;
    }
    .actions{
      display:block;
      width:100%;
      padding-top:10px;
      border-top:1px dashed rgba(231, 238, 252, 0.18);
    }
    #btnNext{
      width:100%;
      min-width:0;
      padding:14px 16px;
      font-weight:900;
      font-size:16px;
      border-radius:14px;
    }
  `);

  // 4) 兜底：直接设置 inline，确保“整行/无 CSV”一定生效
  const btnNext = document.getElementById("btnNext");
  if (btnNext) {
    btnNext.style.width = "100%";
    btnNext.style.minWidth = "0";
  }
  const actions = document.querySelector(".actions");
  if (actions) {
    actions.style.display = "block";
    actions.style.width = "100%";
  }
}

async function main() {
  const gid = window.__GROUP_ID__;
  if (!gid) {
    document.body.textContent = "missing group_id";
    return;
  }

  // 1) CSS：直接用原来的 style.css
  const css = await loadText("/board_static/style.css");
  injectCss(css);

  // 2) HTML：用原来的 index.html
  const html = await loadText("/board_static/index.html");
  injectHtml(html);
  setupServerOnlyUi(gid);

  // 3) JS：用原来的 app.js，但把 API endpoint 替换成 group scoped
  let js = await loadText("/board_static/app.js");
  js = js.replaceAll('"/api/state"', `"/api/groups/${gid}/state"`);
  js = js.replaceAll('"/api/scan_next"', `"/api/groups/${gid}/scan_next"`);
  const run = new Function(js);
  run();

  // app.js 执行后再兜底移除一次 CSV（防止 DOM 变化导致未删除）
  const csvBtn2 = document.querySelector('a[href="/api/csv"]');
  if (csvBtn2) csvBtn2.remove();
}

main();




