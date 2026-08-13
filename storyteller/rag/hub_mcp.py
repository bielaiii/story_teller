from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Annotated, Any, Callable

from mcp.server import MCPServer
from pydantic import Field

from storyteller.rag.hub_registry import HubRegistry
from storyteller.rag.hub_workers import WorkerPool


WORKSPACE_SELECTOR = Annotated[
    str,
    Field(
        description=(
            "工作区短名称（displayName，例如 fuchounvshen）；"
            "仅名称重名时使用 workspaceId；只有一个工作区时可省略"
        )
    ),
]

PROJECT_SELECTOR = Annotated[
    str,
    Field(
        description=(
            "content 下的项目目录名；省略时优先选择与 workspace 同名的项目，"
            "否则单项目自动选中"
        )
    ),
]


class WorkspaceOptionMCPServer(MCPServer):
    """Expose live workspace choices in every routed tool's JSON Schema."""

    def __init__(
        self,
        registry: HubRegistry,
        records_provider: Callable[[], list] | None = None,
        projects_provider: Callable[[Any], list[str]] | None = None,
        default_project_provider: Callable[[Any], str] | None = None,
        **kwargs: Any,
    ):
        self._workspace_registry = registry
        self._records_provider = records_provider or registry.records
        self._projects_provider = projects_provider or registry.projects
        self._default_project_provider = default_project_provider or registry.default_project
        super().__init__(**kwargs)

    async def list_tools(self):
        tools = await super().list_tools()
        records = self._records_provider()
        if not records:
            return tools

        name_counts = Counter(record.display_name for record in records)
        workspace_options = [
            {
                "value": (
                    record.display_name
                    if name_counts[record.display_name] == 1
                    else record.workspace_id
                ),
                "label": record.display_name,
                "projects": self._projects_provider(record),
            }
            for record in records
        ]
        workspace_values = [option["value"] for option in workspace_options]
        project_options = [
            {
                "value": project,
                "label": project,
                "workspace": workspace_option["value"],
            }
            for record, workspace_option in zip(records, workspace_options)
            for project in self._projects_provider(record)
        ]
        project_values = sorted({option["value"] for option in project_options})
        workspace_description = (
            "从当前 Hub 提供的工作区选项中选择；无法根据任务判断时先调用 "
            "list_world_workspaces。只有一个工作区时可省略。"
        )
        project_description = (
            "选择 workspace 的 content 子项目。可省略：优先匹配与 workspace 同名的项目，"
            "否则单项目自动选中；多项目且无同名项时调用 list_world_projects 或选择枚举值。"
        )
        rendered = []
        for tool in tools:
            schema = deepcopy(tool.input_schema)
            workspace = schema.get("properties", {}).get("workspace")
            if isinstance(workspace, dict):
                workspace.pop("default", None)
                workspace["title"] = "工作区"
                workspace["description"] = workspace_description
                workspace["enum"] = workspace_values
                workspace["x-workspace-options"] = workspace_options
            if isinstance(workspace, dict) and len(records) > 1:
                required = list(schema.get("required", []))
                if "workspace" not in required:
                    required.append("workspace")
                schema["required"] = required
            project = schema.get("properties", {}).get("project")
            if isinstance(project, dict):
                project.pop("default", None)
                project["title"] = "项目"
                project["description"] = project_description
                project["enum"] = project_values
                project["x-project-options"] = project_options
                conditions = list(schema.get("allOf", []))
                for record, workspace_option in zip(records, workspace_options):
                    projects = self._projects_provider(record)
                    rule: dict[str, Any] = {
                        "if": {
                            "properties": {"workspace": {"const": workspace_option["value"]}},
                            "required": ["workspace"],
                        },
                        "then": {"properties": {"project": {"enum": projects}}},
                    }
                    if not self._default_project_provider(record) and len(projects) > 1:
                        rule["then"]["required"] = ["project"]
                    conditions.append(rule)
                schema["allOf"] = conditions
                if len(records) == 1:
                    only_projects = self._projects_provider(records[0])
                    if (
                        not self._default_project_provider(records[0])
                        and len(only_projects) > 1
                    ):
                        required = list(schema.get("required", []))
                        if "project" not in required:
                            required.append("project")
                        schema["required"] = required
            rendered.append(tool.model_copy(update={"input_schema": schema}))
        return rendered


