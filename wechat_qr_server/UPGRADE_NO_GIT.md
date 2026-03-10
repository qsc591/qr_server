# 服务器升级指南（无 Git 版）

适用场景：你的项目根目录里有很多其它代码，不想/不方便用 `git diff` 来列清单；只希望**按文件路径覆盖**，让服务器版本升级到“最新：Kakao 多组轮询 + 每组密码 + 图标/UI”。

> **安全提醒**：不要把任何 Discord Token / SSH 私钥发给任何人。本文只用 `scp/rsync` 覆盖文件即可。

---

## 1) 新规则（你现在的“最新服务器版”行为）

- **微信组（kind=wechat）**
  - 只接收：WeChat/Eximbay/Xbot（由 `extract_wechat_qr_entries` 识别）
  - 只在**微信组集合**内部 RR 轮询分配
- **Kakao组（kind=kakao）**
  - 只接收：Kakao（由 `extract_kakao_pay_entries` 识别）
  - 只在**Kakao组集合**内部 RR 轮询分配
  - **创建/进入都使用 reset_password**（不允许单独设置 Kakao 密码，避免误操作）
- **两套轮询互不影响**：Kakao 不会抢微信队列，微信也不会抢 Kakao 队列

---

## 2) 服务器需要覆盖哪些文件（最小集合）

### A) 必须覆盖：`wechat_qr_server/`（服务器端）

- `wechat_qr_server/groups.py`
- `wechat_qr_server/web.py`
- `wechat_qr_server/main.py`
- `wechat_qr_server/config.py`（如果你服务器还在用旧结构，建议一起覆盖）
- `wechat_qr_server/config.example.json`（示例配置更新）
- `wechat_qr_server/README.md`（说明更新）

#### 服务器 UI 静态文件

- `wechat_qr_server/static/index.html`
- `wechat_qr_server/static/index.js`
- `wechat_qr_server/static/style.css`
- `wechat_qr_server/static/group.html`
- `wechat_qr_server/static/group.js`
- `wechat_qr_server/static/board.css`

#### 服务器 board 注入与覆盖（iframe 内 UI）

- `wechat_qr_server/board_static/boot.js`

#### 新增图标（必须上传到服务器）

- `wechat_qr_server/static/icon_wechat.svg`
- `wechat_qr_server/static/icon_kakao.svg`
- `wechat_qr_server/static/icon_back.svg`

### B) 必须覆盖：`wechat_qr_board/`（服务器依赖的核心逻辑/静态 UI）

因为服务器端会：
- `import wechat_qr_board.extract / store`
- `复用 wechat_qr_board/static/{index.html,app.js,style.css}` 作为 board UI

所以至少要保证服务器上这些文件也是你本地“最新版本”：

- `wechat_qr_board/extract.py`
- `wechat_qr_board/store.py`
- `wechat_qr_board/models.py`
- `wechat_qr_board/web.py`（如果你之前改过 CSV 下载/接口，建议同步）
- `wechat_qr_board/static/index.html`
- `wechat_qr_board/static/app.js`
- `wechat_qr_board/static/style.css`

> 如果你服务器上的 `wechat_qr_board` 已经是你“满意的最新本地版”，这部分就不需要重复覆盖。

---

## 3) Debian 服务器覆盖方式（推荐 rsync）

假设：
- 本地工程目录：`H:\\code\\SenRaffle`
- 服务器工程目录：`/root/dc_cart_site`
- 服务器地址：`<SERVER_IP>`

### 3.1 只覆盖 wechat_qr_server（最安全）

在本地 PowerShell 执行：

```powershell
rsync -av --delete `
  ./wechat_qr_server/ `
  root@<SERVER_IP>:/root/dc_cart_site/wechat_qr_server/
```

再单独上传 `wechat_qr_board/static`（如果需要）：

```powershell
rsync -av `
  ./wechat_qr_board/static/ `
  root@<SERVER_IP>:/root/dc_cart_site/wechat_qr_board/static/
```

以及 python 逻辑（如果需要）：

```powershell
rsync -av `
  ./wechat_qr_board/extract.py `
  ./wechat_qr_board/store.py `
  ./wechat_qr_board/models.py `
  root@<SERVER_IP>:/root/dc_cart_site/wechat_qr_board/
```

> Windows 没有 rsync 的话，用 `scp` 也行，但会更繁琐（要逐文件上传）。

---

## 4) 配置注意点（从“固定 Kakao 单组”升级到“多 Kakao 组”）

### 4.1 `config.json` 兼容

现在只保留：
- `kakao_group_enabled`（是否启用 Kakao 识别/分发）

旧字段：
- `kakao_group_id / kakao_group_name / kakao_group_password`

已经不再使用（保留在 config 里也不会影响运行）。

### 4.2 创建 Kakao 组

打开 `/` 首页：
- 输入分组名称，点击“创建分组”
- 在弹窗中选择 **Kakao组**
- 输入 **重置分组密码（reset_password）**
- 创建后把 `/g/<group_id>` 发给对应成员

---

## 5) 重启与验证

### 5.1 重启 systemd（示例）

```bash
sudo systemctl restart wechat-qr-server
sudo systemctl status wechat-qr-server --no-pager -l
```

### 5.2 验证点

- 首页 `/` 能看到创建分组时的 **微信/Kakao 图标**
- “已有分组”列表中间能看到对应图标
- 创建 Kakao 组必须输入密码
- 进入 Kakao 组会要求密码登录；微信组默认不需要密码
- 分组页顶栏有 **下载CSV** + **复制分享链接**
- board 内左侧“位置列表”右上有 **返回按钮（图标）**
- 右侧二维码区域更紧凑；底部“下一个（已扫描）”为整行按钮


