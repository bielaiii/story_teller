# Story Teller 规范化数据与删除架构

状态：已确认的目标方案，尚未实施
最后更新：2026-07-16
适用范围：Story Teller schema v3、本地写入服务、回收站、撤销、图谱、时间线、静态导出

## 1. 决策摘要

Story Teller 将直接从“SQLite 保存 Markdown 文档，再由 Python 扫描和修补引用”的模型，迁移到规范化的关系型 SQLite schema。不建设一套长期存在的过渡删除机制，也不再让删除、恢复或其他操作依赖业务代码维护的后续任务清单。

目标模型遵守以下约束：

- SQLite 是唯一可写数据源；
- 人物、剧情、设定、关系、图谱和时间线之间的结构化引用都保存为数据库外键；
- 普通删除只修改根实体的 `deleted_at` / `purge_at`，不遍历和逐项修改依赖对象；
- 所有页面只读取活动视图，软删除实体及其派生关系自然从页面、图谱和智能提示中消失；
- 七天内恢复只需要取消根实体的软删除状态；
- 七天后由数据库硬删除根实体，外键 `ON DELETE CASCADE` 负责永久删除依赖行；
- 所有写入由统一事务单元自动记录行级变化，撤销不依赖各业务功能手写受影响文件清单；
- Markdown 正文继续作为文本保存，但 Markdown/JSON 文件不再参与运行时一致性；
- schema v2 到 schema v3 采用一次性迁移和原子切换，不实行长期双写。

## 2. 当前问题的根因

当前 `story.db` 的 `documents` 表保存整份 Markdown 文档。数据库只知道某个路径对应一段二进制内容，不知道以下关系：

- `plots.people` 指向人物；
- `entries.people` 指向人物；
- 人物关系的两个端点指向人物；
- 图谱节点、距离、分组成员和保存位置指向人物；
- `characters.events`、`entries.plots` 和时间线节点指向剧情。

因此当前删除人物时，Python 必须扫描若干目录、解析 frontmatter、修改数组、删除关系文件并修补 `graph-layout.md`。任何新引用字段、子目录或新图谱结构都可能因为没有加入扫描逻辑而残留。

这不是再增加一条正则或再补一个修复函数能根治的问题。只要数据库仍将结构化引用藏在不透明文本中，删除正确性就依赖开发者记住所有引用位置。

## 3. 不采用的方案

### 3.1 不采用删除计划驱动的级联修改

不把下面这种对象作为删除执行的依据：

```text
DeletePlan
├─ 删除人物文件
├─ 删除关系文件
├─ 修改剧情文件
├─ 修改设定文件
├─ 修改图谱配置
└─ 更新索引
```

影响范围可以在确认弹窗中展示，但它只能是只读查询结果，不能成为执行正确性的前提。即使预览没有覆盖某种新引用，数据库约束仍必须保证删除后活动数据一致。

### 3.2 不采用长期双写

不同时维护“规范化表”和“Markdown 文档表”两份可写事实来源。迁移完成后，所有修改只进入 schema v3；Markdown/JSON 只能由数据库生成。

### 3.3 不采用删除后的安全修复

诊断工具可以报告损坏或迁移异常，但正常删除不能依赖之后再执行 repair。API 返回成功时，数据库的活动视图必须已经一致。

### 3.4 不依赖文件目录表达引用

文件名、目录层级、`manifest.md` 和 `content-index.json` 都不是实体身份或引用关系。稳定 ID 和外键才是身份与关系。

## 4. 目标数据模型

### 4.1 统一实体表

所有可删除、可恢复的内容都拥有统一实体记录：

```sql
CREATE TABLE entities (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    stable_id     TEXT NOT NULL,
    title         TEXT NOT NULL,
    deleted_at    INTEGER,
    purge_at      INTEGER,
    revision      INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    UNIQUE(project_id, kind, stable_id)
);
```

`kind` 至少覆盖：

- `character`；
- `plot`；
- `entry`；
- `fragment`；
- `relationship`；
- `timeline_line`；
- `chapter`。

稳定 ID 永不复用。软删除期间 ID 和需要唯一的名称仍然保留，避免创建新对象后导致旧对象无法恢复。

