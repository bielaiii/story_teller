---
# 可选：所属故事。
# 类型：自由文本。
# 位于 fragments/<故事名>/ 目录中时可以省略，Story Teller 会使用目录名。
# 根目录文件没有 story 时，是独立 Fragment。
# 同一个故事的总览请写在该目录的 _story.md 中。
# story: 校园复仇

# 可选：同一故事内的排列位置。
# 类型：从 1 开始的正整数；没有 story 的独立 Fragment 不应填写。
# 不提供时按文件自然顺序排列。
# order: 1

# 可选：Fragment 故事内部章号。
# 类型：正整数；不是正式 Plot 章号，可以一直省略。
# 没有 story 的独立 Fragment 不应填写。
# chapterNumber: 1

# 可选：标签列表；每一项都是自由文本。
tags: []
# tags:
#   - 校园
#   - 试探

# 可选：转为 Plot 后是否属于关键剧情。
# 只能填写 YAML 布尔值 true 或 false；默认：false。
key: false

# 可选：转为 Plot 后是否属于高潮剧情。
# 只能填写 YAML 布尔值 true 或 false；默认：false。
climax: false
---

从这里开始填写 Fragment 正文，支持普通 Markdown。

文件名去掉 `.md` 后就是 Fragment 标题。Fragment 不支持 status；转为 Plot 后状态默认是“草稿”。
