# Debian 一键部署（Caddy + HTTPS + systemd）

本仓库包含三部分：

- `wechat_qr_server/`：服务器多人分组版（公网使用）
- `wechat_qr_board/`：分组工作台（被 server 复用）
- `login/`：TTM/2C2P/Alipay 转换逻辑

本文档讲 **Debian 服务器 + Caddy + HTTPS** 的最简单部署方式。

---

## 0) 前置条件

- 你有一个域名（示例：`itpdash.online`）
- DNS A 记录指向服务器公网 IP（建议同时配置 `@` 和 `www`）
- 防火墙放行：TCP 80、TCP 443

---

## 1) 拉取代码（ttm_tsp 分支）

```bash
sudo apt update && sudo apt install -y git

cd /root
rm -rf dc_cart_site
git clone -b ttm_tsp --single-branch https://github.com/qsc591/qr_server dc_cart_site
cd /root/dc_cart_site
```

要求目录下至少存在：

- `wechat_qr_server/`
- `wechat_qr_board/`
- `login/`
- `scripts/install_debian.sh`

---

## 2) 一键安装（推荐）

```bash
chmod +x scripts/install_debian.sh

export DISCORD_TOKEN="你的token"

sudo bash scripts/install_debian.sh \
  --domain itpdash.online \
  --channel-ids "1374797975452127332,1381707134164668526" \
  --app-dir /root/dc_cart_site \
  --reset-password "CHANGE_ME"
```

脚本会：

- 安装 Caddy（官方源）
- 创建 Python venv 并安装 `requirements.txt`
- 生成 `wechat_qr_server/config.json`
- 写入 `/etc/wechat-qr-server.env`（保存 token）
- 写入 `wechat-qr-server.service` 并启动
- 生成 `/etc/caddy/Caddyfile` 并 reload

---

## 3) Playwright（可选）

如果你创建 TTM 分组时开启了“读取支付宝二维码”，建议安装浏览器：

```bash
sudo -H bash -lc 'source /root/dc_cart_site/.venv/bin/activate && python -m playwright install chromium'
```

注意：即使不安装 Playwright，系统也会自动降级为 **只输出 `MPaymentProcess.aspx?...` 跳转链接**，不影响基本使用。

---

## 4) 常用运维命令

```bash
sudo systemctl restart wechat-qr-server
sudo systemctl status wechat-qr-server --no-pager -l
sudo journalctl -u wechat-qr-server -f

sudo systemctl status caddy --no-pager -l
sudo journalctl -u caddy -f
```

