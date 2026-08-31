from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ENTITY_ID = re.compile(r"^[a-z_]+:\d+$")


class CliError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        exit_code: int = 6,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.details = details or {}


class ServiceError(CliError):
    def __init__(self, message: str):
        super().__init__(message, code="service_unavailable", exit_code=3)


class SelectionError(CliError):
    def __init__(self, message: str, *, code: str = "not_found"):
        super().__init__(message, code=code, exit_code=4)


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    content_root: Path
    projects: tuple[str, ...]

    @property
    def workspace_id(self) -> str:
        digest = hashlib.sha256(str(self.content_root).encode("utf-8")).hexdigest()[:16]
        return f"workspace-{digest}"


def projects_in(content_root: Path) -> tuple[str, ...]:
    if not content_root.is_dir():
        return ()
    return tuple(sorted(
        path.name
        for path in content_root.iterdir()
        if path.is_dir() and (path / "story.db").is_file()
    ))


def discover_workspace(start: Path | None = None) -> Workspace:
    configured = str(
        os.environ.get("STORY_TELLER_CONTENT_ROOT")
        or os.environ.get("STORY_FRAGMENT_CONTENT_ROOT")
        or ""
    ).strip()
    if configured:
        content_root = Path(configured).expanduser().resolve()
        projects = projects_in(content_root)
        if not projects:
            raise CliError(
                f"指定的 Content 中没有 Project：{content_root}",
                code="workspace_not_found",
                exit_code=2,
            )
        configured_root = str(
            os.environ.get("STORY_TELLER_WORKSPACE_ROOT")
            or os.environ.get("STORY_FRAGMENT_WORKSPACE_ROOT")
            or ""
        ).strip()
        return Workspace(
            Path(configured_root).expanduser().resolve() if configured_root else content_root.parent,
            content_root,
            projects,
        )
    current = (start or Path.cwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        content_root = candidate / "content"
        projects = projects_in(content_root)
        if projects:
            return Workspace(candidate, content_root.resolve(), projects)
    raise CliError(
        f"从 {current} 向上没有找到 content/<project>/story.db；请在 Story Teller 小说仓库内运行",
        code="workspace_not_found",
        exit_code=2,
    )


def select_project(workspace: Workspace, requested: str = "", start: Path | None = None) -> str:
    requested = str(requested or os.environ.get("STORY_TELLER_DEFAULT_PROJECT") or "").strip()
    if requested:
        if requested not in workspace.projects:
            raise CliError(f"Project 不存在：{requested}", code="project_not_found", exit_code=2)
        return requested
    current = (start or Path.cwd()).resolve()
    for project in workspace.projects:
        root = (workspace.content_root / project).resolve()
        if current == root or root in current.parents:
            return project
    if workspace.root.name in workspace.projects:
        return workspace.root.name
    if len(workspace.projects) == 1:
        return workspace.projects[0]
    raise CliError(
        f"存在多个 Project（{', '.join(workspace.projects)}），请通过 --project 指定",
        code="project_required",
        exit_code=2,
    )


def default_web_url(workspace: Workspace, explicit: str = "") -> str:
    configured = str(
        explicit
        or os.environ.get("STORY_FRAGMENT_WEB_URL")
        or os.environ.get("STORY_TELLER_WEB_URL")
        or ""
    ).strip()
    if configured:
        return configured.rstrip("/")
    port = str(os.environ.get("STORY_TELLER_WEB_PORT") or "4187").strip()
    return f"http://127.0.0.1:{port}/w/{workspace.workspace_id}"


class ApiClient:
    def __init__(self, base_url: str, project: str, *, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.project = project
        self.timeout = timeout
        self.token = ""

    def url(self, path: str, query: dict[str, Any] | None = None) -> str:
        target = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            target += "?" + urlencode(query)
        return target

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        mutation: bool = False,
    ) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if mutation:
            headers["X-Story-Teller-Token"] = self.token
        request = Request(self.url(path, query), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}
            message = str(body.get("error") or body.get("detail") or error.reason or "请求失败")
            code = str(body.get("code") or f"http_{error.code}")
            exit_code = 5 if error.code == 409 else 3 if error.code == 503 else 6
            raise CliError(message, code=code, exit_code=exit_code) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ServiceError(
                f"无法连接 Story Teller 服务：{self.base_url}；请先运行 ./run.sh（{error}）"
            ) from error
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ServiceError("Story Teller 服务返回了无法识别的响应") from error

    def meta(self) -> dict[str, Any]:
        meta = self.request("GET", "api/v1/meta", query={"project": self.project})
        self.token = str(meta.get("mutationToken") or "")
        return meta

    def snapshot(self) -> dict[str, Any]:
        return self.request("GET", self.project_path("snapshot"))

    def project_path(self, suffix: str) -> str:
        return f"api/v1/projects/{quote(self.project, safe='')}/{suffix.lstrip('/')}"

    def detail(self, entity_id: str, *, trash: bool = False) -> dict[str, Any]:
        encoded = quote(entity_id, safe="")
        suffix = f"trash/{encoded}" if trash else f"entities/{encoded}"
        return self.request("GET", self.project_path(suffix))

    def prepare_write(self) -> tuple[dict[str, Any], dict[str, Any]]:
        meta = self.meta()
        if not meta.get("writable"):
            raise CliError(
                str(meta.get("error") or f"Project 当前不可写：{self.project}"),
                code="not_writable",
                exit_code=3,
            )
        if meta.get("mergeRequired") or not meta.get("contentWritable"):
            raise CliError(
                "数据库仍有合并冲突，请先运行 story-teller merge status 或在网页中完成合并",
                code="merge_required",
                exit_code=6,
            )
        if not self.token:
            raise CliError("服务没有提供本地写入授权，请重新启动服务", code="not_writable", exit_code=3)
        return meta, self.snapshot()

    def mutate(
        self,
        method: str,
        suffix: str,
        payload: dict[str, Any],
        *,
        retry_create_conflict: bool = False,
    ) -> dict[str, Any]:
        _meta, snapshot = self.prepare_write()
        body = {"baseRevision": snapshot["project"]["revision"], **payload}
        try:
            return self.request(method, self.project_path(suffix), payload=body, mutation=True)
        except CliError as error:
            if not retry_create_conflict or error.exit_code != 5:
                raise
            _meta, snapshot = self.prepare_write()
            body["baseRevision"] = snapshot["project"]["revision"]
            return self.request(method, self.project_path(suffix), payload=body, mutation=True)


def _matches(item: dict[str, Any], selector: str, title_keys: Iterable[str]) -> bool:
    if selector == str(item.get("entityId") or "") or selector == str(item.get("id") or ""):
        return True
    return any(selector == str(item.get(key) or "").strip() for key in title_keys)


def resolve_item(
    items: Iterable[dict[str, Any]],
    selector: str,
    *,
    noun: str,
    title_keys: tuple[str, ...] = ("title",),
) -> dict[str, Any]:
    value = str(selector or "").strip()
    exact = [item for item in items if _matches(item, value, title_keys)]
    if not exact:
        folded = [
            item for item in items
            if any(value.casefold() == str(item.get(key) or "").strip().casefold() for key in title_keys)
        ]
        exact = folded
    if not exact:
        raise SelectionError(f"找不到{noun}：{value}")
    if len(exact) > 1:
        choices = "、".join(str(item.get("entityId") or item.get("id")) for item in exact[:8])
        raise SelectionError(
            f"{noun}选择器“{value}”不唯一，请改用 ID：{choices}",
            code="ambiguous_selector",
        )
    return exact[0]


def resolve_fragment(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("fragments", []), selector, noun="碎片")


def resolve_parent(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    parent = resolve_fragment(snapshot, selector)
    if parent.get("fragmentType") != "line":
        raise SelectionError(f"父级必须是剧情线：{selector}", code="invalid_parent")
    return parent


def resolve_person(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    value = str(selector or "").strip()
    candidates = list(snapshot.get("characters", []))
    matches = [
        item for item in candidates
        if _matches(item, value, ("name",))
        or value in [str(alias).strip() for alias in item.get("aliases", [])]
    ]
    if not matches:
        folded = value.casefold()
        matches = [
            item for item in candidates
            if folded == str(item.get("name") or "").strip().casefold()
            or folded in [str(alias).strip().casefold() for alias in item.get("aliases", [])]
        ]
    if not matches:
        raise SelectionError(f"找不到人物：{value}")
    if len(matches) > 1:
        choices = "、".join(str(item.get("entityId") or item.get("id")) for item in matches[:8])
        raise SelectionError(
            f"人物选择器“{value}”不唯一，请改用 ID：{choices}",
            code="ambiguous_selector",
        )
    return matches[0]


def resolve_reference(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for collection, key in (("characters", "name"), ("plots", "title"), ("entries", "name"), ("fragments", "title")):
        for item in snapshot.get(collection, []):
            candidates.append({**item, "_referenceTitle": item.get(key, "")})
    return resolve_item(candidates, selector, noun="引用目标", title_keys=("_referenceTitle",))


def resolve_story(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("timeline", {}).get("lines", []), selector, noun="故事线", title_keys=("name",))


def read_text_argument(args: argparse.Namespace, *, optional: bool) -> str | None:
    inline = getattr(args, "body", None)
    filename = getattr(args, "body_file", None)
    if inline is not None:
        return str(inline)
    if filename is not None:
        try:
            return Path(filename).expanduser().read_text(encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法读取正文文件：{filename}（{error}）", code="file_error", exit_code=2) from error
    if not sys.stdin.isatty():
        value = sys.stdin.read()
        if value or not optional:
            return value
    return None if optional else ""


def selected_ids(
    snapshot: dict[str, Any], values: Sequence[str] | None, resolver
) -> list[str] | None:
    if values is None:
        return None
    return [str(resolver(snapshot, value)["entityId"]) for value in values]


def changed_fragments(response: dict[str, Any]) -> list[dict[str, Any]]:
    return list(response.get("changed", {}).get("fragments", []))


def format_time(timestamp: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))
    except (TypeError, ValueError, OSError):
        return "—"


def fragment_label(item: dict[str, Any]) -> str:
    chapter = item.get("chapterNumber")
    prefix = f"第 {chapter} 章  " if chapter else ""
    kind = "剧情线" if item.get("fragmentType") == "line" else "碎片"
    return f"{prefix}{item.get('title', '')}  [{kind} · {item.get('entityId', '')}]"


def emit(value: Any, *, json_output: bool, human: str = "") -> None:
    if json_output:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    elif human:
        print(human)
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def list_command(client: ApiClient, args: argparse.Namespace) -> Any:
    snapshot = client.snapshot()
    fragments = list(snapshot.get("fragments", []))
    if args.tag:
        fragments = [item for item in fragments if args.tag in item.get("tags", [])]
    if args.key:
        fragments = [item for item in fragments if item.get("key")]
    if args.climax:
        fragments = [item for item in fragments if item.get("climax")]
    if args.lines:
        fragments = [item for item in fragments if item.get("fragmentType") == "line"]
    fragments.sort(key=lambda item: (int(item.get("updatedAt") or 0), int(item.get("createdAt") or 0)), reverse=True)
    if args.limit:
        fragments = fragments[:args.limit]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": fragments}, json_output=True)
        return fragments
    if not fragments:
        print("没有符合条件的碎片。")
        return fragments
    if args.tree:
        visible = {item["entityId"]: item for item in fragments}
        children: dict[str, list[dict[str, Any]]] = {}
        for item in fragments:
            parent = item.get("parentFragmentId")
            if parent:
                children.setdefault(str(parent), []).append(item)
        rendered: set[str] = set()
        for line in (item for item in fragments if item.get("fragmentType") == "line"):
            print(fragment_label(line))
            rendered.add(line["entityId"])
            ordered = sorted(
                children.get(line["entityId"], []),
                key=lambda item: (
                    item.get("chapterNumber") is None,
                    int(item.get("chapterNumber") or 0),
                    int(item.get("fragmentOrder") or 0),
                ),
            )
            for child in ordered:
                print(f"  └─ {fragment_label(child)}")
                rendered.add(child["entityId"])
        for item in fragments:
            if item["entityId"] not in rendered and (not item.get("parentFragmentId") or item.get("parentFragmentId") not in visible):
                print(fragment_label(item))
    else:
        for item in fragments:
            print(f"{fragment_label(item)}  · {format_time(item.get('updatedAt'))}")
    return fragments


def show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    fragment = resolve_fragment(snapshot, args.selector)
    detail = client.detail(fragment["entityId"])
    data = detail["data"]
    if args.json_output:
        emit({"ok": True, "project": client.project, "item": detail}, json_output=True)
    else:
        metadata = [fragment_label(data)]
        if data.get("tags"):
            metadata.append("标签：" + "、".join(data["tags"]))
        if data.get("parentFragmentId"):
            metadata.append("父级：" + str(data["parentFragmentId"]))
        print("\n".join(metadata))
        if data.get("body"):
            print("\n" + str(data["body"]))
    return detail


def metadata_payload(args: argparse.Namespace, snapshot: dict[str, Any], *, editing: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for argument, field in (("tags", "tags"), ("appearance", "appearanceNames")):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    people = selected_ids(snapshot, getattr(args, "people", None), resolve_person)
    if people is not None:
        payload["people"] = people
    references = selected_ids(snapshot, getattr(args, "references", None), resolve_reference)
    if references is not None:
        payload["references"] = references
    for argument, field in (("key_value", "key"), ("climax_value", "climax")):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    body = read_text_argument(args, optional=editing)
    if body is not None:
        payload["body"] = body
    return payload


def add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    payload = metadata_payload(args, snapshot, editing=False)
    payload.update({"title": args.title, "fragmentType": "line" if args.line else "chapter"})
    if args.parent:
        payload["parentFragmentId"] = resolve_parent(snapshot, args.parent)["entityId"]
    if args.line and args.parent:
        raise CliError("剧情线不能再归属于另一条剧情线", code="invalid_parent")
    if args.chapter_number is not None:
        if args.line:
            raise CliError("剧情线本身不能设置章号", code="invalid_chapter")
        if not args.parent:
            raise CliError("设置章号时必须同时通过 --parent 指定剧情线", code="invalid_chapter")
        payload["chapterNumber"] = args.chapter_number
    if args.fragment_order is not None:
        payload["fragmentOrder"] = args.fragment_order
    if args.shift_following:
        payload["shiftFollowing"] = True
    response = client.mutate("POST", "fragments", payload, retry_create_conflict=True)
    created = [item for item in changed_fragments(response) if item.get("title") == args.title]
    item = client.detail(created[-1]["entityId"]) if created else None
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": item}
    emit(result, json_output=args.json_output, human=f"已创建：{fragment_label(item['data']) if item else args.title}")
    return result


def edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    fragment = resolve_fragment(snapshot, args.selector)
    payload = metadata_payload(args, snapshot, editing=True)
    if args.title is not None:
        payload["title"] = args.title
    if args.parent is not None:
        payload["parentFragmentId"] = resolve_parent(snapshot, args.parent)["entityId"]
    elif args.no_parent:
        payload["parentFragmentId"] = None
    if args.chapter_number is not None:
        payload["chapterNumber"] = args.chapter_number
    elif args.no_chapter_number:
        payload["chapterNumber"] = None
    if args.fragment_type is not None:
        payload["fragmentType"] = args.fragment_type
    if args.fragment_order is not None:
        payload["fragmentOrder"] = args.fragment_order
    if args.shift_following:
        payload["shiftFollowing"] = True
    if args.plot_chapter or args.clear_plot_plan:
        stored_plan = fragment.get("extra", {}).get("plotChapterPlan", {})
        plan: dict[str, int] = {} if args.clear_plot_plan else {
            str(key): int(value)
            for key, value in stored_plan.items()
            if isinstance(value, int) and value > 0
        }
        for raw in args.plot_chapter:
            selector, separator, number = raw.rpartition("=")
            if not separator or not selector.strip():
                raise CliError("--plot-chapter 格式应为 子碎片=N", code="invalid_argument", exit_code=2)
            child = resolve_fragment(snapshot, selector.strip())
            if child.get("parentFragmentId") != fragment["entityId"]:
                raise CliError(f"{selector} 不属于该剧情线", code="invalid_argument")
            try:
                target = int(number)
            except ValueError as error:
                raise CliError("正式剧情章号必须是整数", code="invalid_argument", exit_code=2) from error
            if target < 1:
                raise CliError("正式剧情章号必须大于 0", code="invalid_argument", exit_code=2)
            plan[child["entityId"]] = target
        payload["plotChapterPlan"] = plan
    if not payload:
        raise CliError("没有提供需要修改的字段", code="no_changes", exit_code=2)
    payload["entityRevision"] = fragment["revision"]
    response = client.mutate("PATCH", f"fragments/{quote(fragment['entityId'], safe='')}", payload)
    detail = client.detail(fragment["entityId"])
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已更新：{fragment_label(detail['data'])}")
    return result


def import_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.file).expanduser().read_text(encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法读取导入文件：{args.file}（{error}）", code="file_error", exit_code=2) from error
    if not text.strip():
        raise CliError("导入内容不能为空", code="invalid_import", exit_code=2)
    response = client.mutate(
        "POST", "fragments/import-clipboard", {"text": text}, retry_create_conflict=True
    )
    items = changed_fragments(response)
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "items": items}
    emit(result, json_output=args.json_output, human=f"已导入 {len(items)} 个碎片（包括剧情线容器）。")
    return result


def promote_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    fragment = resolve_fragment(snapshot, args.selector)
    if fragment.get("fragmentType") == "line":
        raise CliError("剧情线容器不能直接转为正式剧情，请选择其中的章节", code="invalid_fragment")
    payload: dict[str, Any] = {
        "chapterNumber": args.chapter_number,
        "entityRevision": fragment["revision"],
    }
    if args.title is not None:
        payload["title"] = args.title
    if args.stories is not None:
        payload["stories"] = selected_ids(snapshot, args.stories, resolve_story)
    response = client.mutate(
        "POST", f"fragments/{quote(fragment['entityId'], safe='')}/to-plot", payload
    )
    plots = response.get("changed", {}).get("plots", [])
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "items": plots}
    title = plots[-1].get("title") if plots else fragment["title"]
    emit(result, json_output=args.json_output, human=f"已转为正式剧情：{title}（第 {args.chapter_number} 章）")
    return result


def confirm_delete(fragment: dict[str, Any], assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CliError("非交互环境删除时必须添加 --yes", code="confirmation_required", exit_code=2)
    answer = input(f"将“{fragment['title']}”移入回收站？[y/N] ").strip().lower()
    return answer in {"y", "yes"}


def delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    fragment = resolve_fragment(snapshot, args.selector)
    if not confirm_delete(fragment, args.yes):
        result = {"ok": True, "cancelled": True, "item": fragment}
        emit(result, json_output=args.json_output, human="已取消。")
        return result
    response = client.mutate(
        "DELETE", f"entities/{quote(fragment['entityId'], safe='')}", {}
    )
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": fragment}
    emit(result, json_output=args.json_output, human=f"已移入回收站：{fragment['title']}")
    return result


def trash_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("trash"), query={"limit": args.limit})
    items = [item for item in response.get("items", []) if item.get("kind") == "fragment"]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("回收站中没有碎片。")
    else:
        for item in items:
            print(f"{item['title']}  [{item['entityId']}]  · 剩余 {item.get('daysRemaining', 0)} 天")
    return items


def restore_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    response = client.request("GET", client.project_path("trash"), query={"limit": 300})
    items = [item for item in response.get("items", []) if item.get("kind") == "fragment"]
    item = resolve_item(items, args.selector, noun="回收站碎片")
    mutation = client.mutate("POST", f"entities/{quote(item['entityId'], safe='')}/restore", {})
    detail = client.detail(item["entityId"])
    result = {"ok": True, "project": client.project, "revision": mutation.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已恢复：{item['title']}")
    return result


def history_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("operations"), query={"limit": args.limit})
    items = [item for item in response.get("items", []) if item.get("entityKind") == "fragment"]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有可显示的碎片操作。")
    else:
        for item in items:
            state = "可撤销" if item.get("canUndo") else str(item.get("undoBlockedReason") or "不可撤销")
            print(f"{item['id']:>5}  {item['label']}  · {state} · {format_time(item.get('createdAt'))}")
    return items


def undo_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    history = client.request("GET", client.project_path("operations"), query={"limit": 300})
    operation = next(
        (item for item in history.get("items", []) if int(item.get("id") or 0) == args.operation_id),
        None,
    )
    if operation is None:
        raise SelectionError(f"找不到仍在保留期内的操作：{args.operation_id}", code="operation_not_found")
    if operation.get("entityKind") != "fragment":
        raise CliError(
            f"操作 {args.operation_id} 不属于碎片，story-fragment 不会撤销其他内容",
            code="wrong_operation_kind",
            exit_code=2,
        )
    if not operation.get("canUndo"):
        raise CliError(
            str(operation.get("undoBlockedReason") or f"操作 {args.operation_id} 当前不可撤销"),
            code="undo_blocked",
        )
    response = client.mutate("POST", "operations/undo", {"operationId": args.operation_id})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "operationId": args.operation_id}
    emit(result, json_output=args.json_output, human=f"已撤销操作 {args.operation_id}。")
    return result


def yaml_scalar(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_fragment_markdown(detail: dict[str, Any], snapshot: dict[str, Any]) -> str:
    lines = ["---", f"title: {yaml_scalar(detail.get('title', ''))}"]
    if detail.get("fragmentType") == "line":
        lines.append("type: line")
    if detail.get("chapterNumber"):
        lines.append(f"chapterNumber: {int(detail['chapterNumber'])}")
    if detail.get("parentFragmentId"):
        parent = next(
            (item for item in snapshot.get("fragments", []) if item.get("entityId") == detail["parentFragmentId"]),
            None,
        )
        lines.append(f"story: {yaml_scalar(parent.get('title') if parent else detail['parentFragmentId'])}")
    if detail.get("tags"):
        lines.append("tags: [" + ", ".join(yaml_scalar(tag) for tag in detail["tags"]) + "]")
    if detail.get("key"):
        lines.append("key: true")
    if detail.get("climax"):
        lines.append("climax: true")
    if detail.get("references"):
        lines.append("references: [" + ", ".join(yaml_scalar(value) for value in detail["references"]) + "]")
    lines.extend(["---", "", str(detail.get("body") or "").rstrip(), ""])
    return "\n".join(lines)


def export_command(client: ApiClient, args: argparse.Namespace) -> str:
    snapshot = client.snapshot()
    fragment = resolve_fragment(snapshot, args.selector)
    detail = client.detail(fragment["entityId"])["data"]
    rendered = render_fragment_markdown(detail, snapshot)
    if detail.get("fragmentType") == "line":
        children = sorted(
            (item for item in snapshot.get("fragments", []) if item.get("parentFragmentId") == detail["entityId"]),
            key=lambda item: (
                item.get("chapterNumber") is None,
                int(item.get("chapterNumber") or 0),
                int(item.get("fragmentOrder") or 0),
            ),
        )
        for child in children:
            child_detail = client.detail(child["entityId"])["data"]
            chapter = child_detail.get("chapterNumber")
            heading = f"第 {chapter} 章 · {child_detail['title']}" if chapter else child_detail["title"]
            rendered += f"\n\n# {heading}\n\n{str(child_detail.get('body') or '').rstrip()}\n"
    if args.output:
        target = Path(args.output).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法写入导出文件：{target}（{error}）", code="file_error", exit_code=2) from error
        emit(
            {"ok": True, "project": client.project, "path": str(target.resolve()), "entityId": detail["entityId"]},
            json_output=args.json_output,
            human=f"已导出：{target}",
        )
    elif args.json_output:
        emit({"ok": True, "project": client.project, "entityId": detail["entityId"], "markdown": rendered}, json_output=True)
    else:
        sys.stdout.write(rendered)
    return rendered


def add_metadata_arguments(parser: argparse.ArgumentParser, *, editing: bool) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body", help="直接提供 Markdown 正文")
    body.add_argument("--body-file", metavar="FILE", help="从 UTF-8 文件读取正文；也可通过 stdin 传入")
    parser.add_argument("--tag", dest="tags", action="append", default=None, help="标签；可重复，传空集合可用 --clear-tags")
    parser.add_argument("--clear-tags", dest="tags", action="store_const", const=[])
    parser.add_argument("--person", dest="people", action="append", default=None, help="人物名称或 ID；可重复")
    parser.add_argument("--clear-people", dest="people", action="store_const", const=[])
    parser.add_argument("--appearance", action="append", default=None, help="正文中的出场人物名称；可重复")
    parser.add_argument("--clear-appearance", dest="appearance", action="store_const", const=[])
    parser.add_argument("--reference", dest="references", action="append", default=None, help="引用目标名称或 ID；可重复")
    parser.add_argument("--clear-references", dest="references", action="store_const", const=[])
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--key", dest="key_value", action="store_true", default=None, help="标记为关键剧情")
    key.add_argument("--no-key", dest="key_value", action="store_false", help="取消关键剧情")
    climax = parser.add_mutually_exclusive_group()
    climax.add_argument("--climax", dest="climax_value", action="store_true", default=None, help="标记为高潮剧情")
    climax.add_argument("--no-climax", dest="climax_value", action="store_false", help="取消高潮剧情")
    if not editing:
        parser.set_defaults(key_value=False, climax_value=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="story-fragment",
        description="通过已启动的 Story Teller 服务管理灵感碎片和剧情线",
    )
    parser.add_argument("--project", default="", help="Project ID；通常可自动发现")
    parser.add_argument("--web-url", default="", help="Hub 工作区或 Worker 的基础 URL")
    parser.add_argument("--json", dest="json_output", action="store_true", help="输出稳定 JSON，供自动化使用")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="列出碎片，默认按最后修改时间从新到旧")
    list_parser.add_argument("--tree", action="store_true", help="按剧情线和章号显示树状结构")
    list_parser.add_argument("--tag")
    list_parser.add_argument("--key", action="store_true")
    list_parser.add_argument("--climax", action="store_true")
    list_parser.add_argument("--lines", action="store_true", help="只显示剧情线")
    list_parser.add_argument("--limit", type=int, default=0)
    list_parser.set_defaults(handler=list_command)

    show = subparsers.add_parser("show", help="查看碎片完整内容")
    show.add_argument("selector", help="entityId、稳定 ID 或唯一标题")
    show.set_defaults(handler=show_command)

    add = subparsers.add_parser("add", help="创建碎片；标题是唯一必填业务参数")
    add.add_argument("title")
    add.add_argument("--line", action="store_true", help="创建剧情线容器")
    add.add_argument("--parent", help="父剧情线的标题或 ID")
    add.add_argument("--chapter-number", type=int)
    add.add_argument("--fragment-order", type=int)
    add.add_argument("--shift-following", action="store_true")
    add_metadata_arguments(add, editing=False)
    add.set_defaults(handler=add_command)

    edit = subparsers.add_parser("edit", help="只修改明确提供的字段")
    edit.add_argument("selector")
    edit.add_argument("--title")
    parent = edit.add_mutually_exclusive_group()
    parent.add_argument("--parent")
    parent.add_argument("--no-parent", action="store_true")
    chapter = edit.add_mutually_exclusive_group()
    chapter.add_argument("--chapter-number", type=int)
    chapter.add_argument("--no-chapter-number", action="store_true")
    fragment_type = edit.add_mutually_exclusive_group()
    fragment_type.add_argument("--line", dest="fragment_type", action="store_const", const="line")
    fragment_type.add_argument("--chapter", dest="fragment_type", action="store_const", const="chapter")
    edit.add_argument("--fragment-order", type=int)
    edit.add_argument("--shift-following", action="store_true")
    edit.add_argument("--plot-chapter", action="append", help="规划转正规章号：子碎片=N；可重复")
    edit.add_argument("--clear-plot-plan", action="store_true", help="清空整条剧情线的转正规划")
    add_metadata_arguments(edit, editing=True)
    edit.set_defaults(handler=edit_command)

    importer = subparsers.add_parser("import", help="按网页剪贴板规则批量导入 Markdown")
    importer.add_argument("file", nargs="?", default="-", help="UTF-8 文件，或 - 表示 stdin")
    importer.set_defaults(handler=import_command)

    promote = subparsers.add_parser("promote", help="把碎片转为正式剧情")
    promote.add_argument("selector")
    promote.add_argument("--chapter-number", type=int, required=True)
    promote.add_argument("--title")
    promote.add_argument("--story", dest="stories", action="append", default=None, help="正式剧情所属故事线；可重复")
    promote.set_defaults(handler=promote_command)

    delete = subparsers.add_parser("delete", help="将碎片或整条剧情线移入回收站")
    delete.add_argument("selector")
    delete.add_argument("--yes", action="store_true", help="非交互确认")
    delete.set_defaults(handler=delete_command)

    trash = subparsers.add_parser("trash", help="列出回收站中的碎片")
    trash.add_argument("--limit", type=int, default=100)
    trash.set_defaults(handler=trash_command)

    restore = subparsers.add_parser("restore", help="恢复回收站中的碎片")
    restore.add_argument("selector")
    restore.set_defaults(handler=restore_command)

    history = subparsers.add_parser("history", help="列出碎片操作历史")
    history.add_argument("--limit", type=int, default=100)
    history.set_defaults(handler=history_command)

    undo = subparsers.add_parser("undo", help="按操作 ID 撤销")
    undo.add_argument("operation_id", type=int)
    undo.set_defaults(handler=undo_command)

    exporter = subparsers.add_parser("export", help="导出一个碎片或整条剧情线的 Markdown")
    exporter.add_argument("selector")
    exporter.add_argument("-o", "--output")
    exporter.set_defaults(handler=export_command)
    return parser


def normalize_global_options(argv: Sequence[str]) -> list[str]:
    """Allow the three global options before or after a subcommand."""
    source = list(argv)
    global_arguments: list[str] = []
    command_arguments: list[str] = []
    index = 0
    while index < len(source):
        value = source[index]
        if value == "--json":
            global_arguments.append(value)
            index += 1
            continue
        if value in {"--project", "--web-url"}:
            if index + 1 >= len(source):
                command_arguments.append(value)
                index += 1
                continue
            global_arguments.append(value)
            global_arguments.append(source[index + 1])
            index += 2
            continue
        if value.startswith("--project=") or value.startswith("--web-url="):
            global_arguments.append(value)
            index += 1
            continue
        command_arguments.append(value)
        index += 1
    return [*global_arguments, *command_arguments]


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(normalize_global_options(raw_arguments))
    try:
        workspace = discover_workspace()
        project = select_project(workspace, args.project)
        client = ApiClient(default_web_url(workspace, args.web_url), project)
        client.meta()
        args.handler(client, args)
        return 0
    except CliError as error:
        if args.json_output:
            payload = {"ok": False, "error": str(error), "code": error.code}
            if error.details:
                payload["details"] = error.details
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"story-fragment: {error}", file=sys.stderr)
        return error.exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
