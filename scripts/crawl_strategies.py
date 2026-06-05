"""Crawl werewolf strategy articles for different player counts,
then use Doubao LLM to extract structured per-role strategies.

Architecture:
  - Role layer (RoleStrategyCard): role GOAL only (no tactics)
  - Strategy layer (StrategyKnowledgeDoc): all tactical guidance, tagged
    by player_count so agents retrieve count-appropriate strategies.

Usage:
  python scripts/crawl_strategies.py --crawl      # Scrape articles
  python scripts/crawl_strategies.py --extract     # Doubao extraction
  python scripts/crawl_strategies.py --all         # Crawl + extract + ingest
  python scripts/crawl_strategies.py --setup-roles # Create RoleStrategyCards
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data" / "strategies"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Player-count specific search queries
COUNT_QUERIES = {
    6: [
        "狼人杀 6人局 玩法 策略",
        "狼人杀 6人 新手 角色 攻略",
        "werewolf game 6 players strategy guide",
    ],
    9: [
        "狼人杀 9人局 标准玩法 策略",
        "狼人杀 9人 预女猎 配置 攻略",
        "狼人杀 9人局 角色 战术",
    ],
    12: [
        "狼人杀 12人局 标准玩法 角色攻略",
        "狼人杀 12人 预女猎守 配置 策略",
        "狼人杀 12人 预言家 女巫 守卫 猎人 狼人 村民 策略",
        "werewolf 12 player standard strategy guide",
    ],
}

ROLE_GOALS = {
    "Seer": "查验玩家身份，带领好人阵营找出并放逐所有狼人。你需要通过发言和归票将查验信息转化为好人的投票指引。",
    "Witch": "拥有解药和毒药各一瓶。解药可救活被狼人杀害的玩家，毒药可毒杀一名玩家。你需要隐藏身份、在关键时刻用正确的方式使用药水帮助好人阵营。",
    "Guard": "每夜可守护一名玩家使其不被狼人杀害（不能连续两晚守护同一人）。你需要预判狼人的刀口保护关键角色，同时隐藏身份避免被狼人优先清除。",
    "Hunter": "被投票放逐或被狼人杀害时可以开枪带走一名玩家（被女巫毒死则不能开枪）。你需要隐藏身份留存技能威慑力，在关键节点亮明身份带走确定是狼的玩家。",
    "Werewolf": "你属于狼人阵营，知道所有狼队友的身份。每夜可以商议杀害一名玩家（需要多数同意）。白天你需要伪装成好人阵营，通过发言和投票误导好人、保护狼队友不被放逐。目标：存活至狼人数量大于等于好人数量。",
    "Villager": "你是普通村民，没有特殊技能。你需要通过分析发言、票型、查验信息来判断谁是狼人，并在投票中放逐狼人。你的判断力和投票是好人阵营获胜的关键。",
}

EXTRACTION_PROMPT = """你是一位狼人杀策略分析师。以下是从狼人杀攻略网站抓取的文章内容。这些内容针对【{player_count}人局】的狼人杀玩法。

请从中提取每个角色的策略知识。要求：
1. 区分不同角色（预言家/女巫/守卫/猎人/狼人/村民）
2. 针对{player_count}人局的特殊规则和策略（不同人数局玩法不同）
3. 每条策略包含：阶段、触发条件、推荐行动、理由、常见错误
4. 用中文输出

输出 JSON 数组格式：
[
  {{
    "role": "Seer",
    "player_count": {player_count},
    "strategies": [
      {{
        "phase": "night_1|day_1|mid_game|late_game",
        "trigger": "触发条件",
        "action": "推荐行动",
        "rationale": "理由",
        "common_mistake": "常见错误",
        "priority": "high|medium|low"
      }}
    ]
  }},
  ...
]

如果没有某个角色的内容，就返回空数组。

