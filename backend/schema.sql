-- EnglishLearn 数据库结构
-- 版本: 2.0.0
-- 设计说明: 支持学生学习库、系统资料库、学习进度管理

-- ============================================================
-- 核心表
-- ============================================================

-- 学生表
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    grade TEXT,  -- 年级，如 "四年级"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 资料库表
CREATE TABLE IF NOT EXISTS bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT 0,  -- 0=自定义资料库，1=系统课本资料库
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 词条表
-- unit字段说明：
--   - "__ALL__": 不分单元（整个资料库不区分单元）
--   - NULL: 需要设置单元但尚未设置
--   - "Unit 1", "Unit 2"等: 具体单元名称
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_id INTEGER NOT NULL,
    unit TEXT,  -- 单元标识
    position INTEGER NOT NULL,  -- 在单元内的位置（从1开始）
    zh_text TEXT NOT NULL,  -- 中文提示
    en_text TEXT NOT NULL,  -- 英文答案
    item_type TEXT DEFAULT 'WORD',  -- WORD/PHRASE/SENTENCE
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
);

-- ============================================================
-- 学生学习库
-- ============================================================

-- 学生学习库关联表
-- 记录学生选择了哪些资料库及其学习进度
CREATE TABLE IF NOT EXISTS student_learning_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    base_id INTEGER NOT NULL,
    custom_name TEXT,  -- 自定义显示名称（可覆盖base.name）
    current_unit TEXT,  -- 当前学习进度
                        -- "__ALL__": 全部（不分单元或已学完全部）
                        -- "Unit 3": 学到Unit 3（可出题范围: Unit 1-3）
                        -- NULL: 未设置进度
    is_active BOOLEAN DEFAULT 1,  -- 是否启用该资料库
    display_order INTEGER DEFAULT 0,  -- 显示顺序
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
    UNIQUE(student_id, base_id)
);

-- ============================================================
-- 练习单相关
-- ============================================================

-- 练习单表
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    session_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

-- 练习单词条关联表
-- 记录练习单包含哪些词条及其顺序
CREATE TABLE IF NOT EXISTS session_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    position INTEGER NOT NULL,  -- 在练习单中的位置（从1开始）
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- ============================================================
-- 提交记录
-- ============================================================

-- 提交记录表
-- 记录学生的答题情况
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    position INTEGER NOT NULL,  -- 题目位置
    student_text TEXT,  -- 学生答案
    is_correct BOOLEAN,  -- 是否正确
    llm_text TEXT,  -- LLM识别的文本
    ocr_text TEXT,  -- OCR识别的文本
    source TEXT DEFAULT 'manual',  -- manual=手动批改, llm=AI批改
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- ============================================================
-- 索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_items_base_id ON items(base_id);
CREATE INDEX IF NOT EXISTS idx_items_unit ON items(unit);
CREATE INDEX IF NOT EXISTS idx_items_base_unit ON items(base_id, unit);
CREATE INDEX IF NOT EXISTS idx_student_learning_bases_student ON student_learning_bases(student_id);
CREATE INDEX IF NOT EXISTS idx_student_learning_bases_active ON student_learning_bases(student_id, is_active);
CREATE INDEX IF NOT EXISTS idx_session_items_session ON session_items(session_id);
CREATE INDEX IF NOT EXISTS idx_session_items_item ON session_items(item_id);
CREATE INDEX IF NOT EXISTS idx_submissions_session ON submissions(session_id);
CREATE INDEX IF NOT EXISTS idx_submissions_item ON submissions(item_id);
