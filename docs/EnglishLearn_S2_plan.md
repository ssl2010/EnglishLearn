EnglishLearn 第二阶段工作文档（Codex 可直接落地版）

账号管理（极简） + 多学生（家庭） + 专业导航壳（不改现有子页面）

| 版本 | V2-Plan-CodexReady |
| --- | --- |
| 日期 | 2026-01-07 |
| 代码基线 | EnglishLearn_no_media_no_env（当前已跑通：生成/批改/管理练习单与知识库） |
| 本阶段目标 | 引入登录（超级管理员为主）与多学生家庭使用；提供统一入口与导航壳；不改动现有子页面功能 |
| 约束 | 子页面（generate/submit/practice/knowledge/library/profile/dashboard 等）保持原样；仅新增 login/app 壳层与后端认证层 |
| 输出用途 | 可直接作为 Codex / ClaudeCode 等自动编码工具的实现规格说明 |

# 1. 当前代码结构速览（供自动编码定位文件）

- 关键目录：
- frontend/：静态页面（index.html 作为入口菜单；其他页面通过 localStorage('el_cfg') 读取 student/base 上下文）
- backend/app/main.py：FastAPI 主入口，路由与业务逻辑集中在该文件
- backend/schema.sql：SQLite 表结构（由 backend/init_db.py 初始化）
- backend/init_db.py：初始化/重置数据库脚本
## 1.1 现有页面清单（保持不改）

| 文件 | 页面标题 | 主功能（从页面 H1/H2 推断） |
| --- | --- | --- |
| dashboard.html | 家长看板 | 家长看板 |
| generate.html | 生成默写单 | 生成默写单 |
| index.html | 英语学习系统 · 引导页 | 英语学习系统 |
| knowledge.html | 学习库管理 | 学习库管理 |
| library-edit.html | 编辑资料库 | 资料库 |
| library-items.html | 知识点管理 | 知识点管理 |
| library.html | 资料库维护 | 资料库维护 |
| practice-view.html | 练习单查看 | 练习单查看 |
| practice.html | 练习单管理 | 练习单管理 |
| profile.html | 学生信息 | — |
| submit.html | 提交与批改 v2.0 | 提交与批改 |

## 1.2 与本阶段相关的现有 API（节选）

