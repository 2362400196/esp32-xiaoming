"""
自学习服务 - 从对话中学习，自动创建skill

``_log_learning`` 通过数据库仓储（``LearningLogRepository``，append-only + 修剪 100 条）记录。
其余 skill 文件操作（SKILL.md）暂不变更。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

from src.infrastructure.db.repositories.growth_repositories import LearningLogRepository
from src.infrastructure.logging import get_logger
from .models import SkillCandidate
from .similarity import text_similarity

logger = get_logger(__name__)

# 模块级仓储单例（延迟使用全局异步会话工厂，构造时不连接 DB）
_learning_log_repo = LearningLogRepository()

# 自学习技能文件大小上限（字符数），超限自动开新技能，避免单文件无限膨胀
MAX_SKILL_SIZE = 8000
# 合并前相似度阈值，超过则视为重复内容跳过
MERGE_SIMILARITY_THRESHOLD = 0.8

ANALYSIS_PROMPT = """你是一个对话分析器。只输出JSON，不要输出任何其他文字。

分析这段对话，提取信息：

```json
{
    "user_info": {
        "new_facts": ["用户的新信息"],
        "preferences": ["用户偏好"],
        "concerns": ["用户关心的事"]
    },
    "emotion": {
        "current": "happy/sad/anxious/calm/excited/tired/angry/worried/grateful/lonely/confused/neutral",
        "intensity": 0.5,
        "trigger": "情绪原因"
    },
    "memories": [
        {"content": "值得记住的事", "tags": ["标签"], "keywords": ["关键词"]}
    ],
    "skill_candidate": {
        "title": "",
        "content": "",
        "category": "",
        "tags": []
    },
    "ai_feeling": "AI的感受",
    "highlights": ["亮点"],
    "conversation_summary": "摘要"
}
```

规则：
	- 用户信息（user_info）必须尽量提取，即使只是随口一提的偏好也要记录
	- 用户说"喜欢/不喜欢/想吃/想学/想做什么"都是重要的偏好，一定要提取到preferences
	- 用户提到的个人信息（名字、职业、家人、住址等）一定要提取到new_facts
	- 用户关心的话题、反复提及的事情一定要提取到concerns
	- 情绪要准确，不要过度解读
	- skill_candidate在以下情况必须填写：
	  1. 有明确可复用知识（教程、方法、技巧、步骤）→ 提取
	  2. AI对自身性格的认知、AI说话风格的偏好、AI对用户的了解总结 → 提取为skill
	  3. AI对人生、对话、交流的感悟和思考 → 提取为skill
	  4. AI总结的与用户交流的经验教训 → 提取为skill
	- 只有完全无内容的闲聊才让skill_candidate留空
	- 提取AI自我认知时：
	  - title 填写分类（如"ai性格设定"、"对话风格要求"、"交流原则"）
	  - content 详细描述AI应该是什么样的，说话方式是什么
	  - category 填写 "self_growth"
	  - tags 添加 ["ai_self", "成长"]
	- new_facts、preferences、concerns 不能为空，至少各留一个空数组
"""

SKILL_EVALUATION_PROMPT = """
你正在评估一个知识是否应该保存为skill。

候选知识：
{candidate}

已有技能：
{existing_skills}

请判断：
	1. 这个知识是否值得保存为skill？
	   - 如果 category 是 "self_growth"（AI自我认知、性格设定、感悟类），直接保存，不要跳过
	   - 普通知识：是否可复用？（用户以后还会用到）
	   - 普通知识：是否有明确的操作步骤？（不是闲聊）
	   - 普通知识：是否足够通用？（不是一次性的任务）
	
	2. 应该如何处理？
	   - "create_new": 创建新skill（如果和已有skill不相关）
	   - "merge_existing": 合并到现有skill（如果相关），self_growth类合并到已有 self_growth 的skill
	   - "skip": 不保存（普通知识不够有价值时跳过，但self_growth不跳过）

