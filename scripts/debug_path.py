#!/usr/bin/env python3
"""调试路径问题的脚本"""
import os
import sys
import glob

print("=" * 60)
print("EnglishLearn 路径调试脚本")
print("=" * 60)

# 1. 基本信息
print("\n[1] 基本信息")
print(f"Python: {sys.executable}")
print(f"CWD: {os.getcwd()}")
print(f"sys.path:")
for p in sys.path:
    print(f"  - {p}")

# 2. 检查 .pth 文件
print("\n[2] 检查 .pth 文件")
venv_site = "/opt/EnglishLearn/venv/lib/python3.11/site-packages"
pth_files = glob.glob(f"{venv_site}/*.pth")
if pth_files:
    for pth in pth_files:
        print(f"\n=== {pth} ===")
        try:
            with open(pth) as f:
                print(f.read())
        except Exception as e:
            print(f"Error: {e}")
else:
    print("无 .pth 文件")

# 3. 检查 .egg-link 文件
print("\n[3] 检查 .egg-link 文件")
egg_links = glob.glob(f"{venv_site}/*.egg-link")
if egg_links:
    for egg in egg_links:
        print(f"\n=== {egg} ===")
        try:
            with open(egg) as f:
                print(f.read())
        except Exception as e:
            print(f"Error: {e}")
else:
    print("无 .egg-link 文件")

# 4. 测试模块导入
print("\n[4] 测试模块导入")
sys.path.insert(0, "/opt/EnglishLearn")
try:
    from backend.app import openai_vision
    print(f"openai_vision.__file__: {openai_vision.__file__}")

    # 计算配置路径
    dirname = os.path.dirname(openai_vision.__file__)
    config_path = os.path.abspath(os.path.join(dirname, "..", "..", "ai_config.json"))
    print(f"dirname: {dirname}")
    print(f"计算的配置路径: {config_path}")
    print(f"配置文件存在: {os.path.exists(config_path)}")
except Exception as e:
    print(f"导入错误: {e}")

# 5. 检查 services.py
print("\n[5] 测试 services.py")
try:
    from backend.app import services
    print(f"services.__file__: {services.__file__}")
except Exception as e:
    print(f"导入错误: {e}")

# 6. 检查环境变量
print("\n[6] 相关环境变量")
for key in ["EL_AI_CONFIG_PATH", "PYTHONPATH", "EL_APP_DIR"]:
    val = os.environ.get(key, "(未设置)")
    print(f"{key}: {val}")

# 7. 检查 __pycache__ 目录
print("\n[7] 检查 __pycache__ 目录")
pycache_dirs = [
    "/opt/EnglishLearn/backend/__pycache__",
    "/opt/EnglishLearn/backend/app/__pycache__",
    "/opt/EnglishLearn/backend/app/routers/__pycache__",
]
for d in pycache_dirs:
    if os.path.exists(d):
        files = os.listdir(d)
        print(f"{d}: {len(files)} 文件")
        for f in files[:5]:
            print(f"  - {f}")
    else:
        print(f"{d}: 不存在")

print("\n" + "=" * 60)
print("调试完成")
print("=" * 60)
