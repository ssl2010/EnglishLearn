#!/usr/bin/env python3
"""
API 连通性测试脚本

测试 LLM 和 百度 OCR 的连接和 API Key 是否正确
使用与应用相同的方式加载配置

用法:
    sudo -u englishlearn /opt/EnglishLearn/venv/bin/python3 /opt/EnglishLearn/scripts/test_api.py

或者指定环境文件:
    ENV_FILE=/etc/englishlearn.env python3 scripts/test_api.py
"""

import os
import sys
import json
import time
import base64
from pathlib import Path

# 尝试加载环境文件
env_file = os.environ.get("ENV_FILE", "/etc/englishlearn.env")
if os.path.exists(env_file):
    print(f"[INFO] 加载环境文件: {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
else:
    print(f"[WARN] 环境文件不存在: {env_file}")

print("=" * 60)
print("EnglishLearn API 连通性测试")
print("=" * 60)


def test_llm():
    """测试 LLM API (OpenAI 兼容)"""
    print("\n" + "=" * 60)
    print("[1] 测试 LLM API (OpenAI 兼容)")
    print("=" * 60)

    # 获取配置
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY")
    base_url = (
        os.environ.get("EL_OPENAI_BASE_URL")
        or os.environ.get("ARK_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
    )
    model = os.environ.get("EL_OPENAI_VISION_MODEL", "gpt-4o-mini")

    # 如果没有 base_url 但有 ARK_API_KEY，使用火山引擎默认地址
    if not base_url and os.environ.get("ARK_API_KEY"):
        base_url = "https://ark.cn-beijing.volces.com/api/v3"

    print(f"  API Key: {'*' * 8 + api_key[-8:] if api_key and len(api_key) > 8 else '(未配置)'}")
    print(f"  Base URL: {base_url or '(未配置，将使用 OpenAI 默认)'}")
    print(f"  Model: {model}")

    if not api_key:
        print("\n  [FAIL] API Key 未配置！")
        print("  请在 /etc/englishlearn.env 中设置 OPENAI_API_KEY 或 ARK_API_KEY")
        return False

    try:
        from openai import OpenAI

        client_kwargs = {"api_key": api_key, "timeout": 30}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = OpenAI(**client_kwargs)

        print("\n  正在测试连接...")
        start_time = time.time()

        # 简单的文本测试
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "请回复 OK"}],
            max_tokens=10,
        )

        elapsed = time.time() - start_time
        reply = response.choices[0].message.content.strip()

        print(f"  响应: {reply}")
        print(f"  耗时: {elapsed:.2f} 秒")
        print(f"\n  [OK] LLM API 连接正常!")
        return True

    except Exception as e:
        print(f"\n  [FAIL] LLM API 测试失败!")
        print(f"  错误: {e}")
        return False


def test_baidu_ocr():
    """测试百度 OCR API"""
    print("\n" + "=" * 60)
    print("[2] 测试百度 OCR API")
    print("=" * 60)

    api_key = os.environ.get("BAIDU_OCR_API_KEY")
    secret_key = os.environ.get("BAIDU_OCR_SECRET_KEY")

    print(f"  API Key: {'*' * 8 + api_key[-4:] if api_key and len(api_key) > 4 else '(未配置)'}")
    print(f"  Secret Key: {'*' * 8 + secret_key[-4:] if secret_key and len(secret_key) > 4 else '(未配置)'}")

    if not api_key or not secret_key:
        print("\n  [FAIL] 百度 OCR API Key 未配置!")
        print("  请在 /etc/englishlearn.env 中设置 BAIDU_OCR_API_KEY 和 BAIDU_OCR_SECRET_KEY")
        return False

    try:
        import requests

        # 步骤1: 获取 access_token
        print("\n  正在获取 access_token...")
        token_url = "https://aip.baidubce.com/oauth/2.0/token"
        token_params = {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }

        start_time = time.time()
        token_resp = requests.post(token_url, params=token_params, timeout=10)
        token_data = token_resp.json()

        if "access_token" not in token_data:
            print(f"  [FAIL] 获取 access_token 失败!")
            print(f"  响应: {token_data}")
            return False

        access_token = token_data["access_token"]
        print(f"  access_token: {access_token[:20]}...")

        # 步骤2: 测试 OCR 接口（使用一个简单的测试图片）
        print("\n  正在测试 OCR 接口...")

        # 创建一个简单的白色测试图片 (1x1 pixel PNG)
        # 这只是为了测试 API 连通性，不需要真实图片
        test_image_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={access_token}"
        ocr_data = {"image": test_image_base64}

        ocr_resp = requests.post(ocr_url, data=ocr_data, timeout=10)
        ocr_result = ocr_resp.json()

        elapsed = time.time() - start_time

        if "error_code" in ocr_result and ocr_result["error_code"] != 0:
            # 某些错误码是正常的（比如图片太小没有文字）
            error_code = ocr_result.get("error_code")
            if error_code in [216200, 216201, 216202]:  # 图片相关的正常错误
                print(f"  OCR 响应: (图片无内容，但接口正常)")
                print(f"  耗时: {elapsed:.2f} 秒")
                print(f"\n  [OK] 百度 OCR API 连接正常!")
                return True
            else:
                print(f"  [FAIL] OCR 调用失败!")
                print(f"  错误码: {error_code}")
                print(f"  错误信息: {ocr_result.get('error_msg')}")
                return False
        else:
            print(f"  OCR 响应: words_result_num = {ocr_result.get('words_result_num', 0)}")
            print(f"  耗时: {elapsed:.2f} 秒")
            print(f"\n  [OK] 百度 OCR API 连接正常!")
            return True

    except requests.exceptions.Timeout:
        print(f"\n  [FAIL] 百度 OCR API 连接超时!")
        print("  请检查服务器网络是否能访问 aip.baidubce.com")
        return False
    except Exception as e:
        print(f"\n  [FAIL] 百度 OCR API 测试失败!")
        print(f"  错误: {e}")
        return False


def test_network():
    """测试基础网络连通性"""
    print("\n" + "=" * 60)
    print("[0] 测试网络连通性")
    print("=" * 60)

    import requests

    urls = [
        ("百度", "https://www.baidu.com"),
        ("百度 OCR", "https://aip.baidubce.com"),
        ("火山引擎", "https://ark.cn-beijing.volces.com"),
        ("OpenAI", "https://api.openai.com"),
    ]

    results = {}
    for name, url in urls:
        try:
            start = time.time()
            resp = requests.head(url, timeout=5, allow_redirects=True)
            elapsed = time.time() - start
            status = f"OK ({resp.status_code}, {elapsed:.2f}s)"
            results[name] = True
        except requests.exceptions.Timeout:
            status = "超时"
            results[name] = False
        except requests.exceptions.ConnectionError:
            status = "连接失败"
            results[name] = False
        except Exception as e:
            status = f"错误: {e}"
            results[name] = False

        print(f"  {name:12} {url:45} {status}")

    return results


def main():
    # 测试网络
    network_results = test_network()

    # 测试 LLM
    llm_ok = test_llm()

    # 测试百度 OCR
    ocr_ok = test_baidu_ocr()

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"  LLM API:     {'[OK]' if llm_ok else '[FAIL]'}")
    print(f"  百度 OCR:    {'[OK]' if ocr_ok else '[FAIL]'}")
    print("=" * 60)

    if llm_ok and ocr_ok:
        print("\n所有 API 测试通过！")
        return 0
    else:
        print("\n部分 API 测试失败，请检查配置。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
