"""麻薯团子表情包生成器 —— 无背景（透明）GIF89a

用法:
    uv run python scripts/gen_mochi_emotions.py happy        # 只生成 happy
    uv run python scripts/gen_mochi_emotions.py all          # 生成 EXPRS 里全部
产物: src/emos/packs/<PACK>/xxx.gif  +  design/emos-mochi/xxx.png（验稿拼图）

规格（对齐 design/可爱表情包-麻薯-30表情-2026-10-21.html）:
  全帧 + disposal=2、透明索引、12.5fps（delay=8 → 80ms）、≤26 色、
  有效内容收在居中 208×208（240 屏）/ 156×156（180 屏）。
"""
import os, sys, math, json

from PIL import Image, ImageDraw, ImageSequence, ImageChops

PACK = "mochi_cute"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "emos", "packs", PACK)
PREV = os.path.join(ROOT, "..", "design", "emos-mochi")
BASE = 240            # 设计坐标系（240×240 屏幕），小尺寸按比例缩放绘制
SS = 3                # 超采样倍数（PIL 无抗锯齿，靠放大后 LANCZOS 缩回）
FIT = .92             # 整张内容全局缩放：四周留出运动余量，跳动/呆毛不被裁切
KEY = (255, 0, 255)   # 透明键色：背景像素量化后正好落在这个索引上

# ---------------------------------------------------------------- 调色板
ART = {
    "cream":    (255, 246, 233), "cream_s": (242, 224, 200), "white":  (255, 255, 255),
    "ink":      (59, 42, 36),    "blush":   (255, 176, 196), "blush_d":(255, 136, 171),
    "heart":    (255, 111, 145), "amber":   (255, 196, 107), "red":    (255, 107, 90),
    "sky":      (126, 196, 255), "tear":    (168, 220, 255), "sweat":  (143, 216, 255),
    "lilac":    (201, 168, 231), "mint":    (52, 211, 153),  "grey":   (185, 180, 172),
    "cream_sad":    (222, 231, 241), "cream_angry": (255, 213, 205),
    "cream_shy":    (255, 226, 232), "cream_err":   (228, 224, 218),
    "cream_sleepy": (232, 224, 245), "cream_surp":  (255, 236, 210),
    "cream_awk":    (232, 229, 224), "ink_2":       (90, 70, 62),
}
PAL = list(ART.values()) + [KEY]
TIDX = len(PAL) - 1
FLAT = [c for rgb in PAL for c in rgb] + [0] * ((256 - len(PAL)) * 3)
PALIMG = Image.new("P", (1, 1)); PALIMG.putpalette(FLAT)
C = {k: i for i, k in enumerate(ART)}

def col(name, alpha=255):
    r, g, b = ART[name] if name in ART else KEY
    return (r, g, b, alpha)

# ---------------------------------------------------------------- 几何（240 设计坐标）
BODY_UP = (48, 44, 192, 140)      # 上椭圆（窄）
BODY_LO = (26, 86, 214, 202)      # 下椭圆（宽）
EYE_L, EYE_R = (85, 110), (155, 110)
MOUTH_C = (120, 149)
BLUSH_L, BLUSH_R = (59, 133), (181, 133)
HEAD_C = (120, 123)

def _ell(bbox, s=SS, pad=0):
    return [bbox[0] * s, bbox[1] * s, bbox[2] * s, bbox[3] * s]

def new_ss(size=BASE):
    return Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))

# ---------------------------------------------------------------- 零件
def draw_blob(d, shade=True, body="cream"):
    """两颗椭圆叠成糖兜薯；先画下移的暗色副本 → 底部自然形成硬边阴影"""
    if shade:
        d.ellipse(_ell(off(BODY_LO, 0, 11)), fill=col("cream_s"))
        d.ellipse(_ell(off(BODY_UP, 0, 9)), fill=col("cream_s"))
    d.ellipse(_ell(BODY_LO), fill=col(body))
    d.ellipse(_ell(BODY_UP), fill=col(body))
    if shade:
        d.ellipse(_ell((66, 50, 148, 84)), fill=col("white", 235))
        d.ellipse(_ell((150, 56, 172, 72)), fill=col("white", 150))

def draw_feet(d, dy=0, dy2=None):
    for cx, offy in ((85, dy), (155, dy if dy2 is None else dy2)):
        d.ellipse(_ell((cx - 15, 190 + offy, cx + 15, 204 + offy)), fill=col("cream_s"))

