# 今日面具 API 部署

## 本地文件

需要上传整个 `mask-api` 目录，API 运行至少包含：

- `server.py`
- `masks.json`
- `AttrUI/`
- `fonts/`
- `requirements.txt`

接口读取 `masks.json`，图片从 `AttrUI` 读取，卡片字体优先使用 `fonts/` 里的开源字体。`今日面具.txt` 只负责在 Sec 里发送服务器合成好的图片，不是 API 运行必需文件。

## 服务器部署

以下命令在 Ubuntu 22.04 上执行。

文档里的 `root@your-server`、`your-domain.example` 都是占位符。真实服务器 IP、域名或 SSH 地址只在你本机命令行、服务器配置文件里替换，不要提交到 GitHub。

```bash
sudo apt update
sudo apt install -y python3 python3-pip fonts-noto-cjk nginx
sudo mkdir -p /opt/mask-api
```

把本目录上传到服务器：

```powershell
scp -r "D:\Desktop\fzjh_backup\Special_Package\mask-api\*" root@your-server:/opt/mask-api/
```

安装 Python 依赖：

```bash
sudo python3 -m pip install -r /opt/mask-api/requirements.txt
```

安装 systemd 服务：

```bash
sudo cp /opt/mask-api/mask-api.service.example /etc/systemd/system/mask-api.service
sudo nano /etc/systemd/system/mask-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now mask-api
sudo systemctl status mask-api
```

编辑 `mask-api.service` 时，把 `MASK_PUBLIC_BASE_URL` 的 `http://your-domain.example` 改成你的真实公网访问地址。

配置 Nginx：

```bash
sudo cp /opt/mask-api/nginx-mask-api.conf.example /etc/nginx/sites-available/mask-api
sudo nano /etc/nginx/sites-available/mask-api
sudo ln -sf /etc/nginx/sites-available/mask-api /etc/nginx/sites-enabled/mask-api
sudo nginx -t
sudo systemctl reload nginx
```

编辑 Nginx 配置时，把 `server_name your-domain.example;` 改成你的真实域名；如果直接用 IP 访问，可以把 `server_name` 改成 `_`。

如果防火墙开启了 UFW：

```bash
sudo ufw allow 80/tcp
```

## 已经部署过时更新

```powershell
scp "D:\Desktop\fzjh_backup\Special_Package\mask-api\server.py" root@your-server:/opt/mask-api/
scp "D:\Desktop\fzjh_backup\Special_Package\mask-api\masks.json" root@your-server:/opt/mask-api/
scp "D:\Desktop\fzjh_backup\Special_Package\mask-api\今日面具.txt" root@your-server:/opt/mask-api/
scp "D:\Desktop\fzjh_backup\Special_Package\mask-api\requirements.txt" root@your-server:/opt/mask-api/
scp -r "D:\Desktop\fzjh_backup\Special_Package\mask-api\fonts" root@your-server:/opt/mask-api/
```

服务器上执行：

```bash
sudo apt update
sudo apt install -y python3-pip fonts-noto-cjk
sudo python3 -m pip install -r /opt/mask-api/requirements.txt
sudo systemctl restart mask-api
sudo systemctl status mask-api
```

## 测试

```bash
curl http://your-domain.example/health
curl "http://your-domain.example/api/masks/today?qq=123456"
curl http://your-domain.example/api/masks/random
curl -I "http://your-domain.example/card/today.png?qq=123456"
curl -I "http://your-domain.example/images/mianju/guojing.png"
```

浏览器直接打开：

```text
http://your-domain.example/card/today.png?qq=123456
```

## 预览验收约定

以后调整卡片排版、字体、图片大小时，统一用“描述最长”和“描述最短”两张图一起预览，避免只看中等长度描述导致上线后挤压或留白不好看。

- 描述最长：`mianju1189`，`绣女`，`mianju/xiunv2.png`，描述长度 100。
- 描述最短：`mianju1008`，`郭小姐`，`mianju/guoxiang.png`，描述长度 9。

服务器预览地址：

```text
http://your-domain.example/card/masks/mianju1189.png
http://your-domain.example/card/masks/mianju1008.png
```

本地生成预览图：

```powershell
@'
import server
masks = {m["id"]: m for m in server.load_masks()}
for mask_id, filename in (
    ("mianju1189", "preview-longest.png"),
    ("mianju1008", "preview-shortest.png"),
):
    with open(filename, "wb") as fp:
        fp.write(server.render_card(masks[mask_id]))
'@ | python -
```

## API

- `GET /health`
- `GET /api/masks`
- `GET /api/masks/random`
- `GET /api/masks/today?qq=123456`
- `GET /api/masks/{id}`
- `GET /images/{image_path}`
- `GET /card/random.png`
- `GET /card/today.png?qq=123456`
- `GET /card/masks/{id}.png`

`/api/masks/today` 和 `/card/today.png` 都使用 Asia/Shanghai 日期，同一个 `qq` 同一天固定返回同一个面具。

## Sec 词库

`今日面具.txt` 现在只发成品图：

```text
http://your-domain.example/card/today.png?qq=%QQ%
```

这样不再使用手机本地 `$画布 ... 文字 ...$`，可以避开长描述和图片缩放导致的 LexInterpreter 报错。
