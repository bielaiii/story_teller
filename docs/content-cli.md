# 剧情、设定与 RAG CLI

本文说明 `story-teller plot`、`story-teller entry` 和 `story-teller rag`。CLI 会通过唯一 Hub 自动启动或复用对应 Content Worker；所有写入通过本地 HTTP API 进入共享 Application 层，因此与网页具有相同的校验、事务、revision 冲突、Git 合并门禁、七日恢复、确定性导出和 RAG 同步语义。

安装和全局参数见[《人物 CLI》](character-cli.md)。所有命令都支持放在任意位置的 `--project`、`--web-url` 和 `--json`。

## 正式剧情

### 查询

```sh
story-teller plot list
story-teller plot list --status 定稿 --tag 复仇 --story 主线 --query 码头
story-teller plot show "第一次交锋"
```

剧情选择器接受 `entityId`、稳定 ID 或唯一标题；重名时拒绝猜测并要求使用 ID。`show` 返回完整正文以及关联人物、设定和故事线。

### 新建与编辑

```sh
story-teller plot add "第一次交锋" \
  --chapter-number 12 \
  --summary "她在码头发现账本" \
  --body-file ./chapter-12.md \
  --status 定稿 \
  --tag 关键节点 \
  --person 沈清妙 \
  --entry 港口仓库 \
  --story 复仇主线 \
  --key
```

未传 `--chapter-number` 时自动追加到当前最大章号之后。章号冲突默认拒绝；明确使用 `--shift-following` 后，当前章及连续后续章依次顺延。

```sh
story-teller plot edit "第一次交锋" \
  --title "码头第一次交锋" \
  --summary "更新后的摘要" \
  --climax \
  --story-position before \
  --anchor-plot "仓库决战"
```

支持字段：

- 标题、稳定 ID（仅新建）、章号、篇章和插入位置；
- 摘要、Markdown 正文、状态、强调色、标签；
- 出场人物、正文中出现的临时人物名、关联设定和稳定引用；
- 所属故事线；
- 故事时间跟随阅读顺序、发生在另一剧情之前/之后或固定数字位置；
- 关键剧情和高潮剧情。

`edit` 只修改明确提供的字段。列表、正文、摘要、引用、锚点和篇章均提供相应的 `--clear-*` 参数。

### 删除、转碎片与恢复

```sh
story-teller plot delete "第一次交锋"
story-teller plot to-fragment "第一次交锋"
story-teller plot trash
story-teller plot restore plot:12
story-teller plot history
story-teller plot undo 42
```

`to-fragment` 会把正文、标签、颜色和引用迁移到新碎片，原剧情进入回收站；转换作为一个原子操作，可以直接通过 `plot history` 找到并用 `plot undo` 撤销。非交互环境执行删除或转换必须传 `--yes`。

### Markdown 单项、范围和全部导出

```sh
story-teller plot export "第一次交锋"
story-teller plot export "第一次交锋" -o ./第12章.md
story-teller plot export --from "第一次交锋" --to "仓库决战" -o ./剧情范围.md
story-teller plot export --all -o ./全部剧情.md
```

范围按照当前阅读顺序取闭区间。多项导出使用 Markdown 分隔线连接。JSON 输出包含 `entityIds`、`count`，未指定 `-o` 时还包含 `markdown`。

人物下载使用相同模式：

```sh
story-teller character export 沈清妙
story-teller character export --from 沈清妙 --to 林冬 -o ./人物范围.md
story-teller character export --all -o ./全部人物.md
```

## 设定与组织

### 查询、新建、编辑和删除

```sh
story-teller entry list
story-teller entry list --type 组织 --tag 敌对 --query 沈家
story-teller entry show 沈氏集团

story-teller entry add 港口仓库 \
  --type 地点 --subtype 仓库 --area 城东 \
  --alias 旧仓库 --tag 调查 --body-file ./warehouse.md

story-teller entry edit 港口仓库 --status 封锁 --accent '#3f7fc1'
story-teller entry delete 港口仓库
story-teller entry trash
story-teller entry restore entry:8
story-teller entry history
story-teller entry undo 51
```

设定选择器接受 `entityId`、稳定 ID、唯一名称或唯一别名。支持名称、类型、子类型、区域、状态、颜色、正文、别名、标签、关联人物和稳定引用；编辑时可用相应 `--clear-*` 清空。重命名会显示稳定引用影响并要求确认，自动化环境使用 `--yes`。

### 新建组织并维护成员

新建时可以一次提供成员，格式为 `人物[=身份[,状态]]`：

```sh
story-teller entry add 调查组 \
  --type 组织 --subtype 公司 --status 活跃 \
  --member '林冬=负责人,现成员' \
  --member '沈清妙=调查员,秘密成员'
```

日常维护使用独立命令，不需要重填整张成员表：

```sh
story-teller entry member list 调查组
story-teller entry member add 调查组 黎清妍 --role 顾问 --status 秘密成员
story-teller entry member edit 调查组 黎清妍 --role 高级顾问 --status 现成员
story-teller entry member remove 调查组 黎清妍
```

成员身份属于组织，不会自动创建两个人之间的人物关系。添加、编辑和移除成员都会在同一事务中同步 `members`、关联人物和稳定引用，并且可以通过 `entry history` / `entry undo` 撤销。

## 手动重建 RAG

```sh
story-teller rag rebuild
story-teller rag rebuild --json
```

命令从当前 `story.db` 完整重建该 Project 的 RAG 索引，最长等待 120 秒。结果包含：

- `sourceRevision`：索引对应的数据库版本；
- `documents` 与 `chunks`：文档和文本块数量；
- `embeddingStatus` 与 `embeddingError`；
- `path`：生成的索引数据库路径。

当前服务不支持该能力、Project 不可写或索引生成失败时，命令返回非零退出码；`--json` 保持单 JSON 文档输出。
