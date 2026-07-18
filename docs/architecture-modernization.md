# Story Teller 架构升级计划

状态：Schema V3、新前后端、统一编辑器、静态快照与恢复快照已落地；旧运行时已移除
最后更新：2026-07-16
适用范围：`story_teller` 框架、使用该框架的内容仓库、本地 SQLite 数据与静态只读部署

规范化 schema、软删除、外键级联、统一回收站与一次性迁移的详细决策见 [Story Teller 规范化数据与删除架构](./relational-data-deletion-architecture.md)。该专项决策取代任何依赖目录扫描、引用修补清单或删除后 repair 的长期方案。

Schema V3 完成后的产品功能方向与实施顺序见 [Story Teller 产品功能路线图](./product-feature-roadmap.md)。产品功能必须复用规范化实体、稳定引用、统一事务和增量 API，不能重新引入基于 Markdown 扫描的运行时关系。

## 1. 为什么现在需要升级

Story Teller 已经不再是一个只展示 Markdown 的小型页面。当前产品同时承担：

- 剧情、人物、关系、设定、碎片、篇章和时间线的完整编辑；
- 图谱与时间线的 Canvas/WebGPU 交互；
- 七天回收站、操作历史、撤销和安全重命名；
- SQLite 本地数据源、Markdown/JSON 导出和 GitHub 备份；
- 本地可写模式与静态只读模式；
- 正文预览、同步滚动、沉浸写作和 `@` / `/` 智能提示。

“无构建步骤的原生 JavaScript + 单个标准库 Python 服务”曾经显著降低启动成本，但项目规模已经越过这一方案最舒适的边界。截至本提案编写时，主要文件规模约为：

- `server.py`：3057 行；
- `styles.css`：8779 行；
- `src/views/timeline.js`：1785 行；
- `src/views/graph.js`：1151 行；
- `src/core/model.js`：944 行。

当前方案仍然可以运行，框架现有 66 个 Python 测试、4 个 JavaScript 库测试和 9 个 Playwright 浏览器流程均可通过。因此本次升级不是因为系统已经失效，而是为了在继续增加功能之前降低耦合、避免性能和一致性问题继续扩大。

## 2. 保留与改变的边界

### 2.1 继续保留

- 一个本地启动入口，用户仍然只需要运行 `./run.sh`；
- 前端和写入 API 同源、同端口访问；
- 服务只监听 loopback 地址，不引入公网账号体系；
- SQLite 继续作为唯一可写数据源，并随内容仓库提交到 GitHub；
- 正文继续保存为 Markdown 文本；
- Markdown/JSON 继续作为确定性导出，便于 Git diff、静态部署和灾难恢复；
- 静态部署继续保持只读；
- 现有图谱和时间线的 Canvas/WebGPU 绘制算法；
- 稳定 ID、增量迁移、七天撤销和回收站语义；
- 现有轻量、明亮、创作工作台式的视觉方向。

### 2.2 计划改变

- 前端从按顺序加载的全局脚本迁移到 Vite、TypeScript 和 React；
- 长正文编辑从普通 `textarea` 迁移到 CodeMirror 6；
- Python 服务从一个大型 `SimpleHTTPRequestHandler` 迁移到 FastAPI 路由和领域服务；
- SQLite 从“保存整份 Markdown 文档的文档仓库”升级为可查询、可约束的结构化 schema；
- 本地读取从“返回所有 Markdown 后在浏览器解析”升级为结构化 snapshot/delta API；
- 保存后从全项目重新加载升级为局部数据补丁；
- 回收站、操作历史、撤销和重命名撤销统一到一套事务模型；
- 静态前端优先读取生成的结构化快照，不再自行解析全部 Markdown frontmatter；
- 手工维护的资源版本参数改为构建产物内容哈希。

## 3. 技术方案决策

### 3.1 前端

采用：

- Vite；
- TypeScript；
- React；
- TanStack Query；
- Zustand；
- CodeMirror 6；
- Vitest 与 React Testing Library；
- Playwright。

职责划分：

- TanStack Query 只管理来自服务端的实体数据、revision、请求和 mutation；
- Zustand 只管理跨页面但不需要持久化的 UI 状态，例如当前页面、选中实体、筛选条件、图谱 viewport 和时间线焦点；
- 页面内部的弹窗、表单草稿和展开状态尽量留在组件内部；
- Canvas/WebGPU 渲染器保持命令式实现，通过小型 React 适配层接收模型和派发交互事件；
- 不把每个图谱节点和时间线线段改造成 React 状态对象，避免渲染层反过来拖慢算法。

