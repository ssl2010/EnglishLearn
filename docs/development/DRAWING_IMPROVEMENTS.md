# 批改标记绘图改进 - 参考OpenCV实现

## 改进内容

根据参考代码（OpenCV实现）改进了批改标记的绘图方式。

## 关键改进点

### 1. 对号位置 ✓

**之前**：
- 对号绘制在答案bbox的**中心**
- 会遮挡学生的手写内容

**现在**：
- 对号绘制在答案bbox的**右侧**
- 位置：`x2 + 8, y1 - 6`（右侧+8px，上方-6px）
- 不遮挡答案，更清晰

**参考代码**：
```python
# OpenCV版本
start_x = x + w + 8
start_y = y - 6
```

**我的实现**：
```python
# PIL版本
start_x = x2 + 8  # x2 是 bbox 右边界
start_y = y1 - 6  # y1 是 bbox 上边界
```

### 2. 对号形状优化

**参考代码的三个点**：
```python
p1 = (x, y + int(size * 0.55))          # 左点
p2 = (x + int(size * 0.35), y + size)   # 底点
p3 = (x + size, y)                       # 右上点
```

**特点**：
- 左点在55%高度位置
- 底点在35%宽度位置
- 形成更自然的 √ 形状

**我的实现**（完全相同的比例）：
```python
p1 = (start_x, start_y + int(auto_size * 0.55))
p2 = (start_x + int(auto_size * 0.35), start_y + auto_size)
p3 = (start_x + auto_size, start_y)
```

### 3. 对号大小自适应

**参考代码**：固定34px
```python
size = 34  # 固定大小
```

**我的改进**：自适应bbox高度，带限制
```python
auto_size = max(30, min(50, int(bbox_h * 0.8)))
```
- 最小：30px
- 最大：50px
- 默认：bbox高度的80%
- 适应不同大小的答案

### 4. 红圈大小优化

**之前**：
- 固定radius，不考虑bbox形状
- 可能太小或太大

**现在**：
- 椭圆轴长 = bbox的一半 + 6px
- 完美贴合bbox，稍微大一圈

**参考代码**：
```python
# OpenCV版本
axes = (w // 2 + 6, h // 2 + 6)
cv2.ellipse(img, (cx, cy), axes, ...)
```

**我的实现**：
```python
# PIL版本
radius_x = bbox_w / 2 + 6
radius_y = bbox_h / 2 + 6
ellipse_bbox = [cx - radius_x, cy - radius_y,
                cx + radius_x, cy + radius_y]
draw.ellipse(ellipse_bbox, ...)
```

### 5. 线宽统一

- 对号：6px（参考代码默认）
- 红圈：6px（参考代码默认）
- 提供更清晰的视觉效果

## 对比图示

```
之前的实现：
┌─────────────┐
│   tail      │  ← bbox
│      ✓      │  ← 对号在中心，遮挡内容
└─────────────┘

现在的实现：
┌─────────────┐
│   tail      │  ✓  ← 对号在右侧，清晰不遮挡
└─────────────┘

红圈对比：
之前：○ (固定圆形，可能不匹配bbox)
现在：⬭ (椭圆，完美贴合bbox形状)
```

## 技术细节

### PIL vs OpenCV的差异

| 特性 | OpenCV | PIL (我的实现) |
|------|--------|----------------|
| 抗锯齿 | `cv2.LINE_AA` | PIL默认平滑 |
| 椭圆参数 | `(center, axes, angle)` | `[left, top, right, bottom]` |
| 颜色格式 | BGR | RGB/Hex |
| 线宽 | `thickness` | `width` |

### 坐标转换

**OpenCV**：
```python
x, y, w, h = bbox  # x,y是左上角，w,h是宽高
```

**PIL**：
```python
x1, y1, x2, y2 = bbox  # x1,y1是左上角，x2,y2是右下角
bbox_w = x2 - x1
bbox_h = y2 - y1
```

## 参数调整

如果需要微调效果：

### 调整对号大小范围
```python
# services.py line 999
auto_size = max(30, min(50, int(bbox_h * 0.8)))
#             最小  最大     比例
```

### 调整对号位置偏移
```python
# services.py line 995-996
start_x = x2 + 8   # 右侧偏移（增加 = 更远）
start_y = y1 - 6   # 上方偏移（减少 = 更高）
```

### 调整红圈大小余量
```python
# services.py line 1025-1026
radius_x = bbox_w / 2 + 6   # +6 = 额外6px余量
radius_y = bbox_h / 2 + 6
```

### 调整线宽
```python
# services.py line 1060, 1063
draw_checkmark(..., width=6)   # 3-8
draw_red_circle(..., width=6)  # 3-8
```

## 测试建议

1. **重启服务器**（如果使用 `--reload` 会自动重启）
2. **上传新照片**进行识别
3. **检查效果**：
   - ✓ 对号是否在答案右侧
   - ✓ 对号大小是否合适
   - ✓ 红圈是否贴合答案
   - ✓ 标记是否清晰可见

## 预期效果

现在的标记应该更接近参考图的效果：
- 对号在答案右侧，不遮挡内容
- 对号大小适应答案高度
- 红圈完美贴合答案形状
- 线条清晰，视觉效果好

重新识别照片后应该能看到明显改进！
