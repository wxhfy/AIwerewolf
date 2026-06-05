#!/usr/bin/env python3
"""
AI Werewolf 真实调用过程演示
展示 LLM Agent 之间的完整对话过程：发言、推理、投票等
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime

# 确保项目路径在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import EventType


class LLMCallLogger:
    """捕获所有 LLM 调用的完整对话过程"""

    def __init__(self):
        self.calls = []
        self.original_chat_sync = None

    def patch_client(self, client, player_name: str, role: str):
        """给 client 的 chat_sync 方法加上日志"""
        original = client.chat_sync

        def logged_chat_sync(messages, **kwargs):
            # 记录调用前的时间
            call_start = time.time()

            # 构建调用记录
            call_record = {
                "player": player_name,
                "role": role,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "model": client.model,
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 2048),
                "messages": messages,  # 完整的 prompt
            }

            # 打印调用信息
            print(f"\n{'=' * 80}")
            print(f"🤖 [{player_name}] ({role}) 发起 LLM 调用")
            print(f"   模型: {client.model}")
            print(f"   温度: {kwargs.get('temperature', 0.7)}")
            print(f"   最大 tokens: {kwargs.get('max_tokens', 2048)}")
            print(f"{'=' * 80}")

            # 打印 system prompt
            for msg in messages:
                if msg["role"] == "system":
                    print("\n📋 System Prompt:")
                    print(f"   {msg['content'][:500]}...")
                elif msg["role"] == "user":
                    print("\n💬 User Prompt:")
                    # 只显示前1000字符，避免太长
                    content = msg["content"]
                    if len(content) > 1000:
                        print(f"   {content[:1000]}...")
                        print(f"   [省略 {len(content) - 1000} 字符]")
                    else:
                        print(f"   {content}")

            # 调用原始方法
            try:
                response = original(messages, **kwargs)
                latency = time.time() - call_start

                # 解析响应
                text = client.parse_response(response)
                reasoning = client.parse_thinking(response)

                call_record["response"] = text
                call_record["reasoning"] = reasoning
                call_record["latency"] = latency
                call_record["usage"] = response.get("usage", {})

                # 打印响应
                print(f"\n✅ 响应 (耗时 {latency:.2f}s):")
                if reasoning:
                    print("   💭 推理过程:")
                    # 只显示前500字符
                    if len(reasoning) > 500:
                        print(f"      {reasoning[:500]}...")
                    else:
                        print(f"      {reasoning}")
                print("   💬 输出内容:")
                if len(text) > 800:
                    print(f"      {text[:800]}...")
                else:
                    print(f"      {text}")

                self.calls.append(call_record)
                return response

            except Exception as e:
                latency = time.time() - call_start
                print(f"\n❌ 调用失败 (耗时 {latency:.2f}s): {e}")
                call_record["error"] = str(e)
                call_record["latency"] = latency
                self.calls.append(call_record)
                raise

        client.chat_sync = logged_chat_sync


class GameObserver:
    """观察游戏状态变化"""

    def __init__(self):
        self.phase_changes = []
        self.speeches = []
        self.votes = []
        self.deaths = []

    def __call__(self, state):
        """被游戏引擎回调"""
        pass


def print_game_event(event_type: str, payload: dict, player_name: str = None):
    """打印游戏事件"""
    icons = {
        "SYSTEM_MESSAGE": "📢",
        "CHAT_MESSAGE": "💬",
        "VOTE": "🗳️",
        "DEATH": "💀",
        "NIGHT_ACTION": "🌙",
        "GAME_END": "🏆",
    }
    icon = icons.get(event_type, "📌")

    if event_type == "CHAT_MESSAGE":
        speaker = payload.get("speaker", player_name or "???")
        content = payload.get("content", "")
        phase = payload.get("phase", "")
        print(f"\n{icon} [{phase}] {speaker}: {content}")
    elif event_type == "VOTE":
        voter = payload.get("voter", player_name or "???")
        target = payload.get("target", "???")
        print(f"\n{icon} {voter} 投票给 {target}")
        if payload.get("reasoning"):
            print(f"   理由: {payload['reasoning'][:200]}")
    elif event_type == "DEATH":
        victim = payload.get("victim", player_name or "???")
        reason = payload.get("reason", "???")
        print(f"\n{icon} {victim} 死亡 (原因: {reason})")
    elif event_type == "SYSTEM_MESSAGE":
        msg = payload.get("message", "")
        print(f"\n{icon} {msg}")
    else:
        print(f"\n{icon} {event_type}: {json.dumps(payload, ensure_ascii=False)[:200]}")


def run_demo_with_logging():
    """运行一局完整的狼人杀游戏，并记录所有 LLM 调用"""

    print("=" * 80)
    print("🎮 AI Werewolf 真实调用过程演示")
    print("=" * 80)
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 创建日志器
    logger = LLMCallLogger()
    observer = GameObserver()

    # 创建游戏
    print("🎲 创建游戏...")
    game = WerewolfGame(seed=42, max_days=3, player_count=7)

    # 强制使用 LLM agent（而不是 heuristic）
    llm_agents = create_agents(
        game.state.players,
        {
            "type": "llm",
            "seed": 42,
            "temperature": 0.4,
            "character_map": game.characters,
        },
    )
    game.attach_agents(llm_agents)

    # 打印玩家信息
    print("\n👥 玩家列表:")
    for player in game.state.players:
        print(f"   - {player.name} ({player.role.value})")

    # 给每个 AI agent 的 LLM client 打上日志补丁
    print("\n🔧 设置 LLM 调用日志...")
    for player_id, agent in game.agents.items():
        if hasattr(agent, "client"):
            # 找到对应的玩家
            player = game.state.player(player_id)
            if player:
                logger.patch_client(agent.client, player.name, player.role.value)
                print(f"   ✅ 已为 {player.name} ({player.role.value}) 设置日志")

    # 记录原始事件用于后续分析
    original_log = game._log

    def logged_log(event_type, visibility, payload, **kwargs):
        """记录所有游戏事件"""
        original_log(event_type, visibility, payload, **kwargs)

        # 获取当前玩家信息
        player_name = None
        if "speaker_id" in payload:
            player = game.state.player(payload["speaker_id"])
            if player:
                player_name = player.name

        # 打印事件
        if visibility == "public" or event_type in [
            EventType.SYSTEM_MESSAGE,
            EventType.GAME_END,
        ]:
            print_game_event(
                event_type.value if hasattr(event_type, "value") else str(event_type), payload, player_name
            )

    game._log = logged_log

    # 运行游戏
    print("\n" + "=" * 80)
    print("🎮 游戏开始！")
    print("=" * 80)

    try:
        state = game.play()

        # 打印游戏结果
        print("\n" + "=" * 80)
        print("🏆 游戏结束！")
        print("=" * 80)
        print(f"   获胜方: {state.winner.value if state.winner else '无'}")
        print(f"   游戏天数: {state.day}")

        # 打印玩家存活状态
        print("\n👥 最终状态:")
        for player in state.players:
            status = "存活" if player.alive else "死亡"
            print(f"   - {player.name} ({player.role.value}) [{status}]")

    except Exception as e:
        print(f"\n❌ 游戏运行出错: {e}")
        traceback.print_exc()

    # 打印 LLM 调用统计
    print("\n" + "=" * 80)
    print("📊 LLM 调用统计")
    print("=" * 80)
    print(f"   总调用次数: {len(logger.calls)}")

    if logger.calls:
        total_latency = sum(c.get("latency", 0) for c in logger.calls)
        print(f"   总耗时: {total_latency:.2f}s")
        print(f"   平均耗时: {total_latency / len(logger.calls):.2f}s")

        # 按玩家统计
        player_calls = {}
        for call in logger.calls:
            player = call["player"]
            if player not in player_calls:
                player_calls[player] = {"count": 0, "total_latency": 0}
            player_calls[player]["count"] += 1
            player_calls[player]["total_latency"] += call.get("latency", 0)

        print("\n   按玩家统计:")
        for player, stats in player_calls.items():
            print(f"      {player}: {stats['count']}次, 平均{stats['total_latency'] / stats['count']:.2f}s")

    # 保存详细日志
    log_file = os.path.join(os.path.dirname(__file__), "llm_calls_log.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(logger.calls, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 详细日志已保存到: {log_file}")

    return logger.calls


if __name__ == "__main__":
    calls = run_demo_with_logging()
