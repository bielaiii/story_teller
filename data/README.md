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

`group` 用来做人物分组筛选，例如 `主角团`、`港区相关`、`旧案相关`、`神秘人物`。

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
entries: [night-restaurant, second-key]
accent: #8a5cf6
lanes: [主线, 感情线]
status: 待串联
tags: [雨夜, 暧昧, 身份暴露]
key: true
climax: false
---
这里写剧情正文。
```

`lanes` 表示这段剧情属于哪些剧情线。第一个是主要落点，后面的线会在时间线图里用横线连接，适合表现伏笔、支线穿插、分支汇合。

`entries` 表示这个剧情关联的设定条目，例如公司、组织、常驻地点、关键物品。写设定条目的 `id`，剧情全文页左侧会显示这些条目，并且可以点进设定档案。

`status` 表示整理状态，例如 `草稿`、`待串联`、`已接入`。这不是剧情内容本身，只是帮你知道这篇单篇目前整理到什么程度。

`tags` 表示剧情特征，例如 `雨夜`、`暧昧`、`恐怖感`、`身份暴露`。标签不代表剧情线，只用来搜索和筛选。

`key: true` 表示关键线索、重要反转、人物关系变化等关键剧情。

`climax: true` 表示高潮剧情，比如大冲突、最终揭露、战斗、情绪爆发等。两个字段都可以不写；不写就是普通剧情。

3. 在 `manifest.md` 的 `Plots` 下面加一行：

```md
- ./data/plots/010-new-plot.md
```

## 添加设定条目

1. 在 `entries` 目录新建一个 Markdown 文件，例如 `entries/night-restaurant.md`。
2. 按下面格式填写：

```md
---
id: night-restaurant
name: 半潮餐厅
type: 地点
subtype: 餐厅
area: 修船厂后街
accent: #e76f51
aliases: [后街餐厅, 半潮]
tags: [修船厂, 夜间, 匿名包裹]
people: [shen, yan]
plots: [4, 7]
status: 草稿
---
这里写这个设定的介绍、氛围、历史、用途和隐藏信息。
```

设定条目的 `type` 用来做大类筛选，建议固定使用这六类：`组织`、`势力`、`地点`、`物品`、`事件背景`、`规则`。

`subtype` 用来做细分描述，例如 `公司`、`地方人脉`、`餐厅`、`公共建筑`、`设施`、`钥匙`、`旧案`、`时间异常`。比如公司背景可以写成 `type: 组织`、`subtype: 公司`；更松散的人脉、派系、利益网络可以写成 `type: 势力`。

`area` 表示这个条目所属区域、归属范围或常出现的位置，用来帮助你把同一城市或世界观里的设定分组理解。

`tags` 和剧情标签使用同样的筛选逻辑：默认全选，点击某个标签后只看这个标签，再点击其他标签会追加筛选；全部取消时会回到全选状态。

`people` 表示和这个设定强相关的人物，比如公司成员、地点常驻角色、物品持有人或发现者。

`plots` 表示这个设定相关剧情。你也可以在剧情文件里用 `entries: [night-restaurant]` 反向关联；两边任意一种写法都可以让设定档案里出现对应剧情。

3. 在 `manifest.md` 的 `Entries` 下面加一行：

```md
- ./data/entries/night-restaurant.md
```

## 添加灵感碎片

1. 在 `fragments` 目录新建一个 Markdown 文件，例如 `fragments/new-idea.md`。
2. 按下面格式填写：

```md
---
id: new-idea
title: 新灵感
status: 灵感
tags: [电台, 梦境]
accent: #457b9d
---
这里写还没整理成正式剧情点的画面、台词、设定或想法。
```

3. 在 `manifest.md` 的 `Fragments` 下面加一行：

```md
- ./data/fragments/new-idea.md
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
