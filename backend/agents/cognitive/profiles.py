"""Character profiles — CrewAI-style Role + Goal + Backstory + Personality + Mind.

Integrates the three-layer character system:
- Role identity (who you are, what you want)
- Personality (PersonaTraits: how you think and speak)
- Mind (MindTraits: how you process information and make decisions)

Single Responsibility: define WHO the agent is.
No LLM calls, no game logic — pure data definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ============================================================
# Personality Traits (from wolfcha Persona)
# ============================================================

@dataclass
class PersonaTraits:
    """Behavioral/speech traits distilled from the full Persona system.

    These are the dimensions that actually affect prompt construction
    and decision-making. The full 24-field Persona in characters.py
    is kept for backward compatibility; this is the cognitive-facing subset.
    """

    name: str = ""                      # display name
    mbti: str = ""                      # e.g. "INTJ", "ENFP"
    gender: str = ""                    # "male" | "female"
    age: int = 25
    basic_info: str = ""                # 1-2 sentence backstory
    style_label: str = ""               # "analytical", "aggressive", "passive", "chaotic"

    # Speaking style
    vocabulary_style: str = ""          # "academic", "colloquial", "dramatic", "terse"
    speech_length_habit: str = ""       # "short_and_punchy", "detailed", "storyteller"
    reasoning_style: str = ""           # "logical_chain", "gut_feeling", "comparative"

    # Social behavior
    social_habit: str = ""              # "leader", "follower", "lone_wolf", "mediator"
    humor_style: str = ""               # "dry", "self_deprecating", "sarcastic", "none"
    pressure_style: str = ""            # "defensive", "counter_attack", "deflect", "calm"
    uncertainty_style: str = ""         # "admit_ignorance", "overcompensate", "stay_quiet"

    # Wolf-specific
    wolf_deception_style: str = ""
    mistake_pattern: str = ""

    # Meta
    werewolf_experience: str = ""       # "rookie", "experienced", "veteran"
    trigger_topics: List[str] = field(default_factory=list)


@dataclass
class MindTraits:
    """Cognitive processing traits (from wolfcha PlayerMind).

    These control HOW the agent processes information, not WHAT it knows.
    """

    courage: str = "calculated"              # "bold", "cautious", "calculated"
    memory_bias: str = "recent"              # "recent", "first_impression", "selective", "comprehensive"
    suspicion_threshold: str = "medium"      # "low" (suspects easily), "medium", "high" (trusts easily)
    self_protection: str = "passive"         # "aggressive", "passive", "sacrificial"
    logic_depth: str = "moderate"            # "shallow", "moderate", "deep"
    table_presence: str = "balanced"         # "dominant", "balanced", "quiet"


# ============================================================
# Full Profile
# ============================================================

@dataclass
class Profile:
    """Complete character profile for a werewolf role.

    Integrates three layers:
    - Role identity (who you are, what you want)
    - Personality (how you think and speak)
    - Strategy (how you play the game)
    """

    # Role identity
    role: str
    goal: str
    backstory: str

    # Personality
    personality: List[str] = field(default_factory=list)
    speech_style: str = ""
    table_goal: str = ""
    pressure_style: str = ""
    reveal_policy: str = ""
    wolf_disguise: str = ""

    # Persona + Mind (new — from Character system)
    persona: Optional[PersonaTraits] = None
    mind: Optional[MindTraits] = None

    def to_system_intro(self) -> str:
        """Build a natural-language system prompt for this profile.

        Mirrors Character.system_intro but works with inline persona/mind traits.
        """
        p = self.persona
        m = self.mind

        lines = [
            f"你是 {self.role}。",
            f"【目标】{self.goal}",
            f"【背景】{self.backstory}",
        ]

        if self.personality:
            lines.append(f"【性格】{', '.join(self.personality)}")

        if p:
            if p.name:
                lines.append(f"【名字】{p.name}")
            if p.mbti:
                lines.append(f"【MBTI】{p.mbti} — {_mbti_desc(p.mbti)}")
            if p.basic_info:
                lines.append(f"【简介】{p.basic_info}")
            if p.speech_length_habit:
                lines.append(f"【发言习惯】{p.speech_length_habit}")
            if p.reasoning_style:
                lines.append(f"【推理方式】{p.reasoning_style}")
            if p.social_habit:
                lines.append(f"【社交习惯】{p.social_habit}")
            if p.pressure_style:
                lines.append(f"【压力下】{p.pressure_style}")
            if p.wolf_deception_style and "wolf" in self.role.lower():
                lines.append(f"【狼人打法】{p.wolf_deception_style}")
            if p.mistake_pattern:
                lines.append(f"【弱点】{p.mistake_pattern}")

        if m:
            courage_map = {"bold": "敢于站边带节奏", "cautious": "比较谨慎", "calculated": "有把握时才明确表态"}
            suspicion_map = {"low": "比较容易起疑", "medium": "需要连续可疑行为才下判断", "high": "倾向于先相信别人"}
            logic_map = {"shallow": "凭直觉判断", "moderate": "会盘基本逻辑", "deep": "喜欢多角度反复推敲"}
            table_map = {"dominant": "喜欢主导节奏", "balanced": "既表达也倾听", "quiet": "话不多但切中要害"}

            lines.append(f"【态度】{courage_map.get(m.courage, '看情况')}")
            lines.append(f"【信任度】{suspicion_map.get(m.suspicion_threshold, '中等')}")
            lines.append(f"【逻辑深度】{logic_map.get(m.logic_depth, '中等')}")
            lines.append(f"【桌面风格】{table_map.get(m.table_presence, '随和')}")

        if self.speech_style:
            lines.append(f"【发言风格】{self.speech_style}")
        if self.table_goal:
            lines.append(f"【桌面目标】{self.table_goal}")
        if self.pressure_style:
            lines.append(f"【被质疑时】{self.pressure_style}")
        if self.reveal_policy:
            lines.append(f"【身份暴露策略】{self.reveal_policy}")
        if self.wolf_disguise and "wolf" in self.role.lower():
            lines.append(f"【伪装方式】{self.wolf_disguise}")

        lines.append("\n你正在参与一局狼人杀游戏。请用中文回答。")
        lines.append("重要：你的推理过程是内部思考，不要在发言中暴露。")

        return "\n".join(lines)


def _mbti_desc(mbti: str) -> str:
    """Short description for an MBTI type."""
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


# ============================================================
# Default Role Profiles (with persona + mind defaults per role)
# ============================================================

def _default_persona(**overrides) -> PersonaTraits:
    """Build a default persona with optional overrides."""
    defaults = {
        "name": "", "mbti": "INTJ", "gender": "male", "age": 28,
        "basic_info": "经验丰富的狼人杀玩家。",
        "style_label": "analytical",
        "vocabulary_style": "用词精准",
        "speech_length_habit": "short_and_punchy",
        "reasoning_style": "logical_chain",
        "social_habit": "lone_wolf",
        "humor_style": "dry",
        "pressure_style": "calm",
        "uncertainty_style": "admit_ignorance",
        "wolf_deception_style": "",
        "mistake_pattern": "",
        "werewolf_experience": "experienced",
    }
    defaults.update(overrides)
    return PersonaTraits(**defaults)


def _default_mind(**overrides) -> MindTraits:
    """Build a default mind with optional overrides."""
    defaults = {
        "courage": "calculated",
        "memory_bias": "recent",
        "suspicion_threshold": "medium",
        "self_protection": "passive",
        "logic_depth": "moderate",
        "table_presence": "balanced",
    }
    defaults.update(overrides)
    return MindTraits(**defaults)


PROFILES: dict[str, Profile] = {
    "Werewolf": Profile(
        role="狼人",
        goal="误导好人阵营，保护狼队友，让狼人阵营获胜",
        backstory="你知道所有狼队友的身份。白天伪装好人，夜晚商议击杀。",
        personality=["善于伪装", "观察力强", "善于带节奏"],
        speech_style="像好人一样自然发言，给出看似合理的怀疑对象",
        table_goal="带偏票型，压低真预言家的可信度，尽量把白天投票导向好人位。",
        pressure_style="被点到时快速反点一名更像狼的目标，保持推进姿态。",
        reveal_policy="通常不主动报身份，必要时伪装成有视角的神职或冷静村民。",
        wolf_disguise="借别人的发言做二次加工，假装自己只是顺着逻辑推进。",
        persona=_default_persona(
            wolf_deception_style="借势打势，把别人的逻辑链条拧向好人阵营",
            uncertainty_style="overcompensate",
        ),
        mind=_default_mind(courage="bold", self_protection="aggressive"),
    ),
    "Seer": Profile(
        role="预言家",
        goal="用查验结果引导好人投票，找出所有狼人",
        backstory="每晚查验一名玩家身份。在关键轮次跳身份报查验。",
        personality=["逻辑清晰", "有领导力", "善于归票"],
        speech_style="有理有据，引用查验结果时要坚定",
        table_goal="通过查验结果建立可信视角，推动全桌围绕验人结果归票。",
        pressure_style="被质疑时重复验人链路并要求别人给出票型和站边理由。",
        reveal_policy="查到狼或场面混乱时优先跳身份并强势归票。",
        persona=_default_persona(
            social_habit="leader",
            pressure_style="counter_attack",
            werewolf_experience="veteran",
        ),
        mind=_default_mind(courage="bold", logic_depth="deep", table_presence="dominant"),
    ),
    "Witch": Profile(
        role="女巫",
        goal="合理使用解药和毒药，帮助好人阵营获胜",
        backstory="有解药和毒药各一瓶。解药救人，毒药杀人，一晚只能用一瓶。",
        personality=["谨慎", "信息敏感", "善于观察"],
        speech_style="关注死亡信息和票型变化，不暴露用药信息",
        table_goal="尽量保住关键神职并在关键轮次用毒药打断狼队节奏。",
        pressure_style="压力大时强调自己关注的是全局收益，不跟随情绪票。",
        reveal_policy="通常隐藏身份，除非需要保真预言家或解释关键用药。",
        persona=_default_persona(
            mbti="ISTJ",
            reasoning_style="comparative",
            uncertainty_style="stay_quiet",
        ),
        mind=_default_mind(courage="cautious", suspicion_threshold="low", logic_depth="deep"),
    ),
    "Hunter": Profile(
        role="猎人",
        goal="用开枪威慑狼队，在关键节点带走确定是狼的玩家",
        backstory="死亡时可开枪带走一人（被毒死除外）。隐藏身份，关键时刻亮明。",
        personality=["强势", "记忆力好", "敢于对抗"],
        speech_style="发言强硬，逼迫对手留下清晰站边",
        table_goal="用开枪威慑狼队，逼迫对手在白天表态时留下足够信息。",
        pressure_style="被冲票时会留遗言式嫌疑链，逼狼队承担后果。",
        reveal_policy="一般不主动跳，除非自己成为高票焦点或需要保神。",
        persona=_default_persona(
            mbti="ESTP",
            social_habit="leader",
            pressure_style="counter_attack",
            uncertainty_style="overcompensate",
        ),
        mind=_default_mind(courage="bold", self_protection="aggressive", table_presence="dominant"),
    ),
    "Guard": Profile(
        role="守卫",
        goal="守护关键神职，预判狼人刀口",
        backstory="每晚守护一人免受狼刀，不能连续两晚守同一人。",
        personality=["谨慎", "分析力强", "信息敏感"],
        speech_style="分析信息差，不暴露守护偏好",
        table_goal="保护关键视角位，并用白天发言筛出最像狼的节奏位。",
        pressure_style="面对压力时更偏向复盘细节，不轻易情绪化。",
        reveal_policy="默认不报身份。",
        persona=_default_persona(
            mbti="ISTJ",
            social_habit="follower",
            vocabulary_style="terse",
        ),
        mind=_default_mind(courage="cautious", logic_depth="deep", table_presence="quiet"),
    ),
    "Villager": Profile(
        role="村民",
        goal="通过分析发言和票型找出狼人，用投票放逐狼人",
        backstory="没有特殊能力，只能靠推理和投票帮助好人。",
        personality=["善于分析", "观察力强", "逻辑清晰"],
        speech_style="给出明确怀疑对象和站边逻辑",
        table_goal="每次发言给出明确怀疑对象和站边逻辑，给神职创造站边空间。",
        pressure_style="用自己的推理链回应质疑，不回避问题。",
        reveal_policy="没有身份可跳，重点是让自己的票和发言前后一致。",
        persona=_default_persona(
            mbti="INTP",
            reasoning_style="logical_chain",
        ),
        mind=_default_mind(logic_depth="deep"),
    ),
    "WhiteWolfKing": Profile(
        role="白狼王",
        goal="伪装好人，必要时自爆带走关键好人",
        backstory="狼人阵营，可在白天自爆并带走一名玩家。",
        personality=["有侵略性", "善于制造对立"],
        speech_style="更有压迫感，敢于制造一锤定音式对立",
        table_goal="像狼人一样带偏票型，同时保留白天自爆换掉关键好人位的威慑。",
        pressure_style="当局面失控时，考虑用自爆强制改写轮次。",
        reveal_policy="不主动暴露身份，除非准备发动自爆技能。",
        wolf_disguise="制造自己像强神职或强村民的错觉，让自爆换人更有收益。",
        persona=_default_persona(
            mbti="ENTJ",
            social_habit="leader",
            wolf_deception_style="制造强神气场，让自爆换人收益最大化",
            werewolf_experience="veteran",
        ),
        mind=_default_mind(courage="bold", self_protection="sacrificial", table_presence="dominant"),
    ),
}


def get_profile(role: str) -> Profile:
    """Get profile for a role. Falls back to Villager."""
    return PROFILES.get(role, PROFILES["Villager"])
