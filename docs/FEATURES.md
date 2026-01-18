# 功能要点清单

## 系统概述
English Learning 是一个面向小学生的英语默写练习与智能批改系统，支持多资料库学习管理、AI辅助批改和学习进度跟踪。

## 一、学生管理

### 1.0 账号登录
- 超级管理员账号登录（Cookie 会话）
- 统一导航壳（app.html）承载各子页面

### 1.1 学生信息
- 创建学生账户（姓名、年级）
- 更新学生信息
- 头像设置（疯狂动物城角色主题）
- 年级管理（幼儿园K1-K3、小学G1-G6、初中G7-G9、高中G10-G12）

### 1.2 初始化引导
- 首次访问自动引导
- 一键初始化学生信息
- 自动创建默认学习库

## 二、学习库管理

### 2.1 多资料库支持
- 学生可同时使用多个资料库
- 系统资料库和自定义资料库分离管理
- 资料库启用/禁用控制
- 自定义资料库显示名称
- 资料库排序管理

### 2.2 系统资料库
- 内置标准教材（人教版PEP等）
- 系统维护，只读不可修改
- 完整的单元结构和元数据
- 封面图片展示
- 支持添加到学习库

### 2.3 自定义资料库
- 家长自由创建
- 完全可编辑（名称、描述、词条）
- 支持批量导入导出
- 单元结构可选（可不分单元）
- 封面图片上传
- 导入文件支持 `assets` 中的 `cover` 作为封面（编辑页可更换）

### 2.4 学习进度跟踪
- 为每个资料库独立设置进度
- Unit级别进度管理（如"Unit 3"表示学到第3单元）
- 特殊进度标识：
  - `__ALL__`：全部（不分单元或已学完）
  - `NULL`：未设置进度
- 出题范围自动计算（如进度为Unit 3，则可出Unit 1-3的题）

## 三、知识库管理

### 3.1 资料库CRUD
- 创建资料库（系统/自定义）
- 更新资料库元数据
- 删除资料库（带使用检查）
- 资料库列表查询（支持类型筛选）
- 封面图片上传管理

### 3.2 单元管理
- 单元元数据定义
- 单元编码（unit_code）
- 单元名称和描述
- 单元排序（unit_index）
- 批量导入单元信息

### 3.3 词条管理
- 词条CRUD操作
- 三种题型：单词(WORD)、短语(PHRASE)、句子(SENTENCE)
- 中英文对照（zh_text / en_text）
- 单元归属管理
- 难度标签：
  - `write`：会写（需要默写）
  - `read`：会认（只需认识）
  - `NULL`：未设置
- 词条位置管理（position）
- 批量导入导出（JSON格式）

## 四、练习单生成

### 4.1 智能选题
- **出题范围**：
  - 学习进度内（推荐）：根据设置的学习进度自动计算范围
  - 全部单元：不限单元范围
  - 自定义单元：手动指定单元列表
- **跨资料库出题**：支持从多个资料库混合选题
- **题型混合**：自定义单词、短语、句子的数量比例
- **难度筛选**：可按"会写"、"会认"要求筛选词条
- **去重处理**：避免重复题目
- **随机扰动选题**：相同范围重新生成仍可得到不同题目

### 4.2 PDF导出
- 题目单生成（中文提示 → 英文作答）
- 答案单生成（供家长核对）
- 专业排版（ReportLab）
- 支持自定义标题
- 日期标记

### 4.3 练习单管理
- 练习单历史记录（支持分页）
- 按日期/UUID/知识点查询练习单
- 练习单状态管理（待提交/已入库）
- 查看详情（批改结果、原图/缩略图、批改图）
- 重新生成题目单/答案单PDF
- 删除历史练习单

## 五、AI智能批改

### 5.1 双引擎识别

#### LLM视觉识别
- 支持 OpenAI GPT-4o / GPT-4o-mini
- 支持字节ARK Vision API
- 理解试卷整体结构
- 识别题目分区（sections）
- 检测批改标记（红叉、红圈等）
- 提取学生手写答案
- 判断对错

