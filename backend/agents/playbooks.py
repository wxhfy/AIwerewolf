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
    # White Wolf King — a wolf with a one-shot self-destruct that takes one
    # villager out simultaneously. Strategy is wolf-like in the day but adds
    # the boom timing decision; we keep the day playbook close to plain wolf.
    Role.WHITE_WOLF_KING: ActionPlaybook(
        role=Role.WHITE_WOLF_KING,
        public_debate=[
            "白天发言节奏跟标准狼一致：制造怀疑、混票坑、不暴露身份。",
            "若已被预言家查杀或场上局势对狼极不利，可考虑在白天发言阶段提前自爆带走核心好人。",
        ],
        vote_logic=[
            "跟好人主流票坑，避免让自己成为狼队的唯一硬保对象。",
            "若局面已锁定要出狼，宁可弃票或转投他人。",
        ],
        night_logic=[
            "夜里不参与刀人投票（自爆是日间技能），但可统一狼队认知。",
        ],
        reveal_logic=[
            "默认不报身份。",
            "只有在自爆瞬间才暴露白狼王身份，并锁定一个核心好人带走。",
        ],
    ),
    # Idiot — village alignment, his vote does not count but he survives being
    # voted out the FIRST time (then becomes a vote-disabled villager). His
    # strength is information: revealing post-exile clears one slot of suspicion.
    Role.IDIOT: ActionPlaybook(
        role=Role.IDIOT,
        public_debate=[
            "白天发言不要硬跳预言家或猎人——一旦伪跳就失去翻牌优势。",
            "正常给出怀疑对象和站边逻辑，让好人愿意带你一起归票。",
        ],
        vote_logic=[
            "你的票不计入归票，但要表态明确，避免被当作摇摆位推走。",
        ],
        night_logic=[],
        reveal_logic=[
            "只在被投出去触发翻牌时被动暴露身份；不要主动跳白痴。",
            "翻牌后失去投票权，重心转为信息交换和保护神职。",
        ],
    ),
    # ----------------------------------------------------------------------
    # Template roles below — playable=False in the registry. Playbooks ship
    # so the LLM has strategy text the moment any of these gets wired up; the
    # engine doesn't route their abilities yet so they won't appear in any
    # WOLFCHA_ROLE_CONFIGS entry.
    # ----------------------------------------------------------------------
    # Cupid — village; night 0 picks two lovers. When one of the lovers dies
    # the other dies too. Strong influence but no daytime tells beyond
    # voting carefully to protect both lovers.
    Role.CUPID: ActionPlaybook(
        role=Role.CUPID,
        public_debate=[
            "白天伪装成普通村民，避免暴露挑选情侣的视角。",
            "情侣若进入高票位，可侧面引导别的怀疑对象出局。",
        ],
        vote_logic=[
            "优先投像狼的发言位，但避免把票投到自己挑的情侣身上。",
        ],
        night_logic=[
            "第 0 夜挑选两名情侣，优先选互相能形成视角的好人组合。",
            "之后夜里无技能，按好人逻辑参与白天即可。",
        ],
        reveal_logic=[
            "情侣关系暴露会失去隐蔽优势，除非殉情发生不要主动跳。",
        ],
    ),
    # Big Bad Wolf — wolf; once all four village gods (Seer/Witch/Hunter/Guard)
    # are dead, gets a solo extra kill on top of the pack's nightly kill.
    Role.BIG_BAD_WOLF: ActionPlaybook(
        role=Role.BIG_BAD_WOLF,
        public_debate=[
            "白天发言节奏与普通狼一致，不暗示自己掌握额外刀杀。",
            "神职即将全部死亡时，避免在白天暴露过强的攻击性，防止被针对。",
        ],
        vote_logic=[
            "和狼队一致把票导向好人位，避免出现狼内分票。",
        ],
        night_logic=[
            "神职全亡前严格按狼队投票刀人。",
            "神职全亡后挑选最具威胁的好人独立追刀，制造好人阵营崩盘节奏。",
        ],
        reveal_logic=[
            "默认不跳，神职全亡后也不必暴露技能，让额外死亡看起来像普通狼刀。",
        ],
    ),
    # Wolf Cub — wolf; if killed by villagers (vote or witch poison), wolves
    # gain a second kill the following night. Useful to absorb suspicion.
    Role.WOLF_CUB: ActionPlaybook(
        role=Role.WOLF_CUB,
        public_debate=[
            "发言风格类似普通狼，必要时可吸引票位换取下一晚双刀。",
            "避免硬撕队友，让自己的死亡看起来像好人的成功验证。",
        ],
        vote_logic=[
            "可以接受被推上高票位以触发双刀收益，但要评估剩余狼力是否承担得起。",
        ],
        night_logic=[
            "夜里按狼队节奏行动，不暴露自己的死亡触发机制。",
        ],
        reveal_logic=[
            "默认不跳；死亡当日狼队即获得加成，无需主动暴露身份。",
        ],
    ),
    # Wolf King — wolf; on any death (except poison) shoots one player.
    # Mirrors Hunter from the opposing side.
    Role.WOLF_KING: ActionPlaybook(
        role=Role.WOLF_KING,
        public_debate=[
            "可以使用更具压迫感的发言节奏，让好人忌惮投票后的反杀。",
            "必要时伪装成猎人或预言家骗信任。",
        ],
        vote_logic=[
            "跟好人主流票坑减少痕迹，避免被狼队队友单独保护。",
        ],
        night_logic=[
            "和狼队一同选择刀杀目标，不必特别保留自己。",
        ],
        reveal_logic=[
            "被投出局时再确定开枪目标，重点带走带队位或验出狼的关键好人。",
        ],
    ),
    # Knight — village; one-shot daytime duel. Risky but information-rich.
    Role.KNIGHT: ActionPlaybook(
        role=Role.KNIGHT,
        public_debate=[
            "发言要给出清晰的怀疑链，让决斗的目标有充分依据。",
            "决斗前最好让对方再发言一次，减少误杀风险。",
        ],
        vote_logic=[
            "可以延迟到决斗后再发力投票，使决斗结果直接影响票型。",
        ],
        night_logic=[],
        reveal_logic=[
            "决斗发动瞬间被动跳身份；不到时机不要主动暴露。",
        ],
    ),
    # Elder — village; first wolf attack fails. Easy to hide first night.
    Role.ELDER: ActionPlaybook(
        role=Role.ELDER,
        public_debate=[
            "发言风格平稳，不暗示自己的免疫机制。",
            "第二天若意外存活而其他人死亡，可侧面引导好人继续怀疑攻击者。",
        ],
        vote_logic=[
            "按好人逻辑投票，避免因为身份特殊而显得过于自信。",
        ],
        night_logic=[],
        reveal_logic=[
            "若第一次被刀未死，可以择机暴露身份以稳定好人节奏。",
        ],
    ),
}


def build_role_brief(role: Role) -> str:
    # Defensive lookup: if a role is added to engine.rules but not yet given a
    # playbook, fall back to a generic village/wolf brief based on alignment
    # so the agent can still play instead of crashing the whole game.
    playbook = ACTION_PLAYBOOKS.get(role)
    if playbook is None:
        return f"角色目标：{role.value}\n（该角色暂无专属策略指引，请按基本身份逻辑发言/投票，避免暴露身份信息。）"
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
