# Web / CLI 共享内核：5 小时 Goal 执行记录

状态：核心 Goal、Stretch Goal、后续 Application 垂直切片与统一多领域 CLI Goal 均已完成
开始日期：2026-08-28
时间约束：5 小时人工 timebox，不是已确认的 Codex 产品硬限制

官方 [Follow a goal](https://learn.chatgpt.com/use-cases/follow-goals) 文档说明 Goal 适合带明确完成条件和验证循环的多小时任务，但没有声明统一的“5 小时平台上限”；因此本记录只把 5 小时当作本次工程预算。

## Goal

在 5 小时内完成两份架构文档、共享 Application Mutation Pipeline，以及碎片 create、update、import、promote、delete、restore、undo 的完整垂直切片迁移。保持 `/api/v1`、Web 行为和 `story-fragment` 兼容；所有持久化验证使用临时 Content。

## 承诺范围

### 能力一：Application Mutation Pipeline

- [x] 建立 contracts。
- [x] 建立 Application Context、Container 和 Project Provider。
- [x] 将 `finish_mutation` 移入 `MutationExecutor`。
- [x] 保留导出失败 warning 和 RAG 调度语义。
- [x] 增加 Application 与依赖方向测试。

### 能力二：碎片垂直切片

- [x] create
- [x] update
- [x] clipboard import
- [x] fragment → plot
- [x] delete
- [x] restore
- [x] undo
- [x] 保持 `story-fragment` 参数、JSON 和退出码兼容。
- [x] 从临时 SQLite 与生成导出 readback。

### 文档与验证

- [x] 写入共享内核架构文档。
- [x] 写入本执行记录。
- [x] Python 单元测试。
- [x] 前端单元测试。
- [x] 前端生产构建。
- [x] 碎片相关 E2E。
- [x] 确认真实内容数据库 hash 未变化。

## 时间预算

| 阶段 | 预算 |
| --- | ---: |
| 文档、基线和保护真实数据 | 0.5h |
| Application Mutation Pipeline | 1.5h |
| 碎片完整迁移 | 2.0h |
| 测试、构建和 readback | 0.5h |
| 回归修复缓冲 | 0.5h |

## Stretch Goal

两个承诺能力通过验证后完成了 Stretch：

- [x] 由 FastAPI OpenAPI 确定性生成 TypeScript contracts；
- [x] 增加 `contract:generate` 与 `contract:check`；
- [x] 为迁移路由提供稳定 `operationId` 与 `MutationOutcome` 响应模型；
- [x] 碎片页面改用命名 Web Client，不再在页面内拼 API 路径。

## 明确延期到独立 Goal

- 统一 `story-teller` 多领域 CLI；
- `story-fragment` 兼容转发器；
- Hub `client-lease-v1` 与 60 秒空闲退出；
- 拆分大型 `ContentService`；
- 删除全部手写 TypeScript API DTO。

其中“统一 `story-teller` 多领域 CLI”后来作为独立 Goal 实施完成：先落地人物/关系、剧情、设定/组织成员和 RAG，随后补齐全局搜索、逐字段 Git 合并与时间线。此完成状态不回算为原五小时时间盒的产出；`story-fragment` 兼容转发器和 Hub Client Lease 仍保持延期。

## 数据保护基线

Goal 开始时已有用户改动，必须原样保留：

```text
content/fuchouji/story.db
  sha256 374e99c660d055496033ad7acf9b5406488e7364c76367d59f1473c6ff34fb37

content/fuchouji/content-index 2.json
  sha256 680911afdf622b89d16c7b19968de08a0b2b0b4d7beb105865f8af34ced275e1
```

## 最终记录

### 实际完成

- 新增 `contracts` 边界：通用 mutation/undo、碎片、人物、剧情、设定、关系、结构命令和 `MutationOutcome`；`api.models` 继续重导出旧名称。
- 新增 `StoryApplication`、`ProjectProvider`、`MutationExecutor`，以及碎片、人物、剧情、设定、关系、结构、实体生命周期和历史用例。
- 碎片 create、update、clipboard import、promote，以及通用 delete、restore、undo 路由已经变成薄 FastAPI adapter，不再在对应 route 中实例化领域服务或 `UnitOfWork`。
- 人物、剧情、设定、关系、篇章、阅读顺序、故事结构、时间线和图谱的写路由也已迁移为薄 Application adapter。
- `story-fragment` 继续通过原 HTTP 协议工作，没有修改参数解析、JSON 输出或退出码映射。
- Application 测试直接调用七个用例，并从临时 `story.db` 和生成导出 readback；另有导出失败后“数据库已提交 + warning”的回归测试。
- 新增确定性 OpenAPI TypeScript 生成器、漂移检查和生成契约；碎片 React 页面通过 `fragmentMutationClient` 复用这些类型。
- 开启并完成剧情线逐章转正规划，恢复篇章/阅读顺序事务编辑器，并修复保存快捷键、人物档案无障碍契约、恢复中心布局和画布重叠点击回归。
- 后续独立 CLI Goal 新增统一 `story-teller` 启动器，以及人物/关系、剧情、设定/组织、搜索、Git 合并、时间线和 RAG 命令域；时间线移动与 Web 一样同步故事位置和章号，合并命令在普通写入门禁锁定时仍可逐字段完成最终确认。

### 验证结果

```text
npm run schema:check
  PASS · 世界领域注册表与 SQLite Schema 一致

npm run test:unit
  PASS · 142 tests

npm run test:frontend
  PASS · 32 files / 120 tests

npm run build
  PASS · TypeScript + Vite production build

npm run contract:check
  PASS · OpenAPI TypeScript 契约无漂移

npm run test:e2e:v3
  PASS · 29 tests

npm run test:e2e:merge
  PASS · 1 test
```

完整 E2E 最初暴露的 8 项回归已经逐项修复；随后又用完整顺序发现并修复画布重叠节点的点击层级问题。最终 29/29 通过，不再保留已失效的失败清单。

### 真实内容保护

完成时重新计算的 hash 与开始时完全一致：

```text
content/fuchouji/story.db
  sha256 374e99c660d055496033ad7acf9b5406488e7364c76367d59f1473c6ff34fb37

content/fuchouji/content-index 2.json
  sha256 680911afdf622b89d16c7b19968de08a0b2b0b4d7beb105865f8af34ced275e1
```

这两个文件是 Goal 开始前已有的用户改动，本次没有新增修改。

### 未完成项与下一 Goal 起点

- maintenance、Markdown import 和 merge finalize 等管理型写流程仍通过集中后的 `MutationExecutor.finish()` 兼容路径；它们可在下一次 Application 切片中迁移。
- `story-fragment` 兼容转发器仍应作为独立可验收切片实现；统一多领域 CLI 已完成，不再是未完成项。
- Hub Client Lease 涉及独立 `story_teller_hub` 仓库和进程所有权/空闲退出测试，继续单列 Goal。
- `ContentService` 拆分和全量 TypeScript DTO 替换继续按“明确延期”处理；当前只迁移了碎片 Web Client，手写展示模型仍保留。

本次 5 小时估算结论维持为：可靠完成 **2 个代码能力 + 2 份文档**。没有用 stretch 数量替代核心迁移质量，也没有把目标外的失败包装成完成。