def draw_ahoge(d, rot=0, droop=0, body="cream_s", length=1.0):
    """呆毛：单独画到临时层再绕发根旋转"""
    lay = new_ss()
    dd = ImageDraw.Draw(lay)
    bb = (104, 18, 150, 56)
    dd.arc(_ell(bb), 195, 355, fill=col(body), width=6 * SS)
    dd.ellipse(_ell((140, 34, 152, 48)), fill=col(body))
    if length < 1 or droop:
        lay = lay.resize((int(lay.width * (0.8 + 0.2 * length)),) * 2, Image.Resampling.LANCZOS)
    lay = lay.rotate(rot, center=(127 * SS, 50 * SS), resample=Image.Resampling.BICUBIC)
    d._image.paste(lay, (0, 0), lay)

def draw_eye(d, shape, pos, r=13, hl=1.0, dy=0, dx=0, body="ink", alpha=255):
    cx, cy = pos[0] + dx, pos[1] + dy
    if shape == "dot":
        d.ellipse(_ell(rect(cx, cy, r, r)), fill=col(body, alpha))
        if hl > 0:
            h = 4.6 * hl
            d.ellipse(_ell(rect(cx + r * .34, cy - r * .38, h, h)), fill=col("white", alpha))
            if hl > 1.15:
                d.ellipse(_ell(rect(cx - r * .5, cy + r * .42, h * .5, h * .5)), fill=col("white", alpha))
    elif shape == "line":                       # 闭眼线 / 横线眼
        d.ellipse(_ell(rect(cx, cy, r, 3.2)), fill=col(body, alpha))
    elif shape == "half":                       # 半闭（困、无语）
        d.ellipse(_ell(rect(cx, cy + 3, r, r * .42)), fill=col(body, alpha))
    elif shape == "arc_up":                     # ∩ 开心笑眼
        bb = rect(cx, cy + 2, r, r * .82)
        d.arc(_ell(bb), 180, 360, fill=col(body, alpha), width=5 * SS)
    elif shape == "arc_dn":                     # ∪ 大笑眯眼
        bb = rect(cx, cy - 3, r, r * .8)
        d.arc(_ell(bb), 0, 180, fill=col(body, alpha), width=5 * SS)
    elif shape == "wet":                        # 水光眼（委屈/求表扬）
        d.ellipse(_ell(rect(cx, cy, r * 1.18, r * 1.18)), fill=col(body, alpha))
        d.ellipse(_ell(rect(cx + r * .3, cy - r * .34, 6.4, 6.4)), fill=col("white", alpha))
        d.ellipse(_ell(rect(cx - r * .55, cy + r * .5, r * .9, 2.6)), fill=col("tear", alpha))
    elif shape == "heart":                      # 心心眼
        for s in (-1, 1):
            bb = (cx + s * r * .62 - 6.6, cy - 8.2, cx + s * r * .62 + 6.6, cy + 5.4)
            d.ellipse(_ell(bb), fill=col("heart", alpha))
        d.polygon([(cx - r * .82, cy - 1.2), (cx, cy + 9.6), (cx + r * .82, cy - 1.2)],
                  fill=col("heart", alpha))
    elif shape == "cross":                      # 错误
        for a in (-45, 45):
            lay = new_ss(); dd = ImageDraw.Draw(lay)
            dd.rectangle(_ell((cx - r, cy - 2.6, cx + r, cy + 2.6)), fill=col(body, alpha))
            lay = lay.rotate(a, center=(cx * SS, cy * SS), resample=Image.Resampling.BICUBIC)
            d._image.paste(lay, (0, 0), lay)
    elif shape == "white":                      # 惊吓：白眼 + 小瞳孔
        d.ellipse(_ell(rect(cx, cy, r * 1.24, r * 1.24)), fill=col("white", alpha))
        d.ellipse(_ell(rect(cx, cy, r * .42, r * .42)), fill=col(body, alpha))

