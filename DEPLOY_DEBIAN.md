# Debian 一键部署（Caddy + HTTPS + systemd）

本仓库包含两套程序：

- `wechat_qr_board/`：本地版工作台（单机使用）
- `wechat_qr_server/`：服务器多人分组版（公网使用）

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

推荐直接在服务器用 GitHub 拉取到目录（示例仓库：`qsc591/qr_server`）：

```bash
sudo apt update && sudo apt install -y git

cd /root
rm -rf dc_cart_site
git clone https://github.com/qsc591/qr_server dc_cart_site
cd /root/dc_cart_site
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

export DISCORD_TOKEN=DCBOT TOKEN

sudo bash scripts/install_debian.sh \
  --domain itpdash.online \
  --channel-ids "你需要监控的频道ID<,>分割" \
  --app-dir /root/dc_cart_site \
  --reset-password "CHANGE_ME"
```

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

#查看当前绑定的 DCBOT TOKEN
sudo cat /etc/wechat-qr-server.env
#更换绑定的TOKEN
#进入这个文件
DISCORD_TOKEN=NEW_TOKEN_HERE（改成新的)


#编辑 检测频道
/root/dc_cart_site/wechat_qr_server/config.json
"source_channel_ids": [1382031606969274422]  方括号内添加 每个,分开

#编辑重置密码 找到
"reset_password": "123123123",


#改完之后 运行
sudo systemctl restart wechat-qr-server
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




