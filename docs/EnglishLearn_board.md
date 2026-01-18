# EnglishLearn 第二阶段增量：家长看板重构（Codex 可执行规格）

版本：V1  
生成时间：2026-01-18 12:15:00（Asia/Singapore, UTC+8）

---

## 1. 背景与目标

当前工程已跑通：练习单生成、提交/批改、练习单管理、学习库管理、资料库维护等。  
本增量聚焦 **家长看板（dashboard）** 的重新设计与实现，使其满足：

1) **登录后默认进入家长看板**，且 **默认不选择任何学生**。  
2) 在“未选择学生”状态下，需要展示 **所有学生（最多 3 个）** 的学习库掌握概要，并尽量做到 **不翻页**（常见 1280px 宽度下单屏容纳 3 个学生卡片）。  
3) 当选择某个学生后，展示该学生的 **学习库（由多个资料库构成）的详细掌握信息**，包括：学习进度、掌握情况、近期练习、易错等。  
4) **看板粒度到“资料库（base）”级别**，不在看板展开到“单元（unit）”级别（单元细节由学习库管理页面承担）。  
5) 由于学生是陆续学习的，需要用“当前学习进度”来解释掌握：  
   - **学习进度（coverage）**：已尝试的知识点数 / 学习库总知识点数  
   - **掌握情况（mastery）**：已掌握知识点数 / 已尝试知识点数（更符合“掌握”直觉：只评价已经练过的内容。）

---

## 2. 概念口径（务必按此实现）

### 2.1 学习库（Learning Library）
- **每个学生对应唯一一个学习库**（不需要单独名称）。  
- 学习库由 **1~多个资料库（base）** 组成，对应表 `student_learning_bases` 中该学生的 **active** 条目集合。  
- 看板展示的“掌握情况”，以 **当前 active 的资料库集合** 为准。

### 2.2 资料库（Base）
- 资料库是可复用的知识点集合，对应表 `bases` 与 `items`。  
- 单元（unit）属于资料库，不在看板展开。

### 2.3 学习/掌握定义
- **已尝试（learned）**：`student_item_stats.total_attempts > 0` 的知识点。  
- **已掌握（mastered）**：`student_item_stats.consecutive_correct >= mastery_threshold` 的知识点。  
- `mastery_threshold` 已存在于系统设置（`/api/settings`），默认 2。

### 2.4 近期时间窗
- **近 7 天 / 本周**：用于“练习频率”展示（按 UTC+8 的自然日）。  
- **近 30 天**：用于“练习天数”“错题”等统计（按 UTC+8 的自然日，或按 UTC ISO 时间截断也可，要求一致即可）。

---

## 3. 体验设计（UI/信息结构）

### 3.1 登录后的默认态：不选择任何学生（全局概览）
页面标题：**家长看板 / 全部学生**

#### 3.1.1 家长最关心的“最小集合”（Overview 卡片内必须包含）
每个学生 1 张卡片（最多 3 张，单屏横向三列）：

1. **学习进度（coverage）**  
   - 文案：`学习进度：已练 / 总量`（例如 `120 / 360`）  
   - 进度条：`learned_items / total_items`

2. **掌握情况（mastery）**  
   - 文案：`掌握：已掌握 / 已练`（例如 `80 / 120`）  
   - 进度条：`mastered_items / learned_items`（learned=0 时显示 `-`）

3. **练习频率（本周）**  
   - 7 个小格（Mon..Sun）：当天有任意练习单（跨资料库）则点亮。  
   - 文案：`本周：X / weekly_target_days`（目标来自 `/api/settings`）

4. **近 30 天错题强度（简化）**  
   - 只展示 **不同错题知识点数**：`错题（30天）：N`  
   - 解释：从 `practice_results` 中统计近 30 天 `is_correct=0` 的 distinct item_id

5. **最近一次练习时间（简化）**  
   - 文案：`最近练习：YYYY-MM-DD`（无则 `-`）

#### 3.1.2 交互
- 点击某个学生卡片 → 切换到“已选中该学生”的详细态（3.2）。
- 若学生未配置任何 active 资料库：卡片上显示提醒 `未配置学习库`，并提供快捷入口按钮（跳转到 `knowledge.html`）。