文章内容：
{article_text}"""


def crawl_articles() -> list[dict[str, Any]]:
    """Crawl werewolf strategy articles using web search results.
    Saves raw HTML/text to data/strategies/raw/ and returns parsed articles."""

    raw_dir = DATA_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    articles: list[dict[str, Any]] = []

    for player_count, queries in COUNT_QUERIES.items():
        for query in queries:
            print(f"  Searching: {query}")
            # Use DuckDuckGo or direct site crawling
            try:
                # Try known werewolf strategy sites directly
                urls = _search_werewolf_urls(query)
                for url in urls:
                    if any(a["url"] == url for a in articles):
                        continue
                    try:
                        text = _fetch_article(url)
                        if text and len(text) > 200:
                            articles.append(
                                {
                                    "url": url,
                                    "query": query,
                                    "player_count": player_count,
                                    "text": text,
                                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                }
                            )
                            # Save raw
                            fname = re.sub(r"[^a-zA-Z0-9]", "_", url[:80]) + ".txt"
                            (raw_dir / fname).write_text(text, encoding="utf-8")
                            print(f"    ✓ {url[:80]}... ({len(text)} chars)")
                    except Exception as e:
                        print(f"    ✗ {url[:60]}...: {e}")
            except Exception as e:
                print(f"    ✗ search failed: {e}")

    # Save index
    index_path = DATA_DIR / "crawled_articles.json"
    index_path.write_text(
        json.dumps([{k: v for k, v in a.items() if k != "text"} for a in articles], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Total articles: {len(articles)}")
    return articles


def _search_werewolf_urls(query: str) -> list[str]:
    """Search for werewolf strategy URLs. Tries multiple sources."""
    urls: list[str] = []
    import urllib.parse
    import urllib.request

    # Source 1: DuckDuckGo HTML search (no API key needed)
    try:
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={encoded}",
            headers={"User-Agent": "Mozilla/5.0 (compatible; AIwerewolf-research/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Extract result URLs
            for match in re.finditer(r'class="result__url"[^>]*>([^<]+)<', html):
                domain = match.group(1).strip()
                # Prioritize werewolf-specific sites
                if any(
                    kw in domain
                    for kw in ["langrensha", "werewolf", "狼人杀", "9game", "gamersky", "zhihu", "tieba", "baidu"]
                ):
                    continue  # These come from result__a tags
            for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', html):
                url = match.group(1)
                if url.startswith("//"):
                    url = "https:" + url
                if any(kw in url for kw in ["langrensha.net", "langrensha", "werewolf", "狼人杀"]):
                    if url not in urls:
                        urls.append(url)
    except Exception:
        pass

    # Source 2: Known werewolf strategy sites (fallback)
    known_sites = [
        "https://www.langrensha.net/strategy/",
        "https://www.langrensha.net/strategy/2023012902.html",
        "https://www.langrensha.net/strategy/2021030801.html",
        "https://www.langrensha.net/strategy/2023010501.html",
        "https://www.langrensha.net/strategy/2022040202.html",
    ]
    for site in known_sites:
        if site not in urls:
            urls.append(site)

    return urls[:10]  # Limit per query


def _fetch_article(url: str) -> str:
    """Fetch and extract text from a URL."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; AIwerewolf-research/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Simple HTML-to-text extraction
    # Remove scripts, styles, nav elements
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode HTML entities
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove very short lines
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 20]
    return "\n".join(lines)


