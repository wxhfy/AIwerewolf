"""Ingest strategies from Doubao extraction + classic community knowledge
directly into the PostgreSQL strategy_knowledge_docs table.

Run: python scripts/ingest_strategies.py [--dry-run]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import StrategyKnowledgeDoc as SKDModel


def load_doubao_strategies(path: str = "data/health/doubao_strategies.json") -> list[dict]:
    raw = json.loads((ROOT / path).read_text(encoding="utf-8"))
    docs: list[dict] = []
    for role, data in raw.items():
        if "strategies" not in data:
            continue
        for s in data["strategies"]:
            docs.append(
                {
                    "role": role,
                    "doc_type": "good_play",
                    "phase": s.get("phase", "mid_game"),
                    "trigger": s.get("trigger", ""),
                    "action": s.get("action", ""),
                    "rationale": s.get("rationale", ""),
                    "common_mistake": s.get("common_mistake", ""),
                    "priority": s.get("priority", "medium"),
                    "source": "doubao_llm_extraction",
                    "evidence": s.get("source_evidence", ""),
                }
            )
    return docs


def load_classic_strategies() -> list[dict]:
    """Classic werewolf strategies from community knowledge base."""
    return [
        # === Seer ===
        {
            "role": "Seer",
            "doc_type": "good_play",
            "phase": "night_1",
            "priority": "high",
            "trigger": "预言家首夜，需要选择查验目标",
            "action": "优先查验后置位警上玩家或身边顺手位。警上验人可以给后置位定义身份，力度最大；警下验出金水可以拉票。避免验女巫/猎人/守卫等可以自证的牌。",
            "rationale": "查验后置位警上玩家能最大化信息价值——验出查杀可直接归票，验出金水可拉票拿警徽。验无关神牌浪费验人次数。",
            "common_mistake": "首验容易自证的神牌（女巫/猎人/守卫），浪费验人机会。",
            "source": "classic_community",
        },
        {
            "role": "Seer",
            "doc_type": "good_play",
            "phase": "day_1",
            "priority": "high",
            "trigger": "预言家第一天警上发言，需要抢警徽",
            "action": "发言三要素缺一不可：报查验（金水/查杀）+ 留警徽流（至少2晚：1警上+1警下）+ 聊验人心路历程。先说查验结果，再留警徽流，防止狼自爆吞信息。",
            "rationale": "警徽是预言家传递信息的命脉。不报查验=白验人，不留警徽流=自爆即吞全部信息，不聊心路=好人无法认下。",
            "common_mistake": "警徽流只留1晚或不留；第一天怒点四狼导致打到好人被怀疑站边。",
            "source": "classic_community",
        },
        {
            "role": "Seer",
            "doc_type": "good_play",
            "phase": "mid_game",
            "priority": "high",
            "trigger": "面对悍跳狼对跳预言家",
            "action": "从三个维度对比真假预言家：(1)验人逻辑是否自洽 (2)发言是否暴露上帝视角 (3)票型团队面——真预言家孤立，悍跳狼有团队。查杀力度大于金水，果断带队归票。",
            "rationale": "真预言家信息有限但真实，悍跳狼信息无限但需演。从不信任的预言家发言中找逻辑漏洞是最有效的辨别方式。",
            "common_mistake": "被悍跳狼气势压倒后语速突变、结巴——好人直接认不下。被悍跳狼点到漏洞时心态失衡。",
            "source": "classic_community",
        },
        # === Witch ===
        {
            "role": "Witch",
            "doc_type": "good_play",
            "phase": "night_1",
            "priority": "high",
            "trigger": "女巫首夜，收到刀口信息",
            "action": "开解药救人（主流策略）。12人局首夜救人利大于弊——救到好人概率7/11远高于救狼4/11。无论是否自刀，保证警推在先、打乱狼人刀人节奏。有守卫的局更应首夜用药，避免同守同救。",
            "rationale": "不救可能导致预言家首夜被刀，轮次直接落后。即使救到自刀狼也只是回到了自由发言轮次，损失可控。",
            "common_mistake": "首夜不开药导致预言家/关键神被首刀，好人数落后一轮。",
            "source": "classic_community",
        },
        {
            "role": "Witch",
            "doc_type": "good_play",
            "phase": "mid_game",
            "priority": "high",
            "trigger": "女巫持毒药，需要决定毒人时机和目标",
            "action": "毒药三原则：(1)确定是狼才毒 (2)第2-3夜是最佳开毒窗口——太早看不清、太晚可能闷药 (3)宁可闷药也别乱毒。毒药优先级：穿女巫衣服的狼 > 发言爆狼的明狼 > 乱带节奏的疑似狼。绝对不要毒对跳预言家的任何一方。",
            "rationale": "毒错一个好人 = 浪费解药 + 误杀好人 = 顶狼人两夜成果。毒对跳预言家='一死一买单'只会让好人失去验人信息。",
            "common_mistake": "不确定时盲目开毒；毒对跳预言家导致好人失去信息核心；过早暴露女巫身份被狼优先刀闷双药。",
            "source": "classic_community",
        },
        {
            "role": "Witch",
            "doc_type": "good_play",
            "phase": "day_1",
            "priority": "medium",
            "trigger": "女巫双药在手时参与白天发言",
            "action": "以平民视角发言，不能说漏刀位信息（'我知道昨晚谁被刀'直接聊爆）。解药用掉、毒药在手时再起跳带队，报银水排狼坑。银水要高度关注但不轻易发好人身份——银水也可能是自刀狼。",
            "rationale": "隐藏身份的双药女巫是狼人的最大威胁。过早暴露=狼优先刀=闷掉双药。",
            "common_mistake": "过早暴露女巫身份；被救后的银水盲目认好（可能自刀狼骗药）。",
            "source": "classic_community",
        },
        # === Guard ===
        {
            "role": "Guard",
            "doc_type": "good_play",
            "phase": "night_1",
            "priority": "high",
            "trigger": "守卫首夜，需要决定守护目标",
            "action": "空守（有女巫时强制空守）。避免与女巫首夜解药冲突导致'奶穿'（同守同救=被守护的玩家依然死亡）。空守保留后续灵活度，方便后续'守→救→守'循环保护预言家。",
            "rationale": "首夜守人与女巫解药冲突概率高，一旦奶穿损失两轮防守资源。空守是最稳妥的起手。",
            "common_mistake": "首夜自守（有女巫时）与女巫解药冲突+第二晚不能自守；首夜守他人同样有奶穿风险。",
            "source": "classic_community",
        },
        {
            "role": "Guard",
            "doc_type": "good_play",
            "phase": "mid_game",
            "priority": "high",
            "trigger": "预言家已明身份，需要持续保护",
            "action": "守护优先级：双药女巫 > 单药女巫/明预言家 > 自守（身份暴露后）> 站错队的猎人 > 空守。核心是与狼人进行心理博弈——预判狼人的预判。守出平安夜后空守一回合，因为狼人大概率追刀同一目标。",
            "rationale": "守卫活着就是对狼人最大的威慑。隐藏身份比守对人更重要——前期伪装平民，'躲刀、躲验、躲毒、躲票、躲带'。",
            "common_mistake": "连续两晚守同一人（规则禁止）；第一天全盘托出守人信息暴露身份；无脑赌命守人不基于逻辑预判。",
            "source": "classic_community",
        },
        # === Hunter ===
        {
            "role": "Hunter",
            "doc_type": "good_play",
            "phase": "day_1",
            "priority": "high",
            "trigger": "猎人前期，身份未暴露",
            "action": "前期伪装成'有点想法的平民'，暗中观察谁在推你、谁在保你。枪没开的时候才是最可怕的，跳明身份等于告诉狼人'最后再来刀我'。首夜被刀建议闷枪——首夜信息为零，盲带极大概率误伤神职。",
            "rationale": "猎人的核心价值是威慑力而非枪。狼不敢杀有枪的未知猎人=无限生存期。",
            "common_mistake": "开局就跳猎人——狼把你当最后目标，整局开不出枪；首夜被刀盲带导致误伤神职崩盘。",
            "source": "classic_community",
        },
        {
            "role": "Hunter",
            "doc_type": "good_play",
            "phase": "late_game",
            "priority": "high",
            "trigger": "猎人出局，需要选择开枪目标",
            "action": "开枪带人优先级：对跳猎人的狼（穿你衣服的）> 确定是狼的玩家 > 疑似深水狼 > 放弃开枪（闷枪）。绝对不带走神职是猎人的底线。被悍跳狼查杀时不要带走悍跳狼——你已经自证了，带走帮他拉票、死站他边的人命中率极高。",
            "rationale": "能开枪已经自证了身份。带悍跳狼浪费一枪杀已暴露的狼。带站边悍跳狼最坚定的人=一猎换两狼。",
            "common_mistake": "带走对跳预言家浪费一枪；带走上一个站错队的好人；被女巫毒了开不了枪。",
            "source": "classic_community",
        },
        # === Werewolf ===
        {
            "role": "Werewolf",
            "doc_type": "good_play",
            "phase": "day_1",
            "priority": "high",
            "trigger": "狼人第一天，需要决定是否悍跳预言家",
            "action": "必须悍跳，不悍跳等于送好人赢。12人局狼人不悍跳的话，真预言家畅通无阻验3-4轮，狼队全裸。发言最好、逻辑最稳的狼队友负责悍跳。悍跳时严格遵循预言家发言模板，不能暴露'上帝视角'（已知所有身份的信息量）。",
            "rationale": "悍跳是狼人杀的灵魂。不悍跳=给真预言家自由验人=狼队必输。",
            "common_mistake": "不悍跳直接送好人赢；悍跳时信息爆炸（'我知道他没验对'——只有狼人能说出这种话）。",
            "source": "classic_community",
        },
        {
            "role": "Werewolf",
            "doc_type": "good_play",
            "phase": "night_1",
            "priority": "high",
            "trigger": "狼人首夜，需要决定刀人目标和团队分工",
            "action": "四狼分工协作：(1)悍跳狼上警对跳预言家抢警徽 (2)冲锋狼无脑支持悍跳狼冲票 (3)倒钩狼站边真预言家博取信任 (4)深水狼全程假装平民混入决赛圈。关键轮次四狼抱团冲票要齐。刀人优先级：预言家 > 女巫 > 守卫 > 猎人。",
            "rationale": "狼狼建立对立面是核心逻辑——让好人逻辑爆炸。分工明确才能各司其职。",
            "common_mistake": "四狼裸冲（全部上票给悍跳狼）团队面暴露；不建立狼狼对立面导致一损俱损。",
            "source": "classic_community",
        },
        {
            "role": "Werewolf",
            "doc_type": "good_play",
            "phase": "mid_game",
            "priority": "medium",
            "trigger": "需要获取信任或逆转劣势",
            "action": "自刀策略已成为现代标准战术（95%+女巫首夜开药）。自刀人选优先：发言好的高配玩家。自刀后两种路线：(1)上警悍跳（银水加持可信度）(2)不上警倒钩真预言家（坐高身份）。悍跳狼被真预言家拿到警徽且劣势时，果断自爆吞警徽遗言。",
            "rationale": "银水身份在多数局面下相当于金水——极难被抗推。自爆可以吞掉关键信息的遗言，让狼队获得轮次优势。",
            "common_mistake": "自刀后发言前后不一致被识破；非关键轮次随意自爆浪费狼队友。",
            "source": "classic_community",
        },
        # === Villager ===
        {
            "role": "Villager",
            "doc_type": "good_play",
            "phase": "day_1",
            "priority": "high",
            "trigger": "村民白天发言，需要表明立场",
            "action": "站边就是你的能力，投票就是你的技能。每次发言至少包含：表明站边及理由 + 点评前置位 + 投票意向。言行必须一致（踩了A却投B=直接被打成狼）。不划水、不说'过'、不沉默。12人局只有4个村民，地位丝毫不比神职低。",
            "rationale": "村民是好人票数的基石。4个村民全部认真发言=4票锁定狼坑。划水=被标狼抗推=送狼轮次。",
            "common_mistake": "发言划水只说'过'被标狼抗推；在自己没聊清楚时盘狼坑；随便认出（'我是民出我也行'）直接送狼赢。",
            "source": "classic_community",
        },
        {
            "role": "Villager",
            "doc_type": "good_play",
            "phase": "mid_game",
            "priority": "high",
            "trigger": "需要判断谁是狼人",
            "action": "三步找狼法：(1)认悍跳狼——从对跳预言家中找出逻辑不自洽、视野过宽的一方 (2)抓冲锋狼——为悍跳狼号票冲锋铁站边的 (3)抓倒钩狼——视角过于清晰、完全不聊某个明显可疑玩家的、站边过于死的。票型不会骗人——看谁无脑跟票、谁抱团。",
            "rationale": "好人没有团队，狼人有团队。票型是比发言更可靠的狼人信号。站边不站死，错了就认——发现不对劲马上站回来。",
            "common_mistake": "盲目跟风警长/他人失去独立判断；情绪化投票（被打就报复性投回去）不是好人逻辑；一条道走到黑站错边不回头。",
            "source": "classic_community",
        },
        {
            "role": "Villager",
            "doc_type": "good_play",
            "phase": "late_game",
            "priority": "medium",
            "trigger": "进入决赛圈，需要做排除法",
            "action": "从剩余玩家中排除法锁定最后一狼：排除已证神牌 > 排除公认好人 > 排除查验金水 > 对比剩余玩家发言前后一致性。积极表水，珍惜底牌。复盘前期票型找团队面。",
            "rationale": "村民在残局的表水和判断能力直接决定胜负。没有技能不等于没有价值——信息处理能力是最强武器。",
            "common_mistake": "残局放弃思考跟风投票；忽略票型回顾这个最可靠的狼人信号。",
            "source": "classic_community",
        },
    ]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clear-existing", action="store_true", help="Remove existing community/doubao docs before insert")
    args = ap.parse_args()

    print("Loading strategies...")
    doubao_docs = load_doubao_strategies()
    classic_docs = load_classic_strategies()
    all_items = doubao_docs + classic_docs
    print(f"  Doubao: {len(doubao_docs)}, Classic: {len(classic_docs)}, Total: {len(all_items)}")

    if args.dry_run:
        for d in all_items:
            print(f"  [{d['source'][:12]:12s}] {d['role']:<10s} {d['phase']:<12s} {d['trigger'][:60]}")
        return 0

    init_db()
    db = SessionLocal()
    try:
        if args.clear_existing:
            deleted = db.execute(
                text(
                    "DELETE FROM strategy_knowledge_docs WHERE tags::text LIKE '%doubao_llm%' OR tags::text LIKE '%classic_community%'"
                )
            )
            db.commit()
            print(f"  Cleared {deleted.rowcount} existing docs")

        count = 0
        for i, d in enumerate(all_items):
            source_tag = "doubao_llm" if "doubao" in d["source"] else "classic_community"
            doc_id = f"strat-{source_tag}-{d['role'].lower()}-{i:03d}"

            # Check if exists
            existing = db.query(SKDModel).filter(SKDModel.id == doc_id).first()
            if existing:
                continue

            row = SKDModel(
                id=doc_id,
                doc_type=d["doc_type"],
                role=d["role"],
                phase=d.get("phase", "mid_game"),
                situation_pattern=d.get("trigger", ""),
                trigger_conditions=[d.get("trigger", "")],
                recommended_action=d.get("action", ""),
                avoid_action=d.get("common_mistake", ""),
                rationale=d.get("rationale", ""),
                evidence_summary=d.get("evidence", d.get("rationale", "")),
                quality_score=0.85 if "doubao" in d["source"] else 0.90,
                confidence=0.80,
                status="active",
                tags=[source_tag, f"priority:{d.get('priority', 'medium')}", f"role:{d['role']}"],
            )
            db.add(row)
            count += 1

        db.commit()
        print(f"  Inserted {count} new docs (skipped {len(all_items) - count} existing)")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
