# 测试数据说明

## 文件列表

### 1. `C:\temp\Join in G4 with cover.json`（基准导入测试文件）
- **用途**: 基准导入测试（带封面）
- **说明**: 本地路径文件，不纳入版本库
- **内容**:
  - 单元元数据 + 知识点
  - `assets` 中包含 `id="cover"` 的封面图片（base64）

### 2. `4年级上学期英语系统资料.json`
- **用途**: 完整的测试数据样例，包含455个知识点
- **来源**: 外研社四年级上册英语教材
- **内容**:
  - 7个单元 (U1-U7)
  - 455个知识点（单词、短语、句子）
  - 完整的教材元数据

### 3. `template_example.json`
- **用途**: 简化的JSON模板，供快速创建新资料库参考
- **内容**: 最小化示例，展示所有支持的字段

### 4. `complete_example.json`
- **用途**: 另一个简化示例（剑桥教材）
- **内容**: 包含基本结构的示例

---

## JSON 格式说明

### 支持的格式
系统支持 `EL_KB_V1_UNITMETA` 格式，包含以下部分：

#### 1. 基本信息 (`base` 对象)
```json
{
  "base": {
    "name": "资料库名称",           // 必填，不超过100字符
    "education_stage": "小学",      // 可选：小学/初中/高中
    "grade": "4年级",               // 可选：年级，不超过20字符
    "term": "上学期",               // 可选：上学期/下学期
    "version": "2025年秋",          // 可选：版本信息，不超过50字符
    "publisher": "出版社名称",      // 可选：不超过100字符
    "editor": "主编姓名",           // 可选：不超过100字符
    "description": "描述信息"       // 可选：不超过500字符
  }
}
```

#### 2. 单元元数据 (`unit_meta` 数组，可选)
```json
{
  "unit_meta": [
    {
      "unit_code": "U1",           // 必填：单元代码
      "unit_name": "单元名称",      // 必填：单元名称
      "unit_index": 1,             // 必填：单元顺序（用于排序）
      "descriptions": []           // 可选：额外描述
    }
  ]
}
```

#### 4. 资产 (`assets` 数组，可选)
```json
{
  "assets": [
    {
      "id": "cover",
      "mime": "image/jpeg",
      "data": "BASE64_ENCODED_IMAGE"
    }
  ]
}
```

> 说明：`id="cover"` 会被识别为资料库封面。

#### 3. 知识点 (`items` 数组)
```json
{
  "items": [
    {
      "unit_code": "U1",           // 可选：所属单元（留空则为"__ALL__"）
      "type": "WORD",              // 必填：WORD/PHRASE/SENTENCE
      "en_text": "hello",          // 必填：英文原文，不超过200字符
      "zh_hint": "你好",           // 可选：中文提示，不超过200字符
      "difficulty_tag": "write"    // 可选：write（会写）/recognize（会认）
    }
  ]
}
```

---

## 字段说明

### type (知识点类型)
- `WORD`: 单词
- `PHRASE`: 短语
- `SENTENCE`: 句子

### difficulty_tag (难度标签)
- `write`: 会写（要求能够默写）
- `recognize`: 会认（只需要认识）
- 留空: 未设置要求

---

## 导入方法

### 方法1: 通过界面导入
1. 访问 `/library.html`
2. 点击"创建资料库"
3. 填写基本信息
4. 选择JSON文件上传
5. 系统会自动导入知识点和单元元数据

### 方法2: 通过API导入
```bash
curl -X POST http://localhost:8000/api/knowledge-bases/import-file \
  -F "file=@C:\\temp\\Join in G4 with cover.json" \
  -F "mode=skip"
```

---

## 字段映射和兼容性

系统支持以下字段别名（会自动转换）：

| 标准字段 | 兼容别名 |
|---------|---------|
| `editor` | `chief_editor` |
| `description` | `notes` |
| `zh_text` | `zh_hint` |
| `item_type` | `type` |
| `unit` | `unit_code` |

---

## 注意事项

1. **编码**: 文件必须使用 UTF-8 编码（支持 BOM）
2. **文件大小**: 建议不超过 10MB
3. **字段验证**:
   - `en_text` 必填，不超过 200 字符
   - `unit_code` 不超过 50 字符
   - 名称和描述字段有长度限制（见上文）
4. **重复处理**: 导入时，相同 `(base_id, en_text)` 的项目会被跳过（mode=skip）或更新（mode=update）
5. **单元元数据**: 如果提供了 `unit_meta`，系统会自动导入并用于单元排序

---

## 示例使用流程

1. 复制 `template_example.json` 作为起点
2. 修改 `base` 对象中的教材信息
3. 添加 `unit_meta` 定义单元结构
4. 添加 `items` 填充知识点
5. 通过界面或API导入到系统

---

## 更新历史

- 2025-01: 添加 `editor` 字段支持
- 2025-01: 优化元数据字段的提取逻辑
- 2025-01: 添加单元元数据导入功能
