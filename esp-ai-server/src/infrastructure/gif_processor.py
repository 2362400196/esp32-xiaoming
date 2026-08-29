"""GIF 图片处理器

对上传的 GIF 表情包进行居中裁剪（正方形）、缩放和压缩优化。
使用 Pillow 处理多帧 GIF 动画，保留帧延迟、循环次数和透明度。
"""
from __future__ import annotations

import base64
import io
from typing import Optional

from PIL import Image, ImageSequence

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 全局像素上限（3000 万像素），防止超大图片解码导致内存/CPU DoS
Image.MAX_IMAGE_PIXELS = 30_000_000

# 支持的尺寸选项（像素），0 表示保持原始尺寸
SUPPORTED_SIZES = [0, 120, 160, 180, 240]

# process_gif 处理帧数上限（超过截断，防超长动画 CPU DoS）
MAX_PROCESS_FRAMES = 300
# build_emo_gif 帧序列长度上限（防止超长 frame_order 重复解码素材造成 CPU DoS）
MAX_FRAME_ORDER = 200


def process_gif(content: bytes, target_size: int) -> bytes:
    """对 GIF 进行居中裁剪、缩放和压缩。

    处理流程：
      1. 打开 GIF，遍历每一帧
      2. 每帧转为 RGBA，居中裁剪为正方形
      3. 缩放到 target_size × target_size
      4. 转回 P 模式（自适应调色板），保留透明度
      5. 重新保存为优化后的 GIF

    Args:
        content:     原始 GIF 文件内容
        target_size: 目标边长（像素），0 或负数表示保持原始尺寸

    Returns:
        处理后的 GIF 文件内容（处理失败时返回原始内容）
    """
    if target_size <= 0:
        logger.debug("target_size<=0，跳过处理，保持原始尺寸")
        return content

    try:
        input_buf = io.BytesIO(content)
        img = Image.open(input_buf)

        # 确认是 GIF
        if img.format != "GIF":
            logger.warning("非 GIF 格式（%s），跳过处理", img.format)
            return content

        frames: list[Image.Image] = []
        durations: list[int] = []
        loop = 0
        bg_color = None

        # 尝试获取背景色（用于透明区域填充）
        if "background" in img.info:
            try:
                bg_color = img.info["background"]
            except Exception:
                pass

        for frame in ImageSequence.Iterator(img):
            # 帧数上限：超过截断（防超长动画 CPU/内存 DoS）
            if len(frames) >= MAX_PROCESS_FRAMES:
                logger.debug("GIF 帧数超过上限 %d，截断处理", MAX_PROCESS_FRAMES)
                break
            # 转为 RGBA 进行处理
            frame_rgba = frame.convert("RGBA")
            w, h = frame_rgba.size

            # 居中裁剪为正方形
            min_dim = min(w, h)
            left = (w - min_dim) // 2
            top = (h - min_dim) // 2
            frame_cropped = frame_rgba.crop(
                (left, top, left + min_dim, top + min_dim)
            )

            # 缩放到目标尺寸
            frame_resized = frame_cropped.resize(
                (target_size, target_size), Image.LANCZOS
            )

            # 转回 P 模式（带透明度的调色板模式）
            # 使用 quantize 保留 Alpha 通道
            frame_p = _rgba_to_p_with_alpha(frame_resized)
            frames.append(frame_p)

            # 保留原始帧延迟
            duration = frame.info.get("duration", 100)
            durations.append(duration if duration > 0 else 100)

            # 保留循环次数（取第一帧的值）
            if loop == 0 and "loop" in frame.info:
                loop = frame.info.get("loop", 0)

        if not frames:
            logger.warning("GIF 无有效帧，返回原始内容")
            return content

        # 保存为优化后的 GIF
        output_buf = io.BytesIO()
        save_kwargs = {
            "format": "GIF",
            "save_all": True,
            "append_images": frames[1:],
            "duration": durations,
            "loop": loop,
            "disposal": 2,  # 每帧绘制前恢复背景
            "optimize": True,
        }

        # 如果有透明色信息，传入透明色索引
        transparency = frames[0].info.get("transparency")
        if transparency is not None:
            save_kwargs["transparency"] = transparency

        frames[0].save(output_buf, **save_kwargs)

        result = output_buf.getvalue()
        original_kb = len(content) / 1024
        result_kb = len(result) / 1024
        logger.info(
            "GIF 处理完成: %dx%d → %dx%d, %.1fKB → %.1fKB (%.0f%%)",
            img.size[0],
            img.size[1],
            target_size,
            target_size,
            original_kb,
            result_kb,
            (result_kb / original_kb * 100) if original_kb > 0 else 0,
        )
        return result

    except Exception as e:
        logger.error("GIF 处理失败: %s，返回原始内容", e)
        return content


