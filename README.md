# WeChat QR Server (GitHub clean)


旧版本更新 方法
```
cd /root/dc_cart_site

# 1) 停服务
sudo systemctl stop wechat-qr-server

# 2) 拉新分支代码
sudo apt update && sudo apt install -y git
git fetch origin
git checkout ttm_tsp || git checkout -b ttm_tsp origin/ttm_tsp
git pull

# 3) 重新装依赖（用新 requirements.txt）
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
deactivate

# 4) 重启服务
sudo systemctl restart wechat-qr-server
sudo systemctl status wechat-qr-server --no-pager -l
```












这个目录是从主工程里抽出来的 **纯净可上传 GitHub** 版本，只保留运行所需的三部分：

- `wechat_qr_server/`：Discord 监听 + 分组管理 + Web UI（包含 TTM/Alipay 支持）
- `wechat_qr_board/`：单个分组的看板 UI（被 server 以 iframe 方式复用）
- `login/`：T-Splash export → 2C2P PGW → Alipay 跳转/抓码（最小依赖版）

## 运行环境（Linux）

- Python 3.10+（推荐 3.11）

## 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

如果你创建 TTM 分组时开启了“读取支付宝二维码”，需要安装 Playwright 浏览器：

```bash
python -m playwright install chromium
```

（关闭该开关则不会抓码，只提供 `MPaymentProcess.aspx?...` 跳转链接。）

## 配置

复制示例配置并编辑：

```bash
cp wechat_qr_server/config.example.json wechat_qr_server/config.json
```

配置项重点：

- `discord.source_channel_ids`：监听的频道 ID 列表
- `reset_password`：用于初始化/删除分组的管理密码
- `web.host` / `web.port`：Web 服务监听地址
- `web.public_base_url`：可选，用于生成对外分享链接
- `data_dir`：运行数据目录（默认 `data`，会自动创建）

Discord Token 建议用环境变量（避免写进配置/提交到 GitHub）：

```bash
export DISCORD_TOKEN="YOUR_TOKEN"
```

## 启动

在项目根目录运行：

```bash
python -m wechat_qr_server
```

启动后：

- 管理页：`http://127.0.0.1:17889/`
- 进入分组后，可在左上角下载 CSV（TTM 分组会显示“下载TTM订单CSV”）

## GitHub 提示

- 不要提交 `wechat_qr_server/config.json`（已在 `.gitignore` 忽略）
- 不要提交运行数据目录 `data/`