说明：认证引入后，除登录/初始化外的 /api/* 将默认需要登录。

| 方法 | 路径 |
| --- | --- |
| GET | /api/knowledge-bases |
| POST | /api/knowledge-bases |
| POST | /api/knowledge-bases/import-file |
| DELETE | /api/knowledge-bases/{base_id} |
| PUT | /api/knowledge-bases/{base_id} |
| POST | /api/knowledge-bases/{base_id}/cover |
| GET | /api/knowledge-bases/{base_id}/items |
| GET | /api/knowledge-bases/{base_id}/units |
| POST | /api/knowledge-bases/{base_id}/units/import |
| GET | /api/practice-sessions |
| GET | /api/practice-sessions/by-uuid/{practice_uuid} |
| POST | /api/practice-sessions/generate |
| GET | /api/practice-sessions/search |
| DELETE | /api/practice-sessions/{session_id} |
| GET | /api/practice-sessions/{session_id}/detail |
| POST | /api/practice-sessions/{session_id}/manual-correct |
| POST | /api/practice-sessions/{session_id}/regenerate-pdf |
| POST | /api/practice-sessions/{session_id}/submit-image |
| POST | /api/practice-sessions/{session_id}/submit-marked-photo |
| GET | /api/students |
| POST | /api/students |
| GET | /api/students/{student_id} |
| PUT | /api/students/{student_id} |
| GET | /api/students/{student_id}/bases/{base_id}/items |
| GET | /api/students/{student_id}/bases/{base_id}/mastery-stats |
| GET | /api/students/{student_id}/learning-bases |
| POST | /api/students/{student_id}/learning-bases |
| DELETE | /api/students/{student_id}/learning-bases/{lb_id} |
| PUT | /api/students/{student_id}/learning-bases/{lb_id} |
| GET | /api/students/{student_id}/practice-sessions/by-date |
| GET | /api/system/status |

# 2. 第二阶段目标与范围

- Goals：
- G1. 增加登录：默认仅启用“超级管理员账号”（也允许未来扩展多个账号）。
- G2. 多学生：同一账号管理 1–3 个学生（默认最大 3，可配置）。
- G3. 专业导航：新增统一入口（app 壳）+ 顶部上下文选择器 + 左侧菜单；不修改现有子页面。
- G4. 公网安全基线：未登录不能访问业务页面与业务 API。
- Non‑Goals：
- N1. 不做复杂注册/找回/邮箱短信；不做细粒度 RBAC。
- N2. 不重做子页面 UI/交互/布局（只新增壳层）。
# 3. 目标用户体验与导航逻辑（不改子页面）

## 3.1 新增页面与跳转规则

- 新增页面：
- 1) /login.html：登录页（账号+密码）。
- 2) /app.html：应用壳（左侧菜单 + 顶部学生/资料库选择器 + iframe 承载子页面）。
- 跳转规则：
- 未登录访问任何页面（除 /login.html 及必要静态资源）→ 302 跳转 /login.html。
- 登录成功 → 302 跳转 /app.html。
- /（index.html）处理：保持 index.html 原入口菜单不作为主入口；建议改为：检测登录 → 已登录则跳转 /app.html，否则跳转 /login.html。
## 3.2 app.html 结构（Codex 必须按此实现）

布局：左侧 Sidebar（菜单）、顶部 Topbar（上下文选择器 + 账号按钮）、主区 iframe。

- 菜单项映射（iframe src）：
| 菜单名称 | iframe 加载页面 |
| --- | --- |
| 概览 | dashboard.html |
| 生成练习单 | generate.html |
| 提交 / 批改 | submit.html |
| 练习单管理 | practice.html |
| 学习库管理 | knowledge.html |
| 资料库维护 | library.html |
| 学生信息 | profile.html |

- 上下文选择器：
- Student 下拉：来自 GET /api/students（仅当前账号可见）。
- Base/学习库 下拉：来自 GET /api/students/{student_id}/learning-bases。
- 当选择变化时，必须同步写入 localStorage('el_cfg')，以兼容现有子页面（它们依赖 el_cfg）。
## 3.3 el_cfg（保持兼容的最小结构）

现有子页面读取字段（经扫描）：cfg.student_id、cfg.base_id 为必需；可选显示：student_name、base_name、grade_code。

- app.html 必须写入：
```
// localStorage key: el_cfg
{
  "student_id": 1,
  "student_name": "Joanna",
  "base_id": 12,
  "base_name": "四上英语（Unit1-6+Play）",
  "grade_code": "小学4年级"
}
```

注：不要求对子页面做任何改动；它们会继续从 el_cfg 读取上下文。

# 4. 账号管理（极简）设计（Codex 实现规格）

## 4.1 数据库新增表（不与现有 sessions 表冲突）

- 注意：当前 schema.sql 已存在 sessions 表（用于学习会话），因此认证会话表命名为 auth_sessions。
新增 accounts（账号）与 auth_sessions（登录会话）。

建议 SQL（SQLite）：

```
-- accounts
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_super_admin BOOLEAN DEFAULT 0,
  is_active BOOLEAN DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```
-- auth_sessions
CREATE TABLE IF NOT EXISTS auth_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  session_token_hash TEXT NOT NULL UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  last_seen_at TIMESTAMP,
  ip_addr TEXT,
  user_agent TEXT,
  current_student_id INTEGER,
  current_base_id INTEGER,
  FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
```

```
CREATE INDEX IF NOT EXISTS idx_auth_sessions_account_id ON auth_sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
```

## 4.2 初始化超级管理员（必须）

- 要求：公网部署必须能“无交互安全初始化”。提供两种方式，二选一即可：
- 方式A（推荐）：环境变量初始化。首次启动检测 accounts 为空则创建 admin。
- - EL_ADMIN_USER（默认 admin）
- - EL_ADMIN_PASS（必须设置；若为空则拒绝启动或拒绝初始化）
- 方式B：一次性初始化 API（需 init_secret）。
- - POST /api/admin/init-super-admin，body: {username,password,init_secret}
- - init_secret 来自环境变量 EL_INIT_SECRET；成功后将其标记为已用（写入 system_settings）。
## 4.3 登录/退出 API 规格（必须按此实现）

会话方案：HttpOnly Cookie + 服务端 session 存储（auth_sessions）。

- Cookie：
- 名称：el_session
- 属性：HttpOnly; Path=/; SameSite=Lax; Max-Age=EL_SESSION_TTL_SECONDS（默认 7 天）；公网后续可加 Secure。
- API：POST /api/auth/login
```
Request JSON:
{
  "username": "admin",
  "password": "your_password"
}
```

```
Response 200 JSON:
{
  "ok": true,
  "account": {"id": 1, "username": "admin", "is_super_admin": true},
  "context": {"student_id": null, "base_id": null}
}
```

```
Behavior:
- 校验账号存在且 is_active=1
- 验证 password_hash（bcrypt）
- 生成随机 session_token（32 bytes），写入 auth_sessions.session_token_hash=SHA256(token)
- Set-Cookie: el_session=<token>
```

- API：POST /api/auth/logout
```
Response 200 JSON: {"ok": true}
Behavior:
- 删除 auth_sessions 中对应 session_token_hash
- Set-Cookie: el_session=; Max-Age=0
```

- API：GET /api/auth/me
```
Response 200 JSON:
{
  "account": {"id": 1, "username": "admin", "is_super_admin": true},
  "context": {"student_id": 1, "base_id": 12}
}
```

## 4.4 认证中间件（必须）

- 实现方式：在 main.py 注册 HTTP middleware，拦截：
- 1) /api/*：除白名单（/api/auth/login、/api/auth/logout、/api/system/status、初始化接口）外，必须已登录，否则返回 401 JSON。
- 2) *.html：除 /login.html 外，必须已登录，否则 302 跳转 /login.html。
- 3) 静态资源（css/js/png等）：默认放行（若后续有安全需求再细化）。
- 中间件必须在每次请求更新 auth_sessions.last_seen_at，并清理过期会话（可每 N 次请求或后台线程）。
## 4.5 简化权限模型（满足你的要求）

- 本阶段不做细权限，只区分：
- 超级管理员：拥有所有维护能力。
- 普通账号（可选）：也可管理自己的学生/学习库，但不允许危险操作（例如删除系统库/全量清理）。
- 如果本阶段仅启用一个账号：admin.is_super_admin=true，所有功能等价可用。
# 5. 多学生（家庭 ≤3）实现规格

## 5.1 约束与配置

- 配置项（环境变量或 system_settings）：
- EL_MAX_STUDENTS_PER_ACCOUNT=3（默认 3）
- 创建学生 API（POST /api/students）在创建前检查当前账号名下学生数量；达到上限返回 400。
- 学生删除建议：优先“停用 is_active=0”而非物理删除，避免练习记录断裂。
## 5.2 账户归属（两种实现路径，Codex 选其一）

- 路径1（最小改动，推荐先落地）：不改现有业务表结构（students/bases 等不加 account_id）。系统默认只有一个家庭账号，因此无需隔离。
- 路径2（为未来多家庭铺路）：students、bases 增加 account_id 外键，并在所有查询中按当前 account 过滤。此路径代码改动更大。
本阶段建议采用路径1；文档其余实现按路径1 描述。

# 6. 前端新增文件规格（Codex 生成代码）

## 6.1 frontend/login.html（必须）

功能：账号+密码登录；失败提示；成功跳转 /app.html。

- 实现要求：
- 使用 fetch POST /api/auth/login；成功后 window.location='/app.html'。
- 页面只需极简样式（居中卡片 + 输入框 + 登录按钮）。
## 6.2 frontend/app.html（必须）

- 功能：统一壳层。必须实现：
- 顶部：学生选择（下拉）、学习库选择（下拉）、退出按钮。
- 左侧：菜单（见 3.2），点击切换 iframe。
- 首次进入：若 el_cfg 不存在，则自动选择第一个学生与其第一个学习库并写入 el_cfg。
- 如果当前学生没有学习库：提供按钮跳转 library.html 或提示去创建/导入。
- 退出：调用 POST /api/auth/logout → 跳转 /login.html。
## 6.3 对现有页面的改动原则

- 严格不改现有子页面（dashboard/generate/submit/practice/knowledge/library/profile 等）。
- 允许最小改动 index.html：让它作为兼容入口跳转（登录→app，否则→login）。如果你希望完全不改 index.html，也可以把 index.html 保留为菜单页，但这会削弱“专业导航壳”的价值。
# 7. 后端实现细节（Codex 直接照做）

## 7.1 新增 backend/app/auth.py（建议新增文件）

- 职责：密码哈希、会话 token、从 Cookie 解析当前账号。必须提供函数：
- hash_password(plain)->hash（bcrypt）
- verify_password(plain,hash)->bool
- create_session(account_id, ip, ua)->token（写 auth_sessions）
- get_account_by_session(token)->account|None（校验过期）
建议实现片段（仅示例，Codex 需生成完整文件）：

```
# auth.py (sketch)
import os, hashlib, secrets, datetime
from passlib.hash import bcrypt
from .db import db, q1
```

```
def hash_password(p): return bcrypt.hash(p)
def verify_password(p,h): return bcrypt.verify(p,h)
```

```
def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
```

```
def create_session(account_id: int, ip: str|None, ua: str|None, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = sha256(token)
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=ttl_seconds)).isoformat()
    with db() as conn:
        conn.execute(
          "INSERT INTO auth_sessions(account_id, session_token_hash, expires_at, ip_addr, user_agent) VALUES (?,?,?,?,?)",
          (account_id, token_hash, expires_at, ip, ua)
        )
        conn.commit()
    return token
```

## 7.2 main.py 改动点（精确要求）

- 1) 在 StaticFiles mount 之前/之后均可注册 middleware（建议在 app 定义后立即注册）。
- 2) 新增路由：/api/auth/login、/api/auth/logout、/api/auth/me（按 4.3 规格）。
- 3) 启动时初始化：admin 账号（按 4.2 方式A或B）。
- 4) 对危险接口加超级管理员校验（可先只保护 DELETE /api/knowledge-bases/{base_id} 等）。
## 7.3 schema.sql + init_db.py 改动点

- 必须同步修改：
- backend/schema.sql：追加 accounts/auth_sessions 的建表语句（见 4.1）。
- backend/init_db.py：确保 reset/init 时也创建新表。
- 提供迁移策略：对已存在的 el.db 不破坏（若表不存在则 CREATE；若列不存在则 ALTER TABLE ADD COLUMN）。
建议新增迁移脚本：backend/migrate_auth.py，运行方式：python3 backend/migrate_auth.py --db backend/app/el.db（或你的实际 db 路径）。

```
# migrate_auth.py behavior (spec)
- Backup DB: cp el.db el.db.bak.<timestamp>
- Ensure tables accounts/auth_sessions exist (CREATE TABLE IF NOT EXISTS)
- If accounts empty: create admin from env EL_ADMIN_USER/EL_ADMIN_PASS
```

# 8. 验收用例（Codex 写完后必须通过）

## 8.1 手工验收（浏览器）

1. 1) 访问 http://<ip>/ → 未登录应跳转 login.html。
1. 2) 登录成功 → 进入 app.html；左侧菜单可打开各子页面。
1. 3) 顶部可切换学生/学习库；切换后打开 generate/submit 等页面仍正常（因为 el_cfg 更新）。
1. 4) 退出登录后再次访问任意业务页面应跳回 login。
## 8.2 API 验收（curl）

```
# 1) login (保存 cookie)
curl -i -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pass>"}'
```

```
# 2) call protected api
curl -i -b cookies.txt http://127.0.0.1:8000/api/students
```

```
# 3) logout
curl -i -b cookies.txt -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/logout
```

# 9. 给 Codex 的执行计划（可直接复制为任务列表）

1. 按以下顺序实现，确保每一步可运行：
1. Step 1：新增 DB 表 accounts/auth_sessions；更新 schema.sql 与 init_db.py；提供 migrate_auth.py。
1. Step 2：新增 backend/app/auth.py；实现 bcrypt 密码与 session cookie。
1. Step 3：在 main.py 增加 middleware（保护 /api 与 *.html），新增 auth API。
1. Step 4：新增 frontend/login.html 与 frontend/app.html；实现上下文选择器与 iframe 导航；写 el_cfg。
1. Step 5：最小改动 index.html（可选）：已登录→/app.html，未登录→/login.html。
1. Step 6：跑通 8.1/8.2 验收。
“不改子页面”刚性要求提醒：任何对子页面的改动必须是 0；若必须调整（例如新增 auth.js），须先在文档里单独列出并说明理由。本阶段默认不需要。
