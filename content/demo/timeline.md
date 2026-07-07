---
mainLine: 主线
lineSpacing: 54
topPadding: 54
sidePadding: 34
lines: [主线, 电台线, 旧案线, 港区线, 手稿线]
palette: ["#3f7fc1", "#d65f8f", "#3ba878", "#df8d35", "#7164c9", "#2c9fb3", "#d95b6b", "#6676c7"]
---

# Timeline Layout

## Branches

- line: 电台线
  startLine: 主线
  startPosition: 12%
  endLine: 主线
  endPosition: 65%
  side: right
  trackFromMain: 1
  displayLength: 420

- line: 旧案线
  startLine: 主线
  startPosition: 15%
  endLine: 主线
  endPosition: 86%
  side: left
  trackFromMain: 1
  displayLength: 560

- line: 港区线
  startLine: 主线
  startPosition: 29%
  endLine: 主线
  endPosition: 86%
  side: right
  trackFromMain: 2
  displayLength: 500

- line: 手稿线
  startLine: 旧案线
  startPosition: 42%
  endLine: 电台线
  endPosition: 76%
  side: left
  trackFromMain: 2
  displayLength: 300

## Nodes

- plotId: 1
  line: 主线
  linePosition: 4%
  displayTitle: 烧毁的账本
  displaySummary: 账本被烧毁，主线正式露出第一道裂缝。

- plotId: 2
  line: 旧案线
  linePosition: start

- plotId: 3
  line: 港区线
  linePosition: start

- plotId: 4
  line: 手稿线
  linePosition: start

- plotId: 5
  line: 电台线
  linePosition: 55%
  displaySummary: 午夜电台重复播放不存在的证词，电台线开始压向主线。

- plotId: 6
  line: 旧案线
  linePosition: 58%

- plotId: 7
  line: 旧案线
  linePosition: 74%

- plotId: 8
  line: 电台线
  linePosition: end

- plotId: 9
  line: 主线
  linePosition: 94%
