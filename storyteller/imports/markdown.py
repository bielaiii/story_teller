from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

import yaml

from storyteller.domain.content import clean_body, clean_color, clean_text, clean_values
from storyteller.domain.errors import ConflictError, DomainError
from storyteller.domain.uow import MutationResult


PLOT_STATUS = {"素材", "草稿", "待串联", "已接入", "已完成"}
STORY_PALETTE = ["#3f7fc1", "#c94f62", "#2b8a72", "#8a64b8", "#b06b2d", "#2e879e"]
PLOT_KEYS = {"chapterNumber", "stories", "summary", "status", "tags", "key", "climax"}
FRAGMENT_KEYS = {"story", "order", "chapterNumber", "tags", "key", "climax"}
BOOL_KEYS = {"key", "climax"}
MAX_FILES = 1000
MAX_PATH = 240


@dataclass(frozen=True, slots=True)
class MarkdownFile:
    path: str
    text: str
    modified_at: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedMarkdown:
    kind: str
    path: str
    title: str
    metadata: dict[str, Any]
    body: str
    story: str | None
    fingerprint: str
    source_time: int | None


def _error(path: str, message: str) -> DomainError:
    return DomainError(f"{path}：{message}")


def _strict_bool(value: Any, path: str, key: str) -> bool:
    if type(value) is not bool:
        raise _error(path, f"{key} 必须是 true 或 false")
    return value


def _strict_int(value: Any, path: str, key: str, *, minimum: int = 0, maximum: int = 99999) -> int:
    if type(value) is not int or isinstance(value, bool) or not minimum <= value <= maximum:
        raise _error(path, f"{key} 必须是 {minimum}..{maximum} 的整数")
    return value


