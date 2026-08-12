from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from pydantic import Field

from storyteller.rag.manager import RagManager
from storyteller.settings import Settings


def create_mcp_server(manager: RagManager, settings: Settings) -> MCPServer:
    server = MCPServer(
        name="story-teller-world",
        title="Story Teller 世界设定",
        description="只读检索 Story Teller 中的人物、组织、关系、剧情、设定与碎片。",
        instructions=(
            "先调用 list_world_projects、describe_world 和 world_catalog 了解可用内容。回答组织、关系、方向性印象、"
            "剧情出场等事实问题时优先使用 resolve_world_entity、query_world、get_world_entity "
            "和 get_related_world；模糊探索再使用 search_world。引用返回的 stableId/entityId。"
            "碎片是已确定但尚未编入时间线的剧情，默认参与搜索。"
        ),
    )

    def project_id(project: str) -> str:
        value = str(project or settings.default_project).strip()
        if not value:
            available = manager.projects()
            raise ValueError(f"当前工作区包含多个项目，请指定 project：{', '.join(available)}")
        settings.project_root(value)
        return value

    @server.tool(title="列出当前工作区项目", structured_output=True)
    def list_world_projects() -> dict[str, Any]:
        """列出自动发现的 story.db 项目；多项目工作区应先调用本工具。"""
        projects = manager.projects()
        return {
            "projects": projects,
            "defaultProject": settings.default_project,
            "requiresProjectSelection": not settings.default_project and len(projects) > 1,
        }

    @server.tool(title="说明世界数据模型", structured_output=True)
    def describe_world(project: str = "") -> dict[str, Any]:
        """返回实体类型、字段业务含义、确定性、时间线状态和当前 SQLite revision。"""
        return manager.world_schema(project_id(project))

    @server.tool(title="查看世界目录", structured_output=True)
    def world_catalog(project: str = "") -> dict[str, Any]:
        """直接从 story.db 列出内容类型、数量、稳定 ID、确定性和时间线状态。"""
        return manager.live_catalog(project_id(project))

    @server.tool(title="解析世界实体", structured_output=True)
    def resolve_world_entity(
        query: Annotated[str, Field(description="姓名、别名、稳定 ID 或标题")],
        project: str = "",
        entity_types: Annotated[list[str] | None, Field(description="可选实体类型过滤")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """直接从 story.db 将自然名称解析为稳定 entityId；精确事实查询应先使用本工具。"""
        return manager.resolve(project_id(project), query, kinds=entity_types, limit=limit)

    @server.tool(title="结构化查询世界资料", structured_output=True)
    def query_world(
        project: str = "",
        entity_types: Annotated[list[str] | None, Field(description="可选实体类型过滤")] = None,
        filters: Annotated[dict[str, Any] | None, Field(description="字段过滤；字符串使用包含匹配")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """直接查询最新 story.db，适合类型、状态、章节、成员和引用等确定事实。"""
        return manager.query_world(project_id(project), kinds=entity_types, filters=filters, limit=limit)

    @server.tool(title="检索世界设定", structured_output=True)
    def search_world(
        query: Annotated[str, Field(description="自然语言问题或关键词")],
        project: str = "",
        entity_types: Annotated[list[str] | None, Field(description="可选：character、entry、plot、relationship、fragment、chapter")] = None,
        include_fragments: Annotated[bool, Field(description="兼容参数；确定碎片现在默认参与搜索，true 还会包含未来的暂定素材")] = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 8,
    ) -> dict[str, Any]:
        """混合名称、全文、关系边和 embedding 检索；确定碎片默认参与。"""
        return manager.search(
            project_id(project), query, limit=limit,
            kinds=entity_types, include_fragments=include_fragments,
        )

    @server.tool(title="读取一项完整资料", structured_output=True)
    def get_world_entity(
        entity_id: Annotated[str, Field(description="search_world 或 world_catalog 返回的 entityId")],
        project: str = "",
    ) -> dict[str, Any]:
        """按稳定 entityId 直接读取 story.db 的结构化资料和关联。"""
        result = manager.structured_entity(project_id(project), entity_id)
        if not result:
            raise ValueError(f"内容不存在：{entity_id}")
        return result

    @server.tool(title="读取关联资料", structured_output=True)
    def get_related_world(
        entity_id: Annotated[str, Field(description="人物、组织、剧情或其他内容的 entityId")],
        project: str = "",
    ) -> dict[str, Any]:
        """直接从 story.db 返回方向性关系、组织归属、成员和剧情出场。"""
        return manager.live_related(project_id(project), entity_id)

    @server.tool(title="组装 AI 上下文", structured_output=True)
    def build_world_context(
        question: Annotated[str, Field(description="AI 正要回答或创作的问题")],
        project: str = "",
        include_fragments: bool = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
        max_chars: Annotated[int, Field(ge=1000, le=50000)] = 12000,
    ) -> dict[str, Any]:
        """按字符预算组装带来源注释的 Markdown 上下文，可直接交给语言模型。"""
        return manager.context(
            project_id(project), question, limit=limit,
            max_chars=max_chars, include_fragments=include_fragments,
        )

    @server.tool(title="查看 RAG 状态", structured_output=True)
    def rag_status(project: str = "") -> dict[str, Any]:
        """查看索引版本、更新时间、文档数和当前 embedding 模型。"""
        identifier = project_id(project)
        manager.ensure_fresh(identifier)
        return manager.status(identifier)

    @server.resource("story://{project}/catalog", title="世界目录", mime_type="application/json")
    def catalog_resource(project: str) -> dict[str, Any]:
        return manager.live_catalog(project_id(project))

    @server.resource("story://{project}/entity/{entity_id}", title="世界资料", mime_type="text/markdown")
    def entity_resource(project: str, entity_id: str) -> str:
        result = manager.entity(project_id(project), entity_id)
        if not result:
            raise ValueError(f"内容不存在：{entity_id}")
        return result["content"]

    return server
