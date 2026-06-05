"""Quick debug: test LLM agent talk/vote in isolation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.llm.env import load_env_file

load_env_file()

from backend.llm import create_client

# 1. Test client creation
print("=== Testing create_client ===")
client = create_client()
print(f"Provider: {client.provider}, Model: {client.model}, Base URL: {client.base_url}")

# 2. Test a simple chat
print("\n=== Testing chat_sync ===")
try:
    resp = client.chat_sync(
        messages=[
            {"role": "system", "content": "你是狼人杀玩家，输出JSON"},
            {"role": "user", "content": '请用JSON数组格式发言：["第一句话", "第二句话"]'},
        ],
        temperature=1.1,
        max_tokens=256,
        thinking=False,
    )
    text = client.parse_response(resp)
    print(f"Raw response: {text[:500]}")

    # Try parsing
    import json

    try:
        parsed = json.loads(text)
        print(f"Parsed OK: {parsed}")
    except:
        # Try extracting from brackets
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            parsed = json.loads(text[start : end + 1])
            print(f"Parsed (extracted): {parsed}")
        else:
            print("FAILED to parse as JSON array")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

# 3. Test vote-style JSON
print("\n=== Testing vote JSON ===")
try:
    resp = client.chat_sync(
        messages=[
            {"role": "system", "content": "你是狼人杀玩家，输出JSON对象"},
            {"role": "user", "content": '投票阶段，请输出JSON: {"target": "@3号", "reasoning": "理由"}'},
        ],
        temperature=0.4,
        max_tokens=256,
        thinking=False,
    )
    text = client.parse_response(resp)
    print(f"Raw response: {text[:500]}")

    import json

    try:
        parsed = json.loads(text)
        print(f"Parsed OK: {parsed}")
    except:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start : end + 1])
            print(f"Parsed (extracted): {parsed}")
        else:
            print("FAILED to parse as JSON object")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

print("\n=== Done ===")
