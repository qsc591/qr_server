# WeChat QR Board（Discord 抓取 + 扫码工作台）

这个工具会监听 Discord 指定频道的新消息，**当 embed/text 中命中 wechat 相关关键词时**，抓取消息里的二维码图片 URL，并在本地提供一个工作台页面：

- **左侧**：位置/座位列表 + 6分55秒倒计时 + 状态（未扫描/已扫描）
- **右侧**：当前二维码 + 账号信息 + Discord 消息链接 + **Next** 按钮
- 点击 **Next**：写入 CSV（时间、位置、消息链接），并把该位置标记为 **已扫描（绿色）**

> 说明：若你使用 **User Token**，需要 `discord.py==1.7.3`（仓库里已有 `FIX_DISCORD_PY.md` 说明）。

---

## 1) 配置

复制一份配置：

- 直接编辑：`wechat_qr_board/config.json`

然后填：

- `discord.token`: 建议留空，改用环境变量 `DISCORD_TOKEN`
- `discord.use_user_token`: `true`（用用户 token）或 `false`（用 bot token）
- `discord.source_channel_ids`: 需要监听的频道 ID 列表
- `keywords`: 关键词（默认示例是 `payment exported` + `wechat`，你也可以改成 `wechat/weixin/微信` 等）
- `countdown_seconds`: 默认 `415`（6分55秒）
- `web.port`: 本地端口
- `seats`: 可选。预先写死座位列表（左侧会提前显示所有位置，即使还没抓到码）

---

## 2) 运行

在项目根目录执行：

```bash
set DISCORD_TOKEN=你的token
python -m wechat_qr_board.main
```

启动后访问：

- `http://127.0.0.1:<port>/`

CSV 输出默认在：

- `wechat_qr_board/data/scan_log.csv`

状态文件默认在：

- `wechat_qr_board/data/state.json`

页面右下角可以直接点 **下载CSV**（对应 `/api/csv`）。


