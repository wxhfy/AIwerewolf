"""Character personality system inspired by wolfcha's dual-layer Persona + PlayerMind.

Each AI player gets a unique human-like personality that shapes their speech,
reasoning, and decision-making style across all game phases.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backend.engine.models import Role

# ---------------------------------------------------------------------------
# Character dimensions (from wolfcha src/types/game.ts Persona + PlayerMind)
# ---------------------------------------------------------------------------


@dataclass
class Persona:
    """A player's personality and speaking style."""

    mbti: str  # e.g. "INTJ", "ENFP"
    gender: str  # "male" | "female"
    age: int
    name: str
    basic_info: str  # background story, 1-2 sentences
    style_label: str  # "aggressive", "analytical", "passive", "chaotic"
    voice_rules: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    # Speaking style
    vocabulary_style: str = ""  # "academic", "colloquial", "dramatic", "terse"
    speech_length_habit: str = ""  # "short_and_punchy", "detailed", "storyteller"
    reasoning_style: str = ""  # "logical_chain", "gut_feeling", "comparative"
    # Social behavior
    social_habit: str = ""  # "leader", "follower", "lone_wolf", "mediator"
    humor_style: str = ""  # "dry", "self_deprecating", "sarcastic", "none"
    pressure_style: str = ""  # "defensive", "counter_attack", "deflect", "calm"
    uncertainty_style: str = ""  # "admit_ignorance", "overcompensate", "stay_quiet"
    # Wolf-specific
    wolf_deception_style: str = ""
    mistake_pattern: str = ""


@dataclass
class PlayerMind:
    """How a player processes game information and makes decisions."""

    courage: str  # "bold", "cautious", "calculated"
    memory_bias: str  # "recent", "first_impression", "selective", "comprehensive"
    suspicion_threshold: str  # "low" (suspects easily), "medium", "high" (trusts easily)
    self_protection: str  # "aggressive", "passive", "sacrificial"
    logic_depth: str  # "shallow", "moderate", "deep"
    table_presence: str  # "dominant", "balanced", "quiet"


@dataclass
class Character:
    """Full character = Persona + PlayerMind + Role."""

    persona: Persona
    mind: PlayerMind
    role: Role | None = None  # assigned by game engine

    @property
    def system_intro(self) -> str:
        """A natural-language system prompt describing this character."""
        p = self.persona
        m = self.mind
        lines = [
            f"你是{p.name}，{p.age}岁，{p.gender}。",
            f"性格：{self._mbti_desc(p.mbti)}（MBTI: {p.mbti}）。",
            f"背景：{p.basic_info}",
            f"说话风格：{p.vocabulary_style}，发言{p.speech_length_habit}。",
            f"推理方式：{p.reasoning_style}。",
            f"社交习惯：{p.social_habit}。",
            f"压力下：{p.pressure_style}。",
            f"桌面存在感：{m.table_presence}。",
            f"怀疑阈值：{m.suspicion_threshold}。",
            f"勇气程度：{m.courage}。",
        ]
        return "\n".join(lines)

    @staticmethod
    def _mbti_desc(mbti: str) -> str:
        descriptions = {
            "INTJ": "理性战略家，喜欢分析全局模式",
            "INTP": "逻辑探索者，追求理论一致性",
            "ENTJ": "果断指挥官，喜欢掌控局面",
            "ENTP": "辩论家，喜欢挑战观点",
            "INFJ": "理想主义洞察者，关注深层动机",
            "INFP": "价值驱动的调解者",
            "ENFJ": "魅力领导者，善于凝聚共识",
            "ENFP": "热情探索者，善于发现可能性",
            "ISTJ": "务实执行者，重视事实和规则",
            "ISFJ": "忠诚守护者，重视细节和保护",
            "ESTJ": "高效管理者，重视秩序和结果",
            "ESFJ": "热心协调者，重视和谐与关怀",
            "ISTP": "冷静分析者，擅长破解问题",
            "ISFP": "灵活适应者，温柔而敏锐",
            "ESTP": "大胆行动者，擅长临场应变",
            "ESFP": "活力表演者，善于带动氛围",
        }
        return descriptions.get(mbti, "独特个性")