#### 3.1.3 布局约束（确保 3 个孩子不翻页）
- 1280px 宽度下，学生卡片使用 `grid-template-columns: repeat(3, 1fr)`；卡片高度控制在合理范围，避免长表格。
- Overview 不显示：近期练习列表 / 易错 Top10（这些放入详细态）。

---

### 3.2 选择某个学生后的详细态
页面标题：**家长看板 / {student_name}**（这里的 `{student_name}` 仅为展示占位，代码里用真实姓名替换）

页面分为 3 个区块，自上而下：

#### 3.2.1 区块 A：全库总览（该学生学习库聚合）
- 4 个 KPI 卡片（可两行两列）：
  1) 学习库总量（total_items）  
  2) 已练（learned_items）+ 学习进度条  
  3) 已掌握（mastered_items）+ 掌握进度条（相对已练）  
  4) 本周练习：X / target + 7 格小日历

另补充两个轻量指标（可放在同一行小字）：
- 近 30 天练习天数（across library）
- 近 30 天错题知识点数（distinct wrong items）

#### 3.2.2 区块 B：资料库级别掌握概览（核心）
展示该学生学习库中（active）资料库列表的掌握情况（不下钻 unit）：
- 默认展示 **最多 6 个资料库**，超过则提供“展开全部/收起”。
- 每个资料库一行（表格或列表均可），包含：
  - 资料库显示名：`custom_name || base_name || 资料库#id`
  - 学习进度：`learned / total` + 进度条
  - 掌握情况：`mastered / learned` + 进度条
  - （可选）当前进度提示：`current_unit`（来自 student_learning_bases.current_unit，若存在）

#### 3.2.3 区块 C：近期与易错（聚合到学习库）
- 近期练习（最近 10 个练习单，跨资料库）：
  - 列：时间、资料库、状态、题数、PDF 链接（默写单/答案）
- 易错 Top10（近 30 天，跨资料库）：
  - 列：英文知识点、错误次数、所属资料库（简写）

---

## 4. 接口设计（新增，不破坏现有接口）

> 现有 `GET /api/dashboard?student_id=&base_id=&days=` 保持不动（兼容旧实现/不影响其他页面）。  
> 本增量新增 V2 接口供新版 dashboard 使用。

### 4.1 GET /api/dashboard/overview?days=30
用途：未选择学生时，返回所有学生的概览数据（最多 3 个学生）。

**Response（示例结构）**
```json
{
  "days": 30,
  "weekly_target_days": 4,
  "mastery_threshold": 2,
  "students": [
    {
      "student_id": 1,
      "student_name": "糯米",
      "grade": "G4",
      "avatar": "rabbit",
      "active_bases_count": 2,
      "total_items": 360,
      "learned_items": 120,
      "mastered_items": 80,
      "coverage_rate": 0.3333,
      "mastery_rate_in_learned": 0.6667,
      "week_bits": "1010110",
      "week_practice_days": 4,
      "wrong_items_30d": 15,
      "last_practice_at": "2026-01-18"
    }
  ]
}
```

### 4.2 GET /api/dashboard/student?student_id=1&days=30&max_bases=6
用途：选中某学生后的详情数据（学习库聚合）。

