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
            "先调用 world_catalog 了解可用内容。回答事实问题时优先使用 search_world、"
            "get_world_entity 和 get_related_world；引用返回的 stableId/entityId。"
            "碎片默认不是正史，除非用户明确要求，否则不要设置 include_fragments=true。"
        ),
    )

    def project_id(project: str) -> str:
        value = str(project or settings.default_project).strip()
        if not value:
            raise ValueError("请指定 project")
        settings.project_root(value)
        return value

    @server.tool(title="查看世界目录", structured_output=True)
    def world_catalog(project: str = "") -> dict[str, Any]:
        """列出可检索的内容类型、数量和稳定 ID；不返回全文。"""
        return manager.catalog(project_id(project))

    @server.tool(title="检索世界设定", structured_output=True)
    def search_world(
        query: Annotated[str, Field(description="自然语言问题或关键词")],
        project: str = "",
        entity_types: Annotated[list[str] | None, Field(description="可选：character、entry、plot、relationship、fragment、chapter")] = None,
        include_fragments: Annotated[bool, Field(description="是否把默认非正史的灵感碎片加入结果")] = False,
        limit: Annotated[int, Field(ge=1, le=30)] = 8,
    ) -> dict[str, Any]:
        """混合稳定名称、全文和 embedding 检索，返回可引用的世界资料片段。"""
        return manager.search(
            project_id(project), query, limit=limit,
            kinds=entity_types, include_fragments=include_fragments,
        )

    @server.tool(title="读取一项完整资料", structured_output=True)
    def get_world_entity(
        entity_id: Annotated[str, Field(description="search_world 或 world_catalog 返回的 entityId")],
        project: str = "",
    ) -> dict[str, Any]:
        """按稳定 entityId 读取完整 Markdown 资料和一跳关联。"""
        result = manager.entity(project_id(project), entity_id)
        if not result:
            raise ValueError(f"内容不存在：{entity_id}")
        return result

    @server.tool(title="读取关联资料", structured_output=True)
    def get_related_world(
        entity_id: Annotated[str, Field(description="人物、组织、剧情或其他内容的 entityId")],
        project: str = "",
    ) -> dict[str, Any]:
        """返回某项资料的一跳关系、组织归属、成员、剧情出场和正文引用。"""
        result = manager.entity(project_id(project), entity_id)
        if not result:
            raise ValueError(f"内容不存在：{entity_id}")
        return {
            "entityId": result["entityId"], "title": result["title"],
            "kind": result["kind"], "related": result["related"],
            "citation": result["citation"],
        }

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
        return manager.catalog(project_id(project))

    @server.resource("story://{project}/entity/{entity_id}", title="世界资料", mime_type="text/markdown")
    def entity_resource(project: str, entity_id: str) -> str:
        result = manager.entity(project_id(project), entity_id)
        if not result:
            raise ValueError(f"内容不存在：{entity_id}")
        return result["content"]

    return server