def draw_mouth(d, shape, dy=0, w=14, h=None, rot=0, open_=1.0, color="ink", dx=0):
    cx, cy = MOUTH_C[0] + dx, MOUTH_C[1] + dy
    th = {"flat": 4.2, "line": 3.2, "smile": 4.6, "frown": 4.6, "cat": 4.2}.get(shape, 4.2)
    if shape in ("flat", "line"):
        d.ellipse(_ell(rect(cx, cy, w, th / 2)), fill=col(color))
    elif shape == "smile":
        bb = rect(cx, cy - 3, w, w * .62 * open_)
        d.arc(_ell(bb), 0, 180, fill=col(color), width=int(th * SS))
    elif shape == "frown":
        bb = rect(cx, cy + 4, w * .8, w * .5)
        d.arc(_ell(bb), 180, 360, fill=col(color), width=int(th * SS))
    elif shape == "o":
        d.ellipse(_ell(rect(cx, cy, w * .55, w * .55 * open_)), fill=col(color))
    elif shape == "open":                        # 大笑张嘴 + 舌头
        d.ellipse(_ell(rect(cx, cy - 2, w, w * .62 * open_)), fill=col(color))
        d.ellipse(_ell(rect(cx, cy + w * .28, w * .42, w * .26)), fill=col("heart"))
    elif shape == "wave":
        for i, s in enumerate((-1, 1)):
            bb = rect(cx + s * w * .3, cy - (2 if i else -1), w * .34, w * .22)
            d.arc(_ell(bb), 180 if i else 0, 360 if i else 180, fill=col(color), width=int(3.4 * SS))
    elif shape == "cat":                          # ω 猫嘴
        for s in (-1, 1):
            bb = rect(cx + s * w * .3, cy - 2, w * .34, w * .42)
            d.arc(_ell(bb), 0, 190, fill=col(color), width=int(3.6 * SS))
    elif shape == "zig":                          # 锯齿（怒/错）
        pts, n = [], 5
        for i in range(n + 1):
            pts.append((cx - w + 2 * w * i / n, cy - h * .4 + (h * .8 if i % 2 else 0)))
        for i in range(n, -1, -1):
            pts.append((cx - w + 2 * w * i / n, cy + h * .6 + (h * .8 if i % 2 else 0)))
        d.polygon([(x * SS, y * SS) for x, y in pts], fill=col(color))
    elif shape == "tongue":
        d.arc(_ell(rect(cx, cy - 3, w, w * .5)), 0, 180, fill=col(color), width=int(4 * SS))
        d.ellipse(_ell(rect(cx + w * .1, cy + 5, w * .3, w * .3)), fill=col("heart"))
    if rot:
        pass  # 旋转统一交给 head 层，避免碎片化

def draw_blush(d, o=0.45, dark=False, dy=0):
    if o <= 0: return
    cc = "blush_d" if dark else "blush"
    for cx in (BLUSH_L[0], BLUSH_R[0]):
        d.ellipse(_ell(rect(cx, BLUSH_L[1] + dy, 13, 5.6)), fill=col(cc, int(255 * min(1, o))))

def draw_brow(d, show=True, l=17, r=-17, dy=2, color="ink"):
    if not show: return
    for cx, a in ((EYE_L[0], l), (EYE_R[0], r)):
        lay = new_ss(); dd = ImageDraw.Draw(lay)
        dd.rectangle(_ell(rect(cx, 92 + dy, 13, 3)), fill=col(color))
        lay = lay.rotate(a, center=(cx * SS, (92 + dy) * SS), resample=Image.Resampling.BICUBIC)
        d._image.paste(lay, (0, 0), lay)

# ---------------------------------------------------------------- 特效零件
def fx_heart(d, x, y, s=1, alpha=255):
    r = 8 * s
    for k in (-1, 1):
        d.ellipse(_ell((x + k * r * .52 - r * .52, y - r * .66, x + k * r * .52 + r * .52, y + r * .34)),
                  fill=col("heart", alpha))
    d.polygon([(x * SS, (y - r * .2) * SS), ((x - r) * SS, (y + r * .28) * SS),
               ((x + r) * SS, (y + r * .28) * SS), (x * SS, (y + r) * SS)], fill=col("heart", alpha))

def fx_star(d, x, y, s=1, alpha=255, name="amber"):
    r, q = 9 * s, 3.4 * s
    d.polygon([(x * SS, (y - r) * SS), ((x + q) * SS, (y - q) * SS), ((x + r) * SS, y * SS),
               ((x + q) * SS, (y + q) * SS), (x * SS, (y + r) * SS), ((x - q) * SS, (y + q) * SS),
               ((x - r) * SS, y * SS), ((x - q) * SS, (y - q) * SS)], fill=col(name, alpha))