**Response（示例结构）**
```json
{
  "student": {
    "id": 1,
    "name": "糯米",
    "grade": "G4",
    "avatar": "rabbit"
  },
  "days": 30,
  "weekly_target_days": 4,
  "mastery_threshold": 2,

  "library": {
    "active_bases_count": 2,
    "total_items": 360,
    "learned_items": 120,
    "mastered_items": 80,
    "coverage_rate": 0.3333,
    "mastery_rate_in_learned": 0.6667,
    "practice_days_30d": 12,
    "wrong_items_30d": 15,
    "week_bits": "1010110",
    "week_practice_days": 4,
    "last_practice_at": "2026-01-18"
  },

  "bases": {
    "truncated": true,
    "max_bases": 6,
    "rows": [
      {
        "base_id": 10,
        "label": "四上 Unit1-6",
        "current_unit": "U3",
        "total": 240,
        "learned": 90,
        "mastered": 70,
        "coverage_rate": 0.375,
        "mastery_rate_in_learned": 0.7778
      }
    ]
  },

  "recent_sessions": [
    {
      "id": 123,
      "created_at": "2026-01-18T02:13:04.123456+00:00",
      "status": "CORRECTED",
      "base_id": 10,
      "base_label": "四上 Unit1-6",
      "item_count": 29,
      "pdf_url": "/media/xxx.pdf",
      "answer_pdf_url": "/media/xxx_answer.pdf"
    }
  ],

  "top_wrong_30d": [
    {
      "en_text": "Can Ken drive a car?",
      "item_type": "SENTENCE",
      "wrong_count": 5,
      "base_id": 10,
      "base_label": "四上 Unit1-6"
    }
  ]
}
```

---

## 5. 后端实现（Codex 执行任务清单）

### 5.1 需要修改/新增的文件
- `backend/app/services.py`：新增聚合统计函数（overview + student）。  
- `backend/app/main.py`：新增 API 路由 `GET /api/dashboard/overview` 与 `GET /api/dashboard/student`。

### 5.2 services.py：新增函数（建议放在现有 get_dashboard 附近）
新增 3 个函数：

#### (1) `_get_active_learning_bases(conn, student_id) -> List[dict]`
SQL（参考）：
```sql
SELECT
  slb.base_id,
  slb.custom_name,
  slb.current_unit,
  slb.display_order,
  b.name AS base_name
FROM student_learning_bases slb
JOIN bases b ON b.id = slb.base_id
WHERE slb.student_id = ? AND slb.is_active = 1
ORDER BY slb.display_order, slb.id
```

返回每行至少包含：
- base_id
- label = custom_name || base_name || "资料库#{base_id}"
- current_unit（可为空）

#### (2) `get_dashboard_overview(days: int = 30) -> dict`
核心步骤：
1. `mastery_threshold = get_mastery_threshold()`（复用现有 get_setting）
2. `weekly_target_days = get_weekly_target_days()`（复用现有 get_setting）
3. 取所有学生 `SELECT * FROM students ORDER BY id`
4. 对每个学生：
   - active_bases = `_get_active_learning_bases`
   - 若 active_bases 为空：返回该学生的空统计（total/learned/mastered=0）并带提醒字段（可选）
   - 统计 total_items / learned_items / mastered_items（跨 base_id in active_bases）
   - 统计 `wrong_items_30d`（distinct item_id，近 30 天 is_correct=0）
   - 统计本周 `week_bits` 与 `week_practice_days`（跨 base 的 practice_sessions.created_at）
   - 统计 `last_practice_at`（max created_at）
5. 拼装返回 JSON

**统计 SQL（建议）**

- total_items：
```sql
SELECT COUNT(1) AS c FROM items WHERE base_id IN (?,?,...)
```

- learned_items（尝试过）：
```sql
SELECT COUNT(1) AS c
FROM student_item_stats sis
JOIN items i ON i.id = sis.item_id
WHERE sis.student_id = ?
  AND i.base_id IN (?,?,...)
  AND sis.total_attempts > 0
```

- mastered_items：
```sql
SELECT COUNT(1) AS c
FROM student_item_stats sis
JOIN items i ON i.id = sis.item_id
WHERE sis.student_id = ?
  AND i.base_id IN (?,?,...)
  AND sis.consecutive_correct >= ?
```

- wrong_items_30d（distinct item_id，建议用 practice_results，避免“历史错过但近期已对”仍算错题的误差）：
```sql
SELECT COUNT(DISTINCT ei.item_id) AS c
FROM practice_results pr
JOIN practice_sessions ps ON ps.id = pr.session_id
JOIN exercise_items ei ON ei.id = pr.exercise_item_id
WHERE ps.student_id = ?
  AND ps.base_id IN (?,?,...)
  AND pr.is_correct = 0
  AND pr.created_at >= ?
  AND ei.item_id IS NOT NULL
```

