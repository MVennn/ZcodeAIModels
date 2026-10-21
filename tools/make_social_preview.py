#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染 assets/icon.svg → assets/logo.png（512×512）与 assets/social-preview.png（1280×640）。

为什么自己写 SVG 渲染器：门面资源要能随仓重生成，不能依赖本机装了 cairosvg / Inkscape。
这里只实现 icon.svg 用到的那一小撮 SVG 特性（渐变、圆角矩形、路径、二次/三次贝塞尔、
多边形、圆、文本），换 logo 时只改 SVG 一处，PNG 与 social preview 永远同源。

视觉语言照 GoldSunEnhance（GitHub 仓 GSAuxiliary）的 assets/social-preview.png：
深色渐变底 + 左侧 logo 方块 + 右侧标题/副标题/胶囊 + 右下角标语 + 右侧极淡的图形水印。

用法：
    python tools/make_social_preview.py                 # 写 assets/logo.png 与 assets/social-preview.png
    python tools/make_social_preview.py --ico            # 额外写 assets/icon.ico
    python tools/make_social_preview.py --preview-only  # 只写 social-preview.png
"""
from __future__ import annotations

import math
import os
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

SVG_NS = "{http://www.w3.org/2000/svg}"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_SVG = os.path.join(ROOT, "assets", "icon.svg")
LOGO_PNG = os.path.join(ROOT, "assets", "logo.png")
PREVIEW_PNG = os.path.join(ROOT, "assets", "social-preview.png")

# ---------------------------------------------------------------- 门面文案
# 标题、副标题、标语、胶囊标签 —— 改这里就能改门面，不必动渲染代码。
BRAND = {
    "title": "ZcodeAIModels",
    "subtitle": "把模型供应商接进 ZCode 客户端的脚本与文档",
    "tagline": "不改 ZCode 的代码，只写它的配置文件。",
    "pills": ["Python 3", "Node.js 18+", "MIT"],
}

# ---------------------------------------------------------------- 配色
BG_TOP = (43, 50, 66)      # #2B3242
BG_BOT = (22, 26, 34)      # #161A22
ACCENT = (255, 159, 69)
TITLE_C = (245, 247, 251)
SUB_C = (163, 172, 190)
PILL_C = (206, 213, 225)
PILL_FILL = (255, 255, 255, 12)
PILL_LINE = (210, 216, 228, 70)

PREVIEW_W, PREVIEW_H = 1280, 640
SS = 2  # 超采样倍数

# ---------------------------------------------------------------- 字体
FONT_DIR = os.environ.get("WINDIR", r"C:\Windows") + os.path.sep + "Fonts"
FONTS = {
    ("sans", False): ["segoeui.ttf", "DejaVuSans.ttf"],
    ("sans", True): ["segoeuib.ttf", "DejaVuSans-Bold.ttf"],
    ("cjk", False): ["msyh.ttc", "msyhl.ttc", "NotoSansCJK-Regular.ttc"],
    ("cjk", True): ["msyhbd.ttc", "msyh.ttc", "NotoSansCJK-Bold.ttc"],
}


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def load_font(size: int, bold: bool = False, cjk: bool = False):
    for name in FONTS[("cjk" if cjk else "sans", bold)]:
        path = os.path.join(FONT_DIR, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    for base in ("/usr/share/fonts/truetype/dejavu", "/System/Library/Fonts"):
        for name in FONTS[("cjk" if cjk else "sans", bold)]:
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- SVG 解析
def parse_color(value):
    if value is None:
        return None
    value = value.strip()
    if value in ("none", "transparent"):
        return None
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) < 6:
            return None
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    if value.startswith("rgb"):
        nums = re.findall(r"[\d.]+", value)
        if len(nums) < 3:
            return None
        r, g, b = (int(float(n)) for n in nums[:3])
        a = int(float(nums[3]) * 255) if len(nums) > 3 else 255
        return (r, g, b, a)
    return None


def parse_gradients(root):
    grads = {}
    for el in root.iter(SVG_NS + "linearGradient"):
        gid = el.get("id")
        if not gid:
            continue
        x1, y1 = float(el.get("x1", 0)), float(el.get("y1", 0))
        x2, y2 = float(el.get("x2", 1)), float(el.get("y2", 0))
        stops = []
        for stop in el.findall(SVG_NS + "stop"):
            off = float(stop.get("offset", 0))
            col = parse_color(stop.get("stop-color", "#000")) or (0, 0, 0, 255)
            op = stop.get("stop-opacity")
            if op is not None:
                col = (col[0], col[1], col[2], int(col[3] * float(op)))
            stops.append((off, col))
        stops.sort(key=lambda s: s[0])
        if stops:
            grads[gid] = (x1, y1, x2, y2, stops)
    return grads


def gradient_image(size, grad, scale):
    x1, y1, x2, y2, stops = grad
    x1, y1, x2, y2 = x1 * scale, y1 * scale, x2 * scale, y2 * scale
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    dx, dy = x2 - x1, y2 - y1
    den = dx * dx + dy * dy
    t = np.zeros((h, w)) if den == 0 else np.clip(((xs - x1) * dx + (ys - y1) * dy) / den, 0, 1)
    offs = np.array([s[0] for s in stops], dtype=float)
    out = np.zeros((h, w, 4), dtype=np.float64)
    for i in range(4):
        out[:, :, i] = np.interp(t, offs, np.array([s[1][i] for s in stops], dtype=float))
    return Image.fromarray(out.astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- path 解析
_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


def parse_path(d):
    """'M10 20 L30 40' → [('M',[10,20]), ('L',[30,40])]"""
    out, cmd, nums, i, n = [], None, [], 0, len(d)
    while i < n:
        ch = d[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if ch.isalpha():
            if cmd is not None:
                out.append((cmd, nums))
            cmd, nums = ch, []
            i += 1
            continue
        m = _NUM.match(d, i)
        if not m:
            raise ValueError("无法解析 path 数据：%r" % d[i:i + 24])
        nums.append(float(m.group()))
        i = m.end()
    if cmd is not None:
        out.append((cmd, nums))
    return out


def _quad(p0, p1, p2, steps):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def _cubic(p0, p1, p2, p3, steps):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _arc_points(p0, p1, rx, ry, phi_deg, large_arc, sweep, steps=24):
    """SVG 椭圆弧（端点参数化 -> 中心参数化 -> 拆成 <=90 度的三次贝塞尔）。"""
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large_arc == sweep:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2.0

    def _angle(ux, uy, vx, vy):
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / n))) if n else 0.0
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    def _pt(t):
        return (cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p,
                cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p)

    def _deriv(t):
        return (-rx * math.sin(t) * cos_p - ry * math.cos(t) * sin_p,
                -rx * math.sin(t) * sin_p + ry * math.cos(t) * cos_p)

    out = []
    segs = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    delta = dtheta / segs
    for k in range(segs):
        t0 = theta1 + k * delta
        t1 = t0 + delta
        alpha = 4.0 / 3.0 * math.tan(delta / 4.0)
        p0, p1 = _pt(t0), _pt(t1)
        d0, d1 = _deriv(t0), _deriv(t1)
        c1 = (p0[0] + alpha * d0[0], p0[1] + alpha * d0[1])
        c2 = (p1[0] - alpha * d1[0], p1[1] - alpha * d1[1])
        out.extend(_cubic(p0, c1, c2, p1, steps))
    return out


def path_to_subpaths(d, steps=20):
    """path 数据 → 若干条折线（曲线已按 steps 采样）。"""
    subs, cur, start = [], [], (0.0, 0.0)
    ctrl = None  # 上一个控制点，供 T/S 用
    for cmd, a in parse_path(d):
        up = cmd.upper()
        rel = cmd.islower()
        if up == "M":
            if len(a) < 2:
                continue
            if cur:
                subs.append(cur)
            x, y = a[0], a[1]
            if rel and subs:
                px, py = subs[-1][-1]
                x, y = px + x, py + y
            cur = [(x, y)]
            start = (x, y)
            rest = a[2:]
            for i in range(0, len(rest) - 1, 2):
                x2, y2 = rest[i], rest[i + 1]
                if rel:
                    x2, y2 = cur[-1][0] + x2, cur[-1][1] + y2
                cur.append((x2, y2))
        elif up == "L":
            for i in range(0, len(a) - 1, 2):
                x, y = a[i], a[i + 1]
                if rel:
                    x, y = cur[-1][0] + x, cur[-1][1] + y
                cur.append((x, y))
        elif up == "H":
            for x in a:
                if rel:
                    x += cur[-1][0]
                cur.append((x, cur[-1][1]))
        elif up == "V":
            for y in a:
                if rel:
                    y += cur[-1][1]
                cur.append((cur[-1][0], y))
        elif up == "Q":
            for i in range(0, len(a) - 3, 4):
                x1, y1, x2, y2 = a[i:i + 4]
                if rel:
                    bx, by = cur[-1]
                    x1, y1, x2, y2 = bx + x1, by + y1, bx + x2, by + y2
                cur.extend(_quad(cur[-1], (x1, y1), (x2, y2), steps))
                ctrl = (x1, y1)
        elif up == "T":
            for i in range(0, len(a) - 1, 2):
                x, y = a[i], a[i + 1]
                if rel:
                    x, y = cur[-1][0] + x, cur[-1][1] + y
                p0 = cur[-1]
                if ctrl is None:
                    ctrl = p0
                c = (2 * p0[0] - ctrl[0], 2 * p0[1] - ctrl[1])
                cur.extend(_quad(p0, c, (x, y), steps))
                ctrl = c
        elif up == "C":
            for i in range(0, len(a) - 5, 6):
                x1, y1, x2, y2, x3, y3 = a[i:i + 6]
                if rel:
                    bx, by = cur[-1]
                    x1, y1 = bx + x1, by + y1
                    x2, y2 = bx + x2, by + y2
                    x3, y3 = bx + x3, by + y3
                cur.extend(_cubic(cur[-1], (x1, y1), (x2, y2), (x3, y3), steps))
                ctrl = (x2, y2)
        elif up == "S":
            for i in range(0, len(a) - 3, 4):
                x2, y2, x3, y3 = a[i:i + 4]
                if rel:
                    bx, by = cur[-1]
                    x2, y2 = bx + x2, by + y2
                    x3, y3 = bx + x3, by + y3
                p0 = cur[-1]
                c = (2 * p0[0] - ctrl[0], 2 * p0[1] - ctrl[1]) if ctrl else p0
                cur.extend(_cubic(p0, c, (x2, y2), (x3, y3), steps))
                ctrl = (x2, y2)
        elif up == "A":
            for i in range(0, len(a) - 6, 7):
                rx, ry, rot, laf, sf, x, y = a[i:i + 7]
                if rel:
                    x, y = cur[-1][0] + x, cur[-1][1] + y
                cur.extend(_arc_points(cur[-1], (x, y), rx, ry, rot, int(laf), int(sf)))
                ctrl = None
        elif up == "Z":
            if cur:
                cur.append(start)
                subs.append(cur)
                cur = [start]
            ctrl = None
    if cur and len(cur) > 1:
        subs.append(cur)
    return subs


# ---------------------------------------------------------------- 渲染
def _paint(canvas, mask, paint, scale, grads, opacity=1.0):
    """把 paint（渐变或纯色）按 mask 贴到 canvas 上。"""
    if paint is None or mask is None:
        return
    if paint.startswith("url("):
        gid = paint[5:-1].strip().lstrip("#")
        grad = grads.get(gid)
        if grad is None:
            return
        pimg = gradient_image(canvas.size, grad, scale)
    else:
        col = parse_color(paint)
        if col is None:
            return
        pimg = Image.new("RGBA", canvas.size, col)
    if opacity != 1.0:
        pimg.putalpha(pimg.getchannel("A").point(lambda v: int(v * opacity)))
    pimg.putalpha(ImageChops.multiply(pimg.getchannel("A"), mask))
    canvas.alpha_composite(pimg)


def _mask(size, painter):
    m = Image.new("L", size, 0)
    painter(ImageDraw.Draw(m))
    return m


def _round_caps(draw, pts, width):
    """SVG 的 stroke-linecap=round：两端补圆。"""
    r = width / 2.0
    for x, y in (pts[0], pts[-1]):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=255)


def _num(value, default=1.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _draw_shape(canvas, draw, el, tag, style, scale, grads):
    fill = style.get("fill", "#000")
    stroke = style.get("stroke", "none")
    fill_op = _num(style.get("fill-opacity"), 1.0)
    stroke_op = _num(style.get("stroke-opacity"), 1.0)
    try:
        sw = float(style.get("stroke-width", 1))
    except ValueError:
        sw = 1.0
    sw_px = max(1, int(round(sw * scale)))

    if tag == "rect":
        x = float(el.get("x", 0)) * scale
        y = float(el.get("y", 0)) * scale
        w = float(el.get("width", 0)) * scale
        h = float(el.get("height", 0)) * scale
        rx = float(el.get("rx", 0)) * scale
        ry = float(el.get("ry", el.get("rx", 0))) * scale
        radius = min(rx, ry)
        box = [x, y, x + w, y + h]
        if fill not in ("none", None):
            _paint(canvas, _mask(canvas.size, lambda d: d.rounded_rectangle(box, radius=radius, fill=255)),
                   fill, scale, grads, fill_op)
        if stroke not in ("none", None):
            _paint(canvas, _mask(canvas.size, lambda d: d.rounded_rectangle(box, radius=radius, outline=255, width=sw_px)),
                   stroke, scale, grads, stroke_op)
    elif tag in ("circle", "ellipse"):
        cx = float(el.get("cx", 0)) * scale
        cy = float(el.get("cy", 0)) * scale
        if tag == "circle":
            rx = ry = float(el.get("r", 0)) * scale
        else:
            rx = float(el.get("rx", 0)) * scale
            ry = float(el.get("ry", 0)) * scale
        box = [cx - rx, cy - ry, cx + rx, cy + ry]
        if fill not in ("none", None):
            _paint(canvas, _mask(canvas.size, lambda d: d.ellipse(box, fill=255)), fill, scale, grads, fill_op)
        if stroke not in ("none", None):
            _paint(canvas, _mask(canvas.size, lambda d: d.ellipse(box, outline=255, width=sw_px)), stroke, scale, grads, stroke_op)
    elif tag == "polygon":
        nums = [float(v) for v in re.split(r"[\s,]+", el.get("points", "").strip()) if v]
        pts = [(nums[i] * scale, nums[i + 1] * scale) for i in range(0, len(nums) - 1, 2)]
        if len(pts) < 2:
            return
        if fill not in ("none", None):
            _paint(canvas, _mask(canvas.size, lambda d: d.polygon(pts, fill=255)), fill, scale, grads, fill_op)
        if stroke not in ("none", None):
            def _stroke(d):
                d.line(list(pts) + [pts[0]], fill=255, width=sw_px, joint="curve")
                _round_caps(d, list(pts) + [pts[0]], sw_px)
            _paint(canvas, _mask(canvas.size, _stroke), stroke, scale, grads, stroke_op)
    elif tag == "path":
        d = el.get("d", "")
        if not d:
            return
        subs = [[(x * scale, y * scale) for x, y in sub] for sub in path_to_subpaths(d)]
        if not subs:
            return
        if fill not in ("none", None):
            def _fill(d):
                for sub in subs:
                    d.polygon(sub, fill=255)
            _paint(canvas, _mask(canvas.size, _fill), fill, scale, grads, fill_op)
        if stroke not in ("none", None):
            def _stroke(d):
                for sub in subs:
                    d.line(sub, fill=255, width=sw_px, joint="curve")
                    _round_caps(d, sub, sw_px)
            _paint(canvas, _mask(canvas.size, _stroke), stroke, scale, grads, stroke_op)
    elif tag == "text":
        content = "".join(el.itertext()).strip()
        if not content:
            return
        size = float(el.get("font-size", 12)) * scale
        bold = el.get("font-weight", "") in ("bold", "700", "800", "900")
        cjk = has_cjk(content)
        font = load_font(max(6, int(round(size))), bold, cjk)
        x = float(el.get("x", 0)) * scale
        y = float(el.get("y", 0)) * scale
        paint = fill if fill != "none" else "#000"
        def _text(d):
            d.text((x, y), content, font=font, fill=255, anchor="ls")
        _paint(canvas, _mask(canvas.size, _text), paint, scale, grads)


def render_icon(svg_path, out_size, skip_bg=False, ss=3):
    """渲染 icon.svg → out_size×out_size 的 RGBA 图。"""
    root = ET.parse(svg_path).getroot()
    vb = [float(v) for v in (root.get("viewBox") or "0 0 108 108").split()]
    vw, vh = vb[2], vb[3]
    scale = out_size * ss / vw
    w, h = int(round(vw * scale)), int(round(vh * scale))
    grads = parse_gradients(root)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def walk(el, inherited):
        style = dict(inherited)
        for key in ("fill", "stroke", "stroke-width", "stroke-linecap",
                    "stroke-linejoin", "stroke-opacity", "fill-opacity"):
            if el.get(key) is not None:
                style[key] = el.get(key)
        tag = el.tag[len(SVG_NS):] if el.tag.startswith(SVG_NS) else el.tag
        if tag in ("rect", "path", "polygon", "circle", "ellipse", "text"):
            if skip_bg and tag == "rect" and str(style.get("fill", "")).startswith("url("):
                gid = style["fill"][5:-1].strip().lstrip("#")
                if gid in grads and gid.lower() in ("bg", "background", "bg-grad"):
                    pass
                else:
                    _draw_shape(canvas, draw, el, tag, style, scale, grads)
            else:
                _draw_shape(canvas, draw, el, tag, style, scale, grads)
        for child in el:
            walk(child, style)

    walk(root, {"fill": "#000", "stroke": "none", "stroke-width": "1"})
    return canvas.resize((out_size, out_size), Image.LANCZOS)


# ---------------------------------------------------------------- social preview
def _vertical_gradient(size, top, bot):
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


def _radial_mask(size, ease=2.6):
    w, h = size
    m = Image.new("L", size, 0)
    px = m.load()
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    maxd = math.hypot(cx, cy)
    for yy in range(h):
        for xx in range(w):
            d = math.hypot(xx - cx, yy - cy) / maxd
            px[xx, yy] = int(255 * (max(0.0, 1.0 - d) ** ease))
    return m


def _radial_glow(canvas, center, radius, color, max_alpha, ease=2.6):
    mask = _radial_mask((256, 256), ease).resize((radius * 2, radius * 2), Image.LANCZOS)
    mask = mask.point(lambda v: v * max_alpha // 255)
    layer = Image.new("RGBA", (radius * 2, radius * 2), color + (0,))
    layer.putalpha(mask)
    canvas.alpha_composite(layer, (int(center[0] - radius), int(center[1] - radius)))


def _pill(draw, x, y, text, font, h, padx, fill, outline, tcolor):
    bb = draw.textbbox((0, 0), text, font=font)
    w = (bb[2] - bb[0]) + padx * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=fill, outline=outline, width=2)
    draw.text((x + padx, y + h / 2), text, font=font, fill=tcolor, anchor="lm")
    return w


def build_preview(icon_svg):
    W, H = PREVIEW_W * SS, PREVIEW_H * SS
    img = Image.new("RGBA", (W, H))
    img.paste(_vertical_gradient((W, H), BG_TOP, BG_BOT), (0, 0))

    # 环境光晕
    _radial_glow(img, (200 * SS, 290 * SS), 330 * SS, (255, 138, 42), 26)
    _radial_glow(img, (950 * SS, 260 * SS), 350 * SS, (255, 122, 30), 14)

    # 右侧图形水印（只有图形，没有底板）
    ghost_size = 600 * SS
    ghost = render_icon(icon_svg, ghost_size, skip_bg=True, ss=2)
    alpha = ghost.getchannel("A").point(lambda v: v * 13 // 255)
    ghost.putalpha(alpha)
    img.alpha_composite(ghost, (W - ghost_size + 210 * SS, (H - ghost_size) // 2))

    # 左侧 logo 方块
    tile_size = 172 * SS
    tile = render_icon(icon_svg, tile_size, ss=3)
    tile_x, tile_y = 108 * SS, (H - tile_size) // 2
    img.alpha_composite(tile, (tile_x, tile_y))
    ImageDraw.Draw(img).rounded_rectangle(
        [tile_x, tile_y, tile_x + tile_size - 1, tile_y + tile_size - 1],
        radius=int(24 * tile_size / 108), outline=(255, 255, 255, 28), width=2)

    # 文字块
    d = ImageDraw.Draw(img)
    tx = 342 * SS
    max_w = W - tx - 60 * SS
    title = BRAND["title"]
    size = 92 * SS
    while size > 30 * SS:
        f = load_font(size, True, has_cjk(title))
        bb = d.textbbox((0, 0), title, font=f)
        if bb[2] - bb[0] <= max_w:
            break
        size -= 2 * SS
    f_title = f
    subtitle = BRAND["subtitle"]
    sub_size = 40 * SS
    while sub_size > 24 * SS:
        f_sub = load_font(sub_size, True, has_cjk(subtitle))
        bb = d.textbbox((0, 0), subtitle, font=f_sub)
        if bb[2] - bb[0] <= max_w:
            break
        sub_size -= 2 * SS
    f_pill = load_font(24 * SS, True, has_cjk("".join(BRAND["pills"])))
    f_tag = load_font(26 * SS, False, has_cjk(BRAND["tagline"]))

    title_bb = d.textbbox((0, 0), title, font=f_title)
    sub_bb = d.textbbox((0, 0), subtitle, font=f_sub)
    pill_h = 48 * SS
    gap1, gap2 = 16 * SS, 32 * SS
    block_h = (title_bb[3] - title_bb[1]) + gap1 + (sub_bb[3] - sub_bb[1]) + gap2 + pill_h
    y = (H - block_h) // 2

    d.text((tx, y - title_bb[1]), title, font=f_title, fill=TITLE_C + (255,), anchor="la")
    y += (title_bb[3] - title_bb[1]) + gap1
    d.text((tx, y - sub_bb[1]), subtitle, font=f_sub, fill=SUB_C + (255,), anchor="la")
    y += (sub_bb[3] - sub_bb[1]) + gap2

    px = tx + 2 * SS
    for label in BRAND["pills"]:
        pw = _pill(d, px, y, label, f_pill, pill_h, 24 * SS, PILL_FILL, PILL_LINE, PILL_C + (255,))
        px += pw + 16 * SS

    # 右下角标语
    d.text((W - 58 * SS, H - 52 * SS), BRAND["tagline"], font=f_tag,
           fill=ACCENT + (215,), anchor="rs")

    bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    bg.paste(_vertical_gradient((W, H), BG_TOP, BG_BOT), (0, 0))
    img = Image.alpha_composite(bg, img)
    return img.resize((PREVIEW_W, PREVIEW_H), Image.LANCZOS).convert("RGB")


# ---------------------------------------------------------------- 入口
def main():
    preview_only = "--preview-only" in sys.argv
    if not os.path.exists(ICON_SVG):
        print("✗ 找不到 %s" % ICON_SVG)
        return 1
    if not preview_only:
        logo = render_icon(ICON_SVG, 512, ss=3)
        logo.save(LOGO_PNG, "PNG", optimize=True)
        print("saved:", os.path.relpath(LOGO_PNG, ROOT))
        if "--ico" in sys.argv:
            ico = os.path.join(ROOT, "assets", "icon.ico")
            logo.save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                (64, 64), (128, 128), (256, 256)])
            print("saved:", os.path.relpath(ico, ROOT))
    preview = build_preview(ICON_SVG)
    preview.save(PREVIEW_PNG, "PNG", optimize=True)
    print("saved:", os.path.relpath(PREVIEW_PNG, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