### 4.2 类型表

具体字段放入类型表，类型表的主键同时引用统一实体：

```sql
CREATE TABLE characters (
    entity_id         TEXT PRIMARY KEY
                      REFERENCES entities(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    intro_markdown    TEXT NOT NULL DEFAULT '',
    narrative_role    TEXT NOT NULL,
    character_scope   TEXT NOT NULL,
    side              TEXT NOT NULL,
    main_plot_impact  INTEGER NOT NULL,
    color             TEXT NOT NULL
);

CREATE TABLE plots (
    entity_id       TEXT PRIMARY KEY
                    REFERENCES entities(id) ON DELETE CASCADE,
    chapter_id      TEXT NOT NULL,
    sort_key        TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    body_markdown   TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL,
    accent          TEXT NOT NULL
);

CREATE TABLE entries (
    entity_id       TEXT PRIMARY KEY
                    REFERENCES entities(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    subtype         TEXT NOT NULL DEFAULT '',
    body_markdown   TEXT NOT NULL DEFAULT ''
);
```

人物 facts、supplements、aliases、markers、剧情 tags、剧情 lanes 等多值字段使用独立子表或经过约束的 JSON 字段。凡是指向另一实体的字段必须使用关系表和外键，不能使用 JSON ID 数组。

### 4.3 结构化引用表

```sql
CREATE TABLE plot_characters (
    plot_id       TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    character_id  TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    PRIMARY KEY(plot_id, character_id)
);

CREATE TABLE plot_entries (
    plot_id   TEXT NOT NULL REFERENCES plots(entity_id) ON DELETE CASCADE,
    entry_id  TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    PRIMARY KEY(plot_id, entry_id)
);

CREATE TABLE entry_characters (
    entry_id      TEXT NOT NULL REFERENCES entries(entity_id) ON DELETE CASCADE,
    character_id  TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    PRIMARY KEY(entry_id, character_id)
);

CREATE TABLE relationships (
    entity_id          TEXT PRIMARY KEY
                       REFERENCES entities(id) ON DELETE CASCADE,
    from_character_id  TEXT NOT NULL
                       REFERENCES characters(entity_id) ON DELETE CASCADE,
    to_character_id    TEXT NOT NULL
                       REFERENCES characters(entity_id) ON DELETE CASCADE,
    from_role          TEXT NOT NULL,
    to_role            TEXT NOT NULL,
    label              TEXT NOT NULL,
    type               TEXT NOT NULL,
    color              TEXT NOT NULL,
    CHECK(from_character_id <> to_character_id)
);
```

数据库使用唯一索引保证同一人物对只有一条关系，不受端点书写顺序影响。

### 4.4 图谱表

```sql
CREATE TABLE graph_nodes (
    character_id   TEXT PRIMARY KEY
                   REFERENCES characters(entity_id) ON DELETE CASCADE,
    orbit_of       TEXT REFERENCES characters(entity_id) ON DELETE CASCADE,
    orbit_distance REAL,
    orbit_angle    REAL,
    anchor_x       REAL,
    anchor_y       REAL
);

CREATE TABLE graph_distances (
    from_character_id TEXT NOT NULL
                      REFERENCES characters(entity_id) ON DELETE CASCADE,
    to_character_id   TEXT NOT NULL
                      REFERENCES characters(entity_id) ON DELETE CASCADE,
    distance          REAL NOT NULL,
    strength          REAL NOT NULL,
    PRIMARY KEY(from_character_id, to_character_id)
);

CREATE TABLE graph_cluster_members (
    cluster_id    TEXT NOT NULL REFERENCES graph_clusters(id) ON DELETE CASCADE,
    character_id  TEXT NOT NULL REFERENCES characters(entity_id) ON DELETE CASCADE,
    PRIMARY KEY(cluster_id, character_id)
);
```

图谱节点身份来自人物实体。图谱不存在另一套可以脱离人物存在的“人物节点 ID”。

### 4.5 时间线和篇章

时间线节点直接引用剧情实体，剧情线和篇章也使用统一实体软删除：

