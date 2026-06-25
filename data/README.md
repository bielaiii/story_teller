# 数据编辑说明

这个目录里的 Markdown 文件就是小说内容数据。

## 添加人物

1. 在 `characters` 目录新建一个 Markdown 文件，例如 `characters/new-person.md`。
2. 按下面格式填写：

```md
---
id: new_person
name: 新人物
color: #8a5cf6
gradient: linear-gradient(135deg, #8a5cf6, #2f184b)
avatar: ./data/avatars/new-person.jpg
group: 主角团
markers: [男主, 主角团]
x: 60
y: 40
events: [1, 5]
---
这里写人物设定。
```

`avatar` 可以不写。不写时，圆形头像里会显示完整人名；写了以后会使用这张图片作为圆形头像。建议你提供正方形图片，页面会自动用圆形裁切显示。

`group` 用来做人物分组筛选，例如 `主角团`、`港区势力`、`旧案相关`、`神秘人物`。

`markers` 用来显示人物身份标识，例如 `男主`、`女主`、`主角`、`主角团`、`反派`、`中立`。这是显示用标签，可以按你的小说设定自由增删。

3. 在 `manifest.md` 的 `Characters` 下面加一行：

```md
- ./data/characters/new-person.md
```

## 添加剧情

1. 在 `plots` 目录新建一个 Markdown 文件，例如 `plots/010-new-plot.md`。
2. 按下面格式填写：

```md
---
id: 10
chapter: act2
title: 新剧情标题
people: [new_person, lin]
accent: #8a5cf6
lanes: [主线, 感情线]
key: true
climax: false
---
这里写剧情正文。
```

`lanes` 表示这段剧情属于哪些剧情线。第一个是主要落点，后面的线会在时间线图里用横线连接，适合表现伏笔、支线穿插、分支汇合。

`key: true` 表示关键线索、重要反转、人物关系变化等关键剧情。

`climax: true` 表示高潮剧情，比如大冲突、最终揭露、战斗、情绪爆发等。两个字段都可以不写；不写就是普通剧情。

3. 在 `manifest.md` 的 `Plots` 下面加一行：

```md
- ./data/plots/010-new-plot.md
```

## 添加人物关系

1. 在 `relationships` 目录新建一个 Markdown 文件，例如 `relationships/new-person-lin.md`。
2. 按下面格式填写：

```md
---
from: new_person
to: lin
label: 师徒
color: #8a5cf6
type: 同盟
---
```

3. 在 `manifest.md` 的 `Relationships` 下面加一行：

```md
- ./data/relationships/new-person-lin.md
```

如果一个人物只和一个人物有关系，只写这一条关系文件就可以。系统不会自动帮它连到其他人。

`type` 用来做关系类型筛选，例如 `同盟`、`敌对`、`亲属`、`旧案`、`秘密`、`预言`。