#### OCR文字识别
- 百度OCR API集成
- 精确定位手写文字
- 返回文字边界框（bbox）
- 辅助答案位置匹配

### 5.2 并行处理
- LLM和OCR同时工作
- 结果交叉验证
- 一致性检查（consistency_ok）
- BBox匹配算法
- 置信度评分

### 5.3 多页识别
- 支持多页试卷上传
- 准确的页码标识（page_index）
- 页面间题号连续性保持
- 按section分组显示

### 5.4 可视化反馈
- 批改标记绘制：
  - 绿色勾（正确）
  - 红色叉（错误）
  - 可配置标记样式
- 答案裁剪图生成
- 实时预览
- 支持图片缩放和拖拽

### 5.5 结果确认流程
- AI识别结果展示
- 逐题编辑功能
- 切换对错状态
- 拼写错误高亮
- 练习单智能匹配
- 人工确认后入库

### 5.6 调试支持
- 调试模式开关（EL_AI_DEBUG_SAVE）
- 保存原始LLM输出
- 保存原始OCR输出
- 保存输入图片
- 调试数据可重放

## 六、手动批改

### 6.1 纸质批改
- 家长在试卷上标记错误
- 推荐"只标错"策略
- 拍照上传批改后试卷

### 6.2 手动录入
- 逐题输入学生答案
- 自动规则匹配判分
- 支持完全匹配和模糊匹配

### 6.3 混合模式
- 支持AI识别 + 人工修正
- 可切换批改来源（manual/llm）

## 七、学习统计与分析

### 7.1 掌握度跟踪
- 基于连续正确次数判断
- 掌握阈值可配置（默认2次）
- 分词条记录掌握状态
- 实时更新掌握统计
- 掌握详情支持按单元展开查看

### 7.2 易错分析
- 自动记录错误次数
- 易错词汇排行
- 错误类型分类
- 拼写错误提示

### 7.3 学习进展
- 已学词汇数量统计
- 已掌握词汇数量统计
- 按资料库统计
- 按单元统计
- 按题型统计

### 7.4 练习日历
- 可视化练习历史
- 每日练习记录
- 连续练习天数
- 每周目标设置

### 7.5 看板展示
- 全部学生概览（最多3个学生卡片）
- 单学生详情（学习库汇总、资料库掌握列表）
- 近期练习与易错Top10
- 本周练习频率与学习进度条

## 八、系统配置

### 8.1 全局设置
- 掌握阈值配置（1-10次）
- 每周目标天数（1-7天）
- 设置持久化存储
- 自动清理未下载练习单与过期PDF（可配置时间/周期/阈值）

### 8.2 AI配置
- LLM提示词配置（仓库根目录 `ai_config.json`）
- OCR参数配置
- 模型选择（OpenAI/ARK）
- 批改标记样式配置

### 8.3 媒体管理
- 上传图片存储
- 批改图片生成
- 裁剪图存储
- PDF文件管理
- 媒体文件清理

## 九、测试功能

### 9.1 自动化测试
- AI批改功能测试（test_ai_grading.py）
- 固定测试数据集（tests/fixtures/）
- API配置验证
- 结果准确性验证
- 详细测试报告

### 9.2 调试工具
- 调试数据加载
- 模拟运行模式
- 前端调试开关
- API测试脚本

## 十、数据管理

### 10.1 数据库
- SQLite轻量级存储
- 完整的外键约束
- 索引优化
- 级联删除保护

### 10.2 数据导入导出
- JSON格式支持
- 批量导入词条
- 单元信息导入
- 资料库模板
- 支持 `assets` 封面图片导入

### 10.3 数据迁移
- 数据库版本管理
- 迁移脚本（migrate_*.py）
- 字段添加迁移
- 数据兼容性保证

## 十一、前端页面

### 11.1 页面列表
- `index.html` - 首页（学生信息、学习库概览）
- `login.html` - 登录页
- `app.html` - 应用壳（导航 + iframe）
- `knowledge.html` - 学习库管理
- `generate.html` - 练习单生成
- `practice.html` - 练习单管理
- `practice-view.html` - 练习单查看
- `submit.html` - 提交与AI批改
- `dashboard.html` - 学习统计看板
- `library.html` - 资料库浏览
- `library-edit.html` - 资料库编辑
- `library-items.html` - 词条管理
- `profile.html` - 学生档案