def fx_drop(d, x, y, s=1, alpha=255, name="tear"):
    r = 7 * s
    d.ellipse(_ell((x - r * .8, y - r * .3, x + r * .8, y + r)), fill=col(name, alpha))
    d.polygon([(x * SS, (y - r * 1.5) * SS), ((x - r * .72) * SS, y * SS),
               ((x + r * .72) * SS, y * SS)], fill=col(name, alpha))

def fx_z(d, x, y, s=1, alpha=255, name="lilac"):
    w, th = 11 * s, 3 * s
    d.line([(x - w / 2) * SS, (y - w / 2) * SS, (x + w / 2) * SS, (y - w / 2) * SS,
            (x - w / 2) * SS, (y + w / 2) * SS, (x + w / 2) * SS, (y + w / 2) * SS],
           fill=col(name, alpha), width=int(th * SS), joint="curve")

def fx_note(d, x, y, s=1, alpha=255, name="mint"):
    d.ellipse(_ell((x - 6 * s, y, x + 2 * s, y + 5 * s)), fill=col(name, alpha))
    d.line([(x + 2 * s) * SS, (y + 2.4 * s) * SS, (x + 2 * s) * SS, (y - 9 * s) * SS],
           fill=col(name, alpha), width=int(2.2 * s * SS))

