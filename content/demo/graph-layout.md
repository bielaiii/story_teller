---
description: 人物图谱的软约束配置。默认不启用阵型预设，大部分节点仍然自动随机展开；这里只写需要额外控制的距离、抱团和延伸关系。
nodeSpacing: 116
---

## Clusters

- id: main-team
  label: 主角团
  centerX: 52
  centerY: 48
  radius: 190
  strength: 0.42
  members: [lin, su, shen]

- id: old-case
  label: 旧案相关
  centerX: 70
  centerY: 58
  radius: 180
  strength: 0.34
  members: [shen, han, yan]

- id: harbor
  label: 港区相关
  centerX: 26
  centerY: 56
  radius: 160
  strength: 0.46
  members: [qiao, mo]

## Distances

- from: lin
  to: su
  distance: 190
  strength: 0.7

- from: shen
  to: han
  distance: 220
  strength: 0.62

- from: qiao
  to: mo
  distance: 280
  strength: 0.9

## Nodes

- id: mo
  orbitOf: qiao
  orbitDistance: 300
  orbitAngle: -145
  strength: 0.03

- id: yan
  orbitOf: shen
  orbitDistance: 270
  orbitAngle: 35
  strength: 0.022
