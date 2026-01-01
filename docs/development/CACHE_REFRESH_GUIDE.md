# 刷新缓存和验证步骤

## 问题诊断

代码已经正确修改，但浏览器可能缓存了旧版本。

## 解决步骤

### 1. 硬刷新浏览器缓存

**Windows/Linux**:
- Chrome/Edge: `Ctrl + Shift + R` 或 `Ctrl + F5`
- Firefox: `Ctrl + Shift + R`

**Mac**:
- Chrome/Edge: `Cmd + Shift + R`
- Firefox: `Cmd + Shift + R`

### 2. 清空浏览器缓存

如果硬刷新无效：
1. 打开开发者工具 (`F12`)
2. 右键点击刷新按钮
3. 选择"清空缓存并硬性重新加载"

### 3. 重启后端服务器

如果仍然无效，重启FastAPI服务器：
```bash
# 停止当前服务器 (Ctrl+C)
# 然后重新启动
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 验证修改是否生效

刷新后，你应该看到：

**表格列（从左到右）**：
1. 题号
2. 题目/提示
3. LLM识别（不一致时显示红色）
4. 是否正确（绿色✓或红色✗图标）
5. 入库（复选框）
6. 置信度
7. 备注
8. **识别图片**（新增，显示缩略图）

**已删除的列**：
- ~~OCR识别~~
- ~~采信~~（下拉选择框）
- ~~手动输入~~

### 5. 检查浏览器控制台

如果还是不显示，打开开发者工具查看：
- Console标签页是否有JavaScript错误
- Network标签页，刷新页面，查看submit.html是否返回200状态码

## 临时验证方法

在浏览器控制台运行：
```javascript
// 验证HTML版本
document.querySelector('title').textContent
// 应该返回: "提交与批改 v2.0"

// 检查表格列数
document.querySelector('table th:last-child').textContent
// 应该返回: "识别图片"
```

## 如果问题依然存在

请提供：
1. 浏览器类型和版本
2. 浏览器控制台的错误信息
3. Network标签中submit.html的响应内容
