# Story Teller CLI 功能索引与使用手册

本文是 Story Teller 命令行的统一入口，覆盖内容 CLI `story-teller`、碎片兼容 CLI `story-fragment`，以及独立 Hub 仓库提供的管理 CLI `story-hub`。具体字段和长示例仍由各领域文档展开，本文负责说明安装、运行方式、完整命令树、通用约定和常见工作流。

## 1. 三个命令分别负责什么

| 命令 | 用途 | 是否直接写数据库 |
|---|---|---|
| `story-teller` | 人物、关系、剧情、设定、组织、搜索、合并、时间线、RAG、Markdown bundle 导入 | 否；通过 Content HTTP API 和共享 Application 层写入 |
| `story-fragment` | 旧版碎片与剧情线兼容入口 | 否；通过同一 Content HTTP API 写入 |
| `story-hub` | 管理 Workspace、Project、Content Worker 和 MCP 生命周期 | 否；调用唯一 Hub Runtime 的管理 API |

`story-teller` 无需先打开 Web。启动器会发现当前小说仓库，向唯一 Hub 申请 Client Lease，并自动启动或复用对应 Content Worker。多个 CLI 和 Web 复用同一个 Worker；最后一个 CLI 退出后，未被 Web 持有的 Worker 会保留 60 秒再回收。CLI 不会因此自动开启 MCP，也不会改变 Web 的托管状态。

所有内容写入继续拥有与 Web 相同的事务、revision 检查、Git 合并门禁、软删除、七日撤销、确定性导出和 RAG 同步语义。

## 2. 安装与发现当前小说

在小说仓库内可以直接运行：

```sh
./story_teller/story-teller --help
./story_teller/story-teller character list
```

安装全局命令后，可以从小说仓库的任意子目录运行：

```sh
./story_teller/scripts/install-story-teller.sh
story-teller character list
```

启动器从当前目录向上发现最近的 `content/<project>/story.db`。如果一个 Content 下存在多个 Project 且无法自动选择，使用：

```sh
story-teller --project PROJECT_ID character list
```

也可以显式连接已有 Hub Workspace 或 Content Worker：

```sh
story-teller --web-url http://127.0.0.1:4187/w/WORKSPACE_ID character list
story-teller --web-url http://127.0.0.1:PORT character list
```

## 3. `--help` 使用方法

每一级命令都支持 `-h` 或 `--help`，帮助不会启动 Worker，也不会修改数据：

```sh
story-teller --help
story-teller character --help
story-teller character relationship --help
story-teller character relationship add --help
story-teller plot add --help
story-teller import markdown --help

story-fragment --help
story-fragment edit --help

story-hub --help
```

使用方式固定为：

```text
story-teller <命令域> <子命令> [参数]
```

全局参数可以放在子命令前后：

| 参数 | 含义 |
|---|---|
| `--project PROJECT` | 明确选择 Project ID |
| `--web-url URL` | 明确选择 Hub Workspace URL 或 Worker URL |
| `--json` | stdout 只输出一个稳定 JSON 文档，供脚本调用 |

## 4. `story-teller` 功能索引

| 命令域 | 功能 |
|---|---|
| `character` | 人物档案、关系、双向印象、删除恢复、历史和导出 |
| `plot` | 正式剧情、章号、故事位置、转碎片、恢复和导出 |
| `entry` | 世界设定、组织及组织成员 |
| `search` | 跨人物、剧情、设定和碎片的全局搜索 |
| `merge` | 逐字段处理 Git 数据库三方合并冲突 |
| `timeline` | 剧情线、主线、节点归属、故事顺序和章号同步 |
| `rag` | 手动重建当前 Project 的本地 RAG 索引 |
| `import markdown` | 预览并原子导入 `plots/`、`fragments/` Markdown bundle |

### 完整命令树

```text
story-teller
├── character (alias: characters)
│   ├── list
│   ├── show
│   ├── add
│   ├── edit
│   ├── delete
│   ├── trash
│   ├── restore
│   ├── history
│   ├── undo
│   ├── export
│   └── relationship (alias: relationships)
│       ├── list
│       ├── show
│       ├── add
│       ├── edit
│       └── delete
├── plot (alias: plots)
│   ├── list
│   ├── show
│   ├── add
│   ├── edit
│   ├── delete
│   ├── to-fragment (alias: demote)
│   ├── trash
│   ├── restore
│   ├── history
│   ├── undo
│   └── export
├── entry (alias: entries)
│   ├── list
│   ├── show
│   ├── add
│   ├── edit
│   ├── delete
│   ├── trash
│   ├── restore
│   ├── history
│   ├── undo
│   └── member (alias: members)
│       ├── list
│       ├── add
│       ├── edit
│       └── remove
├── search
├── merge
│   ├── status
│   ├── show
│   ├── resolve
│   ├── resolve-all
│   └── finalize
├── timeline
│   ├── show
│   ├── line (alias: lines)
│   │   ├── list
│   │   ├── add
│   │   ├── edit
│   │   └── delete
│   ├── main
│   ├── node (alias: nodes)
│   │   ├── list
│   │   ├── assign
│   │   └── move
│   ├── history
│   └── undo
├── rag
│   └── rebuild
└── import
    └── markdown
```

## 5. 常见内容工作流

### 查询与查看

```sh
story-teller character list --role 主角
story-teller character show 沈清妙
story-teller plot list --story 主线 --tag 复仇
story-teller plot show "第一次交锋"
story-teller entry list --type 组织
story-teller search "码头证据" --kind plot --kind entry
```

选择器通常接受 `entityId`、稳定 ID、唯一名称或标题；人物还接受唯一别名。遇到重名时 CLI 不会猜测，而会要求使用 ID。

