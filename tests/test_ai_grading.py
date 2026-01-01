#!/usr/bin/env python3
"""
测试AI批改功能的基本流程
使用tests/fixtures/目录中的固定测试数据
"""
import os
import sys
import json
from pathlib import Path

# Add backend to path (go up one level from tests/)
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Load .env file
from dotenv import load_dotenv
_DOTENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_DOTENV_PATH, override=False)

from app.services import analyze_ai_photos, _extract_date_from_ocr
from app.openai_vision import is_configured


class Colors:
    """Terminal colors"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'


def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.RESET}")


def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.RESET}")


def print_warning(msg):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}")


def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.RESET}")


def test_ai_configuration():
    """测试AI配置是否正确"""
    print("\n=== 测试AI配置 ===")

    if not is_configured():
        print_error("AI配置不可用，缺少API密钥")
        print_info("请检查 .env 文件中的 OPENAI_API_KEY 或 ARK_API_KEY")
        return False

    print_success("AI配置正常")

    # Check OCR config
    baidu_key = os.environ.get("BAIDU_OCR_API_KEY")
    baidu_secret = os.environ.get("BAIDU_OCR_SECRET_KEY")

    if not baidu_key or not baidu_secret:
        print_warning("百度OCR配置缺失，OCR功能可能无法使用")
    else:
        print_success("百度OCR配置正常")

    return True


def load_debug_images():
    """加载测试图片（优先使用fixtures，其次debug_last）"""
    print("\n=== 加载测试图片 ===")

    # Try fixtures directory first (same directory as this script)
    script_dir = Path(__file__).parent
    fixtures_dir = script_dir / "fixtures"
    debug_dir = script_dir.parent / "backend/media/uploads/debug_last"

    test_dir = None
    if fixtures_dir.exists():
        test_dir = fixtures_dir
        print_info(f"使用测试数据目录: {fixtures_dir}")
    elif debug_dir.exists():
        test_dir = debug_dir
        print_info(f"使用调试数据目录: {debug_dir}")
    else:
        print_error("未找到测试图片目录")
        print_info("请运行前端识别功能生成调试数据，或将测试图片放入 tests/fixtures/")
        return None

    images = []
    for i in range(1, 10):  # Try up to 10 images
        img_path = test_dir / f"input_{i}.jpg"
        if img_path.exists():
            with open(img_path, 'rb') as f:
                images.append(f.read())
            print_success(f"加载图片 {i}: {img_path.name} ({len(images[-1])} bytes)")
        else:
            break

    if not images:
        print_error("未找到测试图片")
        return None

    print_info(f"共加载 {len(images)} 张图片")
    return images


def create_mock_upload_files(image_bytes_list):
    """创建模拟的UploadFile对象"""
    class MockUploadFile:
        def __init__(self, data, filename):
            self._data = data
            self.filename = filename

        @property
        def file(self):
            import io
            return io.BytesIO(self._data)

    return [MockUploadFile(img, f"test_{i+1}.jpg") for i, img in enumerate(image_bytes_list)]


def validate_result(result):
    """验证返回结果的结构"""
    print("\n=== 验证返回结果 ===")

    # Check required fields
    required_fields = ['items', 'image_urls', 'graded_image_urls', 'image_count']
    for field in required_fields:
        if field not in result:
            print_error(f"缺少字段: {field}")
            return False
        print_success(f"字段存在: {field}")

    # Validate items
    items = result.get('items', [])
    print_info(f"识别到 {len(items)} 道题目")

    if not items:
        print_warning("未识别到任何题目")
        return False

    # Check item structure
    sample_item = items[0]
    item_fields = ['position', 'zh_hint', 'llm_text', 'page_index']
    for field in item_fields:
        if field not in sample_item:
            print_error(f"题目缺少字段: {field}")
            return False

    print_success(f"题目结构正确")

    # Check page distribution
    pages = set(item.get('page_index', 0) for item in items)
    print_info(f"题目分布在 {len(pages)} 个页面: {sorted(pages)}")

    # Check extracted date
    if 'extracted_date' in result and result['extracted_date']:
        print_success(f"提取到试卷日期: {result['extracted_date']}")
    else:
        print_warning("未提取到试卷日期")

    # Check matched session
    if result.get('matched_session'):
        ms = result['matched_session']
        print_success(f"匹配到练习单 #{ms.get('session_id')} (匹配度: {ms.get('match_ratio', 0)*100:.1f}%)")
    else:
        print_info("未匹配到练习单")

    return True


def print_item_summary(items):
    """打印题目摘要"""
    print("\n=== 题目摘要 ===")

    # Group by section
    sections = {}
    for item in items:
        section = item.get('section_title') or '未分类'
        if section not in sections:
            sections[section] = []
        sections[section].append(item)

    for section, section_items in sections.items():
        print(f"\n{Colors.BLUE}{section}{Colors.RESET}")

        correct = sum(1 for it in section_items if it.get('is_correct') == True)
        incorrect = sum(1 for it in section_items if it.get('is_correct') == False)
        unknown = len(section_items) - correct - incorrect

        print(f"  题目数: {len(section_items)}")
        print(f"  正确: {Colors.GREEN}{correct}{Colors.RESET}, "
              f"错误: {Colors.RED}{incorrect}{Colors.RESET}, "
              f"未知: {Colors.YELLOW}{unknown}{Colors.RESET}")

        # Show page distribution
        page_dist = {}
        for it in section_items:
            pg = it.get('page_index', 0)
            page_dist[pg] = page_dist.get(pg, 0) + 1

        if len(page_dist) > 1:
            print(f"  页面分布: {dict(sorted(page_dist.items()))}")


def check_page_accuracy(items):
    """检查页码标记准确性的启发式检验"""
    print("\n=== 检查页码准确性 ===")

    # Group by page
    by_page = {}
    for item in items:
        pg = item.get('page_index', 0)
        if pg not in by_page:
            by_page[pg] = []
        by_page[pg].append(item)

    # Check if all items are on one page (likely wrong for multi-page)
    if len(by_page) == 1 and len(items) > 15:
        print_warning(f"所有 {len(items)} 道题都标记在同一页，可能存在页码识别问题")
        return False

    # Check for reasonable distribution
    for pg, pg_items in sorted(by_page.items()):
        print_info(f"Page {pg}: {len(pg_items)} 道题")

    print_success("页码分布看起来合理")
    return True


def main():
    """主测试流程"""
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}AI批改功能测试{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

    # Step 1: Check configuration
    if not test_ai_configuration():
        print_error("\n配置检查失败，无法继续测试")
        return 1

    # Step 2: Load test images
    image_bytes = load_debug_images()
    if not image_bytes:
        print_error("\n无法加载测试图片")
        return 1

    # Step 3: Run AI grading
    print("\n=== 执行AI批改 ===")
    print_info("正在调用LLM和OCR...")

    try:
        # Create mock upload files
        mock_files = create_mock_upload_files(image_bytes)

        # Call the actual function
        result = analyze_ai_photos(
            student_id=1,
            base_id=1,
            uploads=mock_files
        )

        print_success("AI批改完成")

    except Exception as e:
        print_error(f"AI批改失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 4: Validate result
    if not validate_result(result):
        print_error("\n结果验证失败")
        return 1

    # Step 5: Print summary
    items = result.get('items', [])
    print_item_summary(items)

    # Step 6: Check page accuracy
    check_page_accuracy(items)

    # Step 7: Save result for inspection
    output_file = Path(__file__).parent / "test_ai_grading_result.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{Colors.GREEN}{'='*60}{Colors.RESET}")
    print(f"{Colors.GREEN}测试完成！{Colors.RESET}")
    print(f"{Colors.GREEN}{'='*60}{Colors.RESET}")
    print_info(f"详细结果已保存到: {output_file}")

    return 0


if __name__ == '__main__':
    exit(main())
