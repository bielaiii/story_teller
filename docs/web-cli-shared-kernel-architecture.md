# Story Teller Web / CLI 共享内核架构

状态：共享 Mutation Pipeline、主要内容/结构用例与首个生成式 Web Client 已落地
最后更新：2026-08-29

## 1. 目标

Story Teller 的业务能力只实现一次。React Web、CLI、MCP 和后台任务是不同入口，不得各自维护数据库事务、业务校验、导出和 RAG 同步逻辑。

```text
React Web ─┐
CLI ───────┼─ HTTP → FastAPI Adapter → Application → Domain / SQLite
MCP 只读 ──┘                            ├─ mutation delta
                                       ├─ Markdown / JSON export
                                       └─ RAG sync
```

固定依赖方向为：

```text
Web / CLI → HTTP API → Application → Domain / Storage
```

- Domain 不导入 FastAPI、argparse、React 或 HTTP 类型。
- Application 不读取请求头、命令行参数，也不打印终端文本。
- Web 和 CLI 不直接操作 SQLite、`ExportCoordinator` 或 `RagManager`。
- FastAPI 路由不直接编排 `ContentService`、`StructureService`、`EntityService` 或 `UnitOfWork`。

Web 表单和 CLI 参数仍然分别实现，因为它们是不同交互；校验、事务、冲突、撤销、导出、RAG 和响应语义只保留一份。

## 2. 模块设计

```text
storyteller/
├── contracts/
│   ├── common.py
│   ├── fragments.py
│   ├── content.py
│   ├── structures.py
│   └── responses.py
├── application/
│   ├── container.py
│   ├── context.py
│   ├── errors.py
│   ├── projects.py
│   ├── mutations.py
│   ├── fragments.py
│   ├── characters.py
│   ├── plots.py
│   ├── entries.py
│   ├── relationships.py
│   ├── structures.py
│   ├── entities.py
│   └── history.py
├── domain/
├── storage/
├── api/
└── cli/
```

### Contracts

`contracts` 是 Application 和传输适配器共用的边界类型。碎片、人物、剧情、设定、关系、结构和通用 mutation/undo 命令已经移入该层，并由 `api.models` 重导出以维持旧导入兼容。响应由 `MutationOutcome` 统一描述：

```python
class MutationOutcome(BaseModel):
    ok: bool
    fromRevision: int
    projectRevision: int
    changed: dict[str, list[dict]]
    removed: dict[str, list[str]]
    structures: dict[str, object]
    operation: OperationResult
    export: ExportResult
    rag: RagResult | None
    warnings: list[str]
```

### Application Context

```python
@dataclass(frozen=True, slots=True)
class ApplicationContext:
    project_id: str
    source: Literal["web", "cli", "system"]
```

`baseRevision` 和 `entityRevision` 属于具体命令，不能隐藏在 Context 中。

### MutationExecutor

所有写操作必须经过统一执行器：

```text
解析 Project
  → 检查数据库版本与可写状态
  → 检查开放的 Git 合并会话
  → 执行领域事务
  → 读取 mutation delta
  → 调度 RAG
  → 生成确定性导出
  → 返回 MutationOutcome
```

数据库提交成功后，即使导出失败也不得伪装为数据库失败。保持现有行为：返回成功 delta、`export.status=failed` 和 warning，后续可重新导出。

### Application Facade

入口依赖一个长期稳定的门面：

```python
class StoryApplication:
    fragments: FragmentUseCases
    characters: CharacterUseCases
    plots: PlotUseCases
    entries: EntryUseCases
    relationships: RelationshipUseCases
    structures: StructureUseCases
    entities: EntityUseCases
    history: HistoryUseCases
    queries: ProjectQueries
```

当前已建立上述 Facade，并完成碎片、人物、剧情、设定、关系、结构、实体生命周期和历史用例。maintenance、Markdown import 与 merge finalize 仍使用集中执行器的兼容入口，后续按管理型垂直切片迁移。