返回JSON：
{{
    "action": "create_new|merge_existing|skip",
    "target_skill": "如果merge，填写目标skill_id",
    "new_skill_name": "如果create，填写skill名称（小写字母+下划线）",
    "category": "分类（自己决定）",
    "reason": "判断理由",
    "confidence": 0.0-1.0
}}
"""


class SelfLearningService:
    """自学习服务"""

    def __init__(self, data_dir: str, llm_call_func=None):
        self._data_dir = data_dir
        self._llm_call = llm_call_func

    def _get_skills_dir(self, device_id: str) -> str:
        return os.path.join(self._data_dir, "devices", device_id, "skills")

    async def analyze_conversation(self, messages: list[dict]) -> dict:
        """分析对话，提取信息"""
        if not self._llm_call:
            logger.error("[Learning] LLM调用函数未设置")
            return {}

        messages_text = "\n".join([
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in messages[-15:]
        ])

        if not messages_text.strip():
            logger.warning("[Learning] 对话内容为空，跳过分析")
            return {}

        try:
            logger.info(f"[Learning] 开始分析对话，消息数: {len(messages)}")
            result = await self._llm_call(ANALYSIS_PROMPT, messages_text)
            if not result:
                logger.warning("[Learning] LLM返回为空")
                return {}

            logger.debug(f"[Learning] LLM返回: {result[:200]}...")
            parsed = self._parse_json(result)
            if not parsed:
                logger.warning(f"[Learning] JSON解析失败，原始内容: {result[:200]}")
            return parsed
        except Exception as e:
            logger.error(f"[Learning] 分析对话失败: {e}", exc_info=True)
            return {}

    async def evaluate_skill_creation(
        self,
        device_id: str,
        candidate: dict,
    ) -> Optional[dict]:
        """评估是否应该创建skill"""
        if not candidate or not candidate.get("title"):
            return None

        existing_skills = await self._get_existing_skills(device_id)

        prompt = SKILL_EVALUATION_PROMPT.format(
            candidate=json.dumps(candidate, ensure_ascii=False, indent=2),
            existing_skills=json.dumps(existing_skills, ensure_ascii=False, indent=2),
        )

        try:
            result = await self._llm_call(
                "你是一个技能评估专家，判断知识是否值得保存为skill。",
                prompt,
            )
            decision = self._parse_json(result)

            if decision.get("action") == "skip":
                logger.info(f"[Learning] 跳过保存: {decision.get('reason', '')}")
                return None

            return decision
        except Exception as e:
            logger.error(f"[Learning] 评估skill失败: {e}")
            return None

    async def create_or_merge_skill(
        self,
        device_id: str,
        candidate: dict,
        decision: dict,
    ) -> Optional[str]:
        """创建或合并skill"""
        action = decision.get("action", "skip")

        if action == "skip":
            return None

        if action == "merge_existing":
            return await self._merge_to_skill(device_id, candidate, decision)

        if action == "create_new":
            return await self._create_new_skill(device_id, candidate, decision)

        return None

    async def _create_new_skill(
        self,
        device_id: str,
        candidate: dict,
        decision: dict,
    ) -> Optional[str]:
        """创建新skill"""
        skill_name = decision.get("new_skill_name", "")
        if not skill_name:
            skill_name = self._generate_skill_name(candidate.get("title", ""))

        skills_dir = self._get_skills_dir(device_id)
        skill_dir = os.path.join(skills_dir, skill_name)

        if os.path.exists(skill_dir):
            logger.warning(f"[Learning] skill目录已存在: {skill_name}")
            return await self._merge_to_skill(device_id, candidate, {
                "action": "merge_existing",
                "target_skill": skill_name,
            })

        os.makedirs(skill_dir, exist_ok=True)

        skill_content = await self._generate_skill_content(candidate)

        frontmatter = {
            "name": skill_name,
            "description": candidate.get("title", ""),
            "metadata": {
                "cap_groups": [],
                "manage_mode": "readonly",
                "category": [decision.get("category", "general")],
                "tags": candidate.get("tags", []),
                "source": "self_learning",
                "learned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

        content = f"---\n{json.dumps(frontmatter, ensure_ascii=False, indent=2)}\n---\n\n{skill_content}"

        skill_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 同步到 DB，让设备可以使用新skill
        await self._add_skill_to_device(device_id, skill_name)

        # 注册到 skill_system，让前端 API 和 LLM 能立即看到新skill
        try:
            from src.use_cases import skill_system as _skill_system
            _skill_system.reload()
            logger.info(f"[Learning] skill '{skill_name}' 已注册到技能系统")
        except Exception as e:
            logger.warning(f"[Learning] 注册skill到技能系统失败: {e}")

        await self._log_learning(device_id, "create", skill_name, candidate)
        logger.info(f"[Learning] 已创建新skill: {skill_name}")

        return skill_name

    async def _merge_to_skill(
        self,
        device_id: str,
        candidate: dict,
        decision: dict,
    ) -> Optional[str]:
        """合并到现有skill（带内容去重 + 大小上限，超限自动开新技能）"""
        skill_name = decision.get("target_skill", "")
        if not skill_name:
            return None

        skills_dir = self._get_skills_dir(device_id)
        skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")

        if not os.path.exists(skill_path):
            logger.warning(f"[Learning] 目标skill不存在: {skill_name}")
            return await self._create_new_skill(device_id, candidate, {
                "action": "create_new",
                "new_skill_name": skill_name,
                "category": decision.get("category", "general"),
            })

        with open(skill_path, "r", encoding="utf-8") as f:
            existing_content = f.read()

        new_title = candidate.get("title", "新知识")
        new_content = candidate.get("content", "")

        # 1) 去重：与已有内容重复则跳过，不再追加
        if self._is_duplicate(existing_content, new_content):
            logger.info(f"[Learning] 内容重复，跳过合并到 '{skill_name}': {new_title}")
            await self._log_learning(device_id, "skip_duplicate", skill_name, candidate)
            return None

        new_section = f"\n\n## {new_title}\n\n{new_content}"

        # 2) 大小上限：超限自动开新技能，避免单文件无限膨胀
        if len(existing_content) + len(new_section) > MAX_SKILL_SIZE:
            new_name = self._next_skill_name(device_id, skill_name)
            logger.info(f"[Learning] skill '{skill_name}' 已达大小上限，开新技能: {new_name}")
            return await self._create_new_skill(device_id, candidate, {
                "action": "create_new",
                "new_skill_name": new_name,
                "category": decision.get("category", "general"),
            })

        separator = "\n\n---\n"
        if separator in existing_content:
            parts = existing_content.rsplit(separator, 1)
            updated_content = parts[0] + separator + new_section
        else:
            updated_content = existing_content + new_section

        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        await self._log_learning(device_id, "merge", skill_name, candidate)
        logger.info(f"[Learning] 已合并到skill: {skill_name}")

        return skill_name

    def _is_duplicate(self, existing_content: str, new_content: str) -> bool:
        """判断新内容是否与已有内容重复（子串命中或逐段相似度过高）"""
        if not new_content or not new_content.strip():
            return True

        norm_new = re.sub(r"\s+", "", new_content)
        norm_existing = re.sub(r"\s+", "", existing_content)
        if norm_new and norm_new in norm_existing:
            return True

        for section in re.split(r"\n\s*##\s+", existing_content):
            section = section.strip()
            if not section or len(section) < 20:
                continue
            if text_similarity(section, new_content) >= MERGE_SIMILARITY_THRESHOLD:
                return True

        return False

    def _next_skill_name(self, device_id: str, base_name: str) -> str:
        """生成递增的新技能名（如 xxx_2、xxx_3），用于大小超限时开新技能"""
        skills_dir = self._get_skills_dir(device_id)
        n = 2
        while True:
            candidate = f"{base_name}_{n}"
            if not os.path.exists(os.path.join(skills_dir, candidate)):
                return candidate
            n += 1

    async def _generate_skill_content(self, candidate: dict) -> str:
        """生成skill内容"""
        if not self._llm_call:
            return candidate.get("content", "")

        category = candidate.get("category", "")
        if category == "self_growth":
            prompt = f"""
