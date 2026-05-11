#!/usr/bin/env python3
"""测试 Juror B/C 通过自定义 base_url + 绕过代理调用。

用法：
  1. 在 .env 中设置 JUROR_B_API_KEY 和 JUROR_C_API_KEY
  2. 或者在命令行前设置环境变量
  3. python test_api_no_proxy.py

测试内容：
  - Juror B: 开源模型（如 qwen2.5-72b），判断泰语违规文本
  - Juror C: 高阶模型（如 claude-sonnet），判断同一条文本
  - 全部绕过系统代理（no_proxy=True），直连 api.vectorengine.cn
"""

import os
import sys

sys.path.insert(0, ".")

BASE_URL = "https://api.vectorengine.cn/v1/chat/completions"
API_KEY = os.getenv("JUROR_B_API_KEY", "") or os.getenv("JUROR_C_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")

# 测试用的泰语文本（违规）
TOXIC_THAI = "พวกมึงแม่งโง่ ไปตายซะไป พวกสันดานขี้ข้า"
# 测试用的泰语文本（正常）
BENIGN_THAI = "วันนี้อากาศดีมากเลยครับ ไปเที่ยวทะเลกัน"


def test_raw_connection():
    """最底层测试：直接 httpx 请求，看看能不能连通 API。"""
    print("=" * 60)
    print("1. 底层连接测试（绕过代理）")
    print("=" * 60)

    import httpx

    if not API_KEY:
        print("  ⚠ 未设置 API key，跳过。请设置 JUROR_B_API_KEY 环境变量。")
        return False

    payload = {
        "model": "qwen2.5-72b-instruct",
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "max_tokens": 10,
    }

    try:
        with httpx.Client(trust_env=False, timeout=15.0) as client:
            resp = client.post(
                BASE_URL,
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
            print(f"  ✓ 连接成功！响应: {content}")
            return True
    except httpx.ConnectError as e:
        print(f"  ✗ 连接失败: {e}")
        print(f"  → 可能需要设置 HTTPS_PROXY= 清空代理后重试")
        return False
    except Exception as e:
        print(f"  ✗ 错误: {type(e).__name__}: {e}")
        return False


def test_juror_b_thai():
    """Juror B 测试：用 qwen2.5-72b 判断泰语违规。"""
    print("\n" + "=" * 60)
    print("2. Juror B — Qwen2.5-72B (开源中坚)")
    print("=" * 60)

    from jury.juror_b import call_juror_b
    from jury.prompt_builder import build_juror_prompt

    if not API_KEY:
        print("  ⚠ 未设置 API key，跳过。")
        return

    prompts = build_juror_prompt(
        content=TOXIC_THAI,
        source="pantip",
        country="TH",
        language="th",
    )

    print(f"  测试文本: {TOXIC_THAI[:60]}...")

    verdict = call_juror_b(
        content_id="test-th-b",
        language="th",
        system_prompt=prompts["B"]["system"],
        user_prompt=prompts["B"]["user"],
        provider="custom",
        model_name="qwen2.5-72b-instruct",
        base_url=BASE_URL,
        api_key=API_KEY,
        no_proxy=True,  # ← 绕过代理
        timeout=60.0,
    )

    print(f"  违规判定: {verdict.violation}")
    print(f"  类别:     {verdict.category}")
    print(f"  置信度:   {verdict.confidence:.3f}")
    print(f"  延迟:     {verdict.latency_ms:.0f}ms")
    print(f"  Token:    {verdict.tokens_used}")
    print(f"  推理过程:  {verdict.reasoning[:200]}...")


def test_juror_c_thai():
    """Juror C 测试：用 claude-sonnet 判断泰语违规。"""
    print("\n" + "=" * 60)
    print("3. Juror C — GPT-4o (云端高阶)")
    print("=" * 60)

    from jury.juror_c import call_juror_c
    from jury.prompt_builder import build_juror_prompt

    if not API_KEY:
        print("  ⚠ 未设置 API key，跳过。")
        return

    prompts = build_juror_prompt(
        content=TOXIC_THAI,
        source="pantip",
        country="TH",
        language="th",
    )

    print(f"  测试文本: {TOXIC_THAI[:60]}...")

    verdict = call_juror_c(
        content_id="test-th-c",
        language="th",
        system_prompt=prompts["C"]["system"],
        user_prompt=prompts["C"]["user"],
        provider="custom",
        model_name="gpt-4o",
        base_url=BASE_URL,
        api_key=API_KEY,
        no_proxy=True,  # ← 绕过代理
        timeout=60.0,
    )

    print(f"  违规判定: {verdict.violation}")
    print(f"  类别:     {verdict.category}")
    print(f"  置信度:   {verdict.confidence:.3f}")
    print(f"  延迟:     {verdict.latency_ms:.0f}ms")
    print(f"  Token:    {verdict.tokens_used}")
    print(f"  推理过程:  {verdict.reasoning[:200]}...")


def test_benign_thai():
    """Juror B 判断正常泰语文本。"""
    print("\n" + "=" * 60)
    print("4. 正常泰语文本测试（应判 clean）")
    print("=" * 60)

    from jury.juror_b import call_juror_b
    from jury.prompt_builder import build_juror_prompt

    if not API_KEY:
        print("  ⚠ 未设置 API key，跳过。")
        return

    prompts = build_juror_prompt(
        content=BENIGN_THAI,
        source="pantip",
        country="TH",
        language="th",
    )

    print(f"  测试文本: {BENIGN_THAI}")

    verdict = call_juror_b(
        content_id="test-th-benign",
        language="th",
        system_prompt=prompts["B"]["system"],
        user_prompt=prompts["B"]["user"],
        provider="custom",
        model_name="qwen2.5-72b-instruct",
        base_url=BASE_URL,
        api_key=API_KEY,
        no_proxy=True,
        timeout=60.0,
    )

    print(f"  违规判定: {verdict.violation}")
    print(f"  类别:     {verdict.category}")
    print(f"  置信度:   {verdict.confidence:.3f}")
    print(f"  推理过程:  {verdict.reasoning[:200]}...")


if __name__ == "__main__":
    print("Juror B/C API 代理连接测试")
    print(f"Base URL: {BASE_URL}")
    print(f"API Key:  {'已设置' if API_KEY else '⚠ 未设置'}")
    print()

    if not API_KEY:
        print("请先设置 API key:")
        print("  export JUROR_B_API_KEY=sk-your-key")
        print()
        sys.exit(1)

    if test_raw_connection():
        test_juror_b_thai()
        test_juror_c_thai()
        test_benign_thai()

    print("\n" + "=" * 60)
    print("测试完成！")
