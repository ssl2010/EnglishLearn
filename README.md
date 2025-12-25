# English Learning MVP (单孩子 / 无账户 / 可打印默写单)

本工程按《精简需求后.docx》实现一个 **可运行的最小闭环**：
- 本地初始化固化 `student_id / base_id`
- 知识库导入与维护（仅示例：批量导入）
- 默写单生成（C→E），导出 PDF（题目单 + 答案单）
- 提交与批改：先人工录入答案（规则优先、完全匹配）；拍照上传保存原图用于复核
- 学习记录与家长看板：已学/已掌握/易错/最近练习/练习日历

## 运行

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

打开浏览器访问：
- http://127.0.0.1:8000/  （系统引导页）

## 导入示例数据

- `seed/sample_items.json` 提供一个极小示例。
- 在“知识库管理”页面粘贴 JSON 并导入。

## 备注
- AI/OCR 在 MVP 中仅保留接口与数据结构，默认不做自动识别，以保证稳定性。

## 批改方式（推荐）
- 家长根据答案在纸质默写单上批改（**尽量只标错**：红叉/圈错/划线；对的留空）。
- 在【提交与批改】页上传照片，系统识别每题对错并给出建议。
- 家长确认/修正后提交入库，系统更新易错统计与掌握度。

## 系统参数
- 掌握阈值（连续正确次数）默认=2，可在引导页调整。

## OpenAI 视觉识别（可选）

本项目支持用 OpenAI 视觉大模型对「家长已批改的纸质默写单照片」做整页分析，输出逐题的对/错建议（以及可选的学生作答文本）。

### 开启方式
1) 在后端目录安装依赖：
   - `pip install -r requirements.txt`

2) 设置环境变量（只在服务端设置，不要写到前端）：
   - `OPENAI_API_KEY=你的key`
   - 可选：`EL_OPENAI_VISION_MODEL=gpt-4o-mini`
   - 可选：`EL_MARK_GRADING_PROVIDER=openai`  （默认 auto：有 key 则优先 OpenAI，否则回退 OpenCV）

3) 前端页面：进入「提交与批改」页面，选择练习单 -> 上传已批改照片。

### 说明
- 模型输出仅作为“建议”，系统仍要求家长在网页上确认/修正后才会写入统计。
- 建议家长尽量“只标错”（红叉/圈错/划线），正确题目留空，可显著降低误判与成本。
