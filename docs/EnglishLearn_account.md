# EnglishLearn 第二阶段收尾：账号管理 + 初始化管理员（CodexReady 规格，按此直接生成代码）

版本：V1  
生成时间：2026-01-19 03:56:23（UTC+8）

> 已确认决策：  
> - 1.A：**删除账号 = 停用账号（is_active=0）**（并强制注销该账号所有会话）  
> - 2.A：**系统首次初始化使用环境变量创建初始管理员**（并修复当前 ensure_super_admin 的逻辑缺陷，避免后续运行仍强依赖环境变量）

---

## 0. 目标与范围

### 0.1 目标
在现有认证体系（`accounts` + `auth_sessions` + cookie `el_session`）之上，补齐“账号管理”闭环：

- **普通用户**：仅允许修改自己的密码
- **管理员用户（is_super_admin=1）**：可完成
  - 创建用户（用户名、初始密码、是否管理员）
  - 停用/启用用户（停用视为“删除”）
  - 重置密码
  - 权限管理（普通/管理员）

并满足 UI 要求：
- **账号管理页（admin-accounts.html）与我的账号页（account.html）**不应显示学生选择按钮（`frontend/app.html` 顶部 `studentPicker`）

### 0.2 非目标（本轮不做）
- 不做细粒度 RBAC（只保留普通/管理员）
- 不做“找回密码”（邮件/短信）
- 不做按账号数据隔离（当前系统所有账号共享同一套 students / bases / sessions 数据）

---

## 1. 现状基线（以最新代码为准）

归档内关键路径（已存在）：
- 后端：
  - `backend/app/main.py`：`/api/auth/login|logout|me`，`_require_super_admin()`，`auth_middleware`
  - `backend/app/auth.py`：密码哈希、会话创建、`ensure_super_admin()`
  - `backend/schema.sql`：`accounts`、`auth_sessions` 表，含 `is_super_admin`、`is_active`
- 前端：
  - `frontend/app.html`：统一框架 + 顶部学生选择器显示规则（按页面隐藏）
  - `frontend/login.html`：登录
  - `frontend/dashboard.html`：已更新的看板

---

## 2. 关键修复：初始化管理员逻辑（必须做）

### 2.1 问题
当前 `backend/app/auth.py::ensure_super_admin()` 在 **检查 accounts 是否为空之前**就要求 `EL_ADMIN_PASS` 非空：
```py
password = os.environ.get("EL_ADMIN_PASS", "")
if not password:
    raise RuntimeError("EL_ADMIN_PASS is required to initialize admin account")
...
row = qone(conn, "SELECT COUNT(1) AS c FROM accounts")
if count > 0: return
```
这会导致：**即使系统已创建过管理员账号，只要后续运行时未配置 EL_ADMIN_PASS，服务启动就会崩溃**。

### 2.2 修复目标
- **只有当 accounts 为空时才要求 EL_ADMIN_PASS**
- accounts 非空时，直接 return（不依赖环境变量）

### 2.3 修改点（Codex 直接改代码）
文件：`backend/app/auth.py`  
函数：`ensure_super_admin()`

将逻辑调整为：

1) 先查询 `accounts` 数量  
2) 若 `count > 0`：直接 return  
3) 若 `count == 0`：
   - username = `EL_ADMIN_USER`（默认 `admin`）
   - password = `EL_ADMIN_PASS`（必填，否则 raise）
   - 插入管理员账号（is_super_admin=1, is_active=1）

**目标实现（示例代码块，Codex 可直接落地）**
```py
def ensure_super_admin() -> None:
    username = os.environ.get("EL_ADMIN_USER", "admin")
    with db() as conn:
        row = qone(conn, "SELECT COUNT(1) AS c FROM accounts")
        count = int(row["c"]) if row else 0
        if count > 0:
            return

        password = os.environ.get("EL_ADMIN_PASS", "")
        if not password:
            raise RuntimeError("EL_ADMIN_PASS is required to initialize admin account (first run only)")

        conn.execute(
            """
            INSERT INTO accounts(username, password_hash, is_super_admin, is_active, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (username, hash_password(password), 1, 1, utcnow_iso(), utcnow_iso()),
        )
```

