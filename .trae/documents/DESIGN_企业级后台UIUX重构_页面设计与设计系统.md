# 企业级后台 UI/UX 重构：页面设计与设计系统（Desktop-first）

## 0. Global Styles（设计系统 / Apple 简洁风格基线）

### 0.1 设计目标（风格与感受）

* 高留白、低噪音：减少强边框与复杂装饰，信息层级靠排版与间距建立。

* 克制的强调色：全站 1 个主色 + 少量功能色（成功/警告/危险）。

* 可读性优先：标题/正文/辅助信息严格分级，避免“全都一样大”。

### 0.2 Design Tokens（建议值，可在落地时微调）

* Spacing（px）：4 / 8 / 12 / 16 / 24 / 32 / 48

  * 页面容器 padding：24（紧凑场景 16）

  * 模块间距：24；模块内行距：12/16

* Radius（px）：

  * Card/Panel：12

  * Button/Input：8

  * Tag/Badge：999（胶囊）

* Typography：

  * Font family：系统字体栈（优先苹方/思源黑体/系统默认）

  * 字号（px）：12（辅助）/ 14（正文）/ 16（强调正文）/ 20（小标题）/ 24（页标题）

  * 行高：1.4–1.6（正文偏 1.6）

* Color（浅色默认）：

  * Background：#F5F6F7（页面底）

  * Surface：#FFFFFF（卡片/面板底）

  * Text Primary：#111827

  * Text Secondary：#6B7280

  * Border（弱）：#E5E7EB

  * Primary：#2563EB（示例，落地以品牌色为准）

  * Success/Warning/Danger：沿用 Element Plus 语义色，但降低饱和度偏“Apple”

* Shadow（克制）：

  * 卡片默认无阴影或极浅：0 1px 2px rgba(0,0,0,0.06)

  * 弹窗：0 12px 32px rgba(0,0,0,0.12)

### 0.3 Element Plus 组件基线（统一密度与状态）

* 默认尺寸：以 default 为主，列表密集场景可切换 small（必须全站一致）。

* 边框策略：输入类控件保留弱边框；表格以行分隔为主，避免重网格。

* Hover/Active：以背景轻变化与边框轻变化为主，避免强烈变色。

### 0.4 响应式策略（Desktop-first）

* 断点建议：

  * ≥1440：内容最大宽度 1200–1360（居中），两侧留白

  * 1200–1439：内容自适应，仍保持 24 padding

  * <1200：侧边栏可收起为图标栏；关键表格提供横向滚动

***

## 1. 登录页

### Layout

* 居中双栏（左品牌/右表单）或单栏卡片（简洁优先）。Flex 布局，纵向居中。

### Meta Information

* Title：登录 - 管理后台

* Description：企业后台登录入口

* OG：与品牌一致

### Page Structure

1. 背景层：浅灰背景（Background），中央白色 Card（Surface）。
2. 品牌区：Logo + 系统名 + 1 句简短说明。
3. 表单区：账号、密码、登录按钮、错误提示。

### Sections & Components

* 登录 Card

  * Header：系统名（24px）+ 副标题（14px，secondary）

  * Form：

    * Input：默认高度一致；错误时仅显示单行提示

    * Primary Button：唯一主按钮；loading 时禁用

  * Footer：忘记密码/联系管理员（若现有）

Interaction States

* 输入聚焦：边框轻强调 + 阴影极浅

* 错误：就地提示 + 顶部可选 Message（仅一次）

***

## 2. 后台主框架页（标准 Admin Layout，含首页/工作台容器）

### Layout

* 经典三段式：TopBar（固定）+ Sider（左侧）+ Content（滚动）。

* CSS：Flex + sticky；内容区内部使用 Grid/Stack 构建模块。

### Meta Information

* Title：{当前页面标题} - 管理后台

* Description：企业管理后台

### Page Structure

1. TopBar（高度 56–64）
2. Sider（宽度 240，折叠 64）
3. Content（统一容器）

   * Breadcrumb（可选）

   * Page Header（页标题 + 主操作）

   * Page Body（卡片化分区）

### Sections & Components

* TopBar

  * 左：系统名/Logo

  * 中：可选全局搜索（若现有）

  * 右：通知（若现有）+ 用户菜单（头像/退出）

* Sider

  * 菜单：一级为主，尽量不超过两级；当前路由高亮

  * 折叠：折叠后仅图标 + tooltip

* Content 容器规范

  * 最大宽度策略：大屏居中；普通屏自适应

  * 背景：页面底灰，模块用白色卡片承载

Common States（全局一致）

* Loading：Skeleton（与最终高度一致）

* Empty：插画/图标克制 + 明确下一步操作

* Error：简洁错误说明 + 重试按钮

***

## 3. 列表页模板（可作为业务页面统一结构）

### Layout

* 纵向 Stack：筛选区（可折叠）→ 工具栏 → 表格 → 分页。

* 表格区外层使用 Card；内部边界与留白统一。

### Meta Information

* Title：{实体}列表 - 管理后台

* Description：查看与管理 {实体}

### Page Structure

1. Page Header

   * 左：标题（24）+ 描述（secondary）

   * 右：主操作（新增）+ 次操作（导出等，按现有）
2. Filter Panel（可折叠）
3. Table Card
4. Pagination（与表格底部对齐）

### Sections & Components

* Filter Panel

  * 表单项：两列或三列 Grid（根据字段）

  * 操作：查询（Primary）/重置（Secondary）放右侧

* Toolbar

  * 左：批量操作（仅在有选择时出现）

  * 右：密度/列设置（如现有）

* Table

  * 视觉：弱分割线；hover 轻背景；操作列靠右

  * 空态：表格内 Empty，占位不跳动

***

## 4. 表单页模板（新建/编辑）

### Layout

* Page Header + 单列表单（默认）

* 宽表单可用双列 Grid，但保持对齐与节奏一致。

### Meta Information

* Title：{实体}新建/编辑 - 管理后台

* Description：维护 {实体} 信息

### Page Structure

1. Page Header：标题 + 状态/提示 + 主操作（保存）
2. Form Card：按信息分组（Section）
3. Sticky Action Bar：保存/取消（可选）

### Sections & Components

* 表单分组

  * Section Title（16–20）+ divider（弱）

  * 字段对齐：label 右对齐或顶对齐（全站统一一种）

* 校验

  * 只显示一个最相关错误；滚动到首个错误

***

## 5. 详情页模板

### Layout

* 顶部摘要 + 分区信息卡片（两列或单列）。

### Meta Information

* Title：{实体}详情 - 管理后台

* Description：查看 {实体} 详细信息

### Page Structure

1. Page Header：标题 + 状态 Tag + 主操作（编辑）
2. Summary Card：关键字段（编号/时间/状态）
3. Detail Sections：基础信息/业务信息/日志（按现有）

### Sections & Components

* 信息展示

  * 采用 Description/List 样式，字段名 secondary，字段值 primary

  * 可复制字段（如 ID）提供 copy icon，交互克制

***

## 6. 设计系统与规范页（内部治理用）

### Layout

* 左侧目录 + 右侧内容（Anchor），便于查找 Token/组件/模板。

### Page Structure

1. Token 区：展示 spacing/radius/typography/color/shadow 与使用规则
2. 组件区：按钮/输入/表格/弹窗/消息等“默认样式+状态”
3. 模板区：列表/表单/详情完整示例
4. Do & Don’t：常见错误与对照

### Interaction

* 所有示例可复制代码片段（如现有；否则仅展示规范）

