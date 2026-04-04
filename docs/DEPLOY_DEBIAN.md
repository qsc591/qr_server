# Debian 一键部署（Caddy + HTTPS + systemd）

本仓库是 **纯服务器版本**（公网多人分组协作扫码）。

- `wechat_qr_server/`：服务器端（公网访问、分组管理、轮询分发）
- `wechat_qr_board/`：服务器依赖的解析逻辑 + Board 静态 UI（由服务器嵌入/复用）

本文档讲 **Debian 服务器 + Caddy + HTTPS** 的最简单部署方式。

---

## 0) 前置条件

- 你有一个域名（示例：`itpdash.online`）
- 域名的 **DNS A 记录** 指向你的服务器公网 IP
  - **必须同时配置**：
    - `@` → 服务器 IP
    - `www` → 服务器 IP
- 云安全组 / 防火墙放行：**TCP 80、TCP 443**

---

## 1) 上传代码到服务器

推荐直接在服务器用 GitHub 拉取到目录（默认用你之前的仓库；如果你以后换仓库地址，再改这里即可）：

```bash
sudo apt update && sudo apt install -y git

cd /root
rm -rf github_qr_site
git clone https://github.com/qsc591/qr_server github_qr_site
cd /root/github_qr_site
```

要求目录下至少存在：

- `wechat_qr_server/`
- `wechat_qr_board/`
- `scripts/install_debian.sh`

---

## 2) 一键安装（推荐）

在服务器上：

```bash
chmod +x scripts/install_debian.sh

export DISCORD_TOKEN="你的Discord Token"

sudo bash scripts/install_debian.sh \
  --domain <你的域名> \
  --channel-ids "<频道ID1,频道ID2,...>" \
  --app-dir /root/github_qr_site \
  --reset-password "CHANGE_ME" \
  --use-user-token false
```

### 2.1 这两个参数必须由操作者填写（不能固定）

- **`--domain <你的域名>`**
  - 这是你在域名平台（Namecheap/Cloudflare 等）绑定到服务器 IP 的域名
  - Caddy 会用它来自动申请 HTTPS 证书，并把公网流量反代到本程序

- **`--channel-ids "<频道ID1,频道ID2,...>"`**
  - 这是你 Discord 里要监听的**频道 ID**（可以多个，用逗号分隔）
  - 这部分必须由操作者按自己的服务器/频道填写，不能写死

### 2.2 如何获取 Discord 频道 ID（简易）

1. Discord 打开「设置」→「高级」→ 打开「开发者模式」
2. 在目标频道上右键 →「复制频道 ID」
3. 把多个频道 ID 用英文逗号拼起来，例如：`"123,456,789"`

### 2.3 Bot Token / User Token（必须选对）

- **Bot Token（推荐）**：`--use-user-token false`
- **User Token（不推荐）**：`--use-user-token true`

安装脚本会做：

- 安装 Caddy（官方源）
- 创建 Python venv 并安装依赖
- 生成 `wechat_qr_server/config.json`
- 写入 `/etc/wechat-qr-server.env`（保存 token）
- 写入 `wechat-qr-server.service` 并启动
- 生成 `/etc/caddy/Caddyfile` 并 reload

---

## 3) 常用运维命令

```bash
# 服务启动/停止/重启
sudo systemctl start wechat-qr-server
sudo systemctl stop wechat-qr-server
sudo systemctl restart wechat-qr-server

# 查看状态
sudo systemctl status wechat-qr-server --no-pager -l
sudo systemctl status caddy --no-pager -l

# 实时日志
sudo journalctl -u wechat-qr-server -f
sudo journalctl -u caddy -f
```

---

## 4) 常见排错

### 4.1 浏览器打不开域名（ERR_CONNECTION_CLOSED）

在服务器本机自检：

```bash
sudo ss -lntp | egrep ':80|:443'
curl -Ik https://你的域名/
curl -I  http://你的域名/
```

如果服务器本机 OK，但外网不行：

- 云安全组是否放行 80/443
- DNS 是否还在传播/缓存
- `dig +short 你的域名` 是否返回正确 IP

### 4.2 HTTPS 证书申请失败

看 Caddy 日志：

```bash
sudo journalctl -u caddy -n 200 --no-pager
```

最常见原因：

- DNS 没指向当前服务器
- 80/443 没放行
- `www.<domain>` 没有 A 记录

---

## 5) 使用说明（多人分组）

访问：

- `https://你的域名/`

流程：

1. 创建多个分组
2. 把 `/g/<group_id>` 链接发给对应成员
3. Discord 来新码后会按分组轮询分发（互不冲突）
4. 各分组点 “下一个（已扫描）” 自动写 CSV

重置分组：

- 首页 “初始化分组（清空所有分组）” 按钮（需要 `reset_password`）