```sql
CREATE TABLE timeline_nodes (
    plot_id       TEXT PRIMARY KEY REFERENCES plots(entity_id) ON DELETE CASCADE,
    line_id       TEXT NOT NULL REFERENCES timeline_lines(entity_id),
    timeline_key  TEXT NOT NULL
);
```

删除剧情线时，将节点转移到用户选择的接收线是一次显式的业务修改，并与剧情线软删除放在同一个数据库事务中。它不是删除后的补偿任务。

删除仍包含活动剧情的篇章时，数据库服务直接拒绝；不会先删除篇章再异步搬运剧情。

## 5. 活动视图

软删除不修改所有关联行。运行时通过活动视图自动隐藏删除实体和由其失效的关系。

人物活动视图：

```sql
CREATE VIEW active_characters AS
SELECT c.*, e.stable_id, e.title, e.revision
FROM characters c
JOIN entities e ON e.id = c.entity_id
WHERE e.deleted_at IS NULL;
```

人物关系活动视图必须同时确认关系本身和两个端点都处于活动状态：

```sql
CREATE VIEW active_relationships AS
SELECT r.*
FROM relationships r
JOIN entities relationship_entity ON relationship_entity.id = r.entity_id
JOIN entities from_entity ON from_entity.id = r.from_character_id
JOIN entities to_entity ON to_entity.id = r.to_character_id
WHERE relationship_entity.deleted_at IS NULL
  AND from_entity.deleted_at IS NULL
  AND to_entity.deleted_at IS NULL;
```

剧情人物、设定人物、图谱节点、图谱距离和时间线节点使用相同原则。API、图谱、智能提示、搜索和诊断只查询活动视图，不在应用层再次过滤一遍 ID。

## 6. 删除、恢复与永久清理

### 6.1 普通删除

删除人物、剧情、设定、碎片、关系、剧情线或篇章时，只软删除目标实体：

```sql
UPDATE entities
SET deleted_at = :now,
    purge_at = :now + 7天,
    revision = revision + 1,
    updated_at = :now
WHERE id = :entity_id
  AND deleted_at IS NULL;
```

事务提交后：

- 根实体不再出现在活动视图；
- 指向已删除根实体的关联不会出现在活动关联视图；
- 图谱不会得到该人物节点或相连边；
- 智能提示不会得到该实体；
- 正文中的普通文字保持原样；
- 不自动连接断开的两端；
- 不需要执行引用清理、索引修复或图谱修复。

### 6.2 恢复

恢复操作只取消软删除：

```sql
UPDATE entities
SET deleted_at = NULL,
    purge_at = NULL,
    revision = revision + 1,
    updated_at = :now
WHERE id = :entity_id
  AND deleted_at IS NOT NULL
  AND purge_at > :now;
```

原有关联仍然存在，因此会自然重新进入活动视图。若关联的另一端也被删除，则该关联继续隐藏；不会为了恢复一个人物而复活另一项独立删除。

恢复前验证唯一名称和业务约束。软删除期间保留唯一键，原则上应避免恢复冲突；若未来允许复用名称，则恢复必须明确拒绝冲突，不能覆盖新实体。

### 6.3 七天后永久清理

```sql
DELETE FROM entities
WHERE deleted_at IS NOT NULL
  AND purge_at <= :now;
```

硬删除后，外键级联删除类型行、关联行、关系端点和图谱配置。永久清理不调用各业务模块，也不维护实体类型到清理函数的映射。

同一保留策略还必须删除已经到期的行级撤销内容。仅在查询时隐藏过期历史不算真正删除。

为避免已删除正文继续存在于 SQLite 空闲页中，批量永久清理后使用 `VACUUM INTO` 生成新数据库并原子替换当前数据库。该操作在本地服务空闲或启动维护窗口执行。

Git 旧提交仍然会保留过去版本的 `story.db`。这是“完整 Git 备份”和“从所有历史中物理擦除”之间不可同时满足的约束。应用保证当前数据库和后续提交不再包含已过期的回收站正文；若需要从 Git 历史中删除敏感内容，必须单独执行历史重写。

## 7. 剧情顺序

剧情不再保存需要连续重写的整数 `sequence`，而是保存稳定 `sort_key`。活动剧情的显示序号在查询时计算：