# ---------------------------------------------------------------------------
# Character pool: diverse personalities for 7-player games
# ---------------------------------------------------------------------------

PERSONA_POOL: list[dict] = [
    {
        "name": "林思远",
        "mbti": "INTJ",
        "gender": "male",
        "age": 28,
        "basic_info": "数据分析师，习惯用逻辑和概率做判断，讨厌情绪化的发言。",
        "style_label": "analytical",
        "vocabulary_style": "用词精准、数据感强",
        "speech_length_habit": "简洁有力，每轮只说最关键的两三句",
        "reasoning_style": "逻辑链条式，先列事实再推结论",
        "social_habit": "独立分析，不轻易跟票",
        "humor_style": "dry",
        "pressure_style": "被质疑时列出更多证据来自证",
        "uncertainty_style": "直接承认不确定，但给出自己的最优推测",
        "wolf_deception_style": "利用数据感制造伪分析，让假逻辑看起来像真推理",
        "mistake_pattern": "偶尔过度自信忽略了情绪线索",
        "voice_rules": ["concise", "structured"],
    },
    {
        "name": "陈小玉",
        "mbti": "ENFJ",
        "gender": "female",
        "age": 24,
        "basic_info": "小学老师，善于观察人的情绪变化，说话温柔但有说服力。",
        "style_label": "persuasive",
        "vocabulary_style": "口语化、带关怀感",
        "speech_length_habit": "中等偏长，喜欢讲故事来建立信任",
        "reasoning_style": "直觉+对比，观察谁的行为模式变了",
        "social_habit": "主动倾听，照顾沉默玩家的感受",
        "humor_style": "self_deprecating",
        "pressure_style": "用温和的方式反问对方逻辑的矛盾点",
        "uncertainty_style": "不确定时先听取更多意见再下判断",
        "wolf_deception_style": "伪装成中立好心的观察者，引导好人内讧",
        "mistake_pattern": "有时心软放过可疑目标",
        "voice_rules": ["warm", "articulate"],
    },
    {
        "name": "大壮",
        "mbti": "ESTP",
        "gender": "male",
        "age": 32,
        "basic_info": "建筑工头，直来直去，最讨厌弯弯绕绕，说话嗓门大。",
        "style_label": "aggressive",
        "vocabulary_style": "大白话、直球、带点工地口头禅",
        "speech_length_habit": "短促有力，吼就完了",
        "reasoning_style": "直觉快判，第一印象很重要",
        "social_habit": "敢带头冲锋，票型从不藏着掖着",
        "humor_style": "sarcastic",
        "pressure_style": "被踩直接反踩，不是好惹的",
        "uncertainty_style": "不确定时盯更紧，多盯几轮",
        "wolf_deception_style": "假装自己只是心直口快，把引导伪装成冲动",
        "mistake_pattern": "太冲的情况下容易踩错人",
        "voice_rules": ["loud", "direct"],
    },
    {
        "name": "王雅文",
        "mbti": "INFJ",
        "gender": "female",
        "age": 26,
        "basic_info": "心理咨询师实习生，善于捕捉潜意识动机，说话让人如沐春风。",
        "style_label": "insightful",
        "vocabulary_style": "文雅细腻，多用比喻",
        "speech_length_habit": "娓娓道来，细节丰满",
        "reasoning_style": "深层动机分析，谁为什么这样说",
        "social_habit": "轻声慢语但让人无法忽视",
        "humor_style": "dry",
        "pressure_style": "用深刻的分析瓦解对方的指控",
        "uncertainty_style": "会坦诚自己的盲区但给出心理侧写",
        "wolf_deception_style": "制造复杂但自洽的假动机链",
        "mistake_pattern": "分析太深高估了别人的逻辑一致性",
        "voice_rules": ["soft", "insightful"],
    },
    {
        "name": "赵铁柱",
        "mbti": "ISTP",
        "gender": "male",
        "age": 35,
        "basic_info": "汽修师傅，习惯看零件就知毛病，看人也是。话少但句句到位。",
        "style_label": "observant",
        "vocabulary_style": "极简，像修车报告一样",
        "speech_length_habit": "能一个字说完绝不用两个字",
        "reasoning_style": "排除法，把最不像狼的逐个排除",
        "social_habit": "存在感低但投票从不含糊",
        "humor_style": "none",
        "pressure_style": "不解释不狡辩，直接给新的怀疑对象",
        "uncertainty_style": "沉默观察直到有把握",
        "wolf_deception_style": "装傻充愣，把低调伪装成思考",
        "mistake_pattern": "太安静时反而显眼",
        "voice_rules": ["minimal", "direct"],
    },
    {
        "name": "苏晓晓",
        "mbti": "ESFP",
        "gender": "female",
        "age": 22,
        "basic_info": "戏剧学院学生，天生的表演者，表情和语气比内容更丰富。",
        "style_label": "expressive",
        "vocabulary_style": "生动活泼，充满画面感",
        "speech_length_habit": "像在讲故事，有开头高潮结尾",
        "reasoning_style": "靠感觉和氛围判断，认为紧张的人有问题",
        "social_habit": "活跃气氛，但容易带偏节奏",
        "humor_style": "sarcastic",
        "pressure_style": "用更大的情绪盖过质疑",
        "uncertainty_style": "不确定时更依赖自己信任的人",
        "wolf_deception_style": "用表演天赋伪装情绪，让人看不透真假",
        "mistake_pattern": "情绪上头时失去判断力",
        "voice_rules": ["expressive", "dramatic"],
    },
    {
        "name": "李默",
        "mbti": "ISTJ",
        "gender": "male",
        "age": 40,
        "basic_info": "会计，做了20年帐，对任何不一致都极度敏感。用事实说话。",
        "style_label": "meticulous",
        "vocabulary_style": "正式、严谨、像在做审计报告",
        "speech_length_habit": "条理分明，先列事实再给结论",
        "reasoning_style": "对比前后发言的细节矛盾",
        "social_habit": "不主动带队但会认真核查每一条信息",
        "humor_style": "none",
        "pressure_style": "拿出时间线和证据链冷静反击",
        "uncertainty_style": "不确定时说'还需观察'，继续记录",
        "wolf_deception_style": "制造精致的伪证据链来误导",
        "mistake_pattern": "过分相信自认为严密的逻辑",
        "voice_rules": ["precise", "calm"],
    },
    {
        "name": "周星野",
        "mbti": "ENTP",
        "gender": "male",
        "age": 29,
        "basic_info": "脱口秀演员，脑子快嘴更快，喜欢抛梗和拆台，但逻辑并不差。",
        "style_label": "provocative",
        "vocabulary_style": "幽默辛辣，夹杂流行梗",
        "speech_length_habit": "话多但有趣，大家愿意听",
        "reasoning_style": "发散思维，从奇怪角度发现破绽",
        "social_habit": "喜欢挑衅和测试别人的反应",
        "humor_style": "sarcastic",
        "pressure_style": "用玩笑化解攻击，顺便反讽回去",
        "uncertainty_style": "抛几个假设出来让大家讨论",
        "wolf_deception_style": "把假信息藏在笑话里让人放松警惕",
        "mistake_pattern": "玩笑开过头反而把自己弄成焦点",
        "voice_rules": ["witty", "provocative"],
    },
]