## 3. FastAPI 适配器

路由只负责本地 mutation token、HTTP 参数和结果序列化：

```python
@router.post("/projects/{project}/fragments")
def create_fragment(project: str, command: FragmentCreate):
    return application.fragments.create(
        ApplicationContext(project, source="web"),
        command,
    )
```

数据库解析、合并门禁、领域服务、delta、导出和 RAG 不得留在路由函数中。现有 `/api/v1` URL、请求字段、状态码和响应字段保持兼容。

不增加通用 `/commands/{name}`：业务接口继续使用有语义的 REST 路径，避免丢失类型、权限和可发现性。

## 4. Web 适配器

FastAPI OpenAPI 已作为跨语言契约源：

```text
Pydantic Contracts → FastAPI OpenAPI → generated TypeScript DTO
```

仓库内的确定性生成器输出 `frontend/src/api/generated/openapi.ts`，`contract:check` 在生成结果漂移时失败。碎片页面已使用 `fragmentMutationClient.create/update/importClipboard/promote/remove`，不再在页面里拼 URL 和 HTTP 方法；其余页面后续按领域迁移。TanStack Query 层继续统一处理：

- mutation token 刷新；
- base/entity revision；
- 409 安全重试；
- delta 原位应用；
- 服务重启恢复。

静态部署继续读取生成快照并保持只读，不创建写入 Application。

## 5. CLI 适配器

CLI 始终通过本地 HTTP API 写入，不直接打开 SQLite。这样 CLI 天然复用 Web 的：

- 事务和 revision 冲突；
- 合并门禁；
- 软删除、恢复与撤销；
- Markdown/JSON 导出；
- RAG 后台同步。

长期公开入口统一为 `story-teller <domain> <command>`，`story-fragment` 保留兼容转发。普通输出面向用户，`--json` 的 stdout 始终只有一个 JSON 文档；诊断写 stderr，现有退出码保持兼容。

CLI 自动启动属于后续独立切片：由 Hub 提供不改变 managed/attached/MCP 状态的 Client Lease。CLI 执行期间续租，结束后停止心跳，Content Worker 空闲 60 秒退出。

## 6. 现有代码迁移映射

- `app.py::database_for` 移到 Application 的 Project Provider。
- mutation token 仍是 FastAPI dependency。
- 合并门禁移到 `MutationExecutor`。
- `app.py::finish_mutation` 被 `MutationExecutor.execute` 替代。
- 碎片 create/update/import/promote 调用 `FragmentUseCases`；人物、剧情、设定、关系和结构写入调用各自 Use Case；delete/restore 调用 `EntityUseCases`；undo 调用 `HistoryUseCases`。
- `fragment_cli.ApiClient` 暂时保持 HTTP 协议不变；统一 CLI 切片再迁移。
- 大型 `ContentService` 第一阶段不拆，等 Application API 稳定后再按人物、剧情、设定、碎片和关系拆分。

## 7. 新功能开发规则

以后增加一个同时面向 Web 和 CLI 的业务能力，固定流程为：

1. 定义 Contract。
2. 在 Domain 实现业务规则。
3. 在 Application 实现完整用例和副作用编排。
4. 增加薄 FastAPI Route。
5. Web 增加交互，CLI 增加参数与输出。
6. 在 Application 层验证业务一次，在两个适配器层只验证协议与交互。

第 5 步天然不同，不能强行共享；第 1～4 步必须只有一份。

## 8. 验收原则

- Application 直接调用与 HTTP 调用产生相同持久化结果。
- 每次成功写入都从临时数据库 readback，并验证导出。
- Web 与 `story-fragment` 的公开协议保持兼容。
- 导出失败、RAG 不可用、token 过期、409、merge gate 都有回归测试。
- Domain/Application 导入 FastAPI 或 argparse 时，架构测试失败。
- 所有写测试只使用临时 Content，不修改真实小说数据。
