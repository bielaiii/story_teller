# Story Teller Markdown 批量导入目录规范

导入器接受一个目录或多个 Markdown 文件；当前 API 以 JSON 文件数组上传，尚未启用 ZIP 上传。混合导入 Plot 和 Fragment 时，推荐使用以下顶层结构：

```text
story-import/
├── plots/
└── fragments/
```

所有 Markdown 文件都使用 UTF-8。文件名去掉 `.md` 后就是内容标题；YAML 中不填写 `title`。

## 连续导入一组 Plot

```text
story-import/
└── plots/
    ├── 回城前夜.md
    ├── 东港会议.md
    ├── 被替换的账本.md
    └── 江家第一次反击.md
```

每个文件都是一个正式 Plot，并且都必须在 YAML 中提供唯一的正式 `chapterNumber`：

```markdown
---
chapterNumber: 44
stories:
  - 主线
  - 东港
summary: 沈清妙回津海前完成最后一次任务分配。
status: 草稿
tags:
  - 回城
key: true
climax: false
---

这里是正文。
```

Plot 的导入顺序不依赖文件名、目录顺序或文件时间，只由 `chapterNumber` 决定。因此文件名可以专心表达标题，不需要添加 `001-` 之类的排序前缀。

`stories` 是故事列表，不是标签：

- 只有一个故事时填写一项；
- 交叉剧情可以填写多项；
- 未提供时默认只有“主线”；
- Story Teller 在剧情结构里显示为“某某篇”，在时间线里显示为“某某线”，二者是同一个故事对象；
- `tags` 只参与标签筛选，不会创建或匹配故事。

如果 `chapterNumber` 与数据库已有 Plot 或同批文件冲突，预览必须要求用户处理，不能自动追加到末尾。

## 导入独立 Fragment

直接放在 `fragments/` 根目录中的普通 Markdown 是独立 Fragment：

```text
story-import/
└── fragments/
    ├── 主卧边界.md
    ├── 新人物灵感.md
    └── 尚未解释的电话.md
```

独立 Fragment 也使用 YAML frontmatter；如果没有任何属性，frontmatter 可以是空对象：

```markdown
---
{}
---

陆沉舟可以留宿，但沈清妙始终不允许他进入主卧。
```

也可以配置标签和转正后继承的剧情属性：

```markdown
---
tags:
  - 陆沉舟
  - 关系边界
key: false
climax: false
---

这里是碎片正文。
```

独立 Fragment 不应填写 `story`、`order` 或 `chapterNumber`。

## 导入同一个故事的分章节 Fragment

同一个故事使用一个子目录，目录名就是故事标题：

```text
story-import/
└── fragments/
    └── 校园复仇/
        ├── _story.md
        ├── 第一次试探.md
        ├── 处分名单.md
        └── 第一次失败.md
```

`_story.md` 是整条故事的总览，可省略：

```markdown
---
tags:
  - 校园
  - 林越
---

这条故事负责交代沈清妙早年的第一次复仇尝试。
```

没有 `_story.md` 时，Story Teller 自动创建正文为空的故事容器。

目录中的其他 Markdown 每个代表一个 Fragment 章节：

```markdown
---
order: 1
chapterNumber: 3
tags:
  - 试探
key: true
climax: false
---

林越第一次发现沈清妙提前知道了处分结果。
```

其中：

- `order` 是故事内部排列位置，可省略；
- `chapterNumber` 是 Fragment 内部章号，可省略；
- 没有 `chapterNumber` 时显示为未编号章节，不影响保存；
- 正式 Plot 章号、插入位置和故事时间不在 Markdown 中配置，转正时再强制选择；
- `tags`、`key`、`climax` 在转为 Plot 时继承。

不使用目录上传时，可以在每个 Fragment 的 YAML 中写相同的 `story` 名称完成分组；目录与 YAML 同时存在时，两者必须一致，否则预览报错。

## 同时包含独立 Fragment 和多个分章节故事

```text
story-import/
├── plots/
│   ├── 回城前夜.md
│   └── 东港会议.md
└── fragments/
    ├── 主卧边界.md
    ├── 校园复仇/
    │   ├── _story.md
    │   ├── 第一次试探.md
    │   └── 第一次失败.md
    └── 江家暗线/
        ├── _story.md
        ├── 账本来源.md
        └── 财务主管失踪.md
```

导入器应先解析完整目录，再统一查重、解析故事归属和预览。用户确认后，全部内容在同一个 SQLite 事务中写入，并作为一个操作撤销。