---

## 3. 后端：新增账号管理 API（不破坏现有 API）

### 3.1 新增/变更的 API 列表

#### 普通用户
1) `POST /api/auth/change-password`（登录必需）

#### 管理员（require super admin）
2) `GET /api/admin/accounts`  
3) `POST /api/admin/accounts`  
4) `PATCH /api/admin/accounts/{account_id}`（启用/禁用、设管理员/普通）  
5) `POST /api/admin/accounts/{account_id}/reset-password`  
6) `DELETE /api/admin/accounts/{account_id}`（**删除=停用**）

> 注意：`auth_middleware` 已对 `/api/*` 做登录保护；管理员接口额外 `_require_super_admin(request)`。

---

## 4. 后端实现细节（Codex 任务拆解）

### 4.1 新增 Pydantic 请求模型（main.py）
文件：`backend/app/main.py`  
位置：建议放在 `Auth API Endpoints` 区域附近（紧随 LoginReq 或其后）

新增：
```py
class ChangePasswordReq(BaseModel):
    old_password: str
    new_password: str

class AdminCreateAccountReq(BaseModel):
    username: str
    password: str
    is_super_admin: bool = False

class AdminResetPasswordReq(BaseModel):
    new_password: str

class AdminUpdateAccountReq(BaseModel):
    is_super_admin: Optional[bool] = None
    is_active: Optional[bool] = None
```

### 4.2 账号安全规则（必须实现）
**统一规则：**
- 密码最小规则：`len(password) >= 8`（不满足返回 400）
- 用户名规则：`3~32`，允许 `[a-zA-Z0-9._-]`（不满足返回 400）
- 禁止“最后一个管理员”被降级/停用：
  - 当 `active_admin_count == 1` 时，不能对该管理员执行：
    - `is_super_admin=False`
    - `is_active=False`
    - `DELETE`（停用）
- 禁止管理员停用/删除自己（避免锁死）
  - 若 `account_id == request.state.account.id` 且请求是停用/删除：返回 400

### 4.3 在 auth.py 增加可复用的辅助函数（推荐）
文件：`backend/app/auth.py`  
新增函数（Codex 直接加到文件末尾或 ensure_super_admin 后方）：

1) `_validate_username(username: str) -> None`  
2) `_validate_password(pw: str) -> None`  
3) `delete_sessions_for_account(account_id: int) -> None`  
4) `count_active_admins(conn) -> int`  
5) `list_accounts_with_last_seen() -> List[Dict]`  
6) `create_account(username, password, is_super_admin) -> Dict`  
7) `set_account_password(account_id, new_password) -> None`  
8) `update_account_flags(account_id, is_active: Optional[bool], is_super_admin: Optional[bool]) -> None`  
9) `deactivate_account(account_id) -> None`（内部做 is_active=0 + delete sessions）

> 也可以把这些写在 main.py 内部用 SQL 完成；但放 auth.py 更清晰。

#### 4.3.1 list_accounts_with_last_seen 的 SQL（必须字段）
```sql
SELECT
  a.id, a.username, a.is_super_admin, a.is_active, a.created_at, a.updated_at,
  MAX(s.last_seen_at) AS last_seen_at
FROM accounts a
LEFT JOIN auth_sessions s ON s.account_id = a.id
GROUP BY a.id
ORDER BY a.is_super_admin DESC, a.username ASC
```

#### 4.3.2 count_active_admins 的 SQL
```sql
SELECT COUNT(1) AS c FROM accounts WHERE is_super_admin=1 AND is_active=1
```

---

## 5. 后端：路由实现（main.py）

