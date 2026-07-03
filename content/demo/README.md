# 数据编辑说明

这个目录里的 Markdown 文件就是小说内容数据。

## 添加人物

1. 在 `characters` 目录新建一个 Markdown 文件，文件名使用 `ID-姓名.md`，例如 `characters/8-新人物.md`。
2. 按下面格式填写：

```md
---
id: 8
name: 新人物
aliases: [昵称, 常用称呼]
color: "#8a5cf6"
gradient: "linear-gradient(135deg, #8a5cf6, #2f184b)"
avatar: ./avatars/new-person.jpg
group: 主角团
markers: [男主, 主角团]
facts:
  职业: 档案修复师
  关系: 乔弥的旧友
x: 60
y: 40
---
这里写人物设定。
```

人物 `id` 使用自增数字。新建人物时取当前最大人物 ID 加一，例如现有最大值是 `7`，下一个人物就使用 `8`。ID 创建后保持不变；删除人物也不要复用旧 ID。

人物文件名必须与 `id`、`name` 保持一致。通过页面修改人物姓名时，人物文件以及包含该人物的关系文件会一起重命名；配置检查会报告手动编辑后留下的不一致。

`avatar` 可以不写。不写时，圆形头像里会显示完整人名；写了以后会使用这张图片作为圆形头像。建议你提供正方形图片，页面会自动用圆形裁切显示。

`group` 用来做人物分组筛选，例如 `主角团`、`港区相关`、`旧案相关`、`神秘人物`。

`markers` 用来显示人物身份标识，例如 `男主`、`女主`、`主角`、`主角团`、`反派`、`中立`。这是显示用标签，可以按你的小说设定自由增删。

`facts` 用来配置人物详情页中的键值档案，可以自由填写 `关系`、`年龄`、`职业`、`目标` 等字段。字段会按照 Markdown 中的书写顺序显示。

`aliases` 用来填写正文里可能出现的昵称、代号和常用称呼。页面会用人物的完整姓名和别名自动识别每章出场人物；唯一的 `男主`、`女主` 标识也可以直接作为正文称呼。相同别名属于多个人物时不会自动判断，避免认错人。

`events` 不需要手动维护。页面会根据人物在章节中的出现情况，自动整理人物详情页的相关剧情。

3. 使用 `./run.sh` 启动时，刷新网页即可自动发现新人物，无需修改 `manifest.md`。

## 添加剧情

1. 在 `plots` 目录新建一个 Markdown 文件，例如 `plots/010-new-plot.md`。
2. 按下面格式填写：

```md
---
id: 10
chapter: act2
title: 新剧情标题
summary: 一句话概括这一章发生了什么
accent: "#8a5cf6"
lanes: [主线, 感情线]
status: 待串联
tags: [雨夜, 暧昧, 身份暴露]
key: true
climax: false
---
这里写剧情正文。
```

`people` 可以不写。页面会扫描标题和正文，根据人物档案中的完整姓名、别名以及唯一的男主/女主称呼，自动生成出场人物。遇到只写“他”“母亲”这类无法判断的称呼时，仍可用 `people: [8, 1]` 手动补充。

`summary` 用于剧情全文顶部的简短概括。可以不写；不写时页面会自动从正文开头生成摘要。

`lanes` 表示这段剧情属于哪些剧情线。第一个是主要落点，后面的线会在时间线图里用横线连接，适合表现伏笔、支线穿插、分支汇合。

`entries` 也可以不写。页面会根据设定档案中的完整名称和 `aliases`，自动识别正文里出现的组织、势力、地点、物品、事件背景和规则，并显示在剧情全文页左侧。遇到简称重复、正文没有直接写出名称等情况时，可以用 `entries: [night-restaurant, second-key]` 手动补充。

`status` 表示整理状态，例如 `草稿`、`待串联`、`已接入`。这不是剧情内容本身，只是帮你知道这篇单篇目前整理到什么程度。

`tags` 表示剧情特征，例如 `雨夜`、`暧昧`、`恐怖感`、`身份暴露`。标签不代表剧情线，只用来搜索和筛选。

`key: true` 表示关键线索、重要反转、人物关系变化等关键剧情。

`climax: true` 表示高潮剧情，比如大冲突、最终揭露、战斗、情绪爆发等。两个字段都可以不写；不写就是普通剧情。

3. 使用 `./run.sh` 启动时，刷新网页即可自动发现新剧情，无需修改 `manifest.md`。

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
accent: "#e76f51"
aliases: [后街餐厅, 半潮]
tags: [修船厂, 夜间, 匿名包裹]
people: [2, 6]
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

`plots` 不需要手动维护。页面会根据设定在章节中的出现情况，自动整理设定详情页的相关剧情；也可以保留 `plots` 或剧情文件中的 `entries` 作为手动补充。

3. 使用 `./run.sh` 启动时，刷新网页即可自动发现新设定，无需修改 `manifest.md`。

## 添加灵感碎片

1. 在 `fragments` 目录新建一个 Markdown 文件，例如 `fragments/new-idea.md`。
2. 按下面格式填写：