def _rgba_to_p_with_alpha(img: Image.Image) -> Image.Image:
    """将 RGBA 图像转为带透明度的 P 模式。

    Pillow 的 quantize 可以保留 Alpha 通道，生成带 transparency 索引的 P 模式图像。
    """
    # 如果图像没有透明像素，直接用自适应调色板转换
    if img.mode == "RGBA":
        # 检查是否有透明像素
        alpha = img.getchannel("A")
        if alpha.getextrema()[0] == 255:
            # 完全不透明，直接转 RGB 再转 P
            return img.convert("RGB").convert(
                "P", palette=Image.ADAPTIVE, colors=255
            )

    # 有透明像素：使用 quantize 保留 Alpha
    # 方法：先将 RGBA 转为 P 模式，保留透明度索引
    try:
        p_img = img.quantize(colors=255, method=Image.MEDIANCUT, alpha=255)
        return p_img
    except Exception:
        # 回退方案：直接转换
        return img.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)


def validate_size(size: Optional[int]) -> int:
    """校验尺寸参数是否合法，返回有效值。

    Args:
        size: 客户端传入的尺寸值（None 或不合法时返回 0=原图）

    Returns:
        合法的尺寸值
    """
    if size is None:
        return 0
    try:
        size = int(size)
    except (TypeError, ValueError):
        return 0
    if size not in SUPPORTED_SIZES:
        logger.warning("不支持的尺寸 %d，使用原图模式", size)
        return 0
    return size


# ==================== GIF 制作器（抽帧 / 合并 / 裁剪 / 缩放 / 压缩）====================
# 面向 Web 端"GIF 制作器"：用户上传 GIF/图片后，
# 可合并多素材、抽帧、逐帧删改排序、统一帧延迟、裁剪缩放到设备可用尺寸。

# 单个素材解码帧数上限（防御超大 GIF）
MAX_FRAMES_PER_SOURCE = 200
# 合成 GIF 的总帧数上限（避免生成超大文件）
MAX_FRAMES_TOTAL = 120
# 单次请求最大素材数量
MAX_SOURCES = 12
# 帧缩略图默认边长（像素）
THUMB_SIZE = 64

_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}


def _safe_duration(d) -> int:
    """规范化帧延迟：仅在 10ms~10s 之间取用，否则回退 100ms。"""
    try:
        d = int(d)
    except (TypeError, ValueError):
        return 100
    return d if 10 <= d <= 10000 else 100


def decode_frames(content: bytes, max_frames: int = MAX_FRAMES_PER_SOURCE):
    """解码 GIF 动画或单张图片为 RGBA 帧序列。

    Args:
        content:    文件原始字节
        max_frames: 动画帧数上限（0 表示不限制）

    Returns:
        (frames, durations, loop, animated, w, h)
        - frames:     RGBA PIL Image 列表（失败/空时为 None）
        - durations:  每帧延迟（ms）
        - loop:       循环次数（0=无限）
        - animated:   是否多帧 GIF 动画
        - w, h:       原始尺寸
    """
    try:
        img = Image.open(io.BytesIO(content))
        img.load()
        fmt = img.format
    except Exception:
        return None, [], 0, False, 0, 0

    if fmt != "GIF" and fmt not in _IMAGE_FORMATS:
        return None, [], 0, False, 0, 0

    w, h = img.size
    frames: list = []
    durations: list = []
    loop = 0
    animated = False

    try:
        if fmt == "GIF" and getattr(img, "n_frames", 1) > 1:
            animated = True
            loop = img.info.get("loop", 0)
            for i, frame in enumerate(ImageSequence.Iterator(img)):
                if max_frames and i >= max_frames:
                    break
                frames.append(frame.convert("RGBA"))
                durations.append(_safe_duration(frame.info.get("duration", 100)))
        else:
            frames = [img.convert("RGBA")]
            durations = [_safe_duration(100)]
    except Exception:
        return None, [], 0, False, 0, 0

    if not frames:
        return None, [], 0, False, 0, 0
    return frames, durations, loop, animated, w, h


