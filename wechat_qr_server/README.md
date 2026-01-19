# WeChat QR Server（多人分组版）

目标：把 Discord 抓到的微信付款二维码，按“分组”轮询分发给多个人一起处理，**互不冲突**。

- **抓取入库**：`on_message` 抓取并解析二维码条目
- **分组机制**：每个分组有独立面板/独立 CSV/独立状态
- **轮询分发**：新二维码按现有分组 RR 分配（一个二维码只分配给一个分组）
- **启动清空**：服务启动时会删除所有分组（包含落盘目录）

---

## 1) 配置

复制并编辑：

- `wechat_qr_server/config.example.json` → `wechat_qr_server/config.json`

关键字段：

- `discord.source_channel_ids`: 监听的频道ID
- `keywords`: 过滤关键词（你当前本地版是只收 Eximbay QRCodeGenerator weixin）
- `web.host/web.port`: 服务监听地址/端口
- `web.public_base_url`: 可选，用于生成分享链接（例如 `https://pay.example.com`）

Token 建议用环境变量：

```powershell
$env:DISCORD_TOKEN="你的token"
```

---

## 2) 运行（本机/服务器）

在项目根目录：

```powershell
python -m wechat_qr_server
```

打开首页：

- `http://<host>:<port>/`

---

## 3) 使用流程（多人协作）

1. 管理员打开 `/`，创建多个分组（例如 A组/B组/…）
2. 点击“进入”，把分组页面链接 `/g/<group_id>` 发给对应成员
3. Discord 来新支付码后，后台会按分组轮询分发：
   - A 看到第 1 个码
   - B 看到第 2 个码
   - …
4. 每个分组在自己的面板点“下一个（已扫描）”，会写入该分组的 CSV

---

## 4) 公网部署建议

- **直接暴露端口**：在云服务器安全组放行 `web.port`（不推荐长期）
- **推荐反代**：用 Nginx/Caddy 反代到 `127.0.0.1:<port>`，并配 HTTPS