def fx_mark(d, x, y, ch, s=1, alpha=255, name="white"):
    """? / ! / × —— 用几何拼，避免依赖字体"""
    lw = int(4 * s * SS)
    if ch == "!":
        d.line([(x) * SS, (y - 14 * s) * SS, (x) * SS, (y + 4 * s) * SS], fill=col(name, alpha), width=lw)
        d.ellipse(_ell(rect(x, y + 10 * s, 2.4 * s, 2.4 * s)), fill=col(name, alpha))
    elif ch == "?":
        bb = (x - 8 * s, y - 14 * s, x + 8 * s, y - 1 * s)
        d.arc(_ell(bb), 180, 40, fill=col(name, alpha), width=int(3.6 * s * SS))
        d.line([(x + 1 * s) * SS, (y - 3 * s) * SS, (x - 1 * s) * SS, (y + 3 * s) * SS],
               fill=col(name, alpha), width=int(3.4 * s * SS))
        d.ellipse(_ell(rect(x - 1 * s, y + 9 * s, 2.2 * s, 2.2 * s)), fill=col(name, alpha))
    elif ch == "x":
        r = 12 * s
        d.line([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=col(name, alpha), width=lw)
        d.line([(x - r) * SS, (y + r) * SS, (x + r) * SS, (y - r) * SS], fill=col(name, alpha), width=lw)

def fx_ring(d, x, y, r, a0, a1, name="mint", w=9):
    d.arc(_ell((x - r, y - r, x + r, y + r)), a0, a1, fill=col(name), width=int(w * SS))

def fx_dot3(d, xs, y, on=0, alpha=200):
    for i, x in enumerate(xs):
        if i == on:
            d.ellipse(_ell(rect(x, y, 5.6, 5.6)), fill=col("grey", alpha))
        else:
            d.ellipse(_ell(rect(x, y, 4.2, 4.2)), fill=col("grey", int(alpha * .4)))

def fx_steam(d, x, y, s=1, alpha=170, name="white"):
    d.ellipse(_ell((x - 7 * s, y - 7 * s, x + 7 * s, y + 7 * s)), fill=col(name, alpha))

def fx_bub(d, x, y, s=1, alpha=200):
    d.ellipse(_ell((x - 10 * s, y - 10 * s, x + 10 * s, y + 10 * s)), outline=col("tear", alpha), width=int(2.4 * SS))

# ---------------------------------------------------------------- 工具
def rect(cx, cy, rx, ry):
    return (cx - rx, cy - ry, cx + rx, cy + ry)

def off(bbox, dx, dy):
    return (bbox[0] + dx, bbox[1] + dy, bbox[2] + dx, bbox[3] + dy)

class Canvas:
    """把 240 设计坐标下的零件合成到一张 RGBA，支持整体挤压/旋转/位移"""
    def __init__(self):
        self.head = new_ss()
        self.hd = ImageDraw.Draw(self.head)
        self.top = new_ss()
        self.td = ImageDraw.Draw(self.top)
        self.pose = {}

    def __getitem__(self, k):
        return {"head": self.hd, "top": self.td}[k]

    def comp(self, size, pose):
        """240 设计坐标下的整张画（720²）→ 挤压/位移/旋转 → 叠特效层 → 缩到 size*SS"""
        W = BASE * SS
        sx, sy = pose.get("sx", 1), pose.get("sy", 1)
        dx, dy = pose.get("dx", 0) * SS, pose.get("dy", 0) * SS
        ax, ay = HEAD_C[0] * SS, HEAD_C[1] * SS
        h = self.head
        if (sx, sy) != (1, 1):
            hh = h.resize((max(1, int(W * sx)), max(1, int(W * sy))), Image.Resampling.LANCZOS)
            base = Image.new("RGBA", (W, W), (0, 0, 0, 0))
            base.paste(hh, (int(ax - ax * sx + dx), int(ay - ay * sy + dy)))
            h = base
        elif dx or dy:
            base = Image.new("RGBA", (W, W), (0, 0, 0, 0))
            base.paste(h, (int(dx), int(dy)))
            h = base
        if pose.get("rot"):
            h = h.rotate(pose["rot"], resample=Image.Resampling.BICUBIC)
        out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        out = Image.alpha_composite(out, h)
        out = Image.alpha_composite(out, self.top)
        if FIT != 1:                       # 全局留边：给跳动/特效留出运动余量
            fw = int(W * FIT)
            small = out.resize((fw, fw), Image.Resampling.LANCZOS)
            pad = Image.new("RGBA", (W, W), (0, 0, 0, 0))
            pad.paste(small, ((W - fw) // 2, (W - fw) // 2))
            out = pad
        if size != BASE:
            out = out.resize((size * SS, size * SS), Image.Resampling.LANCZOS)
        return out

def to_frames(rgba_frames, size):
    """透明化：缩到目标尺寸 → alpha 二值化 → 贴到 KEY 背景 → 量化到固定调色板"""
    out = []
    for im in rgba_frames:
        if im.size != (size * SS, size * SS):
            im = im.resize((size * SS, size * SS), Image.Resampling.LANCZOS)
        a = im.split()[-1].point(lambda v: 255 if v >= 96 else 0)
        comp = Image.new("RGB", im.size, KEY)
        comp.paste(im.convert("RGB"), (0, 0), a)
        p = comp.resize((size, size), Image.Resampling.LANCZOS)
        p = p.convert("RGB").quantize(palette=PALIMG, dither=Image.Dither.NONE)
        p.info["transparency"] = TIDX
        out.append(p)
    return out

def save(exp, name, outdir):
    size, delays = exp["size"], exp.get("delays")
    n = exp["frames"]
    dl = delays or [exp.get("delay", 80)] * n
    frames_src = []
    for t in range(n):
        cv = Canvas()
        exp["pose"](cv, t, n, exp)
        frames_src.append(cv.comp(exp["size"], cv.pose))
    fr = to_frames(frames_src, size)
    path = os.path.join(outdir, name + ".gif")
    fr[0].save(path, save_all=True, append_images=fr[1:], duration=dl, loop=exp.get("loop", 0),
               disposal=2, optimize=False, version="GIF89a")
    return path, len(fr), os.path.getsize(path)

# ---------------------------------------------------------------- 表情定义
def P(cv, t, n, exp, **kw):
    """通用姿势装配：cv.pose 给整体变换，cv 上画零件"""
    cv.pose = kw
    return cv

def pose_happy(cv, t, n, exp):
    """state:happy —— 弹两下 + ∩ 笑眼 + 大笑弧嘴 + 两颗心上浮 + 常驻腮红"""
    p = t / n
    jump = [0, -3, -9, -14, -15, -11, -5, 0, 2, 0, -3, -9, -14, -15, -11, -5, 0, 0]
    dy = (jump[t % len(jump)] if n > 1 else 0)
    sq = 1 + 0.03 * math.sin(p * 4 * math.pi)
    P(cv, t, n, exp, dy=dy, sx=1 / sq, sy=sq, rot=0)
    d = cv.hd
    draw_blob(d, body="cream")
    draw_ahoge(d, rot=-10 + 18 * math.sin(p * 4 * math.pi), length=.95)
    draw_feet(d, dy=2 if dy < -6 else 0)
    f = cv.hd
    draw_eye(f, "arc_up", EYE_L, r=12, dy=1)
    draw_eye(f, "arc_up", EYE_R, r=12, dy=1)
    draw_mouth(f, "smile", dy=1, w=17, open_=.9 + .1 * math.sin(p * 4 * math.pi))
    draw_blush(f, o=.85)
    for k, (x, y) in enumerate(((178, 60), (40, 74))):
        ph = (p + k * .38) % 1
        yy = y + 30 - ph * 46
        al = int(255 * min(1, (1 - ph) * 3) * min(1, ph * 6))
        fx_heart(cv.td, x, yy, s=.9 + .5 * ph, alpha=al)

def pose_listen(cv, t, n, exp):
    p = t / n
    dy = -3 * math.sin(p * 2 * math.pi)
    P(cv, t, n, exp, dy=dy, rot=-5.5, sx=1, sy=1)
    d = cv.hd
    draw_blob(d, body="cream")
    draw_ahoge(d, rot=-34)
    draw_eye(d, "dot", EYE_L, r=11.4, hl=1.15, dy=-1)
    draw_eye(d, "dot", EYE_R, r=11.4, hl=1.15, dy=-1)
    draw_mouth(d, "smile", w=12, open_=.7)
    draw_blush(d, o=.5)
    ph = (p * 2) % 1
    on = int(ph * 2)
    for i, x in enumerate((14, 218)):
        if i == on:
            for rr, yy in ((11, 104), (17, 100)):
                cv.td.arc(_ell((x - (rr if i else -rr) - rr, yy, x + rr - (0 if i else 2 * rr), yy + 26)),
                          300, 60, fill=col("mint", 220), width=int(4 * SS))

def pose_think(cv, t, n, exp):
    p = t / n
    dx = 6 * math.sin(p * 2 * math.pi)
    P(cv, t, n, exp, dy=-1, sx=1, sy=1, rot=2)
    d = cv.hd
    draw_blob(d, body="cream")
    draw_ahoge(d, rot=12 + 10 * math.sin(p * 2 * math.pi))
    draw_eye(d, "dot", EYE_L, r=8.4, hl=.9, dy=-5, dx=dx * .5)
    draw_eye(d, "dot", EYE_R, r=8.4, hl=.9, dy=-5, dx=dx * .5)
    draw_mouth(d, "o", w=8, open_=1)
    draw_blush(d, o=.3)
    fx_dot3(cv.td, (100, 120, 140), 24, on=int(p * 3) % 3)

def pose_speak(cv, t, n, exp):
    p = t / n
    open_ = [.5, 1.5, .8, 1.9, 1.1, .6, 1.3, 1.7][t % 8]
    P(cv, t, n, exp, dy=-2.5 * abs(math.sin(p * 3 * math.pi)), sx=1, sy=1)
    d = cv.hd
    draw_blob(d, body="cream")
    draw_ahoge(d, rot=6 * math.sin(p * 6 * math.pi))
    blink = t % 10 == 3
    for pos in (EYE_L, EYE_R):
        draw_eye(d, "line" if blink else "dot", pos, r=12.6, hl=1.05, dy=1 if blink else 0)
    draw_mouth(d, "o", w=15, open_=open_)
    draw_blush(d, o=.5)

def pose_idle(cv, t, n, exp):
    p = t / n
    br = math.sin(p * 2 * math.pi)
    P(cv, t, n, exp, dy=1.2 * br, sx=1 + .012 * br, sy=1 - .016 * br)
    d = cv.hd
    draw_blob(d, body="cream")
    if t in (0, 1):
        draw_ahoge(d, rot=-14)
    else:
        draw_ahoge(d, rot=0)
    blink = (t % 13) == 5
    for pos in (EYE_L, EYE_R):
        draw_eye(d, "line" if blink else "dot", pos, r=12.6, dy=2 if blink else 0)
    draw_mouth(d, "flat", w=9)
    draw_blush(d, o=.45)

def pose_net(cv, t, n, exp):
    p = t / n
    P(cv, t, n, exp, dx=5 * math.sin(p * 4 * math.pi), rot=5 * math.sin(p * 4 * math.pi), sx=1, sy=1)
    d = cv.hd
    draw_blob(d, body="cream")
    draw_ahoge(d, rot=26 * math.sin(p * 8 * math.pi))
    draw_eye(d, "dot", EYE_L, r=12, hl=1.1)
    draw_eye(d, "dot", EYE_R, r=12, hl=1.1)
    draw_mouth(d, "smile", w=15, open_=1)
    draw_blush(d, o=.7)
    for i in range(3):
        r = 14 + i * 15
        a = 200 if (int(p * 6) % 3) == i else 60
        fx_ring(cv.td, 210, 34, r, 150, 260, name="sky", w=5)
        cv.td.arc(_ell((210 - r, 34 - r, 210 + r, 34 + r)), 200, 340, fill=col("sky", a), width=int(5 * SS))

def pose_error(cv, t, n, exp):
    p = t / n
    sh = [-6, 6, -4, 4, 0][t % 5]
    P(cv, t, n, exp, dx=sh, sx=1.02, sy=.98)
    d = cv.hd
    draw_blob(d, body="cream_err")
    draw_ahoge(d, rot=sh, body="cream_err", droop=1)
    draw_eye(d, "cross", EYE_L, r=11)
    draw_eye(d, "cross", EYE_R, r=11)
    draw_mouth(d, "zig", w=17, h=13, dy=2)
    draw_blush(d, o=0)

def pose_sad(cv, t, n, exp):
    p = t / n
    P(cv, t, n, exp, dy=4 + 3 * math.sin(p * 2 * math.pi), sx=1 + .012 * math.sin(p * 2 * math.pi),
      sy=1 - .03 * math.sin(p * 2 * math.pi))
    d = cv.hd
    draw_blob(d, body="cream_sad")
    draw_ahoge(d, rot=34, body="cream_sad", length=.7)
    draw_eye(d, "half", EYE_L, r=12, dy=6)
    draw_eye(d, "half", EYE_R, r=12, dy=6)
    draw_mouth(d, "frown", w=14, dy=4)
    draw_blush(d, o=.4)
    for i, x in enumerate((92, 150)):
        ph = (p + i * .5) % 1
        fx_drop(cv.td, x, 128 + ph * 42, s=1.15 - .2 * ph, alpha=int(255 * (1 - ph) * (1 if ph < .85 else 0)))

EXPRS = {
    "sleep":   dict(size=240, frames=20, loop=0, pose=pose_idle,  slot="休息中"),
    "listen":  dict(size=240, frames=22, loop=0, pose=pose_listen, slot="聆听中"),
    "think":   dict(size=240, frames=24, loop=0, pose=pose_think),
    "tts_ing": dict(size=240, frames=16, loop=0, pose=pose_speak, slot="说话中/无情绪"),
    "wifi":    dict(size=240, frames=14, loop=0, pose=pose_net, slot="联网中"),
    "error":   dict(size=240, frames=12, loop=0, pose=pose_error, slot="发生错误"),
    "sad":     dict(size=180, frames=16, loop=0, pose=pose_sad, slot="伤心"),
    "happy":   dict(size=180, frames=18, loop=0, pose=pose_happy, slot="快乐"),
}

def contact_sheet(name, path, out):
    im = Image.open(path)
    fr = [f.copy().convert("RGBA") for f in ImageSequence.Iterator(im)]
    per = min(len(fr), 9)
    rows = (len(fr) + per - 1) // per
    cw, ch = fr[0].size
    for tag, bg in (("checker", None), ("dark", (0, 0, 0, 255))):
        sheet = Image.new("RGBA", (cw * per + 10 * (per + 1), (ch + 10) * rows + 120), bg)
        if tag == "checker":
            for yy in range(0, sheet.height, 16):
                for xx in range(0, sheet.width, 16):
                    c = (235, 235, 235, 255) if (xx // 16 + yy // 16) % 2 else (200, 200, 200, 255)
                    sheet.paste(Image.new("RGBA", (16, 16), c), (xx, yy))
        for i, f in enumerate(fr):
            r, k = divmod(i, per)
            sheet.paste(f, (10 + k * (cw + 10), 10 + r * (ch + 10)), f)
        sheet.save(os.path.join(out, f"{name}_{tag}.png"))

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "happy"
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(PREV, exist_ok=True)
    keys = list(EXPRS) if which == "all" else [which]
    for k in keys:
        path, nf, sz = save(EXPRS[k], k, OUT)
        import shutil; shutil.copy(path, os.path.join(PREV, k + ".gif"))
        contact_sheet(k, path, PREV)
        print(f"{k}.gif  {EXPRS[k]['size']}x{EXPRS[k]['size']}  {nf}帧  {sz/1024:.1f}KB  -> {path}")
    (os.path.join(OUT, "meta.json"), )
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"display_name": "麻薯 · 软白团子"}, f, ensure_ascii=False)

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