### 3.2 编辑器

CodeMirror 6 统一承载剧情、碎片、人物核心设定、人物补充设定和设定正文。

必须实现：

- 中文输入法 composition 正常工作；
- `@` 只搜索人物；
- `/` 搜索设定、地点、组织、物品和术语；
- 中文、全拼和拼音首字母检索；
- 候选框不抢走正文编辑器焦点；
- 插入候选时同步结构化引用；
- Markdown 预览与编辑器双向按比例滚动；
- 普通窗口和沉浸模式复用同一编辑器实例与草稿状态；
- 保存期间不销毁编辑器，不丢失 selection、composition、undo history 和 scroll position。

浏览器无法可靠地把普通文本输入框变成绕过操作系统输入法的“原始物理键盘拼音模式”。新实现不得继续通过焦点转移和伪造 `InputEvent` 与输入法竞争。如果以后仍需要完全绕过输入法，应提供独立的命令检索浮层，而不是改变正文输入链路。

### 3.3 后端

采用 FastAPI + Pydantic，并继续使用 Python 标准库 `sqlite3` 作为第一阶段数据库访问层。

暂不立即引入 ORM，原因是：

- 当前数据库规模和查询模式不需要复杂 ORM；
- 显式 SQL 更容易控制迁移、事务和 Git 可追踪的确定性结果；
- 先解决领域边界和数据模型问题，避免同时替换过多基础设施。

后端按领域拆分：

```text
server/
  app.py
  settings.py
  api/
    meta.py
    projects.py
    characters.py
    plots.py
    entries.py
    relationships.py
    timeline.py
    graph.py
    history.py
    trash.py
  domain/
    models.py
    validation.py
    services/
  storage/
    connection.py
    migrations/
    repositories/
  exports/
    markdown.py
    static_snapshot.py
```

所有路由、授权、能力版本和历史元数据必须通过统一路由注册机制声明，禁止继续在“允许路径集合、dispatch map、历史说明 if/elif”多个位置重复登记同一接口。

### 3.4 运行方式

用户模式仍然是：

```sh
./run.sh
```

Python 服务在同一个端口提供：

- 构建后的前端资源；
- `/api/v1/*`；
- 内容附件；
- 健康检查与能力信息。

开发模式增加 `./dev.sh`：

- Vite 提供热更新；
- API 请求代理到本地 FastAPI；
- 开发端口差异不暴露给普通用户。

构建步骤由开发脚本和 CI 负责，不要求内容作者手工执行 `npm build`。

不采用 Electron 或 Tauri。当前 localhost 模式已经满足离线、文件访问和跨平台需求，桌面壳只会额外引入安装、签名、升级和平台维护成本。

## 4. 目标数据架构

### 4.1 SQLite schema v3

建议的核心表：

```text
projects
chapters
characters
character_aliases
character_markers
character_facts
character_supplements
entries
entry_aliases
plots
plot_people
plot_entries
plot_tags
relationships
timeline_lines
plot_timeline_lines
timeline_connections
graph_settings
graph_position_overrides
assets
operations
operation_changes
trash_items
export_state
```

设计要求：

- 稳定 ID 是业务主键，改名不得改变 ID；
- 剧情 ID 与阅读顺序分离；
- 人物、剧情、设定、关系和时间线引用使用外键；
- 正文使用 `TEXT` 保存原始 Markdown；
- 可扩展但尚未进入正式 schema 的字段放入受控的 `extra_json`，部分更新时必须保留；
- 附件内容进入 `assets`，保证 `story.db` 仍然是完整备份；
- 数据库约束负责阻止重复 ID、重复关系、无效引用和非法顺序；
- UI 诊断负责给出人类可读的问题说明，但不代替数据库约束；
- schema 迁移必须按版本逐步执行，禁止依靠检测缺失列后临时 `ALTER TABLE` 作为长期方案。

### 4.2 写入和导出顺序

目标流程：

```text
请求校验
  → 检查 baseRevision
  → SQLite 事务写入领域数据、operation、undo snapshot 和 export outbox
  → 提交数据库
  → 原子生成受影响的 Markdown/JSON/附件导出
  → 返回 revision 和实体 delta
```

