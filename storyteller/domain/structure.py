from __future__ import annotations

import math
import secrets
import sqlite3
import time
from typing import Any

from storyteller.domain.content import RANK_STEP, clean_color, clean_text, entity_id
from storyteller.domain.errors import DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork
from storyteller.storage.connection import Database


def rank(index: int) -> str:
    return f"{int(index) * RANK_STEP:024d}"


class StructureService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.uow = UnitOfWork(database, project_id)

    def update_chapters(self, base_revision: int, chapters: list[dict[str, Any]]) -> MutationResult:
        if not 1 <= len(chapters) <= 50:
            raise DomainError("篇章数量需要在 1 到 50 之间")
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            existing = {
                str(row["entity_id"]): row
                for row in connection.execute("SELECT * FROM active_chapters")
            }
            for index, identifier in enumerate(existing, start=1):
                connection.execute(
                    "UPDATE chapters SET sort_key=? WHERE entity_id=?",
                    (f"~chapter-{index:04d}", identifier),
                )
            retained: set[str] = set()
            stable_ids: set[str] = set()
            for index, item in enumerate(chapters, start=1):
                identifier = str(item.get("entity_id") or "")
                label = clean_text(item.get("label"), "篇章名称", 80, required=True)
                if identifier:
                    if identifier not in existing:
                        raise DomainError("篇章不存在或已经删除")
                    retained.add(identifier)
                    stable = str(existing[identifier]["stable_id"])
                    connection.execute(
                        "UPDATE chapters SET label=?, sort_key=? WHERE entity_id=?",
                        (label, rank(index), identifier),
                    )
                    connection.execute(
                        "UPDATE entities SET title=?, revision=revision+1, updated_at=? WHERE id=?",
                        (label, now, identifier),
                    )
                else:
                    stable = clean_text(item.get("stable_id"), "篇章 ID", 60, required=True)
                    identifier = entity_id("chapter", stable)
                    if connection.execute("SELECT 1 FROM entities WHERE id=?", (identifier,)).fetchone():
                        raise DomainError(f"篇章 ID 已被使用：{stable}")
                    connection.execute(
                        "INSERT INTO entities(id, project_id, kind, stable_id, title, created_at, updated_at) VALUES(?, ?, 'chapter', ?, ?, ?, ?)",
                        (identifier, self.project_id, stable, label, now, now),
                    )
                    connection.execute(
                        "INSERT INTO chapters(entity_id, label, sort_key) VALUES(?, ?, ?)",
                        (identifier, label, rank(index)),
                    )
                    retained.add(identifier)
                if stable in stable_ids:
                    raise DomainError(f"篇章 ID 重复：{stable}")
                stable_ids.add(stable)
            for identifier in set(existing) - retained:
                plot_count = int(connection.execute(
                    "SELECT COUNT(*) FROM active_plots WHERE chapter_id=?", (identifier,)
                ).fetchone()[0])
                if plot_count:
                    raise DomainError("要删除的篇章中仍有剧情，请先移动剧情")
                connection.execute(
                    "UPDATE chapters SET sort_key=? WHERE entity_id=?",
                    (f"~trash-{existing[identifier]['sort_key']}-{now}-{identifier}", identifier),
                )
                connection.execute(
                    "UPDATE entities SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=? WHERE id=?",
                    (now, now + 7 * 24 * 60 * 60, now, identifier),
                )
            return {"chapterIds": list(retained)}

        return self.uow.mutate(
            base_revision=base_revision, label="调整篇章", action="update",
            entity_kind="chapter", callback=mutation,
        )

    def reorder_plots(self, base_revision: int, plot_ids: list[str]) -> MutationResult:
        if len(plot_ids) != len(set(plot_ids)):
            raise DomainError("剧情阅读顺序中存在重复项")

        def mutation(connection: sqlite3.Connection):
            active = [str(row[0]) for row in connection.execute("SELECT entity_id FROM active_plots ORDER BY sort_key")]
            if set(active) != set(plot_ids):
                raise DomainError("请提交全部活动剧情的完整阅读顺序")
            now = int(time.time())
            for index, identifier in enumerate(active, start=1):
                connection.execute(
                    "UPDATE plots SET sort_key=? WHERE entity_id=?",
                    (f"~plot-{index:06d}", identifier),
                )
            for index, identifier in enumerate(plot_ids, start=1):
                connection.execute("UPDATE plots SET sort_key=? WHERE entity_id=?", (rank(index), identifier))
                connection.execute("UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?", (now, identifier))

        return self.uow.mutate(
            base_revision=base_revision, label="调整剧情阅读顺序", action="reorder",
            entity_kind="plot", callback=mutation,
        )

    def update_story_structure(
        self,
        base_revision: int,
        chapters: list[dict[str, Any]],
        plots: list[dict[str, Any]],
    ) -> MutationResult:
        """Atomically update chapter lifecycle, plot assignments, and reading order."""
        if not 1 <= len(chapters) <= 50:
            raise DomainError("篇章数量需要在 1 到 50 之间")
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            existing_chapters = {
                str(row["entity_id"]): row
                for row in connection.execute("SELECT * FROM active_chapters")
            }
            for index, identifier in enumerate(existing_chapters, start=1):
                connection.execute(
                    "UPDATE chapters SET sort_key=? WHERE entity_id=?",
                    (f"~chapter-{index:04d}", identifier),
                )
            retained: list[str] = []
            stable_ids: set[str] = set()
            for index, item in enumerate(chapters, start=1):
                identifier = str(item.get("entity_id") or "")
                stable = str(item.get("stable_id") or "").strip()
                label = clean_text(item.get("label"), "篇章名称", 80, required=True)
                if identifier:
                    if identifier not in existing_chapters:
                        raise DomainError("篇章不存在或已经删除")
                    stable = str(existing_chapters[identifier]["stable_id"])
                    row = existing_chapters[identifier]
                    next_rank = rank(index)
                    changed = str(row["label"]) != label or str(row["sort_key"]) != next_rank
                    connection.execute(
                        "UPDATE chapters SET label=?, sort_key=? WHERE entity_id=?",
                        (label, next_rank, identifier),
                    )
                    if changed:
                        connection.execute(
                            "UPDATE entities SET title=?, revision=revision+1, updated_at=? WHERE id=?",
                            (label, now, identifier),
                        )
                else:
                    stable = clean_text(stable, "篇章 ID", 60) or f"chapter-{secrets.token_hex(6)}"
                    identifier = entity_id("chapter", stable)
                    if connection.execute("SELECT 1 FROM entities WHERE id=?", (identifier,)).fetchone():
                        raise DomainError(f"篇章 ID 已被使用：{stable}")
                    connection.execute(
                        "INSERT INTO entities(id, project_id, kind, stable_id, title, created_at, updated_at) VALUES(?, ?, 'chapter', ?, ?, ?, ?)",
                        (identifier, self.project_id, stable, label, now, now),
                    )
                    connection.execute(
                        "INSERT INTO chapters(entity_id, label, sort_key) VALUES(?, ?, ?)",
                        (identifier, label, rank(index)),
                    )
                if stable in stable_ids:
                    raise DomainError(f"篇章 ID 重复：{stable}")
                stable_ids.add(stable)
                retained.append(identifier)

            active_plots = {
                str(row["entity_id"]): row
                for row in connection.execute("SELECT * FROM active_plots")
            }
            submitted_ids = [str(item.get("entity_id") or "") for item in plots]
            if len(submitted_ids) != len(set(submitted_ids)) or set(submitted_ids) != set(active_plots):
                raise DomainError("请提交全部活动剧情且不能重复")
            for index, identifier in enumerate(active_plots, start=1):
                connection.execute(
                    "UPDATE plots SET sort_key=? WHERE entity_id=?",
                    (f"~plot-{index:06d}", identifier),
                )
            retained_set = set(retained)
            for index, item in enumerate(plots, start=1):
                identifier = str(item.get("entity_id") or "")
                chapter_id = str(item.get("chapter_id") or "")
                if chapter_id not in retained_set:
                    raise DomainError("剧情引用了不存在或待删除的篇章")
                row = active_plots[identifier]
                next_rank = rank(index)
                changed = str(row["chapter_id"] or "") != chapter_id or str(row["sort_key"]) != next_rank
                connection.execute(
                    "UPDATE plots SET chapter_id=?, sort_key=? WHERE entity_id=?",
                    (chapter_id, next_rank, identifier),
                )
                if changed:
                    connection.execute(
                        "UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?",
                        (now, identifier),
                    )

            for identifier in set(existing_chapters) - retained_set:
                if connection.execute(
                    "SELECT 1 FROM active_plots WHERE chapter_id=?", (identifier,)
                ).fetchone():
                    raise DomainError("要删除的篇章中仍有剧情，请先选择接收篇章")
                connection.execute(
                    "UPDATE chapters SET sort_key=? WHERE entity_id=?",
                    (f"~trash-{existing_chapters[identifier]['sort_key']}-{now}-{identifier}", identifier),
                )
                connection.execute(
                    "UPDATE entities SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=? WHERE id=?",
                    (now, now + 7 * 24 * 60 * 60, now, identifier),
                )
            return {"chapterIds": retained, "plotIds": submitted_ids}

        return self.uow.mutate(
            base_revision=base_revision,
            label="调整篇章与阅读顺序",
            action="reorder",
            entity_kind="story_structure",
            callback=mutation,
        )

    def update_timeline(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        lines = payload.get("lines")
        assignments = payload.get("assignments")
        replacements = payload.get("line_replacements", {})
        if not isinstance(lines, list) or not 1 <= len(lines) <= 30:
            raise DomainError("时间线需要包含 1 到 30 条剧情线")
        if not isinstance(assignments, list) or not isinstance(replacements, dict):
            raise DomainError("时间线节点数据格式不合法")
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            existing = {
                str(row["entity_id"]): row
                for row in connection.execute("SELECT * FROM active_timeline_lines")
            }
            for index, identifier in enumerate(existing, start=1):
                connection.execute(
                    "UPDATE timeline_lines SET sort_key=? WHERE entity_id=?",
                    (f"~line-{index:04d}", identifier),
                )
            retained: list[str] = []
            names: set[str] = set()
            for index, item in enumerate(lines, start=1):
                if not isinstance(item, dict):
                    raise DomainError("剧情线数据格式不合法")
                name = clean_text(item.get("name"), "剧情线名称", 60, required=True)
                if name in names:
                    raise DomainError(f"剧情线名称重复：{name}")
                names.add(name)
                identifier = str(item.get("entity_id") or "")
                if identifier:
                    if identifier not in existing:
                        raise DomainError("剧情线不存在或已经删除")
                    connection.execute(
                        """
                        UPDATE timeline_lines SET color=?, side=?, sort_key=?, start_plot_id=?, end_plot_id=?
                        WHERE entity_id=?
                        """,
                        (
                            clean_color(item.get("color"), "#3f7fc1"), str(item.get("side") or "right"),
                            rank(index), self._plot_target(connection, item.get("start_plot_id")),
                            self._plot_target(connection, item.get("end_plot_id")), identifier,
                        ),
                    )
                    connection.execute(
                        "UPDATE entities SET title=?, revision=revision+1, updated_at=? WHERE id=?",
                        (name, now, identifier),
                    )
                else:
                    stable = str(item.get("stable_id") or f"line-{secrets.token_hex(6)}")
                    identifier = entity_id("timeline_line", stable)
                    if connection.execute("SELECT 1 FROM entities WHERE id=?", (identifier,)).fetchone():
                        raise DomainError("剧情线稳定 ID 已经存在")
                    connection.execute(
                        "INSERT INTO entities(id, project_id, kind, stable_id, title, created_at, updated_at) VALUES(?, ?, 'timeline_line', ?, ?, ?, ?)",
                        (identifier, self.project_id, stable, name, now, now),
                    )
                    connection.execute(
                        """
                        INSERT INTO timeline_lines(entity_id, color, side, sort_key, start_plot_id, end_plot_id)
                        VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            identifier, clean_color(item.get("color"), "#3f7fc1"), str(item.get("side") or "right"),
                            rank(index), self._plot_target(connection, item.get("start_plot_id")),
                            self._plot_target(connection, item.get("end_plot_id")),
                        ),
                    )
                retained.append(identifier)
            main_line_id = str(payload.get("main_line_id") or "")
            if main_line_id not in retained:
                raise DomainError("主线必须对应一条活动剧情线")
            connection.execute("UPDATE timeline_lines SET side='center' WHERE entity_id=?", (main_line_id,))
            connection.execute(
                "UPDATE timeline_lines SET side='right' WHERE entity_id<>? AND side='center'",
                (main_line_id,),
            )

            removed = set(existing) - set(retained)
            for identifier in removed:
                replacement = str(replacements.get(identifier) or "")
                node_rows = list(connection.execute(
                    "SELECT plot_id, story_sort_key FROM plot_timeline_lines WHERE line_id=?",
                    (identifier,),
                ))
                if node_rows and replacement not in retained:
                    raise DomainError("删除仍有节点的剧情线时，必须选择一条接收线")
                for row in node_rows:
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                        (row["plot_id"], replacement, row["story_sort_key"]),
                    )
                connection.execute("DELETE FROM plot_timeline_lines WHERE line_id=?", (identifier,))
                connection.execute(
                    "UPDATE timeline_lines SET sort_key=? WHERE entity_id=?",
                    (f"~trash-{existing[identifier]['sort_key']}-{now}-{identifier}", identifier),
                )
                connection.execute(
                    "UPDATE entities SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=? WHERE id=?",
                    (now, now + 7 * 24 * 60 * 60, now, identifier),
                )

            active_plots = {str(row[0]) for row in connection.execute("SELECT entity_id FROM active_plots")}
            submitted: set[str] = set()
            occupied_story_keys: set[tuple[str, str]] = set()
            connection.execute(
                "DELETE FROM plot_timeline_lines WHERE plot_id IN (SELECT entity_id FROM active_plots)"
            )
            for item in assignments:
                if not isinstance(item, dict):
                    raise DomainError("时间线节点格式不合法")
                plot_id = str(item.get("plot_id") or "")
                if plot_id not in active_plots or plot_id in submitted:
                    raise DomainError("时间线节点重复或引用了不存在的剧情")
                submitted.add(plot_id)
                line_ids = list(dict.fromkeys(str(value) for value in item.get("line_ids", [])))
                if any(value not in retained for value in line_ids):
                    raise DomainError("时间线节点引用了不存在的剧情线")
                story_key = str(item.get("story_sort_key") or "")
                if not story_key.isdigit():
                    story_key = rank(int(item.get("story_order") or len(submitted)))
                for line_id in line_ids:
                    key = (line_id, story_key)
                    if key in occupied_story_keys:
                        raise DomainError("同一剧情线中不能有两个相同故事位置的节点")
                    occupied_story_keys.add(key)
                    connection.execute(
                        "INSERT INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                        (plot_id, line_id, story_key),
                    )
            if submitted != active_plots:
                raise DomainError("请提交全部活动剧情的时间线归属")
            connection.execute(
                """
                UPDATE timeline_settings SET main_line_id=?, line_spacing=?, top_padding=?,
                    side_padding=?, pixels_per_story_unit=? WHERE project_id=?
                """,
                (
                    main_line_id, self._bounded(payload.get("line_spacing"), 72, 48, 180),
                    self._bounded(payload.get("top_padding"), 64, 24, 180),
                    self._bounded(payload.get("side_padding"), 36, 16, 120),
                    self._bounded(payload.get("pixels_per_story_unit"), 760, 560, 1600), self.project_id,
                ),
            )

        return self.uow.mutate(
            base_revision=base_revision, label="编辑时间线", action="update",
            entity_kind="timeline_line", callback=mutation,
        )

    def update_graph(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            numeric = {
                "node_spacing": (40, 500), "initial_jitter": (0, 300),
                "relationship_distance": (40, 1000), "leaf_distance_extra": (0, 500),
                "center_strength": (0, 5), "group_strength": (0, 5), "leaf_strength": (0, 5),
            }
            updates = {}
            for key, bounds in numeric.items():
                if key in payload:
                    value = float(payload[key])
                    if not bounds[0] <= value <= bounds[1]:
                        raise DomainError(f"图谱参数 {key} 超出范围")
                    updates[key] = value
            if updates:
                connection.execute(
                    f"UPDATE graph_settings SET {', '.join(key+'=?' for key in updates)} WHERE project_id=?",
                    tuple(updates.values()) + (self.project_id,),
                )
            characters = {str(row[0]) for row in connection.execute("SELECT entity_id FROM active_characters")}
            if "nodes" in payload:
                node_ids: set[str] = set()
                orbits: dict[str, str] = {}
                for item in payload["nodes"]:
                    character_id = str(item.get("character_id") or "")
                    orbit_of = str(item.get("orbit_of") or "")
                    if character_id in node_ids:
                        raise DomainError("同一个人物不能重复配置图谱节点")
                    node_ids.add(character_id)
                    if character_id not in characters or (orbit_of and orbit_of not in characters) or orbit_of == character_id:
                        raise DomainError("图谱节点引用了不存在或无效的人物")
                    if orbit_of:
                        orbits[character_id] = orbit_of
                    for key, minimum, maximum in (
                        ("orbit_distance", 0, 5000), ("orbit_angle", -3600, 3600),
                        ("strength", 0, 5), ("anchor_x", -100000, 100000), ("anchor_y", -100000, 100000),
                    ):
                        if item.get(key) is None:
                            continue
                        value = float(item[key])
                        if not math.isfinite(value) or not minimum <= value <= maximum:
                            raise DomainError(f"图谱节点参数 {key} 超出范围")
                for character_id in orbits:
                    visited = {character_id}
                    current = orbits.get(character_id)
                    while current:
                        if current in visited:
                            raise DomainError("人物环绕关系不能形成循环")
                        visited.add(current)
                        current = orbits.get(current)
                connection.execute("DELETE FROM graph_nodes")
                for item in payload["nodes"]:
                    character_id = str(item.get("character_id") or "")
                    orbit_of = str(item.get("orbit_of") or "") or None
                    if character_id not in characters or (orbit_of and orbit_of not in characters):
                        raise DomainError("图谱节点引用了不存在的人物")
                    connection.execute(
                        """
                        INSERT INTO graph_nodes(character_id, orbit_of, orbit_distance, orbit_angle, strength, anchor_x, anchor_y)
                        VALUES(?, ?, ?, ?, ?, ?, ?)
                        """,
                        (character_id, orbit_of, item.get("orbit_distance"), item.get("orbit_angle"), item.get("strength"), item.get("anchor_x"), item.get("anchor_y")),
                    )
            if "distances" in payload:
                distance_pairs: set[tuple[str, str]] = set()
                connection.execute("DELETE FROM graph_distances")
                for item in payload["distances"]:
                    from_id = str(item.get("from_character_id") or "")
                    to_id = str(item.get("to_character_id") or "")
                    if from_id not in characters or to_id not in characters or from_id == to_id:
                        raise DomainError("图谱距离引用了无效人物")
                    pair = tuple(sorted((from_id, to_id)))
                    if pair in distance_pairs:
                        raise DomainError("同一对人物只能设置一条距离约束")
                    distance_pairs.add(pair)
                    distance = float(item.get("distance", 250))
                    strength = float(item.get("strength", 1))
                    if not math.isfinite(distance) or not 20 <= distance <= 5000:
                        raise DomainError("图谱人物距离必须在 20 到 5000 之间")
                    if not math.isfinite(strength) or not 0 <= strength <= 5:
                        raise DomainError("图谱距离强度必须在 0 到 5 之间")
                    connection.execute(
                        "INSERT INTO graph_distances(from_character_id, to_character_id, distance, strength) VALUES(?, ?, ?, ?)",
                        (from_id, to_id, distance, strength),
                    )
            if "clusters" in payload:
                cluster_ids: set[str] = set()
                connection.execute("DELETE FROM graph_clusters WHERE project_id=?", (self.project_id,))
                for index, item in enumerate(payload["clusters"], start=1):
                    cluster_id = clean_text(item.get("id"), "分组 ID", 80, required=True)
                    if cluster_id in cluster_ids:
                        raise DomainError("图谱分组 ID 不能重复")
                    cluster_ids.add(cluster_id)
                    numeric_values = {}
                    for key, minimum, maximum in (
                        ("center_x", -100000, 100000), ("center_y", -100000, 100000),
                        ("radius", 0, 10000), ("strength", 0, 5),
                    ):
                        value = item.get(key)
                        if value is None:
                            numeric_values[key] = None
                            continue
                        number = float(value)
                        if not math.isfinite(number) or not minimum <= number <= maximum:
                            raise DomainError(f"图谱分组参数 {key} 超出范围")
                        numeric_values[key] = number
                    connection.execute(
                        "INSERT INTO graph_clusters(id, project_id, label, center_x, center_y, radius, strength, sort_key) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                        (cluster_id, self.project_id, clean_text(item.get("label"), "分组名称", 80, required=True), numeric_values["center_x"], numeric_values["center_y"], numeric_values["radius"], numeric_values["strength"], rank(index)),
                    )
                    for character_id in list(dict.fromkeys(item.get("members", []))):
                        if character_id not in characters:
                            raise DomainError("图谱分组引用了不存在的人物")
                        connection.execute(
                            "INSERT INTO graph_cluster_members(cluster_id, character_id) VALUES(?, ?)",
                            (cluster_id, character_id),
                        )
            return {"updatedAt": now}

        return self.uow.mutate(
            base_revision=base_revision, label="调整人物图谱", action="update",
            entity_kind="character", callback=mutation,
        )

    @staticmethod
    def _plot_target(connection: sqlite3.Connection, value: Any) -> str | None:
        if value in (None, ""):
            return None
        identifier = str(value)
        if not connection.execute("SELECT 1 FROM active_plots WHERE entity_id=?", (identifier,)).fetchone():
            raise DomainError("剧情线锚点引用了不存在的剧情")
        return identifier

    @staticmethod
    def _bounded(value: Any, fallback: int, minimum: int, maximum: int) -> int:
        number = int(value if value is not None else fallback)
        if not minimum <= number <= maximum:
            raise DomainError("时间线视觉参数超出范围")
        return number