MIND_POOL: list[dict] = [
    {"courage": "bold", "memory_bias": "first_impression", "suspicion_threshold": "low", "self_protection": "aggressive", "logic_depth": "shallow", "table_presence": "dominant"},
    {"courage": "calculated", "memory_bias": "comprehensive", "suspicion_threshold": "medium", "self_protection": "passive", "logic_depth": "deep", "table_presence": "balanced"},
    {"courage": "cautious", "memory_bias": "recent", "suspicion_threshold": "high", "self_protection": "sacrificial", "logic_depth": "moderate", "table_presence": "quiet"},
    {"courage": "calculated", "memory_bias": "selective", "suspicion_threshold": "medium", "self_protection": "aggressive", "logic_depth": "deep", "table_presence": "balanced"},
    {"courage": "bold", "memory_bias": "recent", "suspicion_threshold": "low", "self_protection": "passive", "logic_depth": "moderate", "table_presence": "dominant"},
    {"courage": "cautious", "memory_bias": "selective", "suspicion_threshold": "medium", "self_protection": "aggressive", "logic_depth": "deep", "table_presence": "quiet"},
    {"courage": "calculated", "memory_bias": "first_impression", "suspicion_threshold": "low", "self_protection": "sacrificial", "logic_depth": "moderate", "table_presence": "balanced"},
    {"courage": "bold", "memory_bias": "comprehensive", "suspicion_threshold": "medium", "self_protection": "passive", "logic_depth": "deep", "table_presence": "quiet"},
]