SQLite 是唯一事实来源。导出失败不得丢失已经保存的正文，失败状态进入 `export_state` 并由当前服务或下次启动自动重试。UI 必须明确区分“数据已经保存，但导出待修复”和“数据没有保存”，不能让用户重复提交导致重复创建。

### 4.3 静态只读数据

每次导出同时生成：

```text
project.snapshot.json
```

它包含静态页面所需的结构化实体、关系、时间线和 revision。静态前端直接读取该快照；Markdown 文件继续用于阅读、Git diff 和灾难恢复，但不再承担静态前端的运行时 schema。

## 5. API v1 约定

### 5.1 能力与版本

```text
GET /api/v1/meta
```

返回：

```json
{
  "apiVersion": 1,
  "schemaVersion": 3,
  "writable": true,
  "features": ["history-v2", "trash-v2", "delta-v1"]
}
```

前端必须先完成版本握手，再显示写入控件。不能仅凭一个粗粒度 feature 字符串假定几十个接口全部存在。

### 5.2 读取

```text
GET /api/v1/projects/{project}/snapshot
GET /api/v1/projects/{project}/changes?since={revision}
GET /api/v1/projects/{project}/history
GET /api/v1/projects/{project}/trash
```

首屏读取 snapshot；保存和后台同步只读取 changes。正文详情允许按需加载，列表页不必下载所有长正文。

### 5.3 写入响应

所有写入返回统一结构：

```json
{
  "ok": true,
  "projectRevision": 42,
  "changed": {
    "characters": [],
    "plots": []
  },
  "removed": {
    "characters": [],
    "plots": []
  },
  "operation": {
    "id": 128,
    "canUndo": true,
    "expiresAt": 1784736000
  },
  "warnings": []
}
```

每个修改请求带 `baseRevision` 或 `If-Match`。另一个标签页或进程已经修改同一项目时，服务返回明确冲突，前端不得用旧表单静默覆盖新内容。

## 6. 遗留问题清单

### P0：迁移前必须处理

| ID | 问题 | 当前影响 | 升级目标 |
| --- | --- | --- | --- |
| LEG-001 | SQLite 内部仍以 Markdown BLOB 为主 | 无法用外键约束关系，写入仍依赖文件扫描和正则 | schema v3 结构化领域表 |
| LEG-002 | 保存后全量调用 `loadMarkdownData()` | 项目增长后保存变慢，并需要手工恢复滚动和选中状态 | mutation delta 原地更新实体 store |
| LEG-003 | 回收站分成剧情、普通档案和历史三套来源 | 恢复规则不统一，前端需要合并三个接口 | 单一 `trash_items` 与统一恢复事务 |
| LEG-004 | 操作历史快照到期后没有物理清理 | `story.db` 和 Git 历史持续膨胀 | 启动和写入时清理过期历史，并测试保留边界 |
| LEG-005 | `history(deletion_only=True)` 在 `LIMIT` 后过滤 | 高频编辑可能让仍在七天内的删除记录从回收站消失 | SQL 层按删除类型筛选后再分页 |
| LEG-006 | 智能提示弹层抢焦点并拦截物理按键 | 中文输入法仍弹出、可能重复插入字符 | CodeMirror completion，不改变编辑器焦点 |

### P1：核心迁移阶段处理

| ID | 问题 | 当前影响 | 升级目标 |
| --- | --- | --- | --- |
| LEG-007 | 前端使用经典脚本共享全局变量 | 强依赖加载顺序，页面之间可直接改写状态 | TypeScript ES Modules 与明确依赖 |
| LEG-008 | 全局状态和两百多个 DOM 引用集中在 runtime | 页面无法独立初始化、销毁和测试 | 页面组件、自有状态和集中实体 store |
| LEG-009 | 页面路由位于图谱模块 | 页面边界错误，新增页面容易触发无关渲染 | 独立 router 和 page lifecycle |
| LEG-010 | Python 路由、文件操作、验证、历史和序列化集中在 `server.py` | 小改动影响范围大，容易遗漏完整链路 | FastAPI 路由、领域服务、repository、exporter 分层 |
| LEG-011 | 同一业务规则在前后端手写两份 | 角色分类、字段限制等可能漂移 | 后端 Pydantic 为权威，前端由共享 API 类型和选项元数据消费 |
| LEG-012 | 重命名同时有 `last-refactor.json` 和 SQLite history | 多项目间只有一个“最后重命名”，撤销语义重复 | 全部进入统一 operation history |
| LEG-013 | 静态模式和本地模式共同依赖 Markdown 解析模型 | 两套读取方式混在核心模型中 | `LocalDataSource` / `StaticDataSource` 适配层 |
| LEG-014 | 能力契约过粗 | 页面可能显示后端并未真正实现的控件 | API/schema 版本握手与细粒度能力声明 |
| LEG-015 | 真实 HTTP 端到端集成测试数量偏少 | 大部分后端测试绕过统一 POST、SQLite 和历史包装层 | 每个写 API 至少一个 HTTP round-trip 测试 |

