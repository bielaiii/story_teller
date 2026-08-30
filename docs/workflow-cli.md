# 搜索、合并与时间线 CLI

本文说明 `story-teller search`、`story-teller merge` 和 `story-teller timeline`。命令要求对应 Content 的本地 Worker 已启动，并通过与 Web 相同的 HTTP API 读取和写入；时间线保存、Git 合并完整性校验、七日撤销、导出与 RAG 同步仍由共享 Application / Domain 层负责。

安装与全局参数见[《人物 CLI》](character-cli.md)。`--project`、`--web-url` 和 `--json` 可以放在命令中的任意位置。

## 全局搜索

```sh
story-teller search 码头
story-teller search 沈清妙 --kind character
story-teller search 证据 --kind plot --kind fragment --limit 30
story-teller search 调查组 --json
```

搜索范围与 Web 全局搜索一致：

- 人物：姓名、稳定 ID、别名和人物介绍；
- 剧情：标题、摘要和正文预览；
- 设定：名称、别名、标签和正文预览；
- 碎片：标题和正文预览。

结果提供 `kind`、`entityId`、标题、类型说明和命中上下文。默认最多返回 12 项；多个 `--kind` 表示类型并集。JSON 输出固定为一个包含 `query` 和 `items` 的文档，适合脚本继续调用 `show` / `edit`。

## Git 数据库合并

Git 合并驱动无法自动判断同一字段的两侧修改时，普通写入会进入门禁。此时 CLI 的合并专用命令仍可工作：

```sh
story-teller merge status
story-teller merge show 冲突ID
story-teller merge resolve 冲突ID summary --ours
story-teller merge resolve 冲突ID body_markdown --theirs
story-teller merge resolve 冲突ID body_markdown --manual "人工合并后的正文"
story-teller merge resolve 冲突ID body_markdown --manual-file ./merged.md
story-teller merge finalize --yes
```

`show` 会列出每个字段的机器字段名、共同版本、本地版本、远程版本和已经保存的选择。`resolve` 每次只保存一个字段，可反复修改；`--manual` / `--manual-file` 仅允许用于两侧都是文本的字段。若明确要让整项都采用同一侧，可使用：

```sh
story-teller merge resolve-all 冲突ID --ours
story-teller merge resolve-all 冲突ID --theirs
```

只有 `resolvedFields == totalFields` 时才能 `finalize`。最终确认必须显式传 `--yes`；服务会在一个事务内应用所有选择、检查外键与数据库完整性、记录可撤销操作，然后解除 Web/CLI 写入门禁。选择组合不合法时不会部分写入。

## 时间线

### 查看剧情线和节点

```sh
story-teller timeline show
story-teller timeline line list
story-teller timeline node list
story-teller timeline node list --line 主线
```

`timeline show` 返回完整时间线结构和按故事时间排序的节点。`line list` 标记当前主线及每条线的节点数；`node list` 显示故事位置、正式章号、剧情和所属线。

### 剧情线与主线

```sh
story-teller timeline line add 调查线 --id investigation --color '#3ba878' --side left
story-teller timeline line edit 调查线 --name 暗线调查 --color '#123456' --side right
story-teller timeline main 暗线调查
story-teller timeline line delete 暗线调查 --replacement 主线 --yes
```

新建时省略 `--id` 会生成稳定 ID；`--main` 可在创建时直接设为主线。删除至少保留一条线，并要求指定 `--replacement`：原线节点、主线身份和删除动作在同一事务中完成，旧线进入七日回收站。

### 节点归属

```sh
story-teller timeline node assign "第一次交锋" --line 主线
story-teller timeline node assign "第一次交锋" --line 主线 --line 调查线
```

`assign` 用所给剧情线集合替换该剧情当前的全部归属。每个节点至少属于一条线；多次 `--line` 用于同时出现在多条线。非主线的起止节点会随归属自动重新计算。

### 故事顺序与正式章号

```sh
story-teller timeline node move "第一次交锋" --before "仓库决战"
story-teller timeline node move "第一次交锋" --after "仓库决战"
story-teller timeline node move "第一次交锋" --index 12
```

位置从 1 开始。语义与 Web 拖动一致：剧情沿途与相邻节点交换故事位置，同时交换正式章号，把受影响节点改为固定故事位置，并在一次 `/timeline` 事务中保存完整结构。不会只更新一条线而留下其他线顺序不一致。

所有时间线修改都进入统一七日操作历史：

```sh
story-teller timeline history
story-teller timeline undo 42
```

`undo` 会先验证没有较新的冲突修改，再恢复剧情线、节点归属、故事位置和正式章号。

## 自动化错误约定

使用 `--json` 时 stdout 始终只有一个 JSON 文档。常见稳定错误码包括：

- `not_found` / `ambiguous_selector`：选择器不存在或不唯一；
- `merge_incomplete`：仍有字段未处理；
- `manual_not_allowed`：非文本字段要求手动编辑；
- `confirmation_required`：最终合并或删除缺少 `--yes`；
- `merge_required`：普通时间线写入被尚未完成的合并会话锁住；
- `conflict` 或 API 返回的领域码：revision 已过期或校验失败。

失败返回非零退出码，且不会把部分时间线或部分最终合并写入数据库。
