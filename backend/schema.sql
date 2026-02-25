-- EnglishLearn 数据库结构
-- 版本: 3.0.0
-- 设计说明: 支持学生学习库、系统资料库、练习单生成与批改

PRAGMA foreign_keys = ON;

-- ============================================================
-- 核心表
-- ============================================================

-- 学生表
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    grade TEXT,
    account_id INTEGER NOT NULL,
    avatar TEXT DEFAULT 'rabbit',
    weekly_target_days INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- 资料库表
CREATE TABLE IF NOT EXISTS bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT 0,
    account_id INTEGER,
    education_stage TEXT,
    grade TEXT,
    term TEXT,
    version TEXT,
    publisher TEXT,
    editor TEXT,
    cover_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- 单元元数据表
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_id INTEGER NOT NULL,
    unit_code TEXT NOT NULL,
    unit_name TEXT,
    unit_index INTEGER,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
    UNIQUE(base_id, unit_code)
);

-- 词条表
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_id INTEGER NOT NULL,
    unit TEXT,
    position INTEGER NOT NULL,
    zh_text TEXT NOT NULL,
    en_text TEXT NOT NULL,
    item_type TEXT DEFAULT 'WORD',
    difficulty_tag TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
);

-- 学生学习库关联表
CREATE TABLE IF NOT EXISTS student_learning_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    base_id INTEGER NOT NULL,
    custom_name TEXT,
    current_unit TEXT,
    is_active BOOLEAN DEFAULT 1,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
    UNIQUE(student_id, base_id)
);

-- ============================================================
-- 旧版练习单（保留兼容）
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    session_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

-- ============================================================
-- 练习单与批改
-- ============================================================

CREATE TABLE IF NOT EXISTS practice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    base_id INTEGER NOT NULL,
    status TEXT DEFAULT 'DRAFT',
    params_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    corrected_at TIMESTAMP,
    created_date TEXT,
    practice_uuid TEXT,
    pdf_path TEXT,
    answer_pdf_path TEXT,
    downloaded_at TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exercise_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    item_id INTEGER,
    position INTEGER NOT NULL,
    type TEXT,
    en_text TEXT,
    zh_hint TEXT,
    normalized_answer TEXT,
    FOREIGN KEY (session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    item_id INTEGER,
    position INTEGER,
    student_text TEXT,
    is_correct BOOLEAN,
    llm_text TEXT,
    ocr_text TEXT,
    source TEXT DEFAULT 'manual',
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    image_path TEXT,
    text_raw TEXT,
    FOREIGN KEY (session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS practice_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    exercise_item_id INTEGER NOT NULL,
    answer_raw TEXT,
    answer_norm TEXT,
    is_correct INTEGER,
    error_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES practice_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (exercise_item_id) REFERENCES exercise_items(id) ON DELETE CASCADE
);

-- AI 原始产物（LLM/OCR raw）
CREATE TABLE IF NOT EXISTS practice_ai_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_uuid TEXT NOT NULL,
    engine TEXT NOT NULL,
    stage TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_text TEXT,
    content_json TEXT,
    meta_json TEXT,
    source_path TEXT,
    sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 练习单文件（上传图片/后续可扩展）
CREATE TABLE IF NOT EXISTS practice_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_uuid TEXT NOT NULL,
    file_uuid TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    original_filename TEXT,
    byte_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    meta_json TEXT,
    content_blob BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_item_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    total_attempts INTEGER DEFAULT 0,
    correct_attempts INTEGER DEFAULT 0,
    wrong_attempts INTEGER DEFAULT 0,
    consecutive_correct INTEGER DEFAULT 0,
    consecutive_wrong INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    UNIQUE(student_id, item_id)
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 认证与会话
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_super_admin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- ============================================================
-- 索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_items_base_id ON items(base_id);
CREATE INDEX IF NOT EXISTS idx_items_unit ON items(unit);
CREATE INDEX IF NOT EXISTS idx_items_base_unit ON items(base_id, unit);
CREATE INDEX IF NOT EXISTS idx_students_account_id ON students(account_id);
CREATE INDEX IF NOT EXISTS idx_bases_account_id ON bases(account_id);
CREATE INDEX IF NOT EXISTS idx_student_learning_bases_student ON student_learning_bases(student_id);
CREATE INDEX IF NOT EXISTS idx_student_learning_bases_active ON student_learning_bases(student_id, is_active);
CREATE INDEX IF NOT EXISTS idx_units_base ON units(base_id);

CREATE INDEX IF NOT EXISTS idx_session_items_session ON session_items(session_id);
CREATE INDEX IF NOT EXISTS idx_session_items_item ON session_items(item_id);

CREATE INDEX IF NOT EXISTS idx_practice_uuid ON practice_sessions(practice_uuid);
CREATE INDEX IF NOT EXISTS idx_student_date ON practice_sessions(student_id, created_date);
CREATE INDEX IF NOT EXISTS idx_exercise_items_session ON exercise_items(session_id);
CREATE INDEX IF NOT EXISTS idx_practice_results_session ON practice_results(session_id);
CREATE INDEX IF NOT EXISTS idx_practice_results_submission ON practice_results(submission_id);
CREATE INDEX IF NOT EXISTS idx_submissions_session ON submissions(session_id);
CREATE INDEX IF NOT EXISTS idx_submissions_item ON submissions(item_id);
CREATE INDEX IF NOT EXISTS idx_ai_artifacts_practice ON practice_ai_artifacts(practice_uuid);
CREATE INDEX IF NOT EXISTS idx_ai_artifacts_lookup ON practice_ai_artifacts(practice_uuid, engine, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_files_practice ON practice_files(practice_uuid);
CREATE INDEX IF NOT EXISTS idx_files_sha ON practice_files(sha256);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_account_id ON auth_sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