文件：`backend/app/main.py`  
在 `Auth API Endpoints` 后面新增一个区块 `Admin Accounts API Endpoints`。

### 5.1 POST /api/auth/change-password
- 输入：ChangePasswordReq
- 逻辑：
  1) 取当前 account：`_account_from_request(request)`，缺失则 401（理论上 middleware 已挡）
  2) 查询 accounts（by id），验证 `old_password`
  3) 校验新密码规则
  4) 更新 `accounts.password_hash` 与 `updated_at`
  5) **最小实现**：清理该账号全部 sessions，提示用户重新登录
     - `DELETE FROM auth_sessions WHERE account_id=?`

### 5.2 GET /api/admin/accounts
- `_require_super_admin(request)`
- 返回：`{"accounts":[...]}`

### 5.3 POST /api/admin/accounts
- `_require_super_admin(request)`
- username 唯一（违反返回 400）
- 插入 accounts，返回新账号对象（不返回密码）

### 5.4 POST /api/admin/accounts/{account_id}/reset-password
- `_require_super_admin(request)`
- 校验新密码
- 更新 password_hash + updated_at
- `DELETE FROM auth_sessions WHERE account_id=?`（强制重新登录）

### 5.5 PATCH /api/admin/accounts/{account_id}
- `_require_super_admin(request)`
- 允许修改：`is_super_admin`、`is_active`
- 应用“最后管理员保护”和“禁止操作自己停用/删除”
- 若设置 `is_active=false`：同步清理 sessions

### 5.6 DELETE /api/admin/accounts/{account_id}（删除=停用）
- `_require_super_admin(request)`
- 语义：`UPDATE accounts SET is_active=0, updated_at=? WHERE id=?`
- 同步：`DELETE FROM auth_sessions WHERE account_id=?`
- 仍需应用“最后管理员保护”与“禁止停用自己”

---

## 6. 前端：新增页面 + 框架集成（必须隐藏学生选择器）

### 6.1 新增页面
在 `frontend/` 新增 2 个文件：

1) `frontend/account.html`：我的账号（改密码）  
2) `frontend/admin-accounts.html`：账号管理（管理员）

### 6.2 app.html：菜单与学生选择器显示规则
文件：`frontend/app.html`

#### 6.2.1 菜单项新增
将 `menuItems` 扩展为：
- 所有人：增加 `我的账号` → `account.html`
- 管理员：增加 `账号管理` → `admin-accounts.html`

实现方式（推荐）：
1) 在 `state` 增加 `account: null`
2) `init()` 时调用 `/api/auth/me`，把 `res.account` 保存到 `state.account`
3) `renderMenu()` 改为根据 `state.account.is_super_admin` 构造菜单数组
   - 非管理员不渲染“账号管理”

#### 6.2.2 顶部学生选择器隐藏（满足需求）
修改 `updateTopbarForPage(src)` 中 hidePicker 逻辑，加入：
- `page === 'account.html'`
- `page === 'admin-accounts.html'`

示例：
```js
const hidePicker = isProfile || isLibraryPage(page) || page === 'account.html' || page === 'admin-accounts.html' || state.students.length === 0;
studentPicker.classList.toggle('hidden', hidePicker);
```

#### 6.2.3 pageMeta 增补
在 `pageMeta` 中加入：
```js
'account.html': {title:'我的账号'},
'admin-accounts.html': {title:'账号管理'}
```

---

## 7. 前端：account.html（普通用户/管理员通用）

### 7.1 页面功能
- 展示当前用户名、角色（只读）
- 提供改密表单：旧密码、新密码、确认新密码
- 提交后：
  - 调用 `POST /api/auth/change-password`
  - 成功后提示并 **强制退出登录**（配合后端清理 sessions 的最小实现）

### 7.2 强制退出策略（建议）
- 改密成功后：
  1) `await fetch('/api/auth/logout', {method:'POST'})`
  2) `location.href='/login.html'`

