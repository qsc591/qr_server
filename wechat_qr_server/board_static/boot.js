// 复用 wechat_qr_board 的 UI，但把 API 路径改成 group scoped。
// 这里不直接 import（为了零构建），而是动态拉取原来的静态资源并“包一层” API 前缀。

async function loadText(url) {
  const resp = await fetch(url);
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

  // 3) JS：用原来的 app.js，但把 API endpoint 替换成 group scoped
  let js = await loadText("/board_static/app.js");
  js = js.replaceAll('"/api/state"', `"/api/groups/${gid}/state"`);
  js = js.replaceAll('"/api/scan_next"', `"/api/groups/${gid}/scan_next"`);
  // 下载 CSV：替换掉 href（index.html 里是 /api/csv）
  // 直接在 DOM 上改，避免复杂字符串替换
  const run = new Function(js);
  run();

  const csvBtn = document.querySelector('a[href="/api/csv"]');
  if (csvBtn) {
    csvBtn.setAttribute("href", `/api/groups/${gid}/csv`);
  }
}

main();


