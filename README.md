# github_qr_site（多人扫码分组服务器）

本项目用于：监听 Discord 指定频道里的付款二维码消息，并按“分组”轮询分发给多个成员协作扫码。

目录说明（纯服务器版）：
- `wechat_qr_server/`：服务器端（公网访问、分组管理、轮询分发）
- `wechat_qr_board/`：服务器依赖的解析逻辑 + Board 静态 UI（由服务器嵌入/复用）
- `scripts/install_debian.sh`：Debian 一键安装脚本（Caddy + HTTPS + systemd）
- `docs/DEPLOY_DEBIAN.md`：中文部署文档

## Debian 一键安装（推荐）

请先看：`docs/DEPLOY_DEBIAN.md`

核心命令（示例）：

```bash
export DISCORD_TOKEN="你的Discord Token"

sudo bash scripts/install_debian.sh \
  --domain <你的域名> \
  --channel-ids "<频道ID1,频道ID2,...>" \
  --app-dir /root/github_qr_site \
  --reset-password "CHANGE_ME" \
  --use-user-token false
```

注意：
- `--domain` 和 `--channel-ids` 都必须由操作者按自己的环境填写，不能固定写死。


