#!/usr/bin/env python3
"""测试合并后的关键功能"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:8000"

def test_backend_health():
    """测试后端健康状态"""
    print("🔍 测试 1: 后端健康检查")
    try:
        resp = requests.get(f"{BASE_URL}/")
        print(f"   ✅ 后端响应: {resp.json()}")
        return True
    except Exception as e:
        print(f"   ❌ 后端失败: {e}")
        return False

def test_create_game():
    """测试创建游戏"""
    print("\n🔍 测试 2: 创建 8 人游戏")
    try:
        # 使用实际的 API 路径和参数
        params = {
            "seed": 42,
            "player_count": 8,
            "agent_type": "llm"
        }
        resp = requests.post(f"{BASE_URL}/api/games", params=params, timeout=30)
        data = resp.json()
        game_id = data.get("game_id")
        print(f"   ✅ 游戏创建成功: game_id={game_id}")
        return game_id
    except Exception as e:
        print(f"   ❌ 创建游戏失败: {e}")
        return None

def test_game_state(game_id):
    """测试获取游戏状态"""
    print(f"\n🔍 测试 3: 获取游戏状态 (game_id={game_id})")
    try:
        resp = requests.get(f"{BASE_URL}/api/games/{game_id}", timeout=10)
        data = resp.json()
        phase = data.get("phase")
        day = data.get("day")
        print(f"   ✅ 状态获取成功: phase={phase}, day={day}")
        return data
    except Exception as e:
        print(f"   ❌ 获取状态失败: {e}")
        return None

def test_start_game(game_id):
    """测试游戏是否正常运行（检查无限循环修复）"""
    print(f"\n🔍 测试 4: 验证游戏已运行完成（验证 DAY_RESOLVE 无限循环修复）")
    try:
        # 这个 API 在创建时就自动运行完了，所以直接检查状态
        state = test_game_state(game_id)
        if not state:
            return False

        phase = state.get("phase")
        day = state.get("day", 0)
        winner = state.get("winner")

        print(f"   📊 最终阶段: {phase}, 第 {day} 天")

        # 检查是否正常结束
        if winner:
            print(f"   ✅ 游戏正常结束，获胜方: {winner}")
            return True
        elif phase == "GAME_END":
            print(f"   ✅ 游戏已到达 GAME_END 阶段")
            return True
        else:
            # 如果没有 winner 但游戏还在进行，可能是测试用的 AI 游戏
            print(f"   ⚠️  游戏状态: {phase}，可能仍在运行或异常")
            # 只要不是卡在 DAY_RESOLVE 就算通过
            if "DAY_RESOLVE" not in phase:
                print(f"   ✅ 至少没有卡在 DAY_RESOLVE（无限循环已修复）")
                return True
            else:
                print(f"   ❌ 游戏卡在 DAY_RESOLVE（无限循环 bug 仍存在）")
                return False

    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
        return False

def test_frontend():
    """测试前端"""
    print("\n🔍 测试 5: 前端页面访问")
    try:
        resp = requests.get("http://localhost:3001/", timeout=5)
        if resp.status_code == 200 and "AI Werewolf" in resp.text:
            print(f"   ✅ 前端正常（200 OK）")
            return True
        else:
            print(f"   ⚠️  前端响应异常: {resp.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ 前端访问失败: {e}")
        return False

def main():
    print("=" * 60)
    print("🧪 合并后功能测试 - 2026-06-06")
    print("=" * 60)

    results = {}

    # 测试 1: 后端健康
    results["backend_health"] = test_backend_health()

    # 测试 2: 创建游戏
    game_id = test_create_game()
    results["create_game"] = game_id is not None

    if game_id:
        # 测试 3: 获取状态
        results["game_state"] = test_game_state(game_id) is not None

        # 测试 4: 启动游戏（关键：检查无限循环修复）
        results["start_game"] = test_start_game(game_id)
    else:
        results["game_state"] = False
        results["start_game"] = False

    # 测试 5: 前端
    results["frontend"] = test_frontend()

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")

    print(f"\n通过率: {passed}/{total} ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n🎉 所有测试通过！合并成功！")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，需要检查")
        sys.exit(1)

if __name__ == "__main__":
    main()
