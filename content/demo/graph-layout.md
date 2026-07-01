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
  members: [1, 3, 2]

- id: old-case
  label: 旧案相关
  centerX: 70
  centerY: 58
  radius: 180
  strength: 0.34
  members: [2, 5, 6]

- id: harbor
  label: 港区相关
  centerX: 26
  centerY: 56
  radius: 160
  strength: 0.46
  members: [4, 7]

## Distances

- from: 1
  to: 3
  distance: 190
  strength: 0.7

- from: 2
  to: 5
  distance: 220
  strength: 0.62

- from: 4
  to: 7
  distance: 280
  strength: 0.9

## Nodes

- id: 7
  orbitOf: 4
  orbitDistance: 300
  orbitAngle: -145
  strength: 0.03

- id: 6
  orbitOf: 2
  orbitDistance: 270
  orbitAngle: 35
  strength: 0.022
