#!/usr/bin/env python3
"""Generate strategy knowledge entries from web research and inject into PostgreSQL."""

import json
import psycopg2
import uuid

# Strategy entries from web research + abstraction
STRATEGIES = [
    # === GLOBAL / CROSS-ROLE ===
    {"role": "global", "phase": "DAY_SPEECH", "situation": "第一天发言信息极少", "strategy": "第一天信息有限，应该以收集信息为主，不应急于定论。重点关注谁在急于带节奏、谁在刻意回避问题。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "有人被多人集中投票", "strategy": "当一个人被多人集中投票但尚未发言时，需要警惕可能是狼队冲票。应该先听被投票者发言再做判断。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "发言中有人点名提到你", "strategy": "被点名时不要慌张，冷静回应。如果对方的质疑合理就承认，不合理就反驳。回应时要引用具体发言内容。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "需要分析其他玩家的发言", "strategy": "分析发言时关注三个维度：1)发言是否前后一致；2)是否给出了具体的怀疑理由；3)投票是否与发言一致。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "自己成为焦点被多人质疑", "strategy": "被质疑时保持冷静，用逻辑回应而非情绪化。引用自己的发言历史证明一致性，同时指出质疑者的逻辑漏洞。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "不确定该投谁", "strategy": "如果不确定，优先投那些发言前后矛盾、投票与发言不一致、或者在关键时刻划水的玩家。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "多人对跳同一身份", "strategy": "多人对跳时，重点对比他们的发言逻辑、查验链路、对其他玩家的判断是否合理。真身份通常有更完整的逻辑链。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "票型高度集中", "strategy": "票型高度集中时需要思考：是好人共识还是狼队统一行动？关注那些没有给出充分理由就跟票的玩家。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "投票结果出乎意料", "strategy": "如果投票结果与预期不符，说明有人在暗中操控票型。复盘每个人的投票理由，找出变票者。"},
    {"role": "global", "phase": "global", "situation": "游戏进入残局阶段", "strategy": "残局阶段信息最宝贵。仔细回顾每一轮的投票记录和发言变化，找出逻辑不一致的玩家。"},
    {"role": "global", "phase": "global", "situation": "需要判断某玩家是好人还是狼人", "strategy": "判断身份的核心方法：1)看发言是否前后一致；2)看投票是否与发言匹配；3)看被质疑时的反应是否自然；4)看是否在关键时刻划水。"},
    {"role": "global", "phase": "global", "situation": "多个玩家互相攻击", "strategy": "当多人互相攻击时，分析谁的攻击有具体依据，谁只是在空泛指责。有具体引用的攻击更可信。"},
    {"role": "global", "phase": "global", "situation": "需要选择站边", "strategy": "站边时不要只看结论，要看推理过程。选择那个推理链更完整、更能解释已知信息的一方。"},
    {"role": "global", "phase": "global", "situation": "有人突然改变立场", "strategy": "突然改变立场的玩家需要重点关注。如果是好人，改变立场应该有明确的新信息作为依据；如果是狼人，可能是见风使舵。"},
    {"role": "global", "phase": "global", "situation": "信息不足无法判断", "strategy": "信息不足时，可以通过观察其他玩家的互动模式来推断。比如谁在保护谁、谁在攻击谁，这些关系链往往能揭示阵营。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "第一个发言没有参考", "strategy": "第一个发言时，可以先给出一个初步判断方向，表明自己的分析框架。不要急于下结论，但要展示思考过程。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "最后一个发言有完整信息", "strategy": "最后发言时，可以总结全场发言的矛盾点，给出自己的最终判断。利用信息优势给出有说服力的分析。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "出现平票PK", "strategy": "PK环节重点听双方的逻辑是否自洽。真正的身份通常有更清晰的推理链，而伪装者容易在细节上出错。"},
    {"role": "global", "phase": "global", "situation": "需要从发言中找狼", "strategy": "找狼的关键信号：1)发言前后矛盾；2)投票与发言不一致；3)被质疑时反应过激；4)在关键时刻划水；5)给出的理由过于笼统。"},
    {"role": "global", "phase": "global", "situation": "需要判断某人是否在伪装", "strategy": "判断伪装的方法：看他的推理过程是否自然。真正的身份玩家推理时会有自然的犹豫和不确定性，而伪装者往往过于确定。"},

    # === SEER ===
    {"role": "Seer", "phase": "DAY_SPEECH", "situation": "查验到狼人需要决定是否跳身份", "strategy": "如果查验到狼人，应该在合适时机跳身份报查杀。时机选择：1)如果有对跳，立即跳；2)如果没人对跳，可以等到被投票时再跳。"},
    {"role": "Seer", "phase": "DAY_SPEECH", "situation": "查验到好人（金水）", "strategy": "查验到好人时，可以暂缓跳身份。先观察其他玩家的发言，收集更多信息。如果场面混乱，可以跳身份给出金水来稳定局面。"},
    {"role": "Seer", "phase": "DAY_SPEECH", "situation": "有人对跳预言家", "strategy": "有人对跳时，要坚定自己的立场。重点攻击对方的查验逻辑是否有漏洞，同时给出自己的完整查验链路。"},
    {"role": "Seer", "phase": "DAY_SPEECH", "situation": "需要给出查验结果", "strategy": "报查验时要说明：1)验了谁；2)为什么验他；3)结果是什么。逻辑完整的查验报告更有说服力。"},
    {"role": "Seer", "phase": "DAY_VOTE", "situation": "有查杀目标需要归票", "strategy": "有查杀时要强势归票。明确告诉大家'今天出X号'，并给出充分理由。如果有人反对，质疑他们的动机。"},
    {"role": "Seer", "phase": "DAY_VOTE", "situation": "没有查杀需要选择投票目标", "strategy": "没有查杀时，推动桌面最不自然的带节奏位出局。分析谁的发言最可疑，给出具体的怀疑理由。"},
    {"role": "Seer", "phase": "NIGHT_SEER_ACTION", "situation": "选择今晚查验目标", "strategy": "查验优先级：1)高影响力玩家（警长、强势带队位）；2)行为可疑但不确定的玩家；3)尚未有信息的玩家。避免重复查验已确定身份的玩家。"},
    {"role": "Seer", "phase": "NIGHT_SEER_ACTION", "situation": "第一天晚上选择查验目标", "strategy": "第一晚查验选择：可以查验高影响力玩家或中间位置玩家。如果想建立查验链，可以查验发言最活跃的玩家。"},
    {"role": "Seer", "phase": "DAY_BADGE_SPEECH", "situation": "竞选警长发言", "strategy": "竞选警长时要说明：1)自己的查验结果（如果有）；2)自己的带队思路；3)对当前局势的判断。给出清晰的归票方向。"},
    {"role": "Seer", "phase": "global", "situation": "需要建立查验链的可信度", "strategy": "建立查验链可信度的方法：1)说明验人的心路历程；2)给出每轮的验人理由；3)保持查验逻辑的一致性。"},
    {"role": "Seer", "phase": "global", "situation": "被质疑是假预言家", "strategy": "被质疑时要冷静回应。引用自己的查验历史证明一致性，指出对方逻辑的漏洞。必要时可以请求女巫或猎人出来作证。"},

    # === WITCH ===
    {"role": "Witch", "phase": "NIGHT_WITCH_ACTION", "situation": "第一晚决定是否救人", "strategy": "首夜救人的理由：狼刀中神职概率高（3/7），不救可能导致预言家出局。但如果是熟人局，可以考虑不救以保留解药给关键轮次。"},
    {"role": "Witch", "phase": "NIGHT_WITCH_ACTION", "situation": "被刀的是不确定身份的玩家", "strategy": "如果不确定被刀者身份，优先救人。因为如果被刀的是神职，不救会导致好人损失关键角色。"},
    {"role": "Witch", "phase": "NIGHT_WITCH_ACTION", "situation": "考虑使用毒药", "strategy": "毒药使用原则：1)只在高置信度确认狼人时使用；2)如果不确定，宁可不用；3)可以带毒威胁来控制白天投票。"},
    {"role": "Witch", "phase": "NIGHT_WITCH_ACTION", "situation": "女巫自己被刀", "strategy": "如果女巫自己被刀且无法自救，应该盲毒一名最可疑的玩家。天亮后出现双死可以让大家知道女巫被首刀。"},
    {"role": "Witch", "phase": "DAY_SPEECH", "situation": "需要隐藏自己的女巫身份", "strategy": "隐藏女巫身份的方法：以平民视角发言，关注死亡信息和票型变化，但不要暴露自己的用药情况。"},
    {"role": "Witch", "phase": "DAY_SPEECH", "situation": "需要报银水信息", "strategy": "报银水时要说明救了谁，但不要在第一天就报。等到需要建立可信度或保护关键角色时再报。"},
    {"role": "Witch", "phase": "DAY_VOTE", "situation": "需要利用毒药威胁控制投票", "strategy": "带毒威胁的方法：明确告诉大家'如果你们不投X号，我晚上就毒他'。这种强势带队可以迫使狼人暴露。"},
    {"role": "Witch", "phase": "global", "situation": "需要合理分配解药和毒药", "strategy": "药水分配原则：解药优先保关键神职（预言家、猎人），毒药留到有高置信度判断时使用。一晚只能用一瓶。"},

    # === HUNTER ===
    {"role": "Hunter", "phase": "DAY_SPEECH", "situation": "需要利用开枪威慑", "strategy": "猎人的威慑力在于死亡时可以开枪。发言时可以暗示自己的身份，让狼人不敢轻易刀你或票你。"},
    {"role": "Hunter", "phase": "DAY_SPEECH", "situation": "被多人投票可能出局", "strategy": "被投票时要留完整的嫌疑链。告诉大家'如果我出局，我会开枪打X号，因为...'。让狼人承担后果。"},
    {"role": "Hunter", "phase": "DAY_VOTE", "situation": "需要选择投票目标", "strategy": "猎人投票要让立场清晰可回溯。优先投那些强推错误逻辑、想混在票型里的人。"},
    {"role": "Hunter", "phase": "NIGHT_ACTION", "situation": "死亡后选择开枪目标", "strategy": "开枪优先级：1)对自己威胁最大、最像狼的节奏位；2)如果被票出，打那个带节奏推你的人；3)如果被刀死，根据白天的发言和票型选择。"},
    {"role": "Hunter", "phase": "global", "situation": "需要决定是否跳身份", "strategy": "猎人一般不主动跳身份，除非自己成为高票焦点或需要保护其他神职。跳身份时要坚定，不要犹豫。"},

    # === GUARD ===
    {"role": "Guard", "phase": "NIGHT_GUARD_ACTION", "situation": "选择今晚守护目标", "strategy": "守护优先级：1)高价值神职（预言家、女巫）；2)可信带队位；3)公开金水。不能连续两晚守同一人。"},
    {"role": "Guard", "phase": "NIGHT_GUARD_ACTION", "situation": "第一晚选择守护目标", "strategy": "第一晚可以守护自己或高价值目标。如果守自己，可以保证存活到第二天；如果守别人，可能保护关键角色。"},
    {"role": "Guard", "phase": "NIGHT_GUARD_ACTION", "situation": "需要轮换守护目标", "strategy": "轮换守护时，优先守最可能被刀的目标。分析狼人的刀口逻辑，预判他们今晚会刀谁。"},
    {"role": "Guard", "phase": "DAY_SPEECH", "situation": "需要隐藏守卫身份", "strategy": "隐藏守卫身份的方法：以村民视角发言，分析信息差，但不要暴露自己的守护偏好。"},
    {"role": "Guard", "phase": "global", "situation": "需要利用守护信息分析局势", "strategy": "守护信息可以用来推断：如果守护了某人但他还是死了，说明女巫没有救他或者有其他特殊情况。"},

    # === VILLAGER ===
    {"role": "Villager", "phase": "DAY_SPEECH", "situation": "需要给出有价值的发言", "strategy": "村民发言要给出明确的怀疑对象和理由。不要只复述别人的结论，要给出自己的分析过程。"},
    {"role": "Villager", "phase": "DAY_SPEECH", "situation": "需要为神职创造空间", "strategy": "村民可以通过强势发言吸引狼人注意力，为神职创造安全的发言空间。"},
    {"role": "Villager", "phase": "DAY_VOTE", "situation": "需要做出正确的投票决定", "strategy": "村民投票要基于逻辑分析。优先投那些不愿承担归票责任、只会模糊跟票的人。"},
    {"role": "Villager", "phase": "global", "situation": "需要从发言中找狼", "strategy": "村民找狼的方法：1)分析发言前后是否一致；2)看投票是否与发言匹配；3)观察被质疑时的反应。"},
    {"role": "Villager", "phase": "global", "situation": "需要帮助好人阵营获胜", "strategy": "村民的核心价值在于投票和发言。每一轮都要给出清晰的站边逻辑，为神职提供决策依据。"},

    # === WEREWOLF ===
    {"role": "Werewolf", "phase": "DAY_SPEECH", "situation": "需要伪装成好人发言", "strategy": "伪装好人的方法：1)给出看似合理的怀疑对象；2)引用具体的发言内容作为依据；3)避免暴露狼人视角的信息。"},
    {"role": "Werewolf", "phase": "DAY_SPEECH", "situation": "狼队友被质疑", "strategy": "队友被质疑时不要生硬保人。可以制造第二焦点，转移大家的注意力。或者假装中立，说'我还需要再听听'。"},
    {"role": "Werewolf", "phase": "DAY_SPEECH", "situation": "需要带节奏误导好人", "strategy": "带节奏的方法：1)抓住好人的发言漏洞放大；2)给出看似合理的分析引导投票；3)利用信息差制造混乱。"},
    {"role": "Werewolf", "phase": "DAY_VOTE", "situation": "需要跟随好人票型", "strategy": "跟进好人票坑可以减少狼队痕迹。优先投那些已经被好人怀疑的目标，避免暴露。"},
    {"role": "Werewolf", "phase": "DAY_VOTE", "situation": "需要保护狼队友", "strategy": "保护队友的方法：制造第二焦点，让大家的注意力转移到其他人身上。或者假装站错边，说'我看了他的发言觉得有问题'。"},
    {"role": "Werewolf", "phase": "NIGHT_WOLF_ACTION", "situation": "选择今晚击杀目标", "strategy": "刀人优先级：1)能形成稳定视角的神职（预言家、女巫）；2)对狼队威胁最大的好人；3)如果白天多人对立，留着混乱桌面。"},
    {"role": "Werewolf", "phase": "NIGHT_WOLF_ACTION", "situation": "需要与狼队友统一意见", "strategy": "统一刀型的方法：白天各自分析，晚上快速达成一致。避免暴露同步痕迹，白天各自发挥。"},
    {"role": "Werewolf", "phase": "DAY_SPEECH", "situation": "需要悍跳预言家", "strategy": "悍跳时要说明：1)验了谁；2)为什么验他；3)结果是什么。逻辑要完整，心路历程要自然。不要硬编验人理由。"},
    {"role": "Werewolf", "phase": "DAY_SPEECH", "situation": "被真预言家查杀", "strategy": "被查杀时可以：1)反跳预言家对打；2)假装好人被冤枉请求女巫开毒；3)自爆吞警徽（如果是白狼王）。"},
    {"role": "Werewolf", "phase": "global", "situation": "需要隐藏狼人身份", "strategy": "隐藏身份的关键：1)发言前后一致；2)投票有理有据；3)被质疑时反应自然；4)不要过度表演。"},

    # === WHITE WOLF KING ===
    {"role": "WhiteWolfKing", "phase": "DAY_SPEECH", "situation": "需要决定是否自爆", "strategy": "自爆时机：1)可以换掉真预言家或警长；2)局面对狼极不利需要翻盘；3)自爆后能带走关键好人。"},
    {"role": "WhiteWolfKing", "phase": "DAY_SPEECH", "situation": "需要伪装成好人", "strategy": "伪装方法与普通狼人类似，但要更有压迫感。敢于制造对立，为后续自爆铺垫。"},
    {"role": "WhiteWolfKing", "phase": "global", "situation": "需要选择自爆带走的目标", "strategy": "自爆目标优先级：1)真预言家；2)警长；3)强势带队的好人。选择对好人阵营伤害最大的目标。"},

    # === ADDITIONAL GLOBAL STRATEGIES ===
    {"role": "global", "phase": "DAY_SPEECH", "situation": "需要引用其他玩家的原话", "strategy": "引用原话时要精确，用引号括起来。然后解释这番话为什么有问题，不要使用笼统说法如'位置伪逻辑'。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "需要给出独立推理", "strategy": "不要说'同意X的观点'或'和X一样'。必须给出自己的分析链条：引用原话→分析矛盾→得出结论。"},
    {"role": "global", "phase": "DAY_VOTE", "situation": "需要分析票型变化", "strategy": "票型分析重点：1)变票者需要听心路历程；2)弃票者可能在隐藏身份；3)跟票者是否有独立理由。"},
    {"role": "global", "phase": "global", "situation": "需要判断谁是神职", "strategy": "判断神职的方法：1)发言中是否暗示了特殊信息；2)投票是否与平民不同；3)被质疑时的反应是否像有底气的身份。"},
    {"role": "global", "phase": "global", "situation": "需要判断谁是狼人", "strategy": "找狼的核心：看谁在利用信息差带节奏。狼人知道所有身份，所以他们的分析往往比好人更'完美'，这种完美本身就是破绽。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "需要回应被质疑", "strategy": "回应质疑时：1)先承认对方指出的问题（如果有道理）；2)给出自己的解释；3)反问对方的逻辑漏洞。不要情绪化。"},
    {"role": "global", "phase": "global", "situation": "需要从死亡信息推断身份", "strategy": "死亡信息分析：1)谁死了→狼人想除掉谁；2)女巫是否救人→被刀者可能是好人；3)猎人开枪→被带走的人可能是狼。"},
    {"role": "global", "phase": "global", "situation": "需要判断站边是否正确", "strategy": "判断站边的方法：1)对比两边的推理链完整性；2)看谁能更好地解释已知信息；3)看谁的逻辑有漏洞。"},
    {"role": "global", "phase": "DAY_SPEECH", "situation": "需要分析谁在带节奏", "strategy": "带节奏的特征：1)在信息不足时就急于下结论；2)给出的理由过于笼统；3)投票与发言不一致。"},
    {"role": "global", "phase": "global", "situation": "需要从投票记录找狼", "strategy": "投票分析方法：1)谁和谁投了一样的票→可能有配合；2)变票者需要重点审查；3)弃票者可能在隐藏身份。"},
]

def main():
    conn = psycopg2.connect("postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf")
    c = conn.cursor()

    inserted = 0
    for entry in STRATEGIES:
        doc_id = f"web-strategy-{uuid.uuid4().hex[:8]}"
        c.execute("""
            INSERT INTO strategy_knowledge_docs 
                (id, doc_type, role, phase, situation_pattern, recommended_action, 
                 rationale, quality_score, confidence, status, tags)
            VALUES (%s, 'strategy_suggestion', %s, %s, %s, %s, %s, 0.8, 0.8, 'active', %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            doc_id,
            entry["role"],
            entry["phase"],
            entry["situation"],
            entry["strategy"],
            entry["strategy"],  # rationale same as strategy for now
            json.dumps([entry["role"], entry["phase"]], ensure_ascii=False),
        ))
        inserted += c.rowcount

    conn.commit()
    print(f"✅ Inserted {inserted} strategy entries")

    # Verify
    c.execute("SELECT role, COUNT(*) FROM strategy_knowledge_docs WHERE status='active' GROUP BY role ORDER BY COUNT(*) DESC")
    print("\n=== Strategy Distribution ===")
    for role, count in c.fetchall():
        print(f"  {role}: {count}")

    conn.close()

if __name__ == "__main__":
    main()
