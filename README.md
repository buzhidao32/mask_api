# 今日面具 API

一个零框架 Python HTTP API，用固定日期和 QQ 号为用户生成“今日面具”，并支持返回面具数据、原始图片和服务器合成卡片图。

## 项目结构

- `server.py`：API 服务入口。
- `masks.json`：面具数据。
- `AttrUI/`：`masks.json` 当前引用的面具图片。
- `fonts/`：合成卡片优先使用的中文字体。
- `今日面具.txt`：Secluded/Sec 词库文件，仅用于机器人发送服务器合成图。
- `mask-api.service.example`：systemd 服务示例。
- `nginx-mask-api.conf.example`：Nginx 反向代理示例。
- `.env.example`：本地私有环境变量模板，不包含真实服务器信息。
- `SERVER_DEPLOY.md`：服务器部署说明。

## 本地运行

```bash
python -m pip install -r requirements.txt
python server.py
```

默认监听：

```text
http://0.0.0.0:8080
```

常用环境变量：

- `MASK_API_HOST`：监听地址，默认 `0.0.0.0`。
- `MASK_API_PORT`：监听端口，默认 `8080`。
- `MASK_PUBLIC_BASE_URL`：返回给客户端的公网基础地址。
- `MASK_API_ACCESS_LOG`：设为 `1` 时开启访问日志。
- `MASK_CARD_RENDER_SCALE`：卡片渲染倍率，支持 `1` 到 `3`。

真实服务器 IP、域名和 SSH 地址不要写进仓库。需要本地记录时可以复制 `.env.example` 为 `.env.local`，`.env.local` 已被 `.gitignore` 忽略。

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

`/api/masks/today` 和 `/card/today.png` 使用 Asia/Shanghai 日期；同一个 `qq` 在同一天固定返回同一个面具。

## 部署

服务器部署步骤见 [SERVER_DEPLOY.md](SERVER_DEPLOY.md)。
