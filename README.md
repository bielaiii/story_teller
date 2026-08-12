# Story Teller

一个用于编写小说剧情、维护人物与设定、编排阅读顺序和故事时间的本地创作工具。

当前运行架构是 React + TypeScript + CodeMirror 6 前端、FastAPI 本地服务和 Schema V4 SQLite。`story.db` 是唯一可写数据源；Markdown、静态 JSON 与恢复快照都由数据库确定性生成。Schema V4 在规范化内容之上增加了可持久化的 Git 三方合并会话。

架构决策和验收边界见[《架构升级计划》](docs/architecture-modernization.md)、[《规范化数据与删除架构》](docs/relational-data-deletion-architecture.md)和[《产品功能路线图》](docs/product-feature-roadmap.md)。

本地 AI/RAG 的索引、HTTP、MCP 和 embedding 模型切换说明见[《本地 RAG 与 AI 接入》](docs/rag-integration.md)。

## 本地运行

```sh
./run.sh
```

浏览器打开 `http://127.0.0.1:4180/`。启动脚本只监听本机地址，会构建前端、检查并原子迁移当前内容包、清理到期回收站，并自动启动或复用 `127.0.0.1:4181` 上唯一的 Story World Hub，再把当前 Git 仓库注册为一个无端口 stdio worker。

通常不需要再开一个终端。`run-rag.sh` 保留为只启动/复用 Hub 并注册当前仓库的兼容入口：

```sh
./run-rag.sh
```

多个小说仓库共享同一个 `http://127.0.0.1:4181/mcp/`，Hub 会在每个工具的 `workspace` 参数中动态提供可选仓库，AI 客户端无需预先知道名称；项目 worker 本身不绑定端口。只有名称重名时选项才会使用内部 `workspaceId`。端口上已经是兼容 Hub 时直接复用，是其他程序或不兼容 Hub 时明确报错且不会终止对方进程。每次检索前仍按 `story.db` revision 增量同步 RAG。

OpenCode 等本地 AI 推荐使用无端口的 stdio MCP。安装一次全局启动器：

```sh
./scripts/install-story-world-mcp.sh
opencode mcp add story-world -- story-world-mcp
```

然后在 AI 客户端中把本地 MCP 命令配置为 `story-world-mcp`。启动器会根据客户端当前目录向上发现最近的 `content/*/story.db`，使用当前仓库自己的框架；一个工作区有多个内容项目时可通过 `list_world_projects` 选择。不能根据当前目录启动命令的客户端，只需固定配置一次 Hub 地址，并先调用 `list_world_workspaces`。

使用父仓内容目录：

```sh
STORY_TELLER_CONTENT_ROOT=/path/to/novel/content \
STORY_TELLER_DEFAULT_PROJECT=my-novel \
./run.sh
```

开发前端时使用 `./dev.sh`：FastAPI 运行在 4180，Vite 开发服务运行在 5173，并把 API 请求代理到本地服务。

## 数据、Git 与恢复

每个内容包位于 `content/<project>/`，其中：

- `story.db`：唯一事实来源，应随小说仓库提交到 GitHub；
- `characters/`、`plots/`、`entries/` 等 Markdown：便于人工阅读和 Git diff 的只读导出；
- `project.snapshot.json`：静态站点读取的完整只读快照；
- `recovery.snapshot.json`：包含实体、引用、顺序、回收站和操作历史的完整灾难恢复快照。
- `world-schema.json`、`ai-manifest.json`、`AI_CONTEXT.md`：给其他 AI 读取的领域语义、机器入口和简明使用说明，均由数据库和领域注册表生成。

网页写入成功后会更新导出。直接修改导出文件不会改变数据库，后续导出会覆盖这些改动。SQLite 的 `-journal`、`-wal`、`-shm` 文件不要提交。

新增 SQLite 表或字段时必须同步领域注册表：

```sh
npm run schema:sync
npm run schema:check
```

未说明字段是否对 AI 可见、可搜索、可导出的结构会被标记为 `TODO`，并使 CI 失败。完整规则见[《世界领域注册表》](docs/world-schema-registry.md)。

父仓可用 `.gitattributes` 把 `story.db` 交给 `storyteller.merge_driver`。驱动读取 Git 提供的共同、本地和远程三个数据库：先按行和字段合并，再调用 Git 原生文本合并处理正文；无法自动判断的字段写入 `merge_sessions` / `merge_conflicts`。服务检测到开放会话后只允许读取和解决冲突，完成网页确认及完整性检查前拒绝其他写操作。

从旧 Schema V2 数据库迁移或检查导出：

```sh
./scripts/python.sh -m storyteller.bootstrap content/demo
```

数据库丢失时，从恢复快照重建到一个不存在的新路径：

```sh
./scripts/python.sh -m storyteller.recovery \
  content/demo \
  content/demo-restored/story.db \
  --project demo
```

恢复命令不会覆盖现有数据库。先核对恢复结果，再原子替换正式 `story.db`。

## 编辑器快捷能力

剧情、人物、设定、碎片和人物关系正文共用同一个 CodeMirror 编辑器：保存不会刷新页面、关闭弹窗或重建编辑器，光标、选区、撤销栈、折叠状态、同步滚动和沉浸模式都会保留。

- `⌘/Ctrl+S` 原位保存；`⌘/Ctrl+Z`、`⌘/Ctrl+Shift+Z` 撤销和重做；
- `⌘/Ctrl+B/I/E/K` 加粗、斜体、行内代码和链接；
- `⌘/Ctrl+Alt+1/2/3` 设置标题；`Alt+↑/↓` 在标题间跳转；
- `⌘/Ctrl+F/H` 查找和替换；`⌘/Ctrl+Shift+P/F` 切换预览和沉浸模式；
- 正文输入 `@` 检索人物、输入 `/` 检索设定，支持中文、全拼和首字母；
- `Alt+M` / `Alt+/` 打开独立物理拼音检索，不把拼音字母写入正文，也不触发正文输入法候选；
- `F1` 可随时查看完整快捷键表。

## 测试

```sh
npm run test:unit
npm run test:frontend
npm run build
npm run test:e2e:v3
npm run test:e2e:merge
npm run test:e2e:static
```

测试覆盖 Schema V1/V2→V4 与 V3→V4 迁移、SQLite/Git 三方合并、冲突写入门禁和网页解决流程，以及正文哈希、外键、软删除/恢复/永久清理、通用撤销、稳定引用、安全重命名、恢复快照、编辑器状态保持及静态只读模式。
