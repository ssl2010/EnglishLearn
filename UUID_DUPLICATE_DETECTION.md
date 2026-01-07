# UUID重复检测系统

## 概述

基于试卷UUID（ES-XXXX-XXXXXX）的重复提交检测机制，替代了原有基于日期的检测方式，解决了同一天多份试卷被误判为重复的问题。

## UUID格式

```
ES-0055-CF12D2
│  │    └────── 字符部分（6位，字母数字混合，OCR难度高）
│  └─────────── 条码部分（4位数字，OCR难度低）
└────────────── 前缀（固定）
```

## 重复检测逻辑

### 优先级策略

1. **UUID检测**（优先）：`student_id + practice_uuid`
   - 更准确，支持同一天多份试卷
   - 依赖OCR识别质量

2. **日期检测**（降级）：`student_id + created_date`
   - 兼容旧记录（没有UUID的历史数据）
   - 兼容无UUID的试卷

### 识别策略

#### 1. 完整UUID识别
- 正则：`ES-(\d{4})-([A-Z0-9]{6})`
- 直接从OCR文本中提取完整UUID
- 使用OCR置信度作为权重

#### 2. 分段识别（降级方案）
- 条码部分：`ES-(\d{4})` - 数字易识别，权重80%
- 字符部分：`([A-Z0-9]{6})` - 字母数字混合，权重20%
- 最终置信度 = 条码置信度 × 0.8 + 字符置信度 × 0.2

#### 3. 多页一致性检查
- 正反两面UUID必须相同
- 如果不一致：
  - 使用置信度加权投票选择最可能的UUID
  - 向用户显示警告：`⚠️ 多页试卷编号不一致！`
  - 提示可能上传了不同试卷的照片

## 实现细节

### 后端实现

#### 1. UUID提取 (`services.py:66-209`)

```python
def _extract_uuid_from_ocr(ocr_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    返回：
    {
        "uuid": "ES-0055-CF12D2",
        "page_uuids": [...],          # 每页的识别结果
        "consistent": True/False,      # 多页是否一致
        "confidence": 0.95,            # 综合置信度
        "warning": "..." or None       # 警告信息
    }
    """
```

**特性**：
- 支持完整识别和分段组合
- 置信度加权（条码80% + 字符20%）
- 多页一致性验证
- 自动选择最佳结果

#### 2. 重复检测 (`services.py:1997-2081`)

```python
def confirm_ai_extracted(
    student_id: int,
    base_id: int,
    items: List[Dict],
    extracted_date: str = None,
    worksheet_uuid: str = None,  # 新增
    force_duplicate: bool = False
) -> Dict:
```

**检测流程**：
1. 如果有UUID → 查询 `practice_uuid` 字段
2. 如果无UUID或未找到 → 降级查询 `created_date` 字段
3. 找到重复 → 返回警告信息
4. 未找到重复 → 允许入库，保存UUID

#### 3. 数据库存储 (`services.py:2092`)

```sql
INSERT INTO practice_sessions(
    student_id, base_id, status, params_json,
    created_at, completed_at,
    created_date,   -- 保留，兼容旧逻辑
    practice_uuid   -- 新增，主要检测依据
)
VALUES(?,?,?,?,?,?,?,?)
```

### 前端实现

#### 1. UUID显示 (`submit.html:237-248, 690-701`)

```javascript
// 保存UUID信息
window._worksheetUuid = data.worksheet_uuid;
window._uuidInfo = data.uuid_info;

// 显示UUID
msg.textContent = `识别完成；试卷编号：${data.worksheet_uuid}`;

// 显示警告（如果不一致）
if (data.uuid_info && data.uuid_info.warning) {
  msg.innerHTML += `<br><span style="color:#e5484d">${data.uuid_info.warning}</span>`;
}
```

#### 2. UUID提交 (`submit.html:612-622`)

```javascript
const r = await api(`/api/ai/confirm-extracted`, {
  method:'POST',
  body: JSON.stringify({
    student_id: cfg.student_id,
    base_id: cfg.base_id,
    items: items,
    extracted_date: window._extractedDate,
    worksheet_uuid: window._worksheetUuid,  // 新增
    force_duplicate: forceDuplicate
  })
});
```

#### 3. 重复警告优化 (`submit.html:625-632`)

```javascript
// 动态显示标识类型（UUID或日期）
const identifier = r.existing_uuid || r.existing_date || '未知';
const identifierLabel = r.existing_uuid ? '试卷编号' : '日期';

msg.innerHTML = `
  ⚠️ 检测到重复提交<br>
  ${identifierLabel} ${identifier} 的试卷已经提交过...
`;
```

## 用户体验

### 成功识别UUID
```
✓ 识别完成；图片 2 张；试卷日期：2026年01月04日；试卷编号：ES-0055-CF12D2
```

### UUID不一致警告
```
✓ 识别完成；图片 2 张；试卷日期：2026年01月04日；试卷编号：ES-0055-CF12D2
⚠️ 多页试卷编号不一致！识别到: ES-0055-CF12D2, ES-0056-AB12CD。请检查是否上传了不同试卷的照片。
```

### 重复提交检测
```
⚠️ 检测到重复提交
试卷编号 ES-0055-CF12D2 的试卷已经提交过：共 29 题，正确 19 题，正确率 65.5%

[确认重新提交（学生重做）] [取消]
```

## 兼容性

### 向后兼容
- ✅ 旧记录无UUID，使用日期检测
- ✅ 新记录优先UUID检测
- ✅ 无UUID试卷降级日期检测

### 数据迁移
- 无需迁移旧数据
- 新提交自动保存UUID
- 新旧记录可共存

## 优势

1. **解决同天多卷问题**：同一天做多份不同试卷不会误判
2. **唯一性保证**：每份试卷有唯一编号
3. **降级策略**：OCR失败时降级到日期检测
4. **多页验证**：自动检查正反面UUID一致性
5. **置信度优化**：根据识别难度加权处理

## 测试建议

### 1. UUID识别测试
- 上传清晰的试卷照片
- 检查是否正确识别UUID
- 验证多页UUID一致性

### 2. 重复检测测试
- 提交相同UUID的试卷 → 应该提示重复
- 提交不同UUID的试卷（同一天）→ 应该不提示重复
- 确认重新提交 → 应该允许入库

### 3. 降级测试
- 遮挡UUID部分 → 应该降级到日期检测
- 旧记录重新提交 → 应该用日期检测

## 注意事项

1. **OCR质量依赖**：需要清晰的照片确保UUID识别准确
2. **多页一致性**：正反面必须是同一份试卷
3. **置信度阈值**：当前未设置最低置信度，可根据实际情况调整
4. **UUID格式**：目前仅支持 `ES-XXXX-XXXXXX` 格式

## 未来优化

- [ ] 添加置信度阈值，低于阈值提示人工核对
- [ ] 支持更多UUID格式
- [ ] UUID手动修正功能
- [ ] OCR识别失败时的人工输入备选

---

**实现完成时间**: 2026-01-05
**版本**: 1.0.0
