"""
表情包管理模块
管理表情包的创建、删除、列表、以及设备激活表情包的切换。

表情包元数据（``display_name``）与设备激活表情包均存储在数据库
（``EmoPackRepository`` / ``devices.active_emo_pack`` 列）。GIF 文件存磁盘。

目录结构（GIF 文件，磁盘存储）：
  emos/
    packs/
      default/          ← 默认表情包
        happy.gif, ...
      pack_1/           ← 用户创建的表情包（ASCII 目录名）
        happy.gif, ...

元数据存储（DB）：
  emo_packs 表：{pack_name, display_name}

设备激活表情包（DB）：
  devices 表的 active_emo_pack 列
"""
from pathlib import Path
import os
import re
import shutil
from src.infrastructure.db.repositories.emo_repository import EmoPackRepository
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

EMOS_DIR = Path(__file__).parent.parent / "emos"
PACKS_DIR = EMOS_DIR / "packs"
DEVICES_DIR = EMOS_DIR / "devices"

# 模块级仓储单例（延迟使用全局异步会话工厂，构造时不连接 DB）
_emo_repo = EmoPackRepository()


def ensure_dirs():
    """确保基础目录存在"""
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    DEVICES_DIR.mkdir(parents=True, exist_ok=True)


# 表情包目录名白名单：仅允许字母、数字、下划线、连字符
_PACK_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_pack_name(pack_name: str) -> bool:
    """校验表情包目录名是否安全，防止路径遍历攻击。

    - 不允许为空
    - 不允许包含 ``..``（父目录引用）
    - 不允许包含路径分隔符 ``/`` 或 ``\\``
    - 仅允许字母、数字、下划线、连字符
    """
    if not isinstance(pack_name, str) or not pack_name:
        return False
    if ".." in pack_name or "/" in pack_name or "\\" in pack_name:
        return False
    return bool(_PACK_NAME_RE.match(pack_name))


def _next_pack_id() -> str:
    """生成下一个可用的 pack 目录名"""
    ensure_dirs()
    existing = set()
    for d in PACKS_DIR.iterdir():
        if d.is_dir() and d.name.startswith("pack_"):
            try:
                num = int(d.name.split("_", 1)[1])
                existing.add(num)
            except ValueError:
                pass
    i = 1
    while i in existing:
        i += 1
    return f"pack_{i}"