### P2：收尾和长期维护

| ID | 问题 | 当前影响 | 升级目标 |
| --- | --- | --- | --- |
| LEG-016 | CSS 单文件接近九千行 | 覆盖关系难追踪，页面样式容易互相污染 | tokens/base/components/pages 分层样式 |
| LEG-017 | HTML 手工维护多组资源版本参数 | 容易出现前端文件版本不一致 | Vite 内容哈希与单一构建 manifest |
| LEG-018 | CLI 允许绑定非 loopback 地址 | 手工启动参数可能突破本地写入边界 | 启动时拒绝非 loopback 绑定 |
| LEG-019 | SQLite 与生成导出同时进入 Git | 单设备备份良好，但多个内容分支无法合并数据库 | 明确单写者流程；未来需要时再引入可合并操作日志 |
| LEG-020 | 缺少真实中文输入法自动化能力 | 合成 composition 测试不能完全覆盖系统输入法 | 自动测试 + macOS/Windows 人工输入法验收矩阵 |
| LEG-021 | 缺少大数据性能基线 | 无法判断时间线、全文引用推导和保存何时退化 | 固定规模 fixture 与可重复性能预算 |

## 7. 项目级已知数据待办

以下问题属于当前内容仓数据，不属于通用框架代码：

- 当前内容包已经删除人物 ID `11`，但 `graph-layout.md` 仍有该 ID 的成员引用；
- SQLite `PRAGMA integrity_check` 为 `ok`，说明数据库文件没有损坏，但业务引用完整性失败；
- 迁移开始前应通过网页安全修复或受测试的领域服务清理引用，并增加“删除人物同时清理图谱配置”的 HTTP 回归测试；
- 不允许通过手工编辑导出 Markdown 修复，因为 SQLite 才是唯一数据源。

## 8. 分阶段实施计划

### 阶段 0：冻结基线和修复数据

目标：为迁移建立可比较、可回退的基线。

- 修复人物 ID `11` 的图谱残留引用；
- 为遗留问题增加失败后再通过的回归测试；
- 保存当前框架完整测试结果和性能基线；
- 为真实内容数据库生成迁移前备份和 SHA-256；
- 记录当前静态部署输出；
- 冻结新的跨模块大型功能，迁移期间只接受缺陷修复和必要内容功能。

完成条件：

- 父仓内容契约全部通过；
- 框架单元、HTTP 集成和浏览器测试全部通过；
- 迁移前数据库可以从备份恢复。

### 阶段 1：建立新后端骨架

目标：在不改变现有 UI 的前提下建立 `/api/v1`。

- 引入 FastAPI、Pydantic 和明确的依赖锁定；
- 拆出 loopback 安全、项目解析、统一错误格式和 route registry；
- 实现 `/api/v1/meta`；
- 用兼容 repository 读取现有 schema v2；
- 新旧 API 暂时并行；
- 为每个写入领域建立真实 HTTP 测试。

完成条件：旧前端仍可运行；新 API 具有版本握手、统一错误和完整测试。

### 阶段 2：升级 SQLite schema v3

目标：让结构化业务数据真正进入 SQLite。

- 编写显式 `2 → 3` 迁移；
- 先备份，再迁移，再执行结构和业务完整性检查；
- 建立外键、唯一约束、revision、operation history、trash 和 export state；
- 实现结构化 exporter；
- 对同一数据执行 `v2 → v3 → exports → recovery import` round-trip 测试；
- 旧版本程序发现 schema v3 时必须拒绝写入，不得尝试降级。

