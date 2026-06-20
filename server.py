#!/usr/bin/env python3
import hashlib
import io
import json
import mimetypes
import os
import posixpath
import random
from datetime import datetime
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zoneinfo import ZoneInfo

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "masks.json"
SCORE_DATA_FILE = ROOT / "mask_scores.json"
ATTR_UI_DIR = ROOT / "AttrUI"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8080"

FONT_TITLE_CANDIDATES = (
    str(ROOT / "fonts" / "ZhiMangXing-Regular.ttf"),
    str(ROOT / "fonts" / "MaShanZheng-Regular.ttf"),
    str(ROOT / "fonts" / "LongCang-Regular.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/system/fonts/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/STZHONGS.TTF",
    "C:/Windows/Fonts/simsunb.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/Dengb.ttf",
)
FONT_DESC_CANDIDATES = (
    str(ROOT / "fonts" / "MaShanZheng-Regular.ttf"),
    str(ROOT / "fonts" / "ZCOOLXiaoWei-Regular.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/STSONG.TTF",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/Deng.ttf",
)


class MissingImageDependency(RuntimeError):
    pass


def load_masks():
    if not DATA_FILE.is_file():
        raise RuntimeError(f"Missing mask data file: {DATA_FILE}")

    raw_json = DATA_FILE.read_text(encoding="utf-8").strip()

    masks = json.loads(raw_json)
    if not isinstance(masks, list) or not masks:
        raise RuntimeError("Mask data must be a non-empty JSON array")

    seen_ids = set()
    for mask in masks:
        for key in ("id", "name", "description", "image"):
            if not mask.get(key):
                raise RuntimeError(f"Mask record missing {key}: {mask!r}")

        mask["id"] = str(mask["id"]).strip()
        mask["name"] = str(mask["name"]).strip()
        mask["description"] = "".join(str(mask["description"]).split())
        mask["image"] = str(mask["image"]).replace("\\", "/").strip()

        if mask["id"] in seen_ids:
            raise RuntimeError(f"Duplicate mask id: {mask['id']}")
        seen_ids.add(mask["id"])

        image_path = safe_image_path(mask["image"])
        if not image_path.is_file():
            raise RuntimeError(f"Missing image for {mask['id']}: {mask['image']}")

    return masks


def load_score_data():
    """加载面具分数数据，返回 (masks_dict, achievements_dict)"""
    if not SCORE_DATA_FILE.is_file():
        return {}, {}

    raw_json = SCORE_DATA_FILE.read_text(encoding="utf-8").strip()
    data = json.loads(raw_json)

    # 构建面具名字到面具数据的索引（支持 allNames）
    masks_dict = {}
    for mask in data.get("masks", []):
        for name in mask.get("allNames", []):
            masks_dict[name] = mask

    # 构建称号名字到称号数据的索引
    achievements_dict = {}
    for ach in data.get("achievements", []):
        achievements_dict[ach["achievement"]] = ach

    return masks_dict, achievements_dict


def query_score(query, masks_dict, achievements_dict):
    """查询面具或称号分数，返回结果列表"""
    results = []

    # 解析查询类型
    query = query.strip()
    if not query:
        return results

    search_type = None
    search_name = query

    if query.startswith("面具"):
        search_type = "mask"
        search_name = query[2:].strip()
    elif query.startswith("称号"):
        search_type = "achievement"
        search_name = query[2:].strip()

    if not search_name:
        return results

    # 搜索面具
    if search_type in (None, "mask"):
        mask = masks_dict.get(search_name)
        if mask:
            direct_point = mask.get("directPoint", 0)
            achievement_name = ""
            if mask.get("directAchievement"):
                achievement_name = mask["directAchievement"].get("achievement", "")
            results.append({
                "type": "mask",
                "name": mask["maskName"],
                "point": direct_point,
                "achievement": achievement_name,
            })

    # 搜索称号
    if search_type in (None, "achievement"):
        ach = achievements_dict.get(search_name)
        if ach:
            results.append({
                "type": "achievement",
                "name": ach["achievement"],
                "point": ach.get("point", 0),
                "demandNames": ach.get("demandNames", []),
            })

    return results


def safe_image_path(relative_path):
    normalized = posixpath.normpath(unquote(relative_path).replace("\\", "/"))
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise ValueError("Invalid image path")

    image_path = (ATTR_UI_DIR / normalized).resolve()
    attr_root = ATTR_UI_DIR.resolve()
    if image_path != attr_root and attr_root not in image_path.parents:
        raise ValueError("Invalid image path")
    return image_path


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def today_yyyymmdd():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def re_date(value):
    return len(value) == 8 and value.isdigit()


def select_today_mask(masks, qq, date):
    digest = hashlib.sha256(f"{date}:{qq}".encode("utf-8")).digest()
    index = int.from_bytes(digest[:8], "big") % len(masks)
    return index, masks[index]


def load_font(candidates, size):
    if ImageFont is None:
        raise MissingImageDependency("Pillow is not installed")

    for path in candidates:
        if not Path(path).is_file():
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=64)
def font_codepoints(path):
    if TTFont is None:
        return None

    try:
        font = TTFont(path, fontNumber=0, lazy=True)
        codepoints = set()
        for table in font["cmap"].tables:
            codepoints.update(table.cmap.keys())
        font.close()
        return frozenset(codepoints)
    except Exception:
        return None


def font_supports_text(path, text):
    codepoints = font_codepoints(path)
    if codepoints is None:
        return True
    return all((char.isspace() or ord(char) in codepoints) for char in text)


def load_font_for_text(candidates, size, text):
    if ImageFont is None:
        raise MissingImageDependency("Pillow is not installed")

    for path in candidates:
        if not Path(path).is_file() or not font_supports_text(path, text):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return load_font(candidates, size)


def text_size(draw, text, font):
    if not text:
        return 0, 0
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def wrap_text(draw, text, font, max_width, max_lines):
    lines = []
    line = ""
    for char in text:
        if char in "\r\n":
            if line:
                lines.append(line)
                line = ""
            continue

        candidate = line + char
        width, _ = text_size(draw, candidate, font)
        if line and width > max_width:
            lines.append(line)
            line = char.strip()
            if len(lines) >= max_lines:
                break
        else:
            line = candidate

    if line and len(lines) < max_lines:
        lines.append(line)

    if len(lines) == max_lines:
        last = lines[-1]
        if len("".join(lines)) < len(text):
            while last and text_size(draw, last + "...", font)[0] > max_width:
                last = last[:-1]
            lines[-1] = f"{last}..."

    return lines


def draw_centered_text(draw, text, y, font, fill, width=720, stroke_width=0):
    text_width, _ = text_size(draw, text, font)
    x = max(0, (width - text_width) // 2)
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=fill)


def draw_left_aligned_block(draw, lines, y, font, fill, max_width, canvas_width=720, line_height=36, stroke_width=0):
    line_widths = [text_size(draw, line, font)[0] for line in lines]
    block_width = min(max_width, max(line_widths, default=max_width))
    block_x = max(0, (canvas_width - block_width) // 2)
    for idx, line in enumerate(lines):
        draw.text(
            (block_x, y + idx * line_height),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=fill,
        )


def render_card(mask):
    if Image is None or ImageDraw is None or ImageFont is None:
        raise MissingImageDependency("Pillow is not installed")

    render_scale = int(os.environ.get("MASK_CARD_RENDER_SCALE", "2"))
    render_scale = max(1, min(render_scale, 3))
    canvas_width = 720 * render_scale
    canvas_height = 720 * render_scale
    card = Image.new("RGBA", (canvas_width, canvas_height), (255, 255, 255, 255))

    mask_image = Image.open(safe_image_path(mask["image"])).convert("RGBA")
    alpha_bbox = mask_image.getchannel("A").getbbox()
    if alpha_bbox:
        mask_image = mask_image.crop(alpha_bbox)

    max_image_width = 430 * render_scale
    max_image_height = 315 * render_scale
    scale = min(max_image_width / mask_image.width, max_image_height / mask_image.height)
    image_width = max(1, int(mask_image.width * scale))
    image_height = max(1, int(mask_image.height * scale))
    resampling = getattr(Image, "Resampling", Image)
    resample_lanczos = getattr(resampling, "LANCZOS", getattr(Image, "LANCZOS", 1))
    mask_image = mask_image.resize((image_width, image_height), resample_lanczos)

    image_x = (canvas_width - image_width) // 2
    image_y = 72 * render_scale + (max_image_height - image_height) // 2
    card.alpha_composite(mask_image, (image_x, image_y))

    draw = ImageDraw.Draw(card)
    title_font = load_font_for_text(FONT_TITLE_CANDIDATES, 62 * render_scale, mask["name"])
    title_fallback_font = load_font_for_text(FONT_DESC_CANDIDATES, 62 * render_scale, mask["name"])
    desc_color = (51, 51, 51, 255)
    title_color = (17, 17, 17, 255)

    try:
        draw_centered_text(
            draw,
            mask["name"],
            395 * render_scale,
            title_font,
            title_color,
            canvas_width,
            stroke_width=1 * render_scale,
        )
    except UnicodeEncodeError:
        draw_centered_text(
            draw,
            mask["name"],
            395 * render_scale,
            title_fallback_font,
            title_color,
            canvas_width,
            stroke_width=1 * render_scale,
        )

    desc_top = 472 * render_scale
    max_desc_width = 600 * render_scale
    desc_font = None
    desc_lines = []
    line_height = 36
    for size in (32, 31, 30, 29, 28, 27, 26):
        candidate_size = size * render_scale
        candidate_font = load_font_for_text(FONT_DESC_CANDIDATES, candidate_size, mask["description"])
        candidate_line_height = candidate_size + 10 * render_scale
        candidate_lines = wrap_text(draw, mask["description"], candidate_font, max_desc_width, 7)
        if desc_top + len(candidate_lines) * candidate_line_height <= 696 * render_scale:
            desc_font = candidate_font
            desc_lines = candidate_lines
            line_height = candidate_line_height
            break

    if desc_font is None:
        desc_font = load_font_for_text(FONT_DESC_CANDIDATES, 26 * render_scale, mask["description"])
        desc_lines = wrap_text(draw, mask["description"], desc_font, max_desc_width, 7)
        line_height = 36 * render_scale

    draw_left_aligned_block(
        draw,
        desc_lines,
        desc_top,
        desc_font,
        desc_color,
        max_desc_width,
        canvas_width,
        line_height,
        stroke_width=0,
    )

    output = io.BytesIO()
    card.convert("RGB").save(output, "PNG", optimize=True)
    return output.getvalue()


class MaskApiHandler(BaseHTTPRequestHandler):
    server_version = "MaskApi/1.2"

    def parse_request(self):
        """重写parse_request以支持UTF-8 URL"""
        try:
            raw_line = self.rfile.readline(65537)
            if len(raw_line) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return False
            # 用UTF-8解码请求行
            try:
                self.requestline = raw_line.decode('utf-8').strip()
            except UnicodeDecodeError:
                self.requestline = raw_line.decode('latin-1').strip()
            words = self.requestline.split()
            if len(words) == 3:
                self.command, self.path, self.request_version = words
            elif len(words) == 2:
                self.command, self.path = words
                self.request_version = 'HTTP/0.9'
            else:
                return False
            # 继续解析headers
            self.parse_headers()
            return True
        except Exception:
            return False

    def log_message(self, fmt, *args):
        if os.environ.get("MASK_API_ACCESS_LOG", "0") == "1":
            super().log_message(fmt, *args)

    @property
    def masks(self):
        return self.server.masks

    @property
    def masks_by_id(self):
        return self.server.masks_by_id

    @property
    def public_base_url(self):
        return self.server.public_base_url

    @property
    def score_masks(self):
        return self.server.score_masks

    @property
    def score_achievements(self):
        return self.server.score_achievements

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_png(self, body, cache_control="no-store"):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"ok": False, "error": message}, status)

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path.startswith("/images/"):
                image = path.removeprefix("/images/")
                return self.handle_image(image, send_body=False)
        except ValueError:
            pass

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/":
                return self.handle_index()
            if path == "/health":
                return self.send_json({"ok": True, "count": len(self.masks)})
            if path == "/api/masks":
                return self.send_json({"ok": True, "count": len(self.masks), "data": self.with_urls(self.masks)})
            if path == "/api/masks/random":
                return self.send_json({"ok": True, "data": self.with_url(random.choice(self.masks))})
            if path == "/api/masks/today":
                return self.handle_today(query)
            if path == "/api/score":
                return self.handle_score(query)
            if path == "/api/score/text":
                return self.handle_score_text(query)
            if path in ("/card/random.png", "/api/card/random.png"):
                return self.handle_card(random.choice(self.masks))
            if path in ("/card/today.png", "/api/card/today.png"):
                return self.handle_card_today(query)
            if path.startswith("/card/masks/") and path.endswith(".png"):
                mask_id = unquote(path.removeprefix("/card/masks/").removesuffix(".png"))
                return self.handle_card_mask(mask_id)
            if path.startswith("/api/masks/"):
                mask_id = unquote(path.removeprefix("/api/masks/"))
                return self.handle_mask(mask_id)
            if path.startswith("/images/"):
                image = path.removeprefix("/images/")
                return self.handle_image(image)
        except ValueError as exc:
            return self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except BrokenPipeError:
            return

        return self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def handle_index(self):
        return self.send_json(
            {
                "ok": True,
                "name": "mask-api",
                "count": len(self.masks),
                "routes": [
                    "/health",
                    "/api/masks",
                    "/api/masks/random",
                    "/api/masks/today?qq=123456",
                    "/api/masks/{id}",
                    "/api/score?name=面具嫦娥",
                    "/images/{relative_png_path}",
                    "/card/random.png",
                    "/card/today.png?qq=123456",
                    "/card/masks/{id}.png",
                ],
            }
        )

    def handle_today(self, query):
        qq = (query.get("qq") or query.get("user") or [""])[0].strip()
        if not qq:
            return self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing qq query, example: /api/masks/today?qq=123456")

        date = (query.get("date") or [today_yyyymmdd()])[0].strip()
        if not re_date(date):
            return self.send_error_json(HTTPStatus.BAD_REQUEST, "date must be YYYYMMDD")

        index, mask = select_today_mask(self.masks, qq, date)
        return self.send_json({"ok": True, "date": date, "qq": qq, "index": index, "data": self.with_url(mask)})

    def handle_mask(self, mask_id):
        mask = self.masks_by_id.get(mask_id)
        if not mask:
            return self.send_error_json(HTTPStatus.NOT_FOUND, f"Unknown mask id: {mask_id}")
        return self.send_json({"ok": True, "data": self.with_url(mask)})

    def handle_score(self, query):
        name = (query.get("name") or [""])[0].strip()
        if not name:
            return self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Missing name query, example: /api/score?name=面具嫦娥 or /api/score?name=称号广寒上仙"
            )

        results = query_score(name, self.score_masks, self.score_achievements)
        if not results:
            return self.send_json({"ok": True, "query": name, "results": [], "message": f"未找到：{name}"})

        return self.send_json({"ok": True, "query": name, "results": results})

    def handle_score_text(self, query):
        name = (query.get("name") or [""])[0].strip()
        if not name:
            return self.send_text_response("请输入：面具xxx 或 称号xxx")

        # 确保中文正确解码
        name = unquote(name)

        results = query_score(name, self.score_masks, self.score_achievements)
        if not results:
            return self.send_text_response(f"未找到：{name}")

        lines = []
        for r in results:
            if r["type"] == "mask":
                lines.append(f"面具【{r['name']}】分数：{r['point']}")
                if r.get("achievement"):
                    lines.append(f"对应称号：{r['achievement']}")
            elif r["type"] == "achievement":
                lines.append(f"称号【{r['name']}】分数：{r['point']}")
                if r.get("demandNames"):
                    lines.append(f"需要面具：{'、'.join(r['demandNames'])}")

        return self.send_text_response("\n".join(lines))

    def send_text_response(self, text):
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_card_today(self, query):
        qq = (query.get("qq") or query.get("user") or ["default"])[0].strip() or "default"
        date = (query.get("date") or [today_yyyymmdd()])[0].strip()
        if not re_date(date):
            return self.send_error_json(HTTPStatus.BAD_REQUEST, "date must be YYYYMMDD")
        _, mask = select_today_mask(self.masks, qq, date)
        return self.handle_card(mask)

    def handle_card_mask(self, mask_id):
        mask = self.masks_by_id.get(mask_id)
        if not mask:
            return self.send_error_json(HTTPStatus.NOT_FOUND, f"Unknown mask id: {mask_id}")
        return self.handle_card(mask, cache_control="public, max-age=3600")

    def handle_card(self, mask, cache_control="no-store"):
        try:
            body = render_card(mask)
        except MissingImageDependency:
            return self.send_error_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "Pillow is not installed. Run: python -m pip install -r requirements.txt",
            )
        return self.send_png(body, cache_control=cache_control)

    def handle_image(self, relative_path, send_body=True):
        image_path = safe_image_path(relative_path)
        if not image_path.is_file():
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if send_body:
                self.wfile.write("Image not found".encode("utf-8"))
            return

        content_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
        stat = image_path.stat()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(stat.st_size))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        if not send_body:
            return
        with image_path.open("rb") as fp:
            while chunk := fp.read(1024 * 128):
                self.wfile.write(chunk)

    def with_url(self, mask):
        item = dict(mask)
        item["image_url"] = f"{self.public_base_url}/images/{quote(item['image'])}"
        item["card_url"] = f"{self.public_base_url}/card/masks/{quote(item['id'])}.png"
        return item

    def with_urls(self, masks):
        return [self.with_url(mask) for mask in masks]


def main():
    host = os.environ.get("MASK_API_HOST", DEFAULT_HOST)
    port = int(os.environ.get("MASK_API_PORT", DEFAULT_PORT))
    public_base_url = os.environ.get("MASK_PUBLIC_BASE_URL", DEFAULT_PUBLIC_BASE_URL).rstrip("/")

    masks = load_masks()
    score_masks, score_achievements = load_score_data()

    server = ThreadingHTTPServer((host, port), MaskApiHandler)
    server.masks = masks
    server.masks_by_id = {mask["id"]: mask for mask in masks}
    server.public_base_url = public_base_url
    server.score_masks = score_masks
    server.score_achievements = score_achievements

    print(f"mask-api listening on http://{host}:{port}")
    print(f"loaded masks: {len(masks)}")
    print(f"loaded score masks: {len(score_masks)}, achievements: {len(score_achievements)}")
    print(f"public base url: {public_base_url}")
    server.serve_forever()


if __name__ == "__main__":
    main()