def extract_with_doubao(articles: list[dict], player_count: int | None = None) -> list[dict]:
    """Use Doubao LLM to extract strategies from crawled articles."""
    from dotenv import load_dotenv

    load_dotenv()

    from backend.llm import create_client

    client = create_client(
        provider="doubao",
        model=os.environ.get("DOUBAO_MODEL", "ep-20260514115354-k4jz4"),
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url=os.environ["DOUBAO_BASE_URL"],
    )
    client.timeout = 180.0

    all_strategies: list[dict] = []

    for article in articles:
        pc = article["player_count"]
        if player_count and pc != player_count:
            continue

        # Truncate long articles
        text = article["text"][:8000]
        prompt = EXTRACTION_PROMPT.format(player_count=pc, article_text=text)

        print(f"  Extracting from: {article['url'][:60]}... ({len(text)} chars)")
        try:
            response = client.chat_sync(
                [{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.3,
            )
            raw = client.parse_response(response).strip()

            # Extract JSON
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                parts = raw.split("```")
                if len(parts) >= 2:
                    raw = parts[1].strip()

            # Try to parse JSON array
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                if isinstance(parsed, list):
                    for role_block in parsed:
                        if isinstance(role_block, dict) and "strategies" in role_block:
                            all_strategies.append(role_block)
                    print(f"    ✓ {len(parsed)} role blocks extracted")
                elif isinstance(parsed, dict) and "strategies" in parsed:
                    all_strategies.append(parsed)
                    print("    ✓ 1 role block extracted")
            else:
                print("    ⚠ No JSON found in response")

        except Exception as e:
            print(f"    ✗ Extraction failed: {e}")
            continue

    return all_strategies


def ingest_to_db(strategies: list[dict], player_counts: set[int]) -> int:
    """Insert extracted strategies into strategy_knowledge_docs table."""
    from backend.db.database import SessionLocal
    from backend.db.database import init_db
    from backend.db.models import StrategyKnowledgeDoc as SKDModel

    init_db()
    db = SessionLocal()
    count = 0

    try:
        for role_block in strategies:
            role = role_block.get("role", "global")
            pc = role_block.get("player_count", 0)
            strategies_list = role_block.get("strategies", [])

            for i, s in enumerate(strategies_list):
                doc_id = f"crawl-{pc}p-{role.lower()}-{i:03d}"

                existing = db.query(SKDModel).filter(SKDModel.id == doc_id).first()
                if existing:
                    continue

                row = SKDModel(
                    id=doc_id,
                    doc_type="good_play",
                    role=role,
                    phase=s.get("phase", "mid_game"),
                    situation_pattern=s.get("trigger", ""),
                    trigger_conditions=[s.get("trigger", "")],
                    recommended_action=s.get("action", ""),
                    avoid_action=s.get("common_mistake", ""),
                    rationale=s.get("rationale", ""),
                    evidence_summary=f"从{pc}人局攻略文章爬取提取",
                    quality_score=0.85,
                    confidence=0.75,
                    status="active",
                    tags=["crawled", f"player_count:{pc}", f"role:{role}", f"priority:{s.get('priority', 'medium')}"],
                )
                db.add(row)
                count += 1

        db.commit()
    finally:
        db.close()

    return count


def setup_role_cards() -> None:
    """Create RoleStrategyCard records with GOALS ONLY (no tactics)."""
    from backend.db.database import SessionLocal
    from backend.db.database import init_db
    from backend.db.models import RoleStrategyCard

    init_db()
    db = SessionLocal()
    try:
        from sqlalchemy import func

        existing = db.query(func.count(RoleStrategyCard.id)).scalar()
        if existing:
            print(f"  {existing} role cards already exist, updating...")

        for role, goal in ROLE_GOALS.items():
            card_id = f"role-card-{role.lower()}-v1"
            row = db.query(RoleStrategyCard).filter(RoleStrategyCard.id == card_id).first()
            if row:
                row.goal = goal
                row.speech_policy = []
                row.vote_policy = []
                row.skill_policy = []
                row.risk_rules = []
                row.retrieval_policy = {"enabled": True, "top_k": 3, "min_quality": 0.5}
            else:
                row = RoleStrategyCard(
                    id=card_id,
                    role=role,
                    version="v1",
                    goal=goal,
                    speech_policy=[],
                    vote_policy=[],
                    skill_policy=[],
                    risk_rules=[],
                    retrieval_policy={"enabled": True, "top_k": 3, "min_quality": 0.5},
                    status="active",
                )
                db.add(row)
            print(f"  ✓ {role}: goal set, policies empty (delegated to strategy layer)")

        db.commit()
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crawl", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--setup-roles", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--player-count", type=int, default=None)
    args = ap.parse_args()

    if args.setup_roles or args.all:
        print("=== Setting up RoleStrategyCards (goals only) ===")
        setup_role_cards()

    if args.crawl or args.all:
        print("=== Crawling strategy articles ===")
        articles = crawl_articles()
        print(f"Crawled {len(articles)} articles")

    if args.extract or args.all:
        print("=== Doubao LLM extraction ===")
        # Load crawled articles
        index_path = DATA_DIR / "crawled_articles.json"
        if index_path.exists():
            articles = []
            for info in json.loads(index_path.read_text(encoding="utf-8")):
                fname = re.sub(r"[^a-zA-Z0-9]", "_", info["url"][:80]) + ".txt"
                raw_path = DATA_DIR / "raw" / fname
                if raw_path.exists():
                    info["text"] = raw_path.read_text(encoding="utf-8")
                articles.append(info)

            strategies = extract_with_doubao(articles, args.player_count)
            print(f"\nExtracted {len(strategies)} role-strategy blocks")

            # Save
            out_path = DATA_DIR / "extracted_strategies.json"
            out_path.write_text(json.dumps(strategies, ensure_ascii=False, indent=2))
            print(f"Saved to {out_path}")

            if args.ingest or args.all:
                player_counts = set(a["player_count"] for a in articles)
                n = ingest_to_db(strategies, player_counts)
                print(f"Ingested {n} strategies to DB")
        else:
            print("No crawled articles found. Run --crawl first.")

    if not any([args.crawl, args.extract, args.ingest, args.setup_roles, args.all]):
        ap.print_help()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