def _strict_list(value: Any, path: str, key: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _error(path, f"{key} 必须是字符串列表")
    result: list[str] = []
    for item in value:
        clean = item.strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _frontmatter(path: str, text: str) -> tuple[dict[str, Any], str]:
    source = text.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^---\n(?P<meta>[\s\S]*?)\n?---(?:\n|$)", source)
    if not match:
        if not source.startswith("---\n"):
            raise _error(path, "必须以 YAML frontmatter 开始")
        raise _error(path, "缺少 frontmatter 结束标记 ---")
    try:
        loaded = yaml.safe_load(match.group("meta")) or {}
    except yaml.YAMLError as error:
        raise _error(path, f"YAML 无法解析：{error}") from error
    if not isinstance(loaded, dict):
        raise _error(path, "frontmatter 必须是键值对象")
    return {str(key): value for key, value in loaded.items()}, source[match.end():]


def _validate_path(path: str) -> PurePosixPath:
    normalized = str(path or "").replace("\\", "/")
    if not normalized or len(normalized) > MAX_PATH or normalized.startswith("/"):
        raise _error(normalized or "<empty>", "路径不合法")
    pure = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise _error(normalized, "路径不能包含空段、. 或 ..")
    if pure.suffix.lower() != ".md":
        raise _error(normalized, "只支持 .md 文件")
    if pure.parts[0] not in {"plots", "fragments"}:
        raise _error(normalized, "路径必须位于 plots/ 或 fragments/")
    if pure.parts[0] == "plots" and len(pure.parts) < 2:
        raise _error(normalized, "plots/ 下必须有文件")
    if pure.parts[0] == "fragments" and len(pure.parts) > 3:
        raise _error(normalized, "fragments/ 故事目录最多一层")
    if pure.name == "_story.md" and pure.parts[0] != "fragments":
        raise _error(normalized, "_story.md 只能位于 fragments/故事名/")
    return pure


def parse_markdown_file(file: MarkdownFile) -> ParsedMarkdown:
    pure = _validate_path(file.path)
    if file.modified_at is not None and int(file.modified_at) > int(time.time()) + 86_400:
        raise _error(file.path, "modifiedAt 不能是未来时间")
    metadata, body = _frontmatter(file.path, file.text)
    if "title" in metadata:
        raise _error(file.path, "不接受 title，标题使用文件名")
    kind = "plot" if pure.parts[0] == "plots" else "fragment"
    allowed = PLOT_KEYS if kind == "plot" else FRAGMENT_KEYS
    unknown = sorted(set(metadata) - allowed)
    if unknown:
        raise _error(file.path, f"不支持的 key：{', '.join(unknown)}")
    title = pure.stem
    if title == "_story":
        title = pure.parent.name
    title = clean_text(title, "文件标题", 120, required=True)
    if kind == "plot":
        if "chapterNumber" not in metadata:
            raise _error(file.path, "Plot 必须提供 chapterNumber")
        chapter = _strict_int(metadata["chapterNumber"], file.path, "chapterNumber", minimum=1)
        stories = _strict_list(metadata.get("stories", ["主线"]), file.path, "stories")
        if not stories:
            raise _error(file.path, "stories 不能为空")
        if "status" in metadata and (not isinstance(metadata["status"], str) or metadata["status"] not in PLOT_STATUS):
            raise _error(file.path, "status 不是支持的选项")
        if "summary" in metadata and not isinstance(metadata["summary"], str):
            raise _error(file.path, "summary 必须是文本")
        for key in BOOL_KEYS:
            if key in metadata:
                _strict_bool(metadata[key], file.path, key)
        metadata = {**metadata, "chapterNumber": chapter, "stories": stories}
        story = None
    else:
        if pure.name == "_story.md" and len(pure.parts) != 3:
            raise _error(file.path, "故事容器必须是 fragments/<故事名>/_story.md")
        if "story" in metadata and not isinstance(metadata["story"], str):
            raise _error(file.path, "story 必须是文本")
        if "order" in metadata:
            _strict_int(metadata["order"], file.path, "order", minimum=0)
        if "chapterNumber" in metadata and metadata["chapterNumber"] is not None:
            _strict_int(metadata["chapterNumber"], file.path, "chapterNumber", minimum=1)
        for key in BOOL_KEYS:
            if key in metadata:
                _strict_bool(metadata[key], file.path, key)
        if "tags" in metadata:
            _strict_list(metadata["tags"], file.path, "tags")
        directory_story = pure.parts[1] if len(pure.parts) == 3 else ""
        declared_story = str(metadata.get("story") or "").strip()
        if declared_story and directory_story and declared_story != directory_story:
            raise _error(file.path, "YAML story 必须与所在故事目录一致")
        story = declared_story or directory_story or None
    normalized_body = clean_body(body.rstrip("\n"), "正文")
    digest = hashlib.sha256(f"{kind}\0{title}\0{normalized_body}".encode("utf-8")).hexdigest()
    return ParsedMarkdown(kind, pure.as_posix(), title, metadata, normalized_body, story, digest, file.modified_at)


def parse_bundle(files: Iterable[MarkdownFile]) -> list[ParsedMarkdown]:
    values = list(files)
    if not values or len(values) > MAX_FILES:
        raise DomainError(f"一次导入必须包含 1..{MAX_FILES} 个 Markdown 文件")
    parsed = [parse_markdown_file(item) for item in values]
    paths = [item.path for item in parsed]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        raise DomainError(f"导入路径重复：{', '.join(duplicates)}")
    return parsed


class MarkdownImportService:
    """Preview and atomically apply the documented plots/fragments bundle."""

    def __init__(self, database, project_id: str):
        self.database = database
        self.project_id = project_id

    def preview(self, base_revision: int, files: Iterable[MarkdownFile]) -> dict[str, Any]:
        parsed = parse_bundle(files)
        with self.database.read() as connection:
            project = connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()
            if not project:
                raise DomainError("项目不存在")
            if int(project[0]) != int(base_revision):
                raise ConflictError("项目已更新，请重新预览导入")
            existing_titles = {
                str(row[0]) for row in connection.execute(
                    "SELECT title FROM active_entities WHERE kind IN ('plot', 'fragment')"
                )
            }
            existing_numbers = {
                int(row[0]) for row in connection.execute(
                    "SELECT chapter_number FROM active_plots WHERE chapter_number IS NOT NULL"
                )
            }
            existing_fingerprints = {
                hashlib.sha256(f"{kind}\0{title}\0{body}".encode("utf-8")).hexdigest()
                for kind, title, body in connection.execute(
                    """
                    SELECT 'plot', e.title, p.body_markdown FROM active_plots p JOIN entities e ON e.id=p.entity_id
                    UNION ALL
                    SELECT 'fragment', e.title, f.body_markdown FROM active_fragments f JOIN entities e ON e.id=f.entity_id
                    """
                )
            }
            conflicts: list[dict[str, Any]] = []
            items: list[dict[str, Any]] = []
            batch_fingerprints: set[str] = set()
            for item in parsed:
                conflict: list[str] = []
                duplicate = item.fingerprint in existing_fingerprints or item.fingerprint in batch_fingerprints
                if item.title in existing_titles and not duplicate:
                    conflict.append("title")
                chapter = item.metadata.get("chapterNumber")
                if item.kind == "plot" and chapter in existing_numbers and not duplicate:
                    conflict.append("chapterNumber")
                reference_conflicts = self._ambiguous_entry_terms(connection, item.body, str(item.metadata.get("summary", "")))
                if reference_conflicts:
                    conflict.append("ambiguousReference")
                record = {
                    "path": item.path, "kind": item.kind, "title": item.title,
                    "chapterNumber": chapter, "story": item.story,
                    "fingerprint": item.fingerprint, "conflicts": conflict,
                    "referenceConflicts": reference_conflicts,
                    "action": "skip" if duplicate else "import",
                }
                items.append(record)
                if conflict:
                    conflicts.append(record)
                batch_fingerprints.add(item.fingerprint)
        return {"baseRevision": int(base_revision), "items": items, "conflicts": conflicts,
                "requiresResolution": bool(conflicts), "fileCount": len(items),
                "fingerprint": self._bundle_fingerprint(base_revision, parsed)}

    def apply(self, base_revision: int, files: Iterable[MarkdownFile], *, allow_conflicts: bool = False, preview_fingerprint: str | None = None) -> MutationResult:
        parsed = parse_bundle(files)
        if preview_fingerprint and preview_fingerprint != self._bundle_fingerprint(base_revision, parsed):
            raise ConflictError("导入文件已变化，请重新预览")
        now = int(time.time())
        from storyteller.domain.content import ContentService
        content = ContentService(self.database, self.project_id)

        def mutation(connection):
            current = int(connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()[0])
            if current != int(base_revision):
                raise ConflictError("项目已更新，请重新预览导入")
            existing_titles = {str(row[0]) for row in connection.execute("SELECT title FROM active_entities WHERE kind IN ('plot', 'fragment')")}
            existing_numbers = {int(row[0]) for row in connection.execute("SELECT chapter_number FROM active_plots WHERE chapter_number IS NOT NULL")}
            existing_fingerprints = {
                hashlib.sha256(f"{kind}\0{title}\0{body}".encode("utf-8")).hexdigest()
                for kind, title, body in connection.execute(
                    """
                    SELECT 'plot', e.title, p.body_markdown FROM active_plots p JOIN entities e ON e.id=p.entity_id
                    UNION ALL
                    SELECT 'fragment', e.title, f.body_markdown FROM active_fragments f JOIN entities e ON e.id=f.entity_id
                    """
                )
            }
            batch_numbers: set[int] = set()
            batch_fingerprints: set[str] = set()
            created: list[dict[str, Any]] = []
            line_ids: dict[str, str] = {}
            for item in parsed:
                chapter = item.metadata.get("chapterNumber")
                if item.fingerprint in existing_fingerprints or item.fingerprint in batch_fingerprints:
                    created.append({"kind": item.kind, "path": item.path, "skipped": True, "reason": "duplicate"})
                    batch_fingerprints.add(item.fingerprint)
                    continue
                if item.kind == "plot" and chapter in batch_numbers:
                    raise DomainError(f"导入冲突：{item.path}，批次内重复 chapterNumber {chapter}")
                if item.kind == "plot" and chapter in existing_numbers:
                    # chapterNumber is a hard uniqueness constraint; unlike a
                    # title collision it can never be overridden by a choice.
                    raise DomainError(f"导入冲突：{item.path}，chapterNumber {chapter} 已存在")
                if not allow_conflicts and item.title in existing_titles:
                    raise DomainError(f"导入冲突：{item.path}，请在预览中处理")
                if item.kind == "plot":
                    stable = content._next_numeric_id(connection, self.project_id, "plot")
                    identifier = content._create_entity(connection, "plot", stable, item.title, item.source_time or now)
                    rank = content._next_rank(connection, "plots")
                    status = item.metadata.get("status", "草稿")
                    connection.execute("INSERT INTO plots(entity_id, chapter_id, chapter_number, sort_key, story_sort_key, story_order_mode, summary, body_markdown, status, accent, is_key, is_climax) VALUES(?, NULL, ?, ?, ?, 'follow_reading', ?, ?, ?, ?, ?, ?)", (identifier, chapter, rank, rank, str(item.metadata.get("summary", "")), item.body, status, self._least_used_color(connection, "plots"), int(item.metadata.get("key", False)), int(item.metadata.get("climax", False))))
                    ContentService._replace_values(connection, "plot_tags", "plot_id", identifier, "tag", clean_values(item.metadata.get("tags", []), "标签"))
                    for story in item.metadata.get("stories", ["主线"]):
                        line_id = self._ensure_story(connection, story, line_ids, now, content)
                        story_rank = f"{rank}:{line_id}"
                        connection.execute("INSERT OR REPLACE INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)", (identifier, line_id, story_rank))
                    created.append({"entityId": identifier, "kind": "plot", "path": item.path})
                    existing_titles.add(item.title); existing_numbers.add(int(chapter)); batch_numbers.add(int(chapter))
                    batch_fingerprints.add(item.fingerprint)
                else:
                    is_story = PurePosixPath(item.path).name == "_story.md"
                    parent_id = None
                    if not is_story and item.story:
                        parent_id = line_ids.get(item.story) or self._find_story_fragment(connection, item.story)
                        if not parent_id:
                            parent_id = self._insert_fragment(connection, item.story, "", "line", None, 0, {}, now, content)
                            line_ids[item.story] = parent_id
                    fragment_type = "line" if is_story else "chapter"
                    identifier = self._insert_fragment(connection, item.title, item.body, fragment_type, parent_id, int(item.metadata.get("order", 0)), item.metadata, item.source_time or now, content)
                    if is_story:
                        line_ids[item.title] = identifier
                    created.append({"entityId": identifier, "kind": "fragment", "path": item.path})
                    existing_titles.add(item.title)
                    batch_fingerprints.add(item.fingerprint)
            self._resolve_import_references(connection, parsed, created, now, content)
            skipped = sum(1 for item in created if item.get("skipped"))
            return {"created": created, "count": len(created) - skipped, "skipped": skipped}

        return self._uow().mutate(base_revision=base_revision, label=f"批量导入 Markdown（{len(parsed)} 个文件）", action="import", entity_kind="content", callback=mutation, details={"files": [item.path for item in parsed]})

    @staticmethod
    def _bundle_fingerprint(base_revision: int, parsed: Iterable[ParsedMarkdown]) -> str:
        payload = [
            (item.path, item.fingerprint, item.source_time)
            for item in sorted(parsed, key=lambda value: value.path)
        ]
        return hashlib.sha256(json.dumps({"baseRevision": int(base_revision), "files": payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _uow(self):
        from storyteller.domain.uow import UnitOfWork
        return UnitOfWork(self.database, self.project_id)

    @staticmethod
    def _next_numeric_id(service, connection, project_id: str, kind: str) -> str:
        return service._next_numeric_id(connection, project_id, kind)

    @staticmethod
    def _create_entity(service, connection, kind: str, stable: str, title: str, now: int) -> str:
        return service._create_entity(connection, kind, stable, title, now)

    @staticmethod
    def _next_rank(service, connection, table: str) -> str:
        return service._next_rank(connection, table)

    @staticmethod
    def _find_story_fragment(connection, title: str) -> str | None:
        row = connection.execute("SELECT e.id FROM active_fragments f JOIN entities e ON e.id=f.entity_id WHERE e.title=? AND json_extract(e.extra_json, '$.fragmentType')='line'", (title,)).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _mentioned(term: str, text: str) -> bool:
        if len(term) == 1 and term.isascii():
            return False
        if term.isascii() and all(character.isalnum() or character in "_-" for character in term):
            return re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
        return term in text

    @classmethod
    def _entry_terms(cls, connection) -> dict[str, set[str]]:
        terms: dict[str, set[str]] = {}
        for row in connection.execute("SELECT entity_id, name FROM active_entries"):
            terms.setdefault(str(row[1]).casefold(), set()).add(str(row[0]))
            for alias in connection.execute("SELECT alias FROM entry_aliases WHERE entry_id=?", (row[0],)):
                if str(alias[0]).strip():
                    terms.setdefault(str(alias[0]).casefold(), set()).add(str(row[0]))
        return terms

    @classmethod
    def _ambiguous_entry_terms(cls, connection, body: str, summary: str = "") -> list[str]:
        text = f"{summary}\n{body}"
        return sorted(
            term for term, owners in cls._entry_terms(connection).items()
            if len(owners) > 1 and cls._mentioned(term, text)
        )

    @classmethod
    def _automatic_entry_ids(cls, connection, body: str, summary: str = "") -> tuple[list[str], list[str]]:
        text = f"{summary}\n{body}"
        matches: list[str] = []
        ambiguous: list[str] = []
        for term, owners in cls._entry_terms(connection).items():
            if not cls._mentioned(term, text):
                continue
            if len(owners) != 1:
                ambiguous.append(term)
                continue
            owner = next(iter(owners))
            if owner not in matches:
                matches.append(owner)
        return matches, sorted(ambiguous)

    @classmethod
    def _resolve_import_references(cls, connection, parsed, created, now, content) -> None:
        by_path = {
            str(item["path"]): str(item["entityId"])
            for item in created
            if item.get("entityId")
        }
        for item in parsed:
            identifier = by_path.get(item.path)
            if not identifier:
                continue
            payload = {
                "body": item.body,
                "summary": str(item.metadata.get("summary", "")),
                "chapter_number": item.metadata.get("chapterNumber"),
            }
            if item.kind == "plot":
                content._archive_unknown_plot_speakers(connection, identifier, payload, now)
                people = content._automatic_text_people(connection, identifier, payload, "plot")
                connection.execute("DELETE FROM plot_characters WHERE plot_id=?", (identifier,))
                connection.executemany(
                    "INSERT INTO plot_characters(plot_id, character_id, source) VALUES(?, ?, 'automatic')",
                    [(identifier, value) for value in people],
                )
                entries, ambiguous = cls._automatic_entry_ids(connection, item.body, str(item.metadata.get("summary", "")))
                if ambiguous:
                    raise DomainError(f"{item.path}：设定引用存在同名歧义：{', '.join(ambiguous)}")
                connection.execute("DELETE FROM plot_entries WHERE plot_id=?", (identifier,))
                connection.executemany(
                    "INSERT INTO plot_entries(plot_id, entry_id, source) VALUES(?, ?, 'automatic')",
                    [(identifier, value) for value in entries],
                )
                content._sync_character_references(connection, identifier, people)
            else:
                people = content._automatic_text_people(connection, identifier, payload, "fragment")
                content._sync_character_references(connection, identifier, people)

    @staticmethod
    def _insert_fragment(connection, title: str, body: str, fragment_type: str, parent_id: str | None, order: int, metadata: dict[str, Any], now: int, service) -> str:
        stable = service._next_numeric_id(connection, service.project_id, "fragment")
        identifier = service._create_entity(connection, "fragment", stable, title, now)
        connection.execute("INSERT INTO fragments(entity_id, body_markdown, status, accent, is_key, is_climax) VALUES(?, ?, '', ?, ?, ?)", (identifier, body, MarkdownImportService._least_used_color(connection, "fragments"), int(metadata.get("key", False)), int(metadata.get("climax", False))))
        connection.execute("UPDATE entities SET extra_json=? WHERE id=?", (json.dumps({"fragmentType": fragment_type, "parentFragmentId": parent_id, "fragmentOrder": order, "chapterNumber": metadata.get("chapterNumber"), "story": metadata.get("story")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), identifier))
        tags = metadata.get("tags", [])
        connection.executemany("INSERT INTO fragment_tags(fragment_id, tag, position) VALUES(?, ?, ?)", [(identifier, tag, index) for index, tag in enumerate(tags)])
        return identifier

    @staticmethod
    def _ensure_story(connection, title: str, cache: dict[str, str], now: int, service) -> str:
        if title in cache:
            return cache[title]
        row = connection.execute("SELECT entity_id FROM active_timeline_lines WHERE title=?", (title,)).fetchone()
        if row:
            cache[title] = str(row[0]); return cache[title]
        stable = service._next_numeric_id(connection, service.project_id, "timeline_line")
        identifier = service._create_entity(connection, "timeline_line", stable, title, now)
        rank = service._next_rank(connection, "timeline_lines")
        color = MarkdownImportService._least_used_color(connection, "timeline_lines", color_column="color")
        connection.execute("INSERT INTO timeline_lines(entity_id, color, side, sort_key) VALUES(?, ?, 'right', ?)", (identifier, color, rank))
        cache[title] = identifier
        return identifier

    @staticmethod
    def _least_used_color(connection, table: str, *, color_column: str = "accent") -> str:
        counts = {color: 0 for color in STORY_PALETTE}
        for row in connection.execute(f"SELECT {color_column} FROM {table}"):
            color = str(row[0] or "")
            if color in counts:
                counts[color] += 1
        return min(STORY_PALETTE, key=lambda color: (counts[color], STORY_PALETTE.index(color)))
