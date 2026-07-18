# Story Teller

一个用于编写小说剧情、维护人物与设定、编排阅读顺序和故事时间的本地创作工具。

当前运行架构是 React + TypeScript + CodeMirror 6 前端、FastAPI 本地服务和 Schema V3 SQLite。`story.db` 是唯一可写数据源；Markdown、静态 JSON 与恢复快照都由数据库确定性生成。

架构决策和验收边界见[《架构升级计划》](docs/architecture-modernization.md)、[《规范化数据与删除架构》](docs/relational-data-deletion-architecture.md)和[《产品功能路线图》](docs/product-feature-roadmap.md)。

## 本地运行

```sh
./run.sh
```

浏览器打开 `http://127.0.0.1:4180/`。启动脚本只监听本机地址，会构建前端、检查并原子迁移当前内容包、清理到期回收站，再启动同源页面与 API。

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

网页写入成功后会更新导出。直接修改导出文件不会改变数据库，后续导出会覆盖这些改动。SQLite 的 `-journal`、`-wal`、`-shm` 文件不要提交。

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
npm run test:e2e:static
```

测试覆盖 Schema V2→V3 迁移、正文哈希、外键、软删除/恢复/永久清理、通用撤销、稳定引用、安全重命名、恢复快照、编辑器状态保持及静态只读模式。
