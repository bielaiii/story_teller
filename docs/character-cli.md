# 人物 CLI

`story-teller character` 是人物领域的完整命令行入口。它要求对应 Content 的 Web Worker 已经启动，通过本地 HTTP API 复用网页的校验、事务、revision 冲突、Git 合并门禁、七日恢复、确定性导出和 RAG 同步。

## 安装与定位

在小说仓库内可以直接执行：

```sh
./story_teller/story-teller character list
```

安装一次全局启动器：

```sh
./story_teller/scripts/install-story-teller.sh
```

启动器从当前目录向上查找最近的 `content/<project>/story.db`，再调用该小说仓库配套的 Story Teller 框架。多个 Project 无法自动判断时使用 `--project ID`；也可通过 `--web-url` 指定 Hub 工作区或 Worker 地址。

所有命令都接受放在任意位置的全局参数：

```text
--project PROJECT
--web-url URL
--json
```

`--json` 成功时只向 stdout 输出一个带 `ok: true` 的 JSON 文档；失败时输出 `ok: false`、稳定 `code` 和错误文本。普通模式的错误写入 stderr。

## 人物档案

### 查询

```sh
story-teller character list
story-teller character list --role 主角 --scope 主线人物 --group 沈家
story-teller character list --query 清妙 --limit 20 --json
story-teller character show 沈清妙
```

人物选择器接受：

- `entityId`，例如 `character:12`；
- 稳定 ID；
- 唯一姓名；
- 唯一别名。

姓名或别名重名时命令拒绝猜测，并返回候选 `entityId`。

`show` 返回完整人物档案，同时给出关联剧情、碎片、设定/组织和人物关系。JSON 模式下这些集合位于 `related`。

### 新建与编辑

```sh
story-teller character add 林冬 \
  --id lindong \
  --role 反派 \
  --scope 主线人物 \
  --impact 75 \
  --group 调查组 \
  --graph-visible \
  --alias 阿冬 \
  --marker 观察者 \
  --fact 职业=调查员 \
  --core-note "不会轻易相信任何人" \
  --core-persona 核心欲望=查清真相 \
  --supplement-note "习惯在凌晨整理线索" \
  --supplement-persona 偏好=黑咖啡 \
  --destiny-outline-file ./destiny.md \
  --reference character:1
```

`edit` 只修改明确传入的字段：

```sh
story-teller character edit 林冬 \
  --name "林冬（归队）" \
  --yes \
  --role 主角 \
  --impact 90 \
  --no-graph-visible
```

主要参数映射：

| 网页字段 | CLI 参数 |
|---|---|
| 姓名 | `--name`（新建时为位置参数） |
| 戏份定位 | `--role 主角\|反派\|中立\|配角` |
| 出场类型 | `--scope 主线人物\|常驻人物\|一次性角色\|待定角色` |
| 主线影响 | `--impact 0-100` |
| 图谱显示 | `--graph-visible` / `--no-graph-visible` |
| 分组 | `--group` / `--clear-group` |
| 颜色与渐变 | `--color`、`--gradient`、`--clear-gradient` |
| 别名、标识 | 可重复的 `--alias`、`--marker` |
| 人物档案 | 可重复的 `--fact 名称=内容` |
| 核心人设 | `--core-note 文本` 或 `--core-persona 名称=内容` |
| 补充人设 | `--supplement-note 文本` 或 `--supplement-persona 名称=内容` |
| 人物大纲 | `--destiny-outline` 或 `--destiny-outline-file` |
| 兼容人物简介 | `--intro` 或 `--intro-file` |
| 稳定引用 | 可重复的 `--reference SELECTOR` |

列表、档案、人设、正文和引用都有相应的 `--clear-*` 参数。核心人设与兼容人物简介共用旧数据的兼容存储，必须分两次修改；补充人设与旧式 `--supplement` 同理。CLI 会在发起请求前拒绝同一次操作中的歧义组合。

人物重命名会像网页一样在同一事务中更新带稳定引用的相关正文。交互模式会显示受影响内容数量并要求确认；自动化环境必须显式传 `--yes`。

### 导出

```sh
story-teller character export 林冬
story-teller character export 林冬 -o ./林冬.md
story-teller character export --from 沈清妙 --to 林冬 -o ./人物范围.md
story-teller character export --all -o ./全部人物.md
story-teller character export 林冬 --json
```

导出包含基础资料、简介或核心人设、人物大纲、补充人设和人物档案。支持单项、按当前人物顺序的闭区间范围和全部导出；多项内容使用 Markdown 分隔线连接。未指定 `-o` 时普通模式写到 stdout；JSON 模式放在 `markdown` 字段中，并返回 `entityIds` 与 `count`。

## 人物关系与人物印象

```sh
story-teller character relationship list
story-teller character relationship list --character 林冬 --scope core
story-teller character relationship show relationship:lindong__1
```

新建关系：

```sh
story-teller character relationship add 林冬 沈清妙 \
  --from-role 委托人 \
  --to-role 调查者 \
  --from-impression "可靠，但仍有所隐瞒" \
  --to-impression "过于正直" \
  --label 互相试探 \
  --type 盟友 \
  --scope core \
  --line-mode double \
  --color '#6f75c9' \
  --body "双方暂时合作"
```

同一对人物只保留一条关系。用相反顺序再次执行 `add` 时，CLI 会按人物方向转换角色和印象并更新原记录，不会新建重复关系，也不会覆盖没有显式提供的字段。

编辑或删除：

```sh
story-teller character relationship edit 关系ID --scope focus --clear-body
story-teller character relationship delete 关系ID
```

`scope` 支持 `core`、`focus` 和 `hidden`；`line-mode` 支持 `single` 与 `double`。`hidden` 可用于只保存在人物档案中的双向印象，并要求至少填写一方印象。

## 删除、恢复和撤销

人物和人物关系使用同一套恢复命令：

```sh
story-teller character delete 林冬
story-teller character relationship delete 关系ID
story-teller character trash
story-teller character trash --kind character
story-teller character restore character:12
story-teller character history --kind all
story-teller character undo 42
```

交互式删除会询问确认；自动化环境必须显式传 `--yes`。`trash`、`history` 和 `undo` 只处理 `character` 与 `relationship`，不会误操作剧情、设定或碎片。

## 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 成功或用户取消交互式删除 |
| 2 | 参数、工作区或 Project 选择错误 |
| 3 | 服务不可用或 Project 不可写 |
| 4 | 选择器不存在或不唯一 |
| 5 | revision 冲突 |
| 6 | 领域校验、合并门禁或其他请求错误 |
