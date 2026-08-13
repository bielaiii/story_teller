# Story Teller

一个用于编写小说剧情、维护人物与设定、编排阅读顺序和故事时间的本地创作工具。

当前运行架构是 React + TypeScript + CodeMirror 6 前端、FastAPI 本地服务和 Schema V4 SQLite。`story.db` 是唯一可写数据源；Markdown、静态 JSON 与恢复快照都由数据库确定性生成。Schema V4 在规范化内容之上增加了可持久化的 Git 三方合并会话。

架构决策和验收边界见[《架构升级计划》](docs/architecture-modernization.md)、[《规范化数据与删除架构》](docs/relational-data-deletion-architecture.md)和[《产品功能路线图》](docs/product-feature-roadmap.md)。

本地 AI/RAG 的索引、HTTP、MCP 和 embedding 模型切换说明见[《本地 RAG 与 AI 接入》](docs/rag-integration.md)。

## 本地运行

```sh
./run.sh
```

浏览器打开 `http://127.0.0.1:4180/`。4180 是独立 `story_teller_hub` 提供的统一管理页：多个 Git 仓库或 Content 根目录可以同时在线，每个 Content 下的多个 `content/<project>/story.db` 会分别列出。`story_teller` 只提供当前 Content 的 Web/MCP Worker；启动脚本通过 `STORY_TELLER_HUB_ROOT`（默认查找与 Content 仓库同级的 `story_teller_hub`）调用 Hub 安装源，实际共享 `~/.local/share/story-teller-hub/current` 中的唯一 runtime。

Hub 通过 `python -m storyteller.hub_worker` 的稳定 Facade 接入 Worker，只要求协议主版本与必要能力兼容。不同 Content 可以独立使用不同 Story Teller commit、协议次版本、API 和 Schema；源码 dirty 仅告警。Adapter 对外提供 `manifest`、`prepare`、`web`、`mcp` 和可选的 `create-project`，Hub 不依赖这些功能的内部模块结构。

MCP 默认跟随对应 Web Content：`./run.sh` 退出、管理页停止 Content、进程崩溃或心跳超时后，对应 MCP worker 会自动关闭，不影响其他 Content。管理页可以启动、重启、停止或强制终止 Content，单独重启 MCP，新建/扫描/停用/检查 Project，查看 Project 状态与 Web 日志，以及在不删除小说文件的前提下从 Hub 移除 Content。停止后的 Content 可以直接改为 Hub 托管并重新启动。同一个物理 Content 根目录使用进程级所有权锁，始终只有一个可写 Web Worker；Hub 异常死亡时 Worker 会跟随退出，多个浏览器共享该单例。

需要让 MCP 脱离 Web 独立运行时：

```sh
./run-rag.sh
```

独立 MCP 不会因 Web Content 关闭而退出。关闭独立模式或查看 Hub 状态：

```sh
./run-rag.sh stop
./run-rag.sh status
```

多个 Content 共享同一个 `http://127.0.0.1:4181/mcp/`，Hub 会在每个工具的 `workspace` 参数中动态提供当前运行中的 Content 选项，并在 `project` 中提供该 Content 下已启用的 Project；AI 客户端无需预先知道名称。`project` 可省略：优先选择与 workspace 同名的项目，否则单项目自动选中；多项目且无同名项时才需要明确选择。Content 的 MCP worker 本身不绑定端口。网页保存后会合并连续改动并在后台增量同步 RAG；每次检索前仍检查 `story.db` revision 作为正确性兜底。

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

`STORY_TELLER_CONTENT_ROOT` 可以指向 Git 仓库内任意独立 Content 根目录；Content 的稳定 ID 根据规范化真实路径生成，因此同一仓库也可以注册多个 Content。

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
npm run test:e2e:hub
```

测试覆盖 Schema V1/V2→V4 与 V3→V4 迁移、SQLite/Git 三方合并、冲突写入门禁和网页解决流程，以及正文哈希、外键、软删除/恢复/永久清理、通用撤销、稳定引用、安全重命名、恢复快照、编辑器状态保持及静态只读模式。