完成条件：数据条数、ID、正文哈希、关系、顺序、时间线和回收站均与迁移前一致。

### 阶段 3：建立新前端和编辑器

目标：先解决最频繁、风险最高的编辑链路。

- 建立 Vite + TypeScript + React 应用外壳；
- 建立类型化 API client、TanStack Query 和 UI store；
- 接入 CodeMirror 6；
- 迁移剧情、碎片、人物设定和普通设定编辑器；
- 完成 `@`、`/`、中文输入法、拼音、预览、同步滚动和沉浸模式；
- 保存响应直接 patch store，不请求全量 snapshot；
- 通过 URL 或 feature flag 在迁移期间保留旧前端回退入口。

完成条件：所有编辑器真实保存、读回、撤销、恢复和输入法验收通过，页面不刷新、不闪烁、不丢状态。

### 阶段 4：逐页迁移

顺序：

1. 剧情与碎片；
2. 人物与人物详情；
3. 设定；
4. 全局回收站和操作历史；
5. 图谱；
6. 时间线。

每迁移一页，都必须同时迁移：

- 数据读取；
- 用户操作；
- 写 API；
- 局部更新；
- 错误状态；
- 撤销和回收站；
- 浏览器端到端测试；
- 静态只读表现。

不能先做一套新的可见 UI，再等待后端补齐。

### 阶段 5：收尾与移除兼容层

- 切换默认入口到新前端；
- 移除旧全局脚本、旧 Markdown 运行时解析和旧写 API；
- 移除 `last-refactor.json`；
- 拆分 CSS；
- 接入构建哈希；
- 删除只为兼容 schema v2 存在的代码；
- 更新 README、AGENTS.md、开发命令和灾难恢复说明；
- 对真实内容仓完成一次完整迁移演练和回退演练。

## 9. 验收标准

### 数据

- SQLite 是唯一可写数据源；
- 所有关系和引用有数据库约束或显式可验证规则；
- 所有用户写操作产生七天可撤销记录；
- 所有删除统一出现在回收站，并带明确类型；
- 过期回收站与历史会物理清理；
- 导出可以由数据库完全重建；
- 迁移前后的正文哈希、稳定 ID 和顺序一致；
- 新版本拒绝写入更高 schema，旧版本拒绝写入 schema v3。

### 交互

- 保存、删除、恢复、撤销、筛选、搜索、切换页面均不刷新整个文档；
- 保存不重新请求全量项目 snapshot；
- 当前页面、选中项、筛选、展开状态、编辑模式、光标、滚动和图谱 viewport 保持不变；
- 非当前页面不会在启动时初始化；
- 图谱和时间线隐藏后停止无意义的渲染工作；
- 中文输入法在剧情、碎片、人物和设定编辑器中均不重复字符、不丢字符；
- `@` 与 `/` 候选框不抢焦点。

### 测试

- 领域服务单元测试；
- schema 迁移和回滚测试；
- 每个写 API 的真实 HTTP round-trip；
- 每个缺陷的回归测试；
- 核心用户路径 Playwright 测试；
- composition 事件自动测试；
- macOS 系统拼音、搜狗输入法、Windows 微软拼音人工验收；
- 大内容包启动、保存、时间线和图谱性能测试；
- 静态只读构建测试；
- 父仓真实内容契约测试。

## 10. 明确不做的事情

- 不把项目改成云端多人协作服务；
- 不引入 Electron 或 Tauri；
- 不用富文本格式取代 Markdown 正文；
- 不把图谱和时间线算法重写为大量 React DOM；
- 不在第一阶段引入 ORM、消息队列或微服务；
- 不为了技术迁移改变现有视觉风格和主要用户流程；
- 不进行一次性大爆炸替换，必须保留逐阶段验证和回退能力。

## 11. 决策摘要

最终方向是：

```text
Vite + TypeScript + React + CodeMirror
                  ↓
类型化 snapshot / delta API
                  ↓
FastAPI + Pydantic 领域服务
                  ↓
结构化 SQLite schema v3
                  ↓
Markdown 导出 + static snapshot + GitHub 备份
```

升级替换的是已经不适合当前规模的实现方式，不替换已经验证有效的产品边界：本地优先、单端口、SQLite、Markdown 正文、静态只读和 GitHub 备份。