def _thumb_data_url(frame, thumb_size: int) -> str:
    """将单帧转为基础 64 PNG 缩略图（data URL），供前端帧编辑器展示。"""
    t = frame.convert("RGBA")
    t.thumbnail((thumb_size, thumb_size), Image.LANCZOS)
    buf = io.BytesIO()
    t.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def describe_sources(
    files: list[tuple[str, bytes]],
    max_frames: int = MAX_FRAMES_PER_SOURCE,
    thumb_size: int = THUMB_SIZE,
) -> list[dict]:
    """解析每个素材文件：帧数、延迟、尺寸与每帧缩略图，供前端帧编辑器使用。

    Args:
        files:      [(文件名, 文件字节)] 列表
        max_frames: 单素材解码帧数上限
        thumb_size: 缩略图边长

    Returns:
        素材描述列表，每项含 ``id``（对应 files 下标）与 ``frames``。
        无法解析的素材返回 ``{"id": ..., "valid": False, "error": ...}``。
    """
    result: list[dict] = []
    for idx, (name, content) in enumerate(files):
        frames, durations, loop, animated, w, h = decode_frames(content, max_frames)
        if frames is None:
            result.append({"id": idx, "valid": False, "name": name, "error": "无法解码"})
            continue
        result.append({
            "id": idx,
            "valid": True,
            "name": name,
            "animated": animated,
            "w": w,
            "h": h,
            "loop": loop,
            "frames": [
                {"i": i, "d": durations[i], "thumb": _thumb_data_url(frames[i], thumb_size)}
                for i in range(len(frames))
            ],
        })
    return result


def _fit_contain(frame, target: int) -> Image.Image:
    """等比缩放并透明填充到 target×target 正方形画布（不裁剪）。"""
    w, h = frame.size
    scale = min(target / w, target / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = frame.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    canvas.paste(resized, ((target - nw) // 2, (target - nh) // 2), resized)
    return canvas


def build_emo_gif(
    files: list[bytes],
    frame_order: list[dict],
    target_size: int = 0,
    delay: Optional[int] = None,
    loop: int = 0,
    fit: str = "crop",
) -> Optional[bytes]:
    """按帧序列合成设备可用的 GIF（抽帧/合并/裁剪/缩放/压缩）。

    Args:
        files:       素材字节列表，frame_order 中的 ``src`` 为其下标
        frame_order: 有序帧序列 [{"src": 素材下标, "frame": 帧索引}, ...]
        target_size: 目标正方形边长（0=保持原始尺寸，否则须在 SUPPORTED_SIZES 内）
        delay:       统一帧延迟 ms（None=保留各帧原始延迟）
        loop:        循环次数（0=无限）
        fit:         "crop"=居中裁正方形；"fit"=等比缩放+透明填充

    Returns:
        合成后的 GIF 字节；任何一步失败返回 None
    """
    out_rgba: list = []
    out_durations: list = []

    # 帧序列长度上限：防止超长 frame_order 重复解码素材造成 CPU DoS
    if len(frame_order) > MAX_FRAME_ORDER:
        logger.debug("frame_order 超过上限 %d，截断", MAX_FRAME_ORDER)
        frame_order = frame_order[:MAX_FRAME_ORDER]

    for item in frame_order:
        if not isinstance(item, dict):
            continue
        src = item.get("src")
        frame = item.get("frame")
        if not isinstance(src, int) or not isinstance(frame, int):
            continue
        if src < 0 or src >= len(files):
            continue
        frames, durations, _, _, _, _ = decode_frames(files[src])
        if not frames or frame < 0 or frame >= len(frames):
            continue
        out_rgba.append(frames[frame])
        out_durations.append(_safe_duration(delay) if delay else durations[frame])

    if not out_rgba:
        return None
    if len(out_rgba) > MAX_FRAMES_TOTAL:
        out_rgba = out_rgba[:MAX_FRAMES_TOTAL]
        out_durations = out_durations[:MAX_FRAMES_TOTAL]

    target_size = validate_size(target_size)
    if fit != "fit":
        fit = "crop"

    processed: list = []
    for fr in out_rgba:
        if target_size > 0:
            if fit == "fit":
                fr = _fit_contain(fr, target_size)
            else:
                w, h = fr.size
                m = min(w, h)
                left = (w - m) // 2
                top = (h - m) // 2
                fr = fr.crop((left, top, left + m, top + m))
                fr = fr.resize((target_size, target_size), Image.LANCZOS)
        processed.append(_rgba_to_p_with_alpha(fr))

    try:
        output_buf = io.BytesIO()
        save_kwargs = {
            "format": "GIF",
            "save_all": True,
            "append_images": processed[1:],
            "duration": out_durations,
            "loop": loop,
            "disposal": 2,
            "optimize": True,
        }
        transparency = processed[0].info.get("transparency")
        if transparency is not None:
            save_kwargs["transparency"] = transparency
        processed[0].save(output_buf, **save_kwargs)
    except Exception as e:
        logger.error("GIF 合成失败: %s", e)
        return None

    result = output_buf.getvalue()
    logger.info(
        "GIF 合成完成: %d 帧, %dx%d, %.1fKB, loop=%d, fit=%s",
        len(processed),
        target_size or processed[0].size[0],
        target_size or processed[0].size[1],
        len(result) / 1024,
        loop,
        fit,
    )
    return result