### 新建与编辑

```sh
story-teller character add 林冬 --role 配角 --scope 常驻人物
story-teller character edit 林冬 --group 调查组

story-teller plot add "第一次交锋" \
  --chapter-number 12 --body-file ./chapter-12.md --story 主线
story-teller plot edit "第一次交锋" --status 已完成 --key

story-teller entry add 调查组 --type 组织
story-teller entry member add 调查组 林冬 --role 调查员
```

正文、简介等长文本优先使用对应的 `--*-file` 参数。列表参数通常可以重复，例如 `--tag`、`--story`、`--person` 和 `--reference`。每个字段的完整参数以叶子命令帮助为准：

```sh
story-teller character add --help
story-teller plot edit --help
story-teller entry member add --help
```

### 删除、恢复与撤销

```sh
story-teller plot delete "第一次交锋" --yes
story-teller plot trash
story-teller plot restore plot:12
story-teller plot history
story-teller plot undo 42
```

人物、关系、剧情、设定和时间线分别维护自己的历史范围。非交互环境中的删除、转换或最终确认必须显式使用 `--yes`。

### Markdown 导出

```sh
story-teller character export 沈清妙 -o ./沈清妙.md
story-teller character export --all -o ./全部人物.md
story-teller plot export "第一次交锋" -o ./第12章.md
story-teller plot export --from "第一次交锋" --to "仓库决战" -o ./剧情范围.md
```

### Markdown bundle 导入

先预览，不写数据库：

```sh
story-teller import markdown ./story-import \
  --root ./story-import --recursive --check
```

确认预览后应用：

```sh
story-teller import markdown ./story-import \
  --root ./story-import --recursive --yes
```

导入路径必须位于 bundle 根目录的 `plots/` 或 `fragments/` 下。标题冲突需要显式添加 `--allow-title-conflicts`；正式章号冲突和歧义引用属于硬冲突，不能通过该参数跳过。完整目录结构和 frontmatter 字段见[《Markdown 批量导入目录规范》](markdown-import-file-structure.md)。

### Git 合并与时间线

```sh
story-teller merge status
story-teller merge show CONFLICT_ID
story-teller merge resolve CONFLICT_ID body_markdown --manual-file ./merged.md
story-teller merge finalize --yes

story-teller timeline line list
story-teller timeline node assign "第一次交锋" --line 主线 --line 调查线
story-teller timeline node move "第一次交锋" --before "仓库决战"
```

时间线移动会与 Web 一样原子同步故事位置和沿途正式章号，不在 CLI 中复制另一套排序规则。

## 6. 自动化、JSON 与退出码

自动化脚本应使用 `--json` 和 `--yes`：

```sh
story-teller plot list --json
story-teller plot delete plot:12 --yes --json
```

成功时 stdout 是一个包含 `ok: true` 的 JSON 文档；失败时是包含 `ok: false`、稳定 `code` 和错误文本的单一 JSON 文档。诊断信息不混入 JSON stdout。

| 退出码 | 含义 |
|---:|---|
| 0 | 成功，或用户主动取消交互操作 |
| 2 | 参数、文件、确认、Workspace 或 Project 选择错误 |
| 3 | 服务不可用、Project 不可写或能力不支持 |
| 4 | 选择器不存在或不唯一 |
| 5 | revision 或导入冲突 |
| 6 | 领域校验、合并门禁或其他 API 请求错误 |

脚本应优先判断进程退出码，再读取 JSON 的稳定 `code`，不要解析面向人的错误文本。

## 7. `story-fragment` 兼容命令树

`story-fragment` 保留旧脚本和自动化兼容。它通常连接已启动的 Web/Worker；新功能优先添加到统一的 `story-teller` 命令域。

```text
story-fragment
├── list
├── show
├── add
├── edit
├── import
├── promote
├── delete
├── trash
├── restore
├── history
├── undo
└── export
```

这里的 `story-fragment import [FILE|-]` 是按 Web 剪贴板格式导入一段 Markdown；它不同于 `story-teller import markdown` 的多文件 bundle 预览/原子导入。

```sh
story-fragment list --tree
story-fragment add "第一次交锋" --parent 复仇主线 --body-file ./first.md
story-fragment import ./clipboard.md
story-fragment promote fragment:12 --chapter-number 20
story-fragment export fragment:12 -o ./fragment.md
```

## 8. `story-hub` 管理命令树

`story-hub` 来自独立的 `story_teller_hub` 仓库。安装后，Web 管理页与 CLI 都只操作一个 Hub Runtime：

```sh
./scripts/install-story-hub.sh
story-hub status
```

```text
story-hub
├── status
├── workspace
│   ├── list
│   ├── status
│   ├── register
│   ├── start
│   ├── stop
│   ├── force-stop
│   ├── restart
│   ├── scan
│   ├── logs
│   └── remove
├── project
│   ├── list
│   ├── create
│   ├── enable
│   ├── disable
│   └── reload
├── mcp
│   ├── status
│   ├── start
│   ├── stop
│   └── restart
└── client
    └── exec
```

`client exec` 是 `story-teller` 启动器使用的 Client Lease 入口，普通内容操作不需要手动调用。Hub 管理命令使用 `--workspace <ID-or-name>` 选择 Workspace，并都支持 `--json`。完整生命周期说明见 `story_teller_hub/README.md`。

## 9. 领域详细文档

- [人物、关系、双向印象与恢复](character-cli.md)
- [剧情、设定、组织成员与 RAG](content-cli.md)
- [搜索、Git 合并与时间线](workflow-cli.md)
- [Markdown 批量导入目录规范](markdown-import-file-structure.md)
- [Web / CLI 共享内核架构](web-cli-shared-kernel-architecture.md)