- last_practice_at：
```sql
SELECT MAX(created_at) AS t
FROM practice_sessions
WHERE student_id = ? AND base_id IN (?,?,...)
```

- week_bits / week_practice_days（建议 Python 计算，确保 UTC+8 周口径一致）：
  1) SQL 拉取最近 14 天 created_at（给足缓冲）：
  ```sql
  SELECT created_at FROM practice_sessions
  WHERE student_id=? AND base_id IN (?,?,...) AND created_at >= ?
  ```
  2) Python 将 ISO 时间解析为 datetime，转换到 UTC+8，按自然日归集；再按本周 Mon..Sun 生成 7 位 bitstring。

**边界处理**
- total_items=0：coverage_rate=0，显示 `0 / 0`
- learned_items=0：mastery_rate_in_learned = null（前端显示 `-`）

#### (3) `get_dashboard_student(student_id: int, days: int = 30, max_bases: int = 6) -> dict`
核心步骤：
1. 读取 student 基本信息（students 表）
2. active_bases = `_get_active_learning_bases`
3. 聚合 library 总览（同 overview）
4. 资料库级别统计（每个 base 一行，按 active_bases 的 display_order 输出）：
   - 推荐用一条 group SQL 获取 base_id -> total/learned/mastered，再按顺序 merge：
   ```sql
   SELECT
     i.base_id AS base_id,
     COUNT(i.id) AS total,
     COUNT(CASE WHEN sis.total_attempts > 0 THEN 1 END) AS learned,
     COUNT(CASE WHEN sis.consecutive_correct >= ? THEN 1 END) AS mastered
   FROM items i
   LEFT JOIN student_item_stats sis ON sis.item_id = i.id AND sis.student_id = ?
   WHERE i.base_id IN (?,?,...)
   GROUP BY i.base_id
   ```
5. recent_sessions（跨 base，最近 10 个）：
```sql
SELECT
  ps.id, ps.status, ps.created_at, ps.corrected_at, ps.base_id, ps.pdf_path, ps.answer_pdf_path,
  (SELECT COUNT(1) FROM exercise_items ei WHERE ei.session_id = ps.id) AS item_count
FROM practice_sessions ps
WHERE ps.student_id=? AND ps.base_id IN (?,?,...)
ORDER BY ps.id DESC
LIMIT 10
```
并补充 `base_label`，以及 `pdf_url/answer_pdf_url`（沿用现有 get_dashboard 做法）

6. top_wrong_30d（跨 base，近 30 天）：
```sql
SELECT
  i.en_text,
  i.item_type,
  i.base_id,
  COUNT(1) AS wrong_count,
  MAX(pr.created_at) AS last_wrong_at
FROM practice_results pr
JOIN practice_sessions ps ON ps.id = pr.session_id
JOIN exercise_items ei ON ei.id = pr.exercise_item_id
JOIN items i ON i.id = ei.item_id
WHERE ps.student_id = ?
  AND ps.base_id IN (?,?,...)
  AND pr.is_correct = 0
  AND pr.created_at >= ?
GROUP BY i.id
ORDER BY wrong_count DESC, last_wrong_at DESC
LIMIT 10
```
（如需要 base_label，在 Python merge base_id->label）

7. bases 展示限制：
- 输出 `bases.truncated = (active_bases_count > max_bases)`
- `bases.rows` 仅输出前 max_bases（按 display_order），并保留 `max_bases`

---

## 6. API 路由实现（main.py）

### 6.1 新增路由
在 `main.py` 中新增：

- `@app.get("/api/dashboard/overview")`
  - 入参：`days: int = 30`
  - 返回：`services.get_dashboard_overview(days)`

- `@app.get("/api/dashboard/student")`
  - 入参：`student_id: int, days: int = 30, max_bases: int = 6`
  - 返回：`services.get_dashboard_student(student_id, days, max_bases)`

### 6.2 鉴权
- 复用现有 `auth_middleware`（已对 `/api/` 做登录校验），无需额外改动。
- 可选：校验 student_id 存在，否则 404。

---

## 7. 前端实现（dashboard.html + app.html）