---

## 8. 前端：admin-accounts.html（管理员专用）

### 8.1 页面功能
1) 列表展示：
   - username
   - 角色（管理员/普通）
   - 状态（启用/停用）
   - last_seen_at（可显示为 `-`）
   - 操作按钮：`重置密码`、`设为管理员/设为普通`、`停用/启用`

2) 创建账号：
   - 输入：username、初始密码、是否管理员
   - 点击创建 → `POST /api/admin/accounts`

3) 重置密码：
   - 交互：点击后 `prompt()` 输入新密码
   - 调用 `POST /api/admin/accounts/{account_id}/reset-password`

4) 停用（删除）：
   - 文案显示为“停用”（页面顶部说明：删除=停用）
   - 调用 `DELETE /api/admin/accounts/{account_id}`

5) 启用：
   - 调用 `PATCH /api/admin/accounts/{account_id}`：`{"is_active": true}`

### 8.2 页面访问保护
- 页面加载时先调用 `/api/auth/me`
  - 若 `!account.is_super_admin`：显示“需要管理员权限”，并提供“返回看板”按钮

---

## 9. 初始化与部署说明（必须写进 README 或 docs，Codex 可选）

### 9.1 首次启动（accounts 为空）
必须提供环境变量：
- `EL_ADMIN_USER`（可选，默认 admin）
- `EL_ADMIN_PASS`（必填）

示例（shell）：
```bash
export EL_ADMIN_USER=admin
export EL_ADMIN_PASS='ChangeMe123!'
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 9.2 后续启动（accounts 非空）
- **不再要求** `EL_ADMIN_PASS`  
- `EL_ADMIN_USER` 仅在首次创建时生效

---

## 10. 验收用例（必须通过）

### 10.1 初始化验证
1) 新建数据库后启动服务，未设置 `EL_ADMIN_PASS`：
   - 预期：启动失败，并输出明确错误
2) 设置 `EL_ADMIN_PASS` 后启动：
   - 预期：自动创建 admin
3) 第二次启动（已有 accounts），不设置 `EL_ADMIN_PASS`：
   - 预期：启动成功（修复点生效）

### 10.2 普通用户改密
- 普通用户登录 → 进入“我的账号” → 修改密码成功 → 被强制退出 → 用新密码重新登录成功

### 10.3 管理员 CRUD
- 管理员进入“账号管理”
- 创建普通用户
- 将该用户设为管理员 / 再设回普通
- 重置该用户密码（重置后旧会话应失效）
- 停用（删除）该用户（is_active=0，且该用户无法登录）
- 启用该用户（is_active=1，且可再次登录）

### 10.4 保护规则
- 若系统只有 1 个启用管理员：
  - 不能将其降级为普通用户
  - 不能停用/删除它
- 管理员不能停用/删除自己（应返回 400）

---

## 11. Codex 执行清单（按顺序生成代码）

1) 修改 `backend/app/auth.py`：修复 `ensure_super_admin()`（第 2 节），并补充辅助函数（第 4.3 节）  
2) 修改 `backend/app/main.py`：新增 6 个 API（第 3/5 节），加入 Pydantic 模型（第 4.1 节）  
3) 修改 `frontend/app.html`：
   - 动态菜单（基于 `/api/auth/me` 的 is_super_admin）
   - `pageMeta` 增补
   - `updateTopbarForPage()` hidePicker 增补 account/admin 页面
4) 新增 `frontend/account.html`（第 7 节）
5) 新增 `frontend/admin-accounts.html`（第 8 节）
6) 自测：按第 10 节逐条验证

---

## 12. 兼容性说明
- 不修改数据库 schema（`accounts` / `auth_sessions` 字段已满足需求）
- 不破坏既有 API：`/api/auth/login|logout|me` 及其他业务接口不改语义
- 账号管理页不涉及学生上下文，不影响现有“页面级学生选择器适配”机制
