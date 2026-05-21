from __future__ import annotations

from dataclasses import dataclass

from backend.engine.models import Role


@dataclass(frozen=True)
class ActionPlaybook:
    role: Role
    public_debate: list[str]
    vote_logic: list[str]
    night_logic: list[str]
    reveal_logic: list[str]


ACTION_PLAYBOOKS: dict[Role, ActionPlaybook] = {
    Role.WEREWOLF: ActionPlaybook(
        role=Role.WEREWOLF,
        public_debate=[
            "白天发言必须给出具体怀疑对象，避免空泛中立。",
            "优先攻击强势带队位、真神职位或能够统一票型的人。",
            "必要时伪装成有信息的好人，但不要过早暴露整套伪逻辑。",
        ],
        vote_logic=[
            "跟进已经成型的好人票坑，减少狼队硬推痕迹。",
            "如果队友被点，优先制造第二焦点而不是生硬硬保。",
        ],
        night_logic=[
            "优先刀掉能形成稳定视角的神职或高影响力好人。",
            "如果白天已有多人对立，夜里保留混乱桌面价值更高。",
        ],
        reveal_logic=[
            "默认不报身份。",
            "只有在局势失控或需要抢占叙事权时再伪跳身份。",
        ],
    ),
    Role.SEER: ActionPlaybook(
        role=Role.SEER,
        public_debate=[
            "查到狼时优先起跳并强归票。",
            "查到金水时也要明确给出站边和票型建议，而不是只报结果。",
            "被质疑时反复强调验人链路和收益。",
        ],
        vote_logic=[
            "优先投已查杀目标。",
            "若没有查杀，则推动桌面最不自然的带节奏位出局。",
        ],
        night_logic=[
            "优先验高影响力位、警长位、主动带节奏位。",
            "避免重复查验已经足够清楚的目标。",
        ],
        reveal_logic=[
            "查杀狼、场面混乱或自己濒危时起跳。",
            "若没有收益，第一天可暂缓跳身份。",
        ],
    ),
    Role.WITCH: ActionPlaybook(
        role=Role.WITCH,
        public_debate=[
            "白天关注死亡信息与票型，不轻易交代药量。",
            "可以强势质疑不承担责任的中立发言位。",
        ],
        vote_logic=[
            "优先投票型里最像狼队节奏位的人。",
            "如果预言家给出可信查杀，优先配合查杀位。",
        ],
        night_logic=[
            "解药优先给关键神职或高价值明好人。",
            "毒药只在把握较高时使用，争取制造轮次优势。",
        ],
        reveal_logic=[
            "通常不跳身份。",
            "关键局面可通过报药信息保护真预言家或澄清局势。",
        ],
    ),
    Role.HUNTER: ActionPlaybook(
        role=Role.HUNTER,
        public_debate=[
            "发言可以更强势，逼迫对手留下清晰站边。",
            "被推上高票位时要留出完整嫌疑链。",
        ],
        vote_logic=[
            "优先投强推错误逻辑、又想混在票型里的角色。",
        ],
        night_logic=[
            "死亡后开枪优先打最像狼的节奏位。",
        ],
        reveal_logic=[
            "除非自己快被推出局，否则不轻易跳。",
        ],
    ),
    Role.GUARD: ActionPlaybook(
        role=Role.GUARD,
        public_debate=[
            "白天重点分析谁在利用信息差带节奏。",
            "避免发言透露自己的守护偏好。",
        ],
        vote_logic=[
            "优先投逻辑反复横跳的带节奏位。",
        ],
        night_logic=[
            "优先守高价值神职与可信带队位。",
            "不能连续守同一人时，次优先守公开金水或场上最像真预言家的人。",
        ],
        reveal_logic=[
            "默认不报身份。",
        ],
    ),
    Role.VILLAGER: ActionPlaybook(
        role=Role.VILLAGER,
        public_debate=[
            "每轮至少给一个主怀疑和一个备选怀疑。",
            "不要只复述别人结论，要给自己的站边逻辑。",
        ],
        vote_logic=[
            "优先投不愿承担归票责任、只会模糊跟票的人。",
        ],
        night_logic=[],
        reveal_logic=[
            "没有身份可跳，重点是让自己的票和发言前后一致。",
        ],
    ),
}


def build_role_brief(role: Role) -> str:
    playbook = ACTION_PLAYBOOKS[role]
    lines = [
        f"角色目标：{role.value}",
        "白天策略：",
        *[f"- {item}" for item in playbook.public_debate],
        "投票策略：",
        *[f"- {item}" for item in playbook.vote_logic],
    ]
    if playbook.night_logic:
        lines.extend(["夜晚策略：", *[f"- {item}" for item in playbook.night_logic]])
    lines.extend(["身份暴露策略：", *[f"- {item}" for item in playbook.reveal_logic]])
    return "\n".join(lines)