### 7.1 需要修改的文件
- `frontend/dashboard.html`：重写为“overview + student detail”双态页面（不再强依赖 `el_cfg.base_id`）。
- `frontend/app.html`：调整默认登录态为“全部学生”，并对需要学生上下文的菜单项做 gating。

### 7.2 app.html：导航与学生选择逻辑调整
#### 7.2.1 默认进入“全部学生”
- `init()` 中不再默认选中第一个学生。  
- 设置：
  - `state.currentStudentId = null`
  - 写入 cfg：`{ "student_id": null }`（至少保证 dashboard 不会因为 cfg 缺失跳转）
  - 默认页面：`dashboard.html`

#### 7.2.2 学生选择器增加“全部学生”卡片
- 在 `renderStudentCards()` 最前面插入一个特殊卡片：
  - label：`全部学生`
  - 点击后调用 `selectAllStudents()`：
    - `state.currentStudentId = null`
    - `state.bases = []`
    - `state.currentBaseId = null`
    - `localStorage.setItem('el_cfg', JSON.stringify({ student_id:null }))`
    - `setPage('dashboard.html')`

#### 7.2.3 菜单 gating（不改子页面的前提下）
- 为 menuItems 增加字段 `requiresStudent`：
  - dashboard.html: false
  - profile.html / library.html: false（不依赖学生上下文）
  - generate.html / submit.html / practice.html / knowledge.html: true
- 点击 requiresStudent 的菜单项时：
  - 若 `state.currentStudentId` 为 null → 弹出 `alert('请先选择一个学生')` 并保持在 dashboard。

#### 7.2.4 允许 dashboard 内点击学生卡片驱动选择
- app.html 的 message handler 增加：
  - 监听 `{type:'selectStudent', student_id: <id>}` → 调用 `selectStudent(id)`
  - 监听 `{type:'selectAllStudents'}` → 调用 `selectAllStudents()`

### 7.3 dashboard.html：双态渲染
#### 7.3.1 判定规则
- 读取 `localStorage.el_cfg`：
  - 若 `cfg.student_id` 为空/不存在 → 渲染 overview（调用 `/api/dashboard/overview`）
  - 否则 → 渲染 student detail（调用 `/api/dashboard/student?student_id=...`）

#### 7.3.2 overview UI（3 张学生卡片）
- 使用 CSS Grid 三列布局，卡片内展示 3.1.1 定义的最小集合。
- 点击学生卡片：`window.parent.postMessage({type:'selectStudent', student_id}, '*')`

#### 7.3.3 detail UI（A/B/C 三个区块）
- 区块 A：全库总览 KPI
- 区块 B：资料库列表（默认 max_bases=6，支持展开）
  - 展开可在前端通过再次请求 `max_bases=999` 或一次取全量后在前端切换
- 区块 C：recent_sessions 表格 + top_wrong_30d 列表
- 提供快捷入口：
  - 去学习库管理：`/knowledge.html`
  - 去生成练习单：`/generate.html`（仅当 app.html 已选中学生时菜单可点）

---

## 8. 验收标准（必须满足）

1) 登录后进入 `app.html`，默认 iframe 打开 `dashboard.html`，且学生选择器显示“全部学生”被选中。  
2) dashboard 在默认态能展示所有学生概览（<=3 学生，1280px 宽度下单屏可见）。  
3) 点击某学生卡片，切换到该学生详情态，展示：
   - 学习库总览（总量/已练/已掌握/本周频率/30天错题等）
   - 资料库级别掌握列表（不出现 unit 维度）
   - 近期练习（跨资料库）
   - 易错 Top10（近 30 天）
4) 选择“全部学生”后，generate/submit/practice/knowledge 等页面不可进入（提示先选学生），不要求改动这些子页面本身。  
5) 新增接口不破坏旧接口：`GET /api/dashboard?student_id=&base_id=` 仍可工作。

---

## 9. 额外建议（可选，不阻塞本次）
- 为 overview/student 接口补充最小单元测试（pytest），确保统计 SQL 在无数据/有数据时均不抛异常。
- 对 week_bits 的周起始日口径固定为 Mon..Sun（ISO 周），避免地域歧义。