async def migrate_old_format():
    """启动时同步磁盘表情包到 DB，并修复中文目录名。

    - 将旧格式 ``emos/default/`` 迁移为 ``emos/packs/default/``（一次性历史迁移）
    - 将所有磁盘包的元数据同步到 DB（display_name 取目录名）
    - 修复中文目录名：重命名为 ASCII 目录名，中文名写入 DB 的 display_name
    """
    ensure_dirs()
    old_default = EMOS_DIR / "default"
    new_default = PACKS_DIR / "default"
    if old_default.exists() and not new_default.exists():
        shutil.move(str(old_default), str(new_default))
        logger.info(f"[EmoPack] 迁移旧表情目录: {old_default} → {new_default}")

    # 将所有磁盘包的元数据同步到 DB（display_name 取目录名）
    for d in PACKS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            await _emo_repo.upsert_pack(d.name, d.name)
        except Exception as e:
            logger.warning(f"[EmoPack] DB 同步表情包元数据失败 ({d.name}): {e}")

    # 修复中文目录名的包：重命名为 ASCII 目录名，display_name 保留中文名写入 DB
    import re
    for d in list(PACKS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name == "default":
            continue
        if not re.match(r'^[a-zA-Z0-9_]+$', d.name):
            # 中文目录名，需要迁移
            old_display = d.name
            new_name = _next_pack_id()
            new_path = PACKS_DIR / new_name
            shutil.move(str(d), str(new_path))
            try:
                await _emo_repo.upsert_pack(new_name, old_display)
                # 删除旧的 DB 元数据（按旧中文名，若存在）
                await _emo_repo.delete_pack(old_display)
            except Exception as e:
                logger.warning(f"[EmoPack] DB 更新迁移表情包元数据失败: {e}")
            logger.info(f"[EmoPack] 迁移中文表情包: {old_display} → {new_name}")


async def list_packs(viewer_user_id: str | None = None,
                     is_admin: bool = False) -> list[dict]:
    """列出可见的表情包。

    可见性规则：
    - 公共包（``owner_user_id`` 为空，如 default、管理员创建的包）所有人可见
    - 私有包仅归属用户本人可见
    - 管理员可见全部

    返回 [{name, display_name, count, cover, owner_user_id}]
    """
    ensure_dirs()
    # 一次性读取 DB 元数据
    db_packs: dict[str, dict] = {}
    try:
        for p in await _emo_repo.list_packs():
            db_packs[p["name"]] = p
    except Exception as e:
        logger.warning(f"[EmoPack] DB 读取表情包列表失败: {e}")

    packs = []
    for d in sorted(PACKS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = db_packs.get(d.name, {})
        owner = meta.get("owner_user_id")
        if owner and not is_admin and owner != viewer_user_id:
            continue    # 他人的私有表情包不可见
        gifs = [f for f in os.listdir(str(d)) if f.endswith(".gif")]
        cover = meta.get("cover")
        if cover not in gifs:
            cover = _pick_cover(gifs)
        packs.append({
            "name": d.name,
            "display_name": meta.get("display_name") or d.name,
            "count": len(gifs),
            "cover": cover,
            "owner_user_id": owner,
        })
    return packs


# 封面优先取情绪最常用的几个 GIF，都没有则退化为文件名排序第一个，
# 保证任何有内容的表情包都能在前端卡片里显示预览图。
_COVER_CANDIDATES = ("happy.gif", "tts_ing.gif", "listen.gif", "default.gif")


def _pick_cover(gifs: list[str]) -> str | None:
    if not gifs:
        return None
    for name in _COVER_CANDIDATES:
        if name in gifs:
            return name
    return sorted(gifs)[0]


async def get_pack_meta(pack_name: str) -> dict | None:
    """读取单个表情包的元数据（含归属与封面）"""
    try:
        return await _emo_repo.get_pack_meta(pack_name)
    except Exception as e:
        logger.warning(f"[EmoPack] DB 读取表情包元数据失败: {e}")
        return None


def can_manage_pack(meta: dict | None, user_id: str | None, is_admin: bool) -> bool:
    """判断用户能否编辑/删除该表情包：管理员任意，公共包任意登录用户可管理？否——

    普通用户只能管理自己创建的私有包；公共包（含 default）只有管理员能改。
    """
    if is_admin:
        return True
    if not meta:
        return False
    owner = meta.get("owner_user_id")
    return bool(owner) and owner == user_id


async def update_pack_meta(pack_name: str, display_name: str | None = None,
                           cover: str | None = None) -> dict:
    """更新表情包名称/封面。返回 {ok, message}"""
    if not _validate_pack_name(pack_name):
        return {"ok": False, "message": "无效的表情包名称"}
    pack_dir = get_pack_dir(pack_name)
    if not pack_dir:
        return {"ok": False, "message": "表情包不存在"}

    new_name = (display_name or "").strip()
    if display_name is not None:
        if not new_name:
            return {"ok": False, "message": "表情包名称不能为空"}
        meta = await get_pack_meta(pack_name)
        # 同属主下不允许重名（公共包之间、同一用户的私有包之间）
        try:
            for p in await list_packs(viewer_user_id=None, is_admin=True):
                if p["name"] == pack_name:
                    continue
                if (p.get("owner_user_id") or None) != ((meta or {}).get("owner_user_id") or None):
                    continue
                if (p.get("display_name") or p["name"]) == new_name:
                    return {"ok": False, "message": f"表情包 '{new_name}' 已存在"}
        except Exception as e:
            logger.warning(f"[EmoPack] 重名检查失败: {e}")

    if cover is not None:
        # 封面必须来自本包内的 gif 文件
        if cover and not (pack_dir / cover).is_file():
            return {"ok": False, "message": "封面图片不存在于该表情包中"}

    try:
        ok = await _emo_repo.update_pack(
            pack_name,
            display_name=new_name if display_name is not None else None,
            cover=cover,
        )
        if not ok:
            # 兼容历史目录：磁盘有包但 DB 没有元数据行时补建（按公共包处理）
            await _emo_repo.upsert_pack(pack_name, new_name or pack_name, owner_user_id=None)
            ok = await _emo_repo.update_pack(
                pack_name,
                display_name=new_name if display_name is not None else None,
                cover=cover,
            )
    except Exception as e:
        logger.warning(f"[EmoPack] DB 更新表情包失败: {e}")
        return {"ok": False, "message": "保存失败"}
    if not ok:
        return {"ok": False, "message": "表情包元数据不存在"}
    logger.info(f"[EmoPack] 更新表情包: {pack_name} name={new_name or '-'} cover={cover or '-'}")
    return {"ok": True, "message": "保存成功"}


def get_pack_dir(pack_name: str) -> Path | None:
    """获取表情包目录路径，不存在或名称非法返回 None"""
    if not _validate_pack_name(pack_name):
        return None
    ensure_dirs()
    p = PACKS_DIR / pack_name
    return p if p.exists() and p.is_dir() else None


def get_or_create_pack_dir(pack_name: str) -> Path | None:
    """获取或创建表情包目录，名称非法返回 None"""
    if not _validate_pack_name(pack_name):
        return None
    ensure_dirs()
    p = PACKS_DIR / pack_name
    p.mkdir(parents=True, exist_ok=True)
    return p


async def create_pack(display_name: str, owner_user_id: str | None = None) -> dict:
    """创建新表情包，自动生成 ASCII 目录名，中文名存 DB 元数据

    ``owner_user_id`` 为空表示公共包（管理员创建 / 系统默认），
    否则为普通用户私有包。
    """
    if not display_name or display_name.strip() in ("", ".", ".."):
        return {"ok": False, "message": "无效的表情包名称"}

    display_name = display_name.strip()

    # 检查同归属下显示名是否已存在（公共包之间、同一用户的私有包之间）
    try:
        for p in await _emo_repo.list_packs():
            if (p.get("owner_user_id") or None) != (owner_user_id or None):
                continue
            if (p.get("display_name") or p["name"]) == display_name:
                return {"ok": False, "message": f"表情包 '{display_name}' 已存在"}
    except Exception as e:
        logger.warning(f"[EmoPack] DB 检查表情包重复失败: {e}")

    # 自动生成 ASCII 目录名
    dir_name = _next_pack_id()
    p = PACKS_DIR / dir_name
    p.mkdir(parents=True, exist_ok=True)
    try:
        await _emo_repo.upsert_pack(dir_name, display_name, owner_user_id=owner_user_id)
    except Exception as e:
        logger.warning(f"[EmoPack] DB 写入表情包元数据失败: {e}")
    logger.info(f"[EmoPack] 创建表情包: {display_name} → {dir_name} (owner={owner_user_id or 'public'})")
    return {"ok": True, "message": "创建成功", "name": dir_name, "display_name": display_name}


async def delete_pack(pack_name: str) -> dict:
    """删除表情包（不允许删除 default）"""
    if not _validate_pack_name(pack_name):
        return {"ok": False, "message": "无效的表情包名称"}
    if pack_name == "default":
        return {"ok": False, "message": "不能删除默认表情包"}
    ensure_dirs()
    p = PACKS_DIR / pack_name
    if not p.exists():
        return {"ok": False, "message": f"表情包不存在"}
    shutil.rmtree(str(p))
    try:
        await _emo_repo.delete_pack(pack_name)
    except Exception as e:
        logger.warning(f"[EmoPack] DB 删除表情包元数据失败: {e}")
    logger.info(f"[EmoPack] 删除表情包: {pack_name}")
    return {"ok": True, "message": "删除成功"}


async def get_active_pack(device_id: str) -> str:
    """获取设备当前激活的表情包目录名，默认 'default'"""
    ensure_dirs()
    try:
        name = await _emo_repo.get_active_pack(device_id)
        if name and (PACKS_DIR / name).exists():
            return name
    except Exception as e:
        logger.warning(f"[EmoPack] DB 读取激活表情包失败: {e}")
    return "default"


async def set_active_pack(device_id: str, pack_name: str) -> dict:
    """设置设备激活的表情包（pack_name 为目录名）"""
    if not _validate_pack_name(pack_name):
        return {"ok": False, "message": "无效的表情包名称"}
    ensure_dirs()
    p = PACKS_DIR / pack_name
    if not p.exists():
        return {"ok": False, "message": f"表情包不存在"}
    try:
        await _emo_repo.set_active_pack(device_id, pack_name)
    except Exception as e:
        logger.warning(f"[EmoPack] DB 设置激活表情包失败: {e}")
    # display_name 从 DB 读取，失败时回退到目录名
    display = pack_name
    try:
        meta = await _emo_repo.get_pack_meta(pack_name)
        if meta:
            display = meta.get("display_name", pack_name)
    except Exception as e:
        logger.warning(f"[EmoPack] DB 读取表情包元数据失败: {e}")
    logger.info(f"[EmoPack] 设备 {device_id} 切换表情包 → {display}")
    return {"ok": True, "message": "切换成功"}


def list_pack_emos(pack_name: str, scheme: str = "http", host: str = "localhost:8088") -> list[dict]:
    """获取某个表情包的完整表情列表"""
    if not _validate_pack_name(pack_name):
        return []
    p = get_pack_dir(pack_name)
    if not p:
        return []
    files = []
    for f in sorted(os.listdir(str(p))):
        if f.endswith(".gif"):
            fpath = str(p / f)
            size = os.path.getsize(fpath)
            files.append({
                "name": f.replace(".gif", ""),
                "filename": f,
                "size": size,
                "url": f"{scheme}://{host}/emos/packs/{pack_name}/{f}",
            })
    return files