```sql
SELECT
    p.*,
    ROW_NUMBER() OVER (ORDER BY p.sort_key, e.stable_id) AS display_sequence
FROM plots p
JOIN entities e ON e.id = p.entity_id
WHERE e.deleted_at IS NULL;
```

因此：

- 删除剧情后显示编号自动连续；
- 后续剧情不会被批量改写；
- 恢复剧情后回到原来的阅读位置；
- 插入剧情只生成位于前后剧情之间的排序键；
- 稳定 ID、阅读位置和用户看到的“第几篇”不再混为一个字段。

## 8. 统一事务与撤销

### 8.1 单一写入入口

所有写入都通过一个数据库 Unit of Work 完成。禁止路由直接写表、直接改导出文件或在事务提交后再运行补偿性业务任务。

一次请求的验证、业务修改、revision 更新和操作历史必须处于同一个 SQLite 事务中。任何一步失败，SQLite 回滚整个请求。

### 8.2 自动行级变更记录

统一 ORM 基类和 Session 事件自动记录本次事务中的新增、修改、软删除和关联表变化：

```text
operations
- id
- project_id
- actor
- label
- created_at
- expires_at
- undone_at

operation_changes
- operation_id
- table_name
- primary_key
- before_json
- after_json
- before_revision
- after_revision
```

业务功能不手写 `affectedFiles`、`patches` 或 `deleteTargets`。新增一种结构化表时，只要它进入统一 ORM 事务，就自动受到历史和撤销机制管理。

自动记录下来的行变化是已完成事务的审计结果，不是等待后续执行的任务清单。

### 8.3 撤销规则

撤销在新事务中反向应用行变化，并检查当前 revision 是否仍等于原操作的 `after_revision`：

- 没有后续冲突时整体撤销；
- 任一行已被后续操作修改时整体拒绝；
- 不进行部分撤销；
- 不覆盖较新的用户编辑；
- 撤销本身也产生新的 operation。

## 9. 回收站

回收站直接查询 `entities.deleted_at IS NOT NULL`，不再拼接剧情文件回收站、档案 JSON 回收站和部分操作历史。

统一实体表天然提供：

- 删除类型；
- 稳定 ID；
- 标题；
- 删除时间；
- 到期时间；
- 是否可恢复；
- 预览入口。

回收站查询先在 SQL 层筛选删除状态和七天窗口，再分页。不能先截取最近若干次普通操作，再从结果中筛选删除项。

级联隐藏的关系不会显示为独立删除项。例如删除人物导致其关系边不可见时，回收站只显示人物；恢复人物后，未被单独删除的关系自然恢复。用户主动删除某条关系时，该关系实体本身进入回收站。

## 10. 正文、智能提示与引用

剧情、人物、设定和碎片正文继续保存为 Markdown 文本。删除实体不会搜索并替换正文中的自然语言。

智能提示选择人物或设定时同时完成两件事：

- 在正文插入可读名称；
- 在对应关系表写入结构化引用。

智能提示候选只查询活动视图。姓名只是展示内容，稳定引用使用实体 ID；重命名不会改变引用身份。

如果未来需要正文中的可点击精确引用，应设计专门的结构化 mention 标记或编辑器 decoration，不能通过全局搜索姓名推断身份。

## 11. API 与前端状态

建议的核心接口：

```text
DELETE /api/v1/entities/{entityId}
POST   /api/v1/entities/{entityId}/restore
GET    /api/v1/trash
GET    /api/v1/trash/{entityId}
GET    /api/v1/operations
POST   /api/v1/operations/{operationId}/undo
```

删除确认弹窗可以查询影响统计，例如关系数量、剧情关联数量和图谱配置数量。但这些统计只用于向用户解释结果，不传回服务器作为删除命令，也不决定数据库清理范围。

mutation 响应返回实体 revision 和必要的 store delta。前端从实体 store 中移除或恢复目标，不重新加载整个项目，不刷新页面，不重建未受影响的编辑器和 viewport。

## 12. 导出与 Git

运行时只读取 SQLite。`manifest.md`、`content-index.json` 和各 Markdown 文件不参与本地读写逻辑。