### 11.2 交互功能
- 实时表单验证
- 拖拽上传图片
- 图片缩放预览
- 内联编辑
- 加载动画
- 错误提示

## 十二、API接口

### 12.1 学生管理
- GET /api/students - 获取所有学生
- GET /api/students/{id} - 获取单个学生
- POST /api/students - 创建学生
- PUT /api/students/{id} - 更新学生

### 12.0 认证
- POST /api/auth/login - 登录
- POST /api/auth/logout - 退出
- GET /api/auth/me - 当前账号

### 12.2 资料库管理
- GET /api/knowledge-bases - 获取资料库列表
- POST /api/knowledge-bases - 创建资料库
- PUT /api/knowledge-bases/{id} - 更新资料库
- DELETE /api/knowledge-bases/{id} - 删除资料库
- POST /api/knowledge-bases/{id}/cover - 上传封面

### 12.3 学习库管理
- GET /api/students/{id}/learning-bases - 获取学习库
- POST /api/students/{id}/learning-bases - 添加到学习库
- PUT /api/students/{id}/learning-bases/{lb_id} - 更新配置
- DELETE /api/students/{id}/learning-bases/{lb_id} - 移除

### 12.4 词条管理
- GET /api/knowledge-bases/{id}/items - 获取词条
- POST /api/knowledge-items - 创建词条
- PUT /api/knowledge-items/{id} - 更新词条
- DELETE /api/knowledge-items/{id} - 删除词条
- POST /api/knowledge-items/import - 批量导入

### 12.5 练习单管理
- POST /api/practice-sessions/generate - 生成练习单
- GET /api/practice-sessions - 获取练习单列表
- GET /api/practice-sessions/search - 条件查询
- GET /api/practice-sessions/by-uuid/{uuid} - 按UUID查询
- GET /api/students/{id}/practice-sessions/by-date - 按日期查询
- GET /api/practice-sessions/{id}/detail - 练习单详情
- POST /api/practice-sessions/{id}/regenerate-pdf - 重新生成PDF
- DELETE /api/practice-sessions/{id} - 删除练习单

### 12.6 批改相关
- POST /api/ai/grade-photos - AI批改
- POST /api/ai/confirm-extracted - 确认AI结果
- POST /api/practice-sessions/{id}/manual-correct - 手动批改
- POST /api/practice-sessions/{id}/submit-image - 上传原图
- POST /api/practice-sessions/{id}/submit-marked-photo - 上传批改图

### 12.7 统计分析
- GET /api/dashboard - 获取统计看板（旧版）
- GET /api/dashboard/overview - 全部学生概览
- GET /api/dashboard/student - 单学生详情看板
- GET /api/students/{id}/bases/{base_id}/mastery-stats - 掌握度统计
- GET /api/students/{id}/bases/{base_id}/items - 掌握详情列表

### 12.8 系统设置
- GET /api/settings - 获取设置
- PUT /api/settings - 更新设置
- GET /api/system/status - 系统状态

## 十三、技术特性

### 13.1 性能优化
- 数据库索引优化
- 并行API调用（LLM+OCR）
- 图片压缩处理
- 懒加载策略

### 13.2 安全性
- 文件类型验证
- 文件大小限制
- SQL注入防护
- CORS配置

### 13.3 可扩展性
- 模块化设计
- 插件式AI引擎
- 配置化提示词
- 开放式API

### 13.4 用户体验
- 响应式设计
- 友好的错误提示
- 加载状态反馈
- 操作撤销支持

## 十四、未来规划

### 短期
- 学习库排序拖拽
- 批量进度更新
- 资料库导出功能
- 更多系统课本

### 中期
- 跨资料库智能出题
- 学习进度可视化图表
- 智能推荐资料库
- 语音朗读功能

### 长期
- 多学生管理
- 账号体系
- 云端同步
- 移动端应用
- 社区共享资料库

---

**最后更新**: 2026-01-07
**文档版本**: 1.0.0