def create_hub_mcp_server(
    registry: HubRegistry,
    workers: WorkerPool,
    records_provider: Callable[[], list] | None = None,
    projects_provider: Callable[[Any], list[str]] | None = None,
    default_project_provider: Callable[[Any], str] | None = None,
    resolve_project_provider: Callable[[Any, str], str] | None = None,
) -> MCPServer:
    active_records = records_provider or registry.records
    projects_for = projects_provider or registry.projects
    default_for = default_project_provider or registry.default_project
    resolve_for = resolve_project_provider or registry.resolve_project
    server = WorkspaceOptionMCPServer(
        registry=registry,
        records_provider=active_records,
        projects_provider=projects_for,
        default_project_provider=default_for,
        name="story-world-hub",
        title="Story World Hub",
        description="通过一个本机端口只读访问多个 Git 小说仓库的世界资料。",
        instructions=(
            "需要 workspace 的工具会直接提供当前可用选项。根据用户正在讨论的小说选择；无法判断时"
            "调用 list_world_workspaces 或询问用户。project 选择该仓库 content 下的项目，可省略："
            "优先匹配与 workspace 同名的项目，否则单项目自动选中；仍不明确时调用 list_world_projects。"
            "禁止根据相似名称猜测。精确事实优先使用结构化工具，"
            "模糊探索再使用 search_world 或 build_world_context。碎片默认属于确定内容。"
        ),
    )

    def select(workspace: str):
        records = active_records()
        clean = str(workspace or "").strip()
        if not clean:
            if len(records) == 1:
                return records[0]
            choices = ", ".join(record.display_name for record in records)
            raise ValueError(f"请指定 workspace；当前可用：{choices or '无'}")
        exact = [
            record for record in records
            if clean in {record.workspace_id, record.display_name, record.project}
        ]
        if len(exact) == 1:
            return exact[0]
        if not exact:
            raise ValueError(f"工作区未运行：{clean}")
        raise ValueError(f"工作区名称不唯一，请使用 workspaceId：{clean}")

    async def forward(
        workspace: str,
        project: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = select(workspace)
        selected_project = resolve_for(record, project)
        forwarded = dict(arguments or {})
        forwarded["project"] = selected_project
        result = await workers.call(record, tool, forwarded)
        result.setdefault("workspaceId", record.workspace_id)
        result.setdefault("workspaceName", record.display_name)
        result.setdefault("project", selected_project)
        return result

    @server.tool(title="列出世界工作区", structured_output=True)
    async def list_world_workspaces() -> dict[str, Any]:
        """列出 Hub 当前注册的 Git 小说仓库以及 worker 连接状态。"""
        records = active_records()
        return {
            "workspaces": [
                {
                    **registry.public_dict(record),
                    "projects": projects_for(record),
                    "defaultProject": default_for(record),
                    "connected": workers.connected(record.workspace_id),
                }
                for record in records
            ],
            "requiresWorkspaceSelection": len(records) != 1,
        }

    @server.tool(title="列出工作区项目", structured_output=True)
    async def list_world_projects(workspace: WORKSPACE_SELECTOR = "") -> dict[str, Any]:
        """列出所选 Git 仓库 content 下当前可用的 story.db 项目。"""
        record = select(workspace)
        projects = projects_for(record)
        default = default_for(record)
        return {
            "workspaceId": record.workspace_id,
            "workspaceName": record.display_name,
            "projects": projects,
            "defaultProject": default,
            "requiresProjectSelection": not bool(default) and len(projects) > 1,
        }

    @server.tool(title="说明世界数据模型", structured_output=True)
    async def describe_world(workspace: WORKSPACE_SELECTOR = "", project: PROJECT_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, project, "describe_world")

    @server.tool(title="查看世界目录", structured_output=True)
    async def world_catalog(workspace: WORKSPACE_SELECTOR = "", project: PROJECT_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, project, "world_catalog")

    @server.tool(title="解析世界实体", structured_output=True)
    async def resolve_world_entity(
        query: Annotated[str, Field(description="姓名、别名、稳定 ID 或标题")],
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
        entity_types: list[str] | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        return await forward(workspace, project, "resolve_world_entity", {
            "query": query, "entity_types": entity_types, "limit": limit,
        })

    @server.tool(title="结构化查询世界资料", structured_output=True)
    async def query_world(
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
        entity_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        return await forward(workspace, project, "query_world", {
            "entity_types": entity_types, "filters": filters, "limit": limit,
        })

    @server.tool(title="检索世界设定", structured_output=True)
    async def search_world(
        query: Annotated[str, Field(description="自然语言问题或关键词")],
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
        entity_types: list[str] | None = None,
        include_fragments: bool = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 8,
    ) -> dict[str, Any]:
        return await forward(workspace, project, "search_world", {
            "query": query, "entity_types": entity_types,
            "include_fragments": include_fragments, "limit": limit,
        })

    @server.tool(title="读取一项完整资料", structured_output=True)
    async def get_world_entity(
        entity_id: str,
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
    ) -> dict[str, Any]:
        return await forward(workspace, project, "get_world_entity", {"entity_id": entity_id})

    @server.tool(title="读取关联资料", structured_output=True)
    async def get_related_world(
        entity_id: str,
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
    ) -> dict[str, Any]:
        return await forward(workspace, project, "get_related_world", {"entity_id": entity_id})

    @server.tool(title="组装 AI 上下文", structured_output=True)
    async def build_world_context(
        question: str,
        workspace: WORKSPACE_SELECTOR = "",
        project: PROJECT_SELECTOR = "",
        include_fragments: bool = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
        max_chars: Annotated[int, Field(ge=1000, le=50000)] = 12000,
    ) -> dict[str, Any]:
        return await forward(workspace, project, "build_world_context", {
            "question": question, "include_fragments": include_fragments,
            "limit": limit, "max_chars": max_chars,
        })

    @server.tool(title="查看项目 RAG 状态", structured_output=True)
    async def rag_status(workspace: WORKSPACE_SELECTOR = "", project: PROJECT_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, project, "rag_status")

    return server