请根据以下AI自我认知的素材，生成一份完整的AI人格设定文档。

知识标题：{candidate.get('title', '')}
知识内容：{candidate.get('content', '')}

要求：
1. 用第一人称"我"来书写
2. 描述AI的性格特征、说话风格、行为准则
3. 包含AI对自己与用户关系的理解
4. 格式为markdown
5. 语气自然、真诚，像在写自述

返回完整的skill文档内容（不要包含frontmatter）。
"""
            system_msg = "你是一个AI人格设定专家，请帮助AI书写自我认知文档。"
        else:
            prompt = f"""
请根据以下知识创建一个skill文档。

知识标题：{candidate.get('title', '')}
知识内容：{candidate.get('content', '')}

要求：
1. 标题清晰
2. 步骤明确
3. 包含示例（如果适用）
4. 格式为markdown
5. 内容实用、易懂

返回完整的skill文档内容（不要包含frontmatter）。
"""
            system_msg = "你是一个技能文档编写专家，请创建清晰、实用的技能文档。"

        try:
            return await self._llm_call(system_msg, prompt)
        except Exception as e:
            logger.error(f"[Learning] 生成skill内容失败: {e}")
            return candidate.get("content", "")

    async def _get_existing_skills(self, device_id: str) -> list[dict]:
        """获取设备已有的skill列表"""
        skills_dir = self._get_skills_dir(device_id)
        if not os.path.exists(skills_dir):
            return []

        skills = []
        for entry in os.scandir(skills_dir):
            if not entry.is_dir():
                continue

            skill_path = os.path.join(entry.path, "SKILL.md")
            if not os.path.exists(skill_path):
                continue

            try:
                with open(skill_path, "r", encoding="utf-8") as f:
                    content = f.read()

                import re
                fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                if fm_match:
                    meta = json.loads(fm_match.group(1))
                    skills.append({
                        "id": entry.name,
                        "name": meta.get("name", entry.name),
                        "description": meta.get("description", ""),
                        "category": meta.get("metadata", {}).get("category", []),
                        "tags": meta.get("metadata", {}).get("tags", []),
                    })
            except Exception:
                continue

        return skills

    def _generate_skill_name(self, title: str) -> str:
        """从标题生成skill名称"""
        import re
        name = re.sub(r'[^\w\s]', '', title.lower())
        name = re.sub(r'\s+', '_', name.strip())
        return name[:32] if name else f"skill_{int(time.time())}"

    async def _add_skill_to_device(self, device_id: str, skill_name: str) -> None:
        """将新skill添加到设备配置的 skills 列表。

        调用 DeviceRepository.add_skill_to_device（异步）。
        """
        try:
            from src.infrastructure.db.repositories.device_repository import DeviceRepository
            repo = DeviceRepository()
            ok = await repo.add_skill_to_device(device_id, skill_name)
            if ok:
                logger.info(f"[Learning] 已将 skill '{skill_name}' 添加到 DB 设备 {device_id[:16]}")
                # 热重载在线设备配置
                self._hot_reload_device_config(device_id)
            else:
                logger.warning(f"[Learning] 在 DB 中找不到设备: {device_id}")
        except Exception as e:
            logger.error(f"[Learning] DB 添加 skill 失败: {e}")

    def _hot_reload_device_config(self, device_id: str) -> None:
        """热重载在线设备的配置，让新skill立即生效。

        阶段 3：数据源改为 DB（通过 load_devices()）。
        """
        try:
            from src.infrastructure.web import get_app
            app = get_app()
            if not app:
                return

            registry = getattr(app.state, 'device_registry', None)
            if not registry:
                return

            # 通过 device_key 或 MAC 找到设备
            device = registry.get_by_mac(device_id) or registry.resolve(device_id)
            if device and hasattr(device, 'user_config') and device.user_config:
                if hasattr(device.user_config, 'skills'):
                    # 从 DB 读取最新的设备配置
                    from src.use_cases.auxiliary_services import load_devices
                    dm = load_devices()
                    fresh_cfg = dm.resolve(device_id) or dm.devices.get(device_id)
                    if fresh_cfg and hasattr(fresh_cfg, 'skills'):
                        device.user_config.skills = getattr(fresh_cfg, 'skills', []) or []
                        logger.info(f"[Learning] 已热重载设备 {device_id[:16]} 的 skills 配置")
        except Exception as e:
            logger.warning(f"[Learning] 热重载设备配置失败: {e}")

    async def _log_learning(
        self,
        device_id: str,
        action: str,
        skill_name: str,
        candidate: dict,
    ) -> None:
        """记录学习日志

        阶段 3：改为调用 ``LearningLogRepository.append``（append-only + 修剪 100 条），
        替代 ``learning_log.json`` 的整体读写。DB 失败时仅记录日志，不中断业务。
        """
        log_entry = {
            "timestamp": time.time(),
            "action": action,
            "skill_name": skill_name,
            "title": candidate.get("title", ""),
            "category": candidate.get("category", ""),
        }

        try:
            await _learning_log_repo.append(device_id, log_entry)
        except Exception as e:
            logger.warning(f"[SelfLearning] DB 记录学习日志失败: {e}")

    @staticmethod
    def _parse_json(text: str) -> dict:
        """解析JSON，支持截断修复，确保始终返回 dict"""
        if not text:
            return {}

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                # LLM 返回了数组，尝试包装或取第一个元素
                logger.warning(f"[Learning] LLM返回了数组而非对象，长度={len(parsed)}")
                return {"user_info": {"new_facts": []}, "emotion": {}, "memories": [], "conversation_summary": ""}
            return parsed
        except json.JSONDecodeError:
            pass

        import re
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

            # 尝试修复截断的 JSON：补全缺失的闭合括号
            try:
                # 统计未闭合的括号
                open_braces = candidate.count('{') - candidate.count('}')
                open_brackets = candidate.count('[') - candidate.count(']')

                if open_braces > 0 or open_brackets > 0:
                    # 先尝试在最后一个完整的值后截断并补全
                    # 找最后一个逗号或冒号后的完整值
                    fixed = candidate.rstrip()

                    # 去掉尾部不完整的部分（如 "key": "val 后面没有引号和逗号）
                    # 尝试逐个字符回退，直到能解析
                    for i in range(len(fixed), max(start, len(fixed) - 200), -1):
                        trial = fixed[:i]
                        # 补全缺失的括号
                        ob = trial.count('{') - trial.count('}')
                        ok = trial.count('[') - trial.count(']')
                        if ob >= 0 and ok >= 0:
                            trial += ']' * ok + '}' * ob
                            try:
                                result = json.loads(trial)
                                if isinstance(result, dict):
                                    return result
                            except json.JSONDecodeError:
                                continue
            except Exception as e:
                logger.debug(f"[SelfLearning] JSON 修复解析失败: {e}")

        return {}