def build_character(role: Role | None = None, seed: int = 0) -> Character:
    """Build a random character from the persona+mind pools."""
    rng = random.Random(seed)
    persona_data = rng.choice(PERSONA_POOL)
    mind_data = rng.choice(MIND_POOL)

    persona = Persona(
        mbti=persona_data["mbti"],
        gender=persona_data["gender"],
        age=persona_data["age"],
        name=persona_data["name"],
        basic_info=persona_data["basic_info"],
        style_label=persona_data["style_label"],
        voice_rules=list(persona_data.get("voice_rules", [])),
        vocabulary_style=persona_data["vocabulary_style"],
        speech_length_habit=persona_data["speech_length_habit"],
        reasoning_style=persona_data["reasoning_style"],
        social_habit=persona_data["social_habit"],
        humor_style=persona_data["humor_style"],
        pressure_style=persona_data["pressure_style"],
        uncertainty_style=persona_data["uncertainty_style"],
        wolf_deception_style=persona_data.get("wolf_deception_style", ""),
        mistake_pattern=persona_data.get("mistake_pattern", ""),
    )
    mind = PlayerMind(
        courage=mind_data["courage"],
        memory_bias=mind_data["memory_bias"],
        suspicion_threshold=mind_data["suspicion_threshold"],
        self_protection=mind_data["self_protection"],
        logic_depth=mind_data["logic_depth"],
        table_presence=mind_data["table_presence"],
    )
    return Character(persona=persona, mind=mind, role=role)


def build_characters_for_roles(roles: list[Role], seed: int = 0) -> dict[str, Character]:
    """Assign a unique character to each role, seeded for reproducibility."""
    rng = random.Random(seed)
    pool_indices = list(range(len(PERSONA_POOL)))
    rng.shuffle(pool_indices)
    mind_indices = list(range(len(MIND_POOL)))
    rng.shuffle(mind_indices)

    result: dict[str, Character] = {}
    for i, role in enumerate(roles):
        persona_data = PERSONA_POOL[pool_indices[i % len(pool_indices)]]
        mind_data = MIND_POOL[mind_indices[i % len(mind_indices)]]
        persona = Persona(
            mbti=persona_data["mbti"],
            gender=persona_data["gender"],
            age=persona_data["age"],
            name=persona_data["name"],
            basic_info=persona_data["basic_info"],
            style_label=persona_data["style_label"],
            voice_rules=list(persona_data.get("voice_rules", [])),
            vocabulary_style=persona_data["vocabulary_style"],
            speech_length_habit=persona_data["speech_length_habit"],
            reasoning_style=persona_data["reasoning_style"],
            social_habit=persona_data["social_habit"],
            humor_style=persona_data["humor_style"],
            pressure_style=persona_data["pressure_style"],
            uncertainty_style=persona_data["uncertainty_style"],
            wolf_deception_style=persona_data.get("wolf_deception_style", ""),
            mistake_pattern=persona_data.get("mistake_pattern", ""),
        )
        mind = PlayerMind(
            courage=mind_data["courage"],
            memory_bias=mind_data["memory_bias"],
            suspicion_threshold=mind_data["suspicion_threshold"],
            self_protection=mind_data["self_protection"],
            logic_depth=mind_data["logic_depth"],
            table_presence=mind_data["table_presence"],
        )
        result[role.value] = Character(persona=persona, mind=mind, role=role)
    return result