```md
---
id: new-idea
title: 新灵感
status: 灵感
tags: [电台, 梦境]
accent: "#457b9d"
---
这里写还没整理成正式剧情点的画面、台词、设定或想法。
```

3. 使用 `./run.sh` 启动时，刷新网页即可自动发现新碎片，无需修改 `manifest.md`。

## 添加人物关系

1. 在 `relationships` 目录新建一个 Markdown 文件，文件名由两个端点生成，例如 `relationships/8-新人物__1-林秋.md`。
2. 按下面格式填写：

```md
---
people:
  - id: 8
    role: 师父
  - id: 1
    role: 徒弟
label: 师徒
color: "#8a5cf6"
type: 同盟
---
```

3. 使用 `./run.sh` 启动时，刷新网页即可自动发现新关系，无需修改 `manifest.md`。

如果一个人物只和一个人物有关系，只写这一条关系文件就可以。系统不会自动帮它连到其他人。

`people` 必须恰好包含两个端点。`id` 对应人物档案的稳定 ID，`role` 表示这个人物在当前关系中的身份。人物详情页会读取对方的 `role`，因此同一份文件可以让徒弟看到“师父”，也让师父看到“徒弟”。

`type` 用来做关系类型筛选，例如 `同盟`、`敌对`、`亲属`、`旧案`、`秘密`、`预言`。

## 调整人物图谱布局

人物图谱默认会根据人物关系自动布局。你不需要给每个人都手动设置位置。

如果某些节点太乱，可以在 `graph-layout.md` 里增加软约束。软约束不会把节点钉死，只会像弹簧一样影响自动布局。

### 阵型

默认不需要写阵型。图谱会先根据人物关系和自然随机偏移自动展开。

当你确实想要某一组节点有明显轮廓时，可以在 `graph-layout.md` 里加 `Formations`。阵型只是位置参考，仍然是软约束，不会覆盖手动拖拽后固定的位置。每个阵型都可以加 `jitter`，让节点保留大概形状但不死板。

男女主水平居中：

```md
## Formations

- id: lead-pair
  type: pair
  members: [1, 3]
  centerX: 50
  centerY: 50
  direction: horizontal
  distance: 280
  strength: 0.88
  jitter: 22
```

`centerX` 和 `centerY` 表示这一组的中心点在画布中的百分比。`direction: horizontal` 表示左右展开，`direction: vertical` 表示上下展开。`distance` 是两个节点之间的大概距离。

十字形：

```md
## Formations

- id: old-case-cross
  type: cross
  center: 2
  north: 6
  south: 5
  west: 1
  east: 4
  centerX: 56
  centerY: 52
  spacing: 220
  strength: 0.82
  jitter: 20
```

放射形：

```md
## Formations

- id: qiao-star
  type: star
  center: 4
  members: [7, 1, 3, 5]
  centerX: 32
  centerY: 55
  radius: 230
  startAngle: -90
  strength: 0.72
  jitter: 26
```

环形：

```md
## Formations

- id: suspect-ring
  type: ring
  members: [1, 3, 2, 5, 6, 4]
  centerX: 55
  centerY: 52
  radius: 260
  strength: 0.68
  jitter: 24
```

链条：

```md
## Formations

- id: clue-chain
  type: chain
  members: [6, 2, 5, 4]
  centerX: 58
  centerY: 44
  direction: horizontal
  spacing: 180
  strength: 0.7
  jitter: 18
```

三角形：

```md
## Formations

- id: lead-triangle
  type: triangle
  members: [1, 3, 2]
  centerX: 50
  centerY: 50
  radius: 190
  strength: 0.72
  jitter: 20
```

支持的阵型类型是 `pair`、`cross`、`star`、`ring`、`chain`、`triangle`。如果一个节点同时出现在多个阵型里，会受到多个参考位置影响；为了仍然看出形状，建议一个强阵型配合其他弱阵型使用。

`nodeSpacing` 可以写在 `graph-layout.md` 顶部元信息里，用来控制节点之间的最小间距：

```md
---
nodeSpacing: 116
---
```

系统每帧都会做碰撞分离，避免头像互相重叠。

### 抱团

```md
## Clusters

- id: harbor
  label: 港区相关
  centerX: 26
  centerY: 56
  radius: 160
  strength: 0.46
  members: [4, 7]
```

`members` 会自然靠近。`centerX` 和 `centerY` 是这个团大概在画布中的位置百分比。`radius` 越大越松散，`strength` 越大越听配置。

### 指定距离

```md
## Distances

- from: qiao
  to: 7
  distance: 280
  strength: 0.9
```

`distance` 是希望两个节点保持的大概距离。它会和关系线、抱团、拖拽位置一起折中。

### 向外延伸

```md
## Nodes

- id: 7
  orbitOf: 4
  orbitDistance: 300
  orbitAngle: -145
  strength: 0.03
```

这适合“某个人只和一个核心人物有关”的情况。`orbitOf` 是核心节点，`orbitDistance` 是离核心多远，`orbitAngle` 是延伸方向：`0` 向右，`90` 向下，`-90` 向上，`180` 向左。

手动拖动过的节点会优先停在你松手的位置，配置不会把它强行拉回去。
