#!/bin/bash
# 清理历史的 crop 裁剪图片文件
# 这些文件是测试期间生成的，占用约 80-100 MB 空间
# 删除后不影响系统功能，因为已改为按需生成

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CROP_DIR="$PROJECT_ROOT/backend/media/uploads/crops"
MEDIA_DIR="$PROJECT_ROOT/backend/media"

echo "======================================"
echo "清理 crop 裁剪图片文件"
echo "======================================"
echo ""

# 检查是否存在 crop 目录
if [ ! -d "$CROP_DIR" ]; then
    echo "✅ crop 目录不存在，无需清理"
    exit 0
fi

# 统计文件数量和大小
CROP_COUNT=$(find "$CROP_DIR" -type f -name "crop_*.jpg" | wc -l)
if [ "$CROP_COUNT" -eq 0 ]; then
    echo "✅ 没有找到 crop 文件，无需清理"
    exit 0
fi

CROP_SIZE=$(du -sh "$CROP_DIR" | cut -f1)

echo "发现 crop 文件:"
echo "  数量: $CROP_COUNT 个"
echo "  大小: $CROP_SIZE"
echo ""

# 询问确认
read -p "确认删除这些文件吗？ (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 已取消"
    exit 1
fi

# 删除文件
echo "正在删除..."
rm -f "$CROP_DIR"/crop_*.jpg

# 检查是否还有其他文件
REMAINING=$(find "$CROP_DIR" -type f | wc -l)
if [ "$REMAINING" -eq 0 ]; then
    echo "删除 crop 目录（已空）..."
    rm -rf "$CROP_DIR"
fi

echo ""
echo "✅ 清理完成！"
echo ""
echo "释放空间: $CROP_SIZE"
echo "删除文件: $CROP_COUNT 个"
echo ""
echo "注意: 系统已改为按需生成裁剪图片，不再保存到磁盘"
echo "如需启用保存，请在 .env 中设置 SAVE_CROP_IMAGES=1"