导出器从某个确定的数据库 revision 生成完整快照：

- 不根据业务操作维护“需要更新的文件列表”；
- 不从旧导出读取状态；
- 在临时目录生成全部目标内容；
- 校验完成后原子替换导出目录；
- 同一数据库 revision 必须生成字节一致的结果。

本地 Git 备份至少提交 `story.db`。Markdown/JSON 快照可以用于可读 diff 和静态部署，但它们始终是可重新生成的产物。

新的 `manifest.md` 只包含作品级配置，不保存人物、剧情或关系文件路径清单。静态部署使用构建时生成的结构化 snapshot，不让浏览器重新解析整个 Markdown 文件树。

## 13. 一次性迁移

schema v2 到 schema v3 使用临时数据库完成，不在正式内容包中边读边改：

1. 以当前 schema v2 `story.db` 为只读输入；
2. 从 `documents` 解析实体、正文、结构化字段和引用；
3. 写入新的 schema v3 临时数据库；
4. 执行外键、唯一性、分类约束和引用完整性检查；
5. 比对人物、剧情、设定、碎片、关系、图谱和时间线数量；
6. 比对所有 Markdown 正文的内容哈希；
7. 从 schema v3 生成一次完整导出并与可迁移内容比对；
8. 全部校验通过后，停止旧服务并原子替换 `story.db`；
9. 同一个代码提交切换到只支持 schema v3 的新 API 和前端；
10. 保留迁移前数据库备份用于人工回退，但运行时不再双写或读取它。

迁移程序必须可重复执行：相同 schema v2 输入应得到语义一致的 schema v3 数据。迁移失败不得改变正式数据库。

## 14. 约束与测试

### 14.1 数据库约束

- 每个连接执行 `PRAGMA foreign_keys = ON`；
- CI 和启动检查执行 `PRAGMA foreign_key_check`；
- 稳定 ID 使用唯一约束且永不复用；
- 关系端点不能相同；
- 活动人物姓名遵守明确的唯一性策略；
- revision 由统一事务层更新；
- 禁止绕过 repository / Unit of Work 的直接写入。

### 14.2 必须覆盖的行为

- 删除人物后，所有活动视图都不再返回人物、节点或相连关系；
- 删除不会自动连接原关系两端；
- 恢复人物后，仍然有效且未被单独删除的关联重新出现；
- 七天后硬删除人物，所有外键子行被数据库级联清除；
- 删除剧情后显示顺序自动连续，稳定 ID 和 sort key 不被批量重写；
- 恢复剧情后回到原阅读位置；
- 在任意事务步骤注入异常时，数据库没有部分修改；
- 后续编辑触及同一行时，旧操作撤销被安全拒绝；
- 超过 200 次普通编辑后，七天内删除项仍在回收站；
- 到期历史正文从数据库删除，维护后不残留于 SQLite 空闲页；
- 删除和恢复后前端不整页刷新，编辑器、滚动位置和图谱 viewport 保持稳定；
- 完整数据库迁移前后正文哈希一致。

测试应优先验证数据库约束和活动视图，而不是断言某个 Python 函数包含若干目录名。新增引用表后，`PRAGMA foreign_key_check`、统一实体契约和通用删除测试必须自动覆盖它。

## 15. 完成标准

只有满足以下条件，才算完成本次重构：

- 本地运行时完全不读取 schema v2 `documents` 作为业务数据；
- 人物、剧情、设定、关系、图谱和时间线引用全部进入规范化表；
- 正常删除代码不扫描 Markdown、不拼装 patch 清单、不调用 repair；
- 删除、恢复、永久清理和撤销都由同一事务模型完成；
- 回收站只有一个数据来源；
- 所有实体类型拥有一致的七天保留语义；
- SQLite 外键和活动视图能够独立保证删除后无活动悬空引用；
- schema v2 数据完整迁移，正文哈希无损；
- 现有用户界面的关键状态在 mutation 后保持不变；
- 旧 `manifest.md` 内容清单、档案 JSON 回收站和剧情文件回收站退出运行时路径；
- 单元、集成、迁移和浏览器端到端测试全部通过。
