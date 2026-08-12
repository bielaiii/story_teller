from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Annotated, Any

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


class WorkspaceOptionMCPServer(MCPServer):
    """Expose live workspace choices in every routed tool's JSON Schema."""

    def __init__(self, registry: HubRegistry, **kwargs: Any):
        self._workspace_registry = registry
        super().__init__(**kwargs)

    async def list_tools(self):
        tools = await super().list_tools()
        records = self._workspace_registry.records()
        if not records:
            return tools

        name_counts = Counter(record.display_name for record in records)
        options = [
            {
                "value": (
                    record.display_name
                    if name_counts[record.display_name] == 1
                    else record.workspace_id
                ),
                "label": record.display_name,
                "project": record.project,
            }
            for record in records
        ]
        values = [option["value"] for option in options]
        description = (
            "从当前 Hub 提供的工作区选项中选择；无法根据任务判断时先调用 "
            "list_world_workspaces。只有一个工作区时可省略。"
        )
        rendered = []
        for tool in tools:
            schema = deepcopy(tool.input_schema)
            workspace = schema.get("properties", {}).get("workspace")
            if not isinstance(workspace, dict):
                rendered.append(tool)
                continue
            workspace.pop("default", None)
            workspace["title"] = "工作区"
            workspace["description"] = description
            workspace["enum"] = values
            workspace["x-workspace-options"] = options
            if len(records) > 1:
                required = list(schema.get("required", []))
                if "workspace" not in required:
                    required.append("workspace")
                schema["required"] = required
            rendered.append(tool.model_copy(update={"input_schema": schema}))
        return rendered


def create_hub_mcp_server(registry: HubRegistry, workers: WorkerPool) -> MCPServer:
    server = WorkspaceOptionMCPServer(
        registry=registry,
        name="story-world-hub",
        title="Story World Hub",
        description="通过一个本机端口只读访问多个 Git 小说仓库的世界资料。",
        instructions=(
            "需要 workspace 的工具会直接提供当前可用选项。根据用户正在讨论的小说选择；无法判断时"
            "调用 list_world_workspaces 或询问用户。只有一个工作区时 workspace 可省略。禁止根据相似"
            "名称猜测。精确事实优先使用结构化工具，"
            "模糊探索再使用 search_world 或 build_world_context。碎片默认属于确定内容。"
        ),
    )

    def select(workspace: str):
        return registry.resolve(workspace)

    async def forward(workspace: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        record = select(workspace)
        result = await workers.call(record, tool, arguments)
        result.setdefault("workspaceId", record.workspace_id)
        result.setdefault("workspaceName", record.display_name)
        return result

    @server.tool(title="列出世界工作区", structured_output=True)
    async def list_world_workspaces() -> dict[str, Any]:
        """列出 Hub 当前注册的 Git 小说仓库以及 worker 连接状态。"""
        records = registry.records()
        return {
            "workspaces": [
                {**record.public_dict(), "connected": workers.connected(record.workspace_id)}
                for record in records
            ],
            "requiresWorkspaceSelection": len(records) != 1,
        }

    @server.tool(title="说明世界数据模型", structured_output=True)
    async def describe_world(workspace: WORKSPACE_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, "describe_world")

    @server.tool(title="查看世界目录", structured_output=True)
    async def world_catalog(workspace: WORKSPACE_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, "world_catalog")

    @server.tool(title="解析世界实体", structured_output=True)
    async def resolve_world_entity(
        query: Annotated[str, Field(description="姓名、别名、稳定 ID 或标题")],
        workspace: WORKSPACE_SELECTOR = "",
        entity_types: list[str] | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        return await forward(workspace, "resolve_world_entity", {
            "query": query, "entity_types": entity_types, "limit": limit,
        })

    @server.tool(title="结构化查询世界资料", structured_output=True)
    async def query_world(
        workspace: WORKSPACE_SELECTOR = "",
        entity_types: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        return await forward(workspace, "query_world", {
            "entity_types": entity_types, "filters": filters, "limit": limit,
        })

    @server.tool(title="检索世界设定", structured_output=True)
    async def search_world(
        query: Annotated[str, Field(description="自然语言问题或关键词")],
        workspace: WORKSPACE_SELECTOR = "",
        entity_types: list[str] | None = None,
        include_fragments: bool = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 8,
    ) -> dict[str, Any]:
        return await forward(workspace, "search_world", {
            "query": query, "entity_types": entity_types,
            "include_fragments": include_fragments, "limit": limit,
        })

    @server.tool(title="读取一项完整资料", structured_output=True)
    async def get_world_entity(
        entity_id: str,
        workspace: WORKSPACE_SELECTOR = "",
    ) -> dict[str, Any]:
        return await forward(workspace, "get_world_entity", {"entity_id": entity_id})

    @server.tool(title="读取关联资料", structured_output=True)
    async def get_related_world(
        entity_id: str,
        workspace: WORKSPACE_SELECTOR = "",
    ) -> dict[str, Any]:
        return await forward(workspace, "get_related_world", {"entity_id": entity_id})

    @server.tool(title="组装 AI 上下文", structured_output=True)
    async def build_world_context(
        question: str,
        workspace: WORKSPACE_SELECTOR = "",
        include_fragments: bool = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
        max_chars: Annotated[int, Field(ge=1000, le=50000)] = 12000,
    ) -> dict[str, Any]:
        return await forward(workspace, "build_world_context", {
            "question": question, "include_fragments": include_fragments,
            "limit": limit, "max_chars": max_chars,
        })

    @server.tool(title="查看项目 RAG 状态", structured_output=True)
    async def rag_status(workspace: WORKSPACE_SELECTOR = "") -> dict[str, Any]:
        return await forward(workspace, "rag_status")

    return server
