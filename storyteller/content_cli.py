from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from storyteller.fragment_cli import (
    ApiClient,
    CliError,
    SelectionError,
    emit,
    format_time,
    resolve_item,
    resolve_person,
    resolve_reference,
    resolve_story,
)


def resolve_plot(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("plots", []), selector, noun="正式剧情")


def resolve_entry(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    value = str(selector or "").strip()
    candidates = list(snapshot.get("entries", []))
    exact = [
        item for item in candidates
        if value in {str(item.get("entityId") or ""), str(item.get("id") or ""), str(item.get("name") or "").strip()}
        or value in [str(alias).strip() for alias in item.get("aliases", [])]
    ]
    if not exact:
        folded = value.casefold()
        exact = [
            item for item in candidates
            if folded == str(item.get("name") or "").strip().casefold()
            or folded in [str(alias).strip().casefold() for alias in item.get("aliases", [])]
        ]
    if not exact:
        raise SelectionError(f"找不到设定：{value}")
    if len(exact) > 1:
        choices = "、".join(str(item.get("entityId") or item.get("id")) for item in exact[:8])
        raise SelectionError(f"设定选择器“{value}”不唯一，请改用 ID：{choices}", code="ambiguous_selector")
    return exact[0]


def resolve_chapter(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("chapters", []), selector, noun="篇章", title_keys=("label",))


def read_file(path: str, label: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(f"无法读取{label}文件：{path}（{error}）", code="file_error", exit_code=2) from error


def apply_text_argument(
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    argument: str,
    file_argument: str,
    clear_argument: str,
    field: str,
    label: str,
) -> None:
    inline = getattr(args, argument, None)
    filename = getattr(args, file_argument, None)
    clear = bool(getattr(args, clear_argument, False))
    if clear:
        payload[field] = ""
    elif filename is not None:
        payload[field] = read_file(filename, label)
    elif inline is not None:
        payload[field] = inline


def apply_list_argument(
    payload: dict[str, Any],
    args: argparse.Namespace,
    *,
    argument: str,
    clear_argument: str,
    field: str,
) -> None:
    values = getattr(args, argument, None)
    clear = bool(getattr(args, clear_argument, False))
    if values is not None and clear:
        raise CliError(f"不能同时设置和清空 {field}", code="invalid_argument", exit_code=2)
    if clear:
        payload[field] = []
    elif values is not None:
        payload[field] = list(values)


def confirm_action(message: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CliError("非交互环境必须添加 --yes", code="confirmation_required", exit_code=2)
    return input(f"{message}？[y/N] ").strip().lower() in {"y", "yes"}


def mutation_result(
    client: ApiClient,
    response: dict[str, Any],
    detail: dict[str, Any] | None,
    args: argparse.Namespace,
    human: str,
) -> dict[str, Any]:
    result = {
        "ok": True,
        "project": client.project,
        "revision": response.get("projectRevision"),
        "item": detail,
    }
    emit(result, json_output=args.json_output, human=human)
    return result


def kind_trash(client: ApiClient, args: argparse.Namespace, kind: str, label: str) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("trash"), query={"limit": args.limit})
    items = [item for item in response.get("items", []) if item.get("kind") == kind]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print(f"回收站中没有{label}。")
    else:
        for item in items:
            print(f"{item['title']}  [{item['entityId']}]  · 剩余 {item.get('daysRemaining', 0)} 天")
    return items


def kind_restore(client: ApiClient, args: argparse.Namespace, kind: str, label: str) -> dict[str, Any]:
    response = client.request("GET", client.project_path("trash"), query={"limit": 300})
    items = [item for item in response.get("items", []) if item.get("kind") == kind]
    item = resolve_item(items, args.selector, noun=f"回收站{label}")
    mutation = client.mutate("POST", f"entities/{quote(item['entityId'], safe='')}/restore", {})
    return mutation_result(client, mutation, client.detail(item["entityId"]), args, f"已恢复：{item['title']}")


def kind_history(client: ApiClient, args: argparse.Namespace, kind: str, label: str) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("operations"), query={"limit": args.limit})
    items = [item for item in response.get("items", []) if item.get("entityKind") == kind]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print(f"没有{label}操作。")
    else:
        for item in items:
            state = "可撤销" if item.get("canUndo") else str(item.get("undoBlockedReason") or "不可撤销")
            print(f"{item['id']:>5}  {item['label']}  · {state} · {format_time(item.get('createdAt'))}")
    return items


def kind_undo(client: ApiClient, args: argparse.Namespace, kind: str, label: str) -> dict[str, Any]:
    history = client.request("GET", client.project_path("operations"), query={"limit": 300})
    operation = next((item for item in history.get("items", []) if int(item.get("id") or 0) == args.operation_id), None)
    if operation is None:
        raise SelectionError(f"找不到仍在保留期内的操作：{args.operation_id}", code="operation_not_found")
    if operation.get("entityKind") != kind:
        raise CliError(f"操作 {args.operation_id} 不属于{label}", code="wrong_operation_kind", exit_code=2)
    if not operation.get("canUndo"):
        raise CliError(str(operation.get("undoBlockedReason") or "当前不可撤销"), code="undo_blocked")
    response = client.mutate("POST", "operations/undo", {"operationId": args.operation_id})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "operationId": args.operation_id}
    emit(result, json_output=args.json_output, human=f"已撤销操作 {args.operation_id}。")
    return result


def plot_label(item: dict[str, Any]) -> str:
    chapter = item.get("chapterNumber")
    prefix = f"第 {chapter} 章 · " if chapter is not None else ""
    return f"{prefix}{item.get('title', '')}  [{item.get('status') or '—'} · {item.get('entityId', '')}]"


def plot_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    snapshot = client.snapshot()
    items = list(snapshot.get("plots", []))
    if args.status:
        items = [item for item in items if item.get("status") == args.status]
    if args.tag:
        items = [item for item in items if args.tag in item.get("tags", [])]
    if args.story:
        story_id = resolve_story(snapshot, args.story)["entityId"]
        items = [item for item in items if story_id in item.get("stories", [])]
    if args.query:
        query = args.query.casefold()
        items = [item for item in items if query in " ".join((
            str(item.get("title") or ""), str(item.get("summary") or ""),
            str(item.get("bodyPreview") or ""), " ".join(item.get("tags", [])),
        )).casefold()]
    items.sort(key=lambda item: (int(item.get("sequence") or 0), str(item.get("entityId") or "")))
    if args.limit:
        items = items[: args.limit]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有符合条件的正式剧情。")
    else:
        for item in items:
            print(plot_label(item))
    return items


def plot_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    plot = resolve_plot(snapshot, args.selector)
    detail = client.detail(plot["entityId"])
    data = detail["data"]
    people = [item for item in snapshot.get("characters", []) if item["entityId"] in data.get("people", [])]
    entries = [item for item in snapshot.get("entries", []) if item["entityId"] in data.get("entries", [])]
    stories = [item for item in snapshot.get("timeline", {}).get("lines", []) if item["entityId"] in data.get("stories", [])]
    result = {"ok": True, "project": client.project, "item": detail, "related": {"characters": people, "entries": entries, "stories": stories}}
    if args.json_output:
        emit(result, json_output=True)
    else:
        print(plot_label(data))
        if data.get("summary"):
            print("摘要：" + str(data["summary"]))
        if people:
            print("人物：" + "、".join(item["name"] for item in people))
        if entries:
            print("设定：" + "、".join(item["name"] for item in entries))
        if stories:
            print("故事线：" + "、".join(item["name"] for item in stories))
        if data.get("body"):
            print("\n" + str(data["body"]).rstrip())
    return result


def plot_payload(
    args: argparse.Namespace,
    snapshot: dict[str, Any],
    *,
    editing: bool,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for argument, field in (
        ("title", "title"), ("stable_id", "stableId"), ("chapter_number", "chapterNumber"),
        ("summary", "summary"), ("status", "status"), ("accent", "accent"),
        ("story_position_mode", "storyPositionMode"), ("story_sort_key", "storySortKey"),
        ("key_value", "key"), ("climax_value", "climax"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    if getattr(args, "shift_following", False):
        payload["shiftFollowing"] = True
    apply_text_argument(payload, args, argument="body", file_argument="body_file", clear_argument="clear_body", field="body", label="剧情正文")
    if getattr(args, "clear_summary", False):
        payload["summary"] = ""

    apply_list_argument(payload, args, argument="tags", clear_argument="clear_tags", field="tags")
    apply_list_argument(payload, args, argument="appearance_names", clear_argument="clear_appearance_names", field="appearanceNames")

    people_values = getattr(args, "people", None)
    if people_values is not None and getattr(args, "clear_people", False):
        raise CliError("不能同时设置和清空出场人物", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_people", False):
        payload["people"] = []
    elif people_values is not None:
        payload["people"] = [resolve_person(snapshot, value)["entityId"] for value in people_values]

    entry_values = getattr(args, "entries", None)
    if entry_values is not None and getattr(args, "clear_entries", False):
        raise CliError("不能同时设置和清空关联设定", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_entries", False):
        payload["entries"] = []
    elif entry_values is not None:
        payload["entries"] = [resolve_entry(snapshot, value)["entityId"] for value in entry_values]

    story_values = getattr(args, "stories", None)
    if story_values is not None and getattr(args, "clear_stories", False):
        raise CliError("不能同时设置和清空故事线", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_stories", False):
        payload["stories"] = []
    elif story_values is not None:
        payload["stories"] = [resolve_story(snapshot, value)["entityId"] for value in story_values]

    reference_values = getattr(args, "references", None)
    if reference_values is not None and getattr(args, "clear_references", False):
        raise CliError("不能同时设置和清空引用", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_references", False):
        payload["references"] = []
    elif reference_values is not None:
        payload["references"] = [resolve_reference(snapshot, value)["entityId"] for value in reference_values]

    if getattr(args, "chapter", None) is not None:
        payload["chapterId"] = resolve_chapter(snapshot, args.chapter)["entityId"]
    elif getattr(args, "clear_chapter", False):
        payload["chapterId"] = None
    if getattr(args, "after", None) is not None:
        payload["afterEntityId"] = resolve_plot(snapshot, args.after)["entityId"]
    if getattr(args, "anchor_plot", None) is not None:
        payload["storyAnchorPlotId"] = resolve_plot(snapshot, args.anchor_plot)["entityId"]
    elif getattr(args, "clear_anchor", False):
        payload["storyAnchorPlotId"] = None

    collections_changed = any(field in payload for field in ("people", "entries", "references"))
    if collections_changed:
        character_ids = {item["entityId"] for item in snapshot.get("characters", [])}
        entry_ids = {item["entityId"] for item in snapshot.get("entries", [])}
        current_references = list((current or {}).get("references", []))
        current_people = list((current or {}).get("people", []))
        current_entries = list((current or {}).get("entries", []))
        people = list(payload.get("people", current_people))
        entries = list(payload.get("entries", current_entries))
        references = list(payload.get("references", current_references))
        references = [item for item in references if item not in character_ids and item not in entry_ids]
        payload["references"] = list(dict.fromkeys([*references, *people, *entries]))

    mode = payload.get("storyPositionMode")
    if mode in {"before", "after"} and "storyAnchorPlotId" not in payload:
        raise CliError("before/after 故事位置必须通过 --anchor-plot 指定参考剧情", code="invalid_argument", exit_code=2)
    if mode == "fixed" and not str(payload.get("storySortKey") or "").strip():
        raise CliError("fixed 故事位置必须通过 --story-sort-key 指定数字位置", code="invalid_argument", exit_code=2)
    if editing and not payload:
        raise CliError("没有提供需要修改的字段", code="no_changes", exit_code=2)
    return payload


def plot_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    if args.chapter_number is None:
        args.chapter_number = max((int(item.get("chapterNumber") or 0) for item in snapshot.get("plots", [])), default=0) + 1
    payload = plot_payload(args, snapshot, editing=False)
    response = client.mutate("POST", "plots", payload, retry_create_conflict=True)
    changed = [item for item in response.get("changed", {}).get("plots", []) if item.get("title") == args.title]
    detail = client.detail(changed[-1]["entityId"]) if changed else None
    return mutation_result(client, response, detail, args, f"已创建剧情：{args.title}")


def plot_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    plot = resolve_plot(snapshot, args.selector)
    current = client.detail(plot["entityId"])["data"]
    payload = plot_payload(args, snapshot, editing=True, current=current)
    payload["entityRevision"] = plot["revision"]
    response = client.mutate("PATCH", f"plots/{quote(plot['entityId'], safe='')}", payload)
    detail = client.detail(plot["entityId"])
    return mutation_result(client, response, detail, args, f"已更新剧情：{detail['data']['title']}")


def plot_delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    plot = resolve_plot(snapshot, args.selector)
    if not confirm_action(f"将“{plot['title']}”移入回收站", assume_yes=args.yes):
        result = {"ok": True, "cancelled": True, "item": plot}
        emit(result, json_output=args.json_output, human="已取消。")
        return result
    response = client.mutate("DELETE", f"entities/{quote(plot['entityId'], safe='')}", {})
    return mutation_result(client, response, None, args, f"已移入回收站：{plot['title']}")


def plot_to_fragment_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    plot = resolve_plot(snapshot, args.selector)
    if not confirm_action(
        f"把“{plot['title']}”放入碎片箱；原剧情进入回收站且整次操作可撤销",
        assume_yes=args.yes,
    ):
        result = {"ok": True, "cancelled": True, "item": plot}
        emit(result, json_output=args.json_output, human="已取消。")
        return result
    response = client.mutate("POST", f"plots/{quote(plot['entityId'], safe='')}/to-fragment", {})
    changed = list(response.get("changed", {}).get("fragments", []))
    detail = client.detail(changed[-1]["entityId"]) if changed else None
    result = {
        "ok": True,
        "project": client.project,
        "revision": response.get("projectRevision"),
        "sourceEntityId": plot["entityId"],
        "item": detail,
    }
    emit(result, json_output=args.json_output, human=f"已放入碎片箱：{plot['title']}")
    return result


def plot_trash_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    return kind_trash(client, args, "plot", "正式剧情")


def plot_restore_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    return kind_restore(client, args, "plot", "正式剧情")


def plot_history_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("operations"), query={"limit": args.limit})
    items = [
        item for item in response.get("items", [])
        if item.get("entityKind") == "plot"
        or (item.get("action") == "convert" and str(item.get("label") or "").startswith("剧情放入碎片："))
    ]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有正式剧情操作。")
    else:
        for item in items:
            state = "可撤销" if item.get("canUndo") else str(item.get("undoBlockedReason") or "不可撤销")
            print(f"{item['id']:>5}  {item['label']}  · {state} · {format_time(item.get('createdAt'))}")
    return items


def plot_undo_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    history = client.request("GET", client.project_path("operations"), query={"limit": 300})
    operation = next((item for item in history.get("items", []) if int(item.get("id") or 0) == args.operation_id), None)
    if operation is None:
        raise SelectionError(f"找不到仍在保留期内的操作：{args.operation_id}", code="operation_not_found")
    is_plot_operation = operation.get("entityKind") == "plot" or (
        operation.get("action") == "convert"
        and str(operation.get("label") or "").startswith("剧情放入碎片：")
    )
    if not is_plot_operation:
        raise CliError(f"操作 {args.operation_id} 不属于正式剧情", code="wrong_operation_kind", exit_code=2)
    if not operation.get("canUndo"):
        raise CliError(str(operation.get("undoBlockedReason") or "当前不可撤销"), code="undo_blocked")
    response = client.mutate("POST", "operations/undo", {"operationId": args.operation_id})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "operationId": args.operation_id}
    emit(result, json_output=args.json_output, human=f"已撤销操作 {args.operation_id}。")
    return result


def render_plot_markdown(plot: dict[str, Any]) -> str:
    chapter = plot.get("chapterNumber") if plot.get("chapterNumber") is not None else plot.get("sequence")
    heading = f"# 第 {chapter} 章" + (f" · {str(plot.get('title') or '').strip()}" if str(plot.get("title") or "").strip() else "")
    return f"{heading}\n\n{str(plot.get('body') or '').strip()}\n"


def select_export_items(
    snapshot: dict[str, Any],
    selector: str | None,
    export_all: bool,
    from_selector: str | None,
    to_selector: str | None,
) -> list[dict[str, Any]]:
    items = list(snapshot.get("plots", []))
    range_requested = from_selector is not None or to_selector is not None
    if export_all:
        if selector or range_requested:
            raise CliError("--all 不能与剧情选择器或范围同时使用", code="invalid_argument", exit_code=2)
        return items
    if range_requested:
        if selector or from_selector is None or to_selector is None:
            raise CliError("范围导出必须同时提供 --from 和 --to", code="invalid_argument", exit_code=2)
        first, last = resolve_plot(snapshot, from_selector), resolve_plot(snapshot, to_selector)
        indexes = {item["entityId"]: index for index, item in enumerate(items)}
        start, end = sorted((indexes[first["entityId"]], indexes[last["entityId"]]))
        return items[start : end + 1]
    if not selector:
        raise CliError("请提供剧情选择器，或使用 --all / --from 与 --to", code="invalid_argument", exit_code=2)
    return [resolve_plot(snapshot, selector)]


def plot_export_command(client: ApiClient, args: argparse.Namespace) -> str:
    snapshot = client.snapshot()
    selected = select_export_items(snapshot, args.selector, args.all, args.from_plot, args.to_plot)
    if not selected:
        raise SelectionError("没有可导出的正式剧情")
    details = [client.detail(item["entityId"])["data"] for item in selected]
    rendered = "\n\n---\n\n".join(render_plot_markdown(item).rstrip() for item in details) + "\n"
    entity_ids = [item["entityId"] for item in details]
    result = {"ok": True, "project": client.project, "entityIds": entity_ids, "count": len(details)}
    if args.output:
        target = Path(args.output).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法写入导出文件：{target}（{error}）", code="file_error", exit_code=2) from error
        result["path"] = str(target.resolve())
        emit(result, json_output=args.json_output, human=f"已导出 {len(details)} 篇剧情：{target}")
    elif args.json_output:
        emit({**result, "markdown": rendered}, json_output=True)
    else:
        sys.stdout.write(rendered)
    return rendered


def add_plot_fields(parser: argparse.ArgumentParser, *, editing: bool) -> None:
    if editing:
        parser.add_argument("--title")
    else:
        parser.add_argument("title")
        parser.add_argument("--id", dest="stable_id")
        parser.add_argument("--after", help="插入到指定剧情之后")
    parser.add_argument("--chapter-number", type=int)
    parser.add_argument("--shift-following", action="store_true", help="章号冲突时顺延连续后续章节")
    chapter = parser.add_mutually_exclusive_group()
    chapter.add_argument("--chapter", help="所属篇章的 ID 或唯一名称")
    chapter.add_argument("--clear-chapter", action="store_true")
    summary = parser.add_mutually_exclusive_group()
    summary.add_argument("--summary")
    summary.add_argument("--clear-summary", action="store_true")
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body")
    body.add_argument("--body-file")
    body.add_argument("--clear-body", action="store_true")
    parser.add_argument("--status", default=None if editing else "草稿")
    parser.add_argument("--accent", default=None if editing else "#3f7fc1")
    parser.add_argument("--tag", dest="tags", action="append")
    parser.add_argument("--clear-tags", action="store_true")
    parser.add_argument("--person", dest="people", action="append")
    parser.add_argument("--clear-people", action="store_true")
    parser.add_argument("--appearance", dest="appearance_names", action="append")
    parser.add_argument("--clear-appearance-names", action="store_true")
    parser.add_argument("--entry", dest="entries", action="append")
    parser.add_argument("--clear-entries", action="store_true")
    parser.add_argument("--story", dest="stories", action="append")
    parser.add_argument("--clear-stories", action="store_true")
    parser.add_argument("--reference", dest="references", action="append")
    parser.add_argument("--clear-references", action="store_true")
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--key", dest="key_value", action="store_true", default=None if editing else False)
    key.add_argument("--no-key", dest="key_value", action="store_false")
    climax = parser.add_mutually_exclusive_group()
    climax.add_argument("--climax", dest="climax_value", action="store_true", default=None if editing else False)
    climax.add_argument("--no-climax", dest="climax_value", action="store_false")
    parser.add_argument("--story-position", dest="story_position_mode", choices=("follow_reading", "before", "after", "fixed"))
    anchor = parser.add_mutually_exclusive_group()
    anchor.add_argument("--anchor-plot")
    anchor.add_argument("--clear-anchor", action="store_true")
    parser.add_argument("--story-sort-key")


def register_plot_domain(domains: argparse._SubParsersAction) -> None:
    plot = domains.add_parser("plot", aliases=["plots"], help="管理正式剧情、转碎片和 Markdown 导出")
    commands = plot.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="列出和筛选正式剧情")
    listing.add_argument("--status")
    listing.add_argument("--tag")
    listing.add_argument("--story")
    listing.add_argument("--query", "-q")
    listing.add_argument("--limit", type=int, default=0)
    listing.set_defaults(handler=plot_list_command)
    show = commands.add_parser("show", help="查看完整剧情和关联内容")
    show.add_argument("selector")
    show.set_defaults(handler=plot_show_command)
    add = commands.add_parser("add", help="新建正式剧情；未给章号时追加到末尾")
    add_plot_fields(add, editing=False)
    add.set_defaults(handler=plot_add_command)
    edit = commands.add_parser("edit", help="只修改明确提供的剧情字段")
    edit.add_argument("selector")
    add_plot_fields(edit, editing=True)
    edit.set_defaults(handler=plot_edit_command)
    delete = commands.add_parser("delete", help="将剧情移入回收站")
    delete.add_argument("selector")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(handler=plot_delete_command)
    convert = commands.add_parser("to-fragment", aliases=["demote"], help="把正式剧情放入碎片箱")
    convert.add_argument("selector")
    convert.add_argument("--yes", action="store_true")
    convert.set_defaults(handler=plot_to_fragment_command)
    trash = commands.add_parser("trash", help="列出剧情回收站")
    trash.add_argument("--limit", type=int, default=100)
    trash.set_defaults(handler=plot_trash_command)
    restore = commands.add_parser("restore", help="恢复回收站剧情")
    restore.add_argument("selector")
    restore.set_defaults(handler=plot_restore_command)
    history = commands.add_parser("history", help="列出剧情操作历史")
    history.add_argument("--limit", type=int, default=100)
    history.set_defaults(handler=plot_history_command)
    undo = commands.add_parser("undo", help="撤销剧情操作")
    undo.add_argument("operation_id", type=int)
    undo.set_defaults(handler=plot_undo_command)
    exporter = commands.add_parser("export", help="单项、范围或全部导出剧情 Markdown")
    exporter.add_argument("selector", nargs="?")
    exporter.add_argument("--all", action="store_true")
    exporter.add_argument("--from", dest="from_plot")
    exporter.add_argument("--to", dest="to_plot")
    exporter.add_argument("-o", "--output")
    exporter.set_defaults(handler=plot_export_command)


def entry_label(item: dict[str, Any]) -> str:
    subtype = f" · {item.get('subtype')}" if item.get("subtype") else ""
    return f"{item.get('name', '')}  [{item.get('type', '—')}{subtype} · {item.get('entityId', '')}]"


def entry_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    items = list(client.snapshot().get("entries", []))
    if args.type:
        items = [item for item in items if item.get("type") == args.type]
    if args.tag:
        items = [item for item in items if args.tag in item.get("tags", [])]
    if args.query:
        query = args.query.casefold()
        items = [item for item in items if query in " ".join((
            str(item.get("name") or ""), " ".join(item.get("aliases", [])),
            str(item.get("bodyPreview") or ""), " ".join(item.get("tags", [])),
        )).casefold()]
    items.sort(key=lambda item: (str(item.get("type") or ""), str(item.get("name") or "")))
    if args.limit:
        items = items[: args.limit]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有符合条件的设定或组织。")
    else:
        for item in items:
            print(entry_label(item))
    return items


def entry_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    entry = resolve_entry(snapshot, args.selector)
    detail = client.detail(entry["entityId"])
    data = detail["data"]
    character_map = {item["entityId"]: item for item in snapshot.get("characters", [])}
    members = [{**member, "character": character_map.get(member["characterId"])} for member in data.get("members", [])]
    plots = [item for item in snapshot.get("plots", []) if entry["entityId"] in item.get("entries", [])]
    result = {"ok": True, "project": client.project, "item": detail, "members": members, "related": {"plots": plots}}
    if args.json_output:
        emit(result, json_output=True)
    else:
        print(entry_label(data))
        if data.get("area") or data.get("status"):
            print(f"区域：{data.get('area') or '—'} · 状态：{data.get('status') or '—'}")
        if data.get("aliases"):
            print("别名：" + "、".join(data["aliases"]))
        if members:
            print("成员：" + "、".join(
                f"{(member.get('character') or {}).get('name', member['characterId'])}（{member.get('role') or member.get('status') or '成员'}）"
                for member in members
            ))
        if data.get("body"):
            print("\n" + str(data["body"]).rstrip())
    return result


def parse_member(raw: str, snapshot: dict[str, Any]) -> dict[str, str]:
    selector, separator, metadata = raw.partition("=")
    character = resolve_person(snapshot, selector.strip())
    role = ""
    status = "现成员"
    if separator:
        role, status_separator, requested_status = metadata.partition(",")
        role = role.strip()
        if status_separator and requested_status.strip():
            status = requested_status.strip()
    return {"characterId": str(character["entityId"]), "role": role, "status": status}


def parse_members(values: Sequence[str] | None, snapshot: dict[str, Any]) -> list[dict[str, str]] | None:
    if values is None:
        return None
    members = [parse_member(value, snapshot) for value in values]
    identifiers = [item["characterId"] for item in members]
    if len(identifiers) != len(set(identifiers)):
        raise CliError("组织成员不能重复", code="invalid_argument", exit_code=2)
    return members


def entry_payload(
    args: argparse.Namespace,
    snapshot: dict[str, Any],
    *,
    editing: bool,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for argument, field in (
        ("name", "name"), ("stable_id", "stableId"), ("entry_type", "type"),
        ("subtype", "subtype"), ("area", "area"), ("status", "status"), ("accent", "accent"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    for argument, field in (
        ("clear_subtype", "subtype"), ("clear_area", "area"), ("clear_status", "status"),
    ):
        if getattr(args, argument, False):
            payload[field] = ""
    apply_text_argument(payload, args, argument="body", file_argument="body_file", clear_argument="clear_body", field="body", label="设定正文")
    apply_list_argument(payload, args, argument="aliases", clear_argument="clear_aliases", field="aliases")
    apply_list_argument(payload, args, argument="tags", clear_argument="clear_tags", field="tags")

    people_values = getattr(args, "people", None)
    if people_values is not None and getattr(args, "clear_people", False):
        raise CliError("不能同时设置和清空关联人物", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_people", False):
        payload["people"] = []
    elif people_values is not None:
        payload["people"] = [resolve_person(snapshot, value)["entityId"] for value in people_values]

    members = parse_members(getattr(args, "members", None), snapshot)
    if members is not None and people_values is not None:
        raise CliError("组织成员和普通关联人物不能在同一次操作中同时设置", code="invalid_argument", exit_code=2)
    if members is not None and getattr(args, "clear_members", False):
        raise CliError("不能同时设置和清空组织成员", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_members", False):
        payload["members"] = []
    elif members is not None:
        payload["members"] = members
        payload["people"] = [item["characterId"] for item in members]

    reference_values = getattr(args, "references", None)
    if reference_values is not None and getattr(args, "clear_references", False):
        raise CliError("不能同时设置和清空引用", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_references", False):
        payload["references"] = []
    elif reference_values is not None:
        payload["references"] = [resolve_reference(snapshot, value)["entityId"] for value in reference_values]

    if any(field in payload for field in ("people", "members", "references")):
        character_ids = {item["entityId"] for item in snapshot.get("characters", [])}
        current_people = list((current or {}).get("people", []))
        current_references = list((current or {}).get("references", []))
        people = list(payload.get("people", current_people))
        references = list(payload.get("references", current_references))
        references = [item for item in references if item not in character_ids]
        payload["references"] = list(dict.fromkeys([*references, *people]))
    if editing and not payload:
        raise CliError("没有提供需要修改的字段", code="no_changes", exit_code=2)
    return payload


def entry_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    payload = entry_payload(args, snapshot, editing=False)
    response = client.mutate("POST", "entries", payload, retry_create_conflict=True)
    changed = [item for item in response.get("changed", {}).get("entries", []) if item.get("name") == args.name]
    detail = client.detail(changed[-1]["entityId"]) if changed else None
    return mutation_result(client, response, detail, args, f"已创建设定：{args.name}")


def entry_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    entry = resolve_entry(snapshot, args.selector)
    current = client.detail(entry["entityId"])["data"]
    payload = entry_payload(args, snapshot, editing=True, current=current)
    requested_name = str(payload.get("name") or "").strip()
    if requested_name and requested_name != str(entry.get("name") or "").strip() and not args.yes:
        sources = {
            item["entityId"] for collection in ("characters", "plots", "entries", "fragments", "relationships")
            for item in snapshot.get(collection, [])
            if entry["entityId"] in item.get("references", []) or entry["entityId"] in item.get("entries", [])
        }
        if not confirm_action(
            f"将“{entry['name']}”重命名为“{requested_name}”，并同步更新 {len(sources)} 项稳定引用",
            assume_yes=False,
        ):
            result = {"ok": True, "cancelled": True, "item": entry}
            emit(result, json_output=args.json_output, human="已取消。")
            return result
    payload["entityRevision"] = entry["revision"]
    response = client.mutate("PATCH", f"entries/{quote(entry['entityId'], safe='')}", payload)
    detail = client.detail(entry["entityId"])
    return mutation_result(client, response, detail, args, f"已更新设定：{detail['data']['name']}")


def entry_delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    entry = resolve_entry(snapshot, args.selector)
    if not confirm_action(f"将“{entry['name']}”移入回收站", assume_yes=args.yes):
        result = {"ok": True, "cancelled": True, "item": entry}
        emit(result, json_output=args.json_output, human="已取消。")
        return result
    response = client.mutate("DELETE", f"entities/{quote(entry['entityId'], safe='')}", {})
    return mutation_result(client, response, None, args, f"已移入回收站：{entry['name']}")


def entry_trash_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    return kind_trash(client, args, "entry", "设定")


def entry_restore_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    return kind_restore(client, args, "entry", "设定")


def entry_history_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    return kind_history(client, args, "entry", "设定")


def entry_undo_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    return kind_undo(client, args, "entry", "设定")


def current_members(client: ApiClient, snapshot: dict[str, Any], selector: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    entry = resolve_entry(snapshot, selector)
    detail = client.detail(entry["entityId"])
    if detail["data"].get("type") != "组织":
        raise CliError("只有组织设定可以维护成员", code="invalid_entry_type", exit_code=2)
    members = [
        {"characterId": str(item["characterId"]), "role": str(item.get("role") or ""), "status": str(item.get("status") or "现成员")}
        for item in detail["data"].get("members", [])
    ]
    return entry, detail, members


def entry_member_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    snapshot = client.snapshot()
    _entry, _detail, members = current_members(client, snapshot, args.entry)
    names = {item["entityId"]: item["name"] for item in snapshot.get("characters", [])}
    items = [{**item, "name": names.get(item["characterId"], item["characterId"])} for item in members]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("组织还没有成员。")
    else:
        for item in items:
            print(f"{item['name']}  [{item['characterId']}] · {item['role'] or '未填写身份'} · {item['status']}")
    return items


def save_members(
    client: ApiClient,
    args: argparse.Namespace,
    entry: dict[str, Any],
    members: list[dict[str, str]],
    human: str,
) -> dict[str, Any]:
    snapshot = client.snapshot()
    current = client.detail(entry["entityId"])["data"]
    character_ids = {item["entityId"] for item in snapshot.get("characters", [])}
    references = [item for item in current.get("references", []) if item not in character_ids]
    member_ids = [item["characterId"] for item in members]
    response = client.mutate(
        "PATCH",
        f"entries/{quote(entry['entityId'], safe='')}",
        {
            "members": members,
            "people": member_ids,
            "references": list(dict.fromkeys([*references, *member_ids])),
            "entityRevision": entry["revision"],
        },
    )
    return mutation_result(client, response, client.detail(entry["entityId"]), args, human)


def entry_member_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    entry, _detail, members = current_members(client, snapshot, args.entry)
    character = resolve_person(snapshot, args.character)
    if any(item["characterId"] == character["entityId"] for item in members):
        raise CliError(f"{character['name']} 已经是该组织成员", code="member_exists", exit_code=2)
    members.append({"characterId": character["entityId"], "role": args.role or "", "status": args.status or "现成员"})
    return save_members(client, args, entry, members, f"已添加组织成员：{character['name']}")


def entry_member_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    entry, _detail, members = current_members(client, snapshot, args.entry)
    character = resolve_person(snapshot, args.character)
    member = next((item for item in members if item["characterId"] == character["entityId"]), None)
    if member is None:
        raise SelectionError(f"{character['name']} 不是该组织成员")
    if args.role is None and args.status is None:
        raise CliError("请至少提供 --role 或 --status", code="no_changes", exit_code=2)
    if args.role is not None:
        member["role"] = args.role
    if args.status is not None:
        member["status"] = args.status
    return save_members(client, args, entry, members, f"已更新组织成员：{character['name']}")


def entry_member_remove_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    entry, _detail, members = current_members(client, snapshot, args.entry)
    character = resolve_person(snapshot, args.character)
    if not any(item["characterId"] == character["entityId"] for item in members):
        raise SelectionError(f"{character['name']} 不是该组织成员")
    remaining = [item for item in members if item["characterId"] != character["entityId"]]
    return save_members(client, args, entry, remaining, f"已移除组织成员：{character['name']}")


def add_entry_fields(parser: argparse.ArgumentParser, *, editing: bool) -> None:
    if editing:
        parser.add_argument("--name")
    else:
        parser.add_argument("name")
        parser.add_argument("--id", dest="stable_id")
    parser.add_argument("--type", dest="entry_type", default=None if editing else "地点")
    subtype = parser.add_mutually_exclusive_group()
    subtype.add_argument("--subtype")
    subtype.add_argument("--clear-subtype", action="store_true")
    area = parser.add_mutually_exclusive_group()
    area.add_argument("--area")
    area.add_argument("--clear-area", action="store_true")
    status = parser.add_mutually_exclusive_group()
    status.add_argument("--status")
    status.add_argument("--clear-status", action="store_true")
    parser.add_argument("--accent")
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body")
    body.add_argument("--body-file")
    body.add_argument("--clear-body", action="store_true")
    parser.add_argument("--alias", dest="aliases", action="append")
    parser.add_argument("--clear-aliases", action="store_true")
    parser.add_argument("--tag", dest="tags", action="append")
    parser.add_argument("--clear-tags", action="store_true")
    parser.add_argument("--person", dest="people", action="append")
    parser.add_argument("--clear-people", action="store_true")
    parser.add_argument("--member", dest="members", action="append", metavar="PERSON[=ROLE[,STATUS]]")
    parser.add_argument("--clear-members", action="store_true")
    parser.add_argument("--reference", dest="references", action="append")
    parser.add_argument("--clear-references", action="store_true")


def register_entry_domain(domains: argparse._SubParsersAction) -> None:
    entry = domains.add_parser("entry", aliases=["entries"], help="管理设定、组织和组织成员")
    commands = entry.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="列出和筛选设定/组织")
    listing.add_argument("--type")
    listing.add_argument("--tag")
    listing.add_argument("--query", "-q")
    listing.add_argument("--limit", type=int, default=0)
    listing.set_defaults(handler=entry_list_command)
    show = commands.add_parser("show", help="查看完整设定、组织成员和关联剧情")
    show.add_argument("selector")
    show.set_defaults(handler=entry_show_command)
    add = commands.add_parser("add", help="新建设定；组织使用 --type 组织")
    add_entry_fields(add, editing=False)
    add.set_defaults(handler=entry_add_command)
    edit = commands.add_parser("edit", help="只修改明确提供的设定字段")
    edit.add_argument("selector")
    add_entry_fields(edit, editing=True)
    edit.add_argument("--yes", action="store_true", help="确认重命名及稳定引用同步")
    edit.set_defaults(handler=entry_edit_command)
    delete = commands.add_parser("delete", help="将设定移入回收站")
    delete.add_argument("selector")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(handler=entry_delete_command)
    trash = commands.add_parser("trash", help="列出设定回收站")
    trash.add_argument("--limit", type=int, default=100)
    trash.set_defaults(handler=entry_trash_command)
    restore = commands.add_parser("restore", help="恢复回收站设定")
    restore.add_argument("selector")
    restore.set_defaults(handler=entry_restore_command)
    history = commands.add_parser("history", help="列出设定操作历史")
    history.add_argument("--limit", type=int, default=100)
    history.set_defaults(handler=entry_history_command)
    undo = commands.add_parser("undo", help="撤销设定操作")
    undo.add_argument("operation_id", type=int)
    undo.set_defaults(handler=entry_undo_command)
    member = commands.add_parser("member", aliases=["members"], help="维护组织成员身份")
    member_commands = member.add_subparsers(dest="member_command", required=True)
    member_list = member_commands.add_parser("list", help="列出组织成员")
    member_list.add_argument("entry")
    member_list.set_defaults(handler=entry_member_list_command)
    member_add = member_commands.add_parser("add", help="添加组织成员")
    member_add.add_argument("entry")
    member_add.add_argument("character")
    member_add.add_argument("--role")
    member_add.add_argument("--status", default="现成员")
    member_add.set_defaults(handler=entry_member_add_command)
    member_edit = member_commands.add_parser("edit", help="编辑成员身份或状态")
    member_edit.add_argument("entry")
    member_edit.add_argument("character")
    member_edit.add_argument("--role")
    member_edit.add_argument("--status")
    member_edit.set_defaults(handler=entry_member_edit_command)
    member_remove = member_commands.add_parser("remove", help="从组织移除成员")
    member_remove.add_argument("entry")
    member_remove.add_argument("character")
    member_remove.set_defaults(handler=entry_member_remove_command)


def rag_rebuild_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    meta = client.meta()
    if not meta.get("writable") or not meta.get("routes", {}).get("ragRebuild"):
        raise CliError("当前本地服务不支持重建 RAG", code="not_supported", exit_code=3)
    client.timeout = max(client.timeout, 120)
    result = client.request("POST", client.project_path("rag/rebuild"), mutation=True)
    emit(
        {"ok": True, "project": client.project, **result},
        json_output=args.json_output,
        human=(
            f"RAG 已重建：版本 {result.get('sourceRevision')} · "
            f"{result.get('documents')} 个文档 · {result.get('chunks')} 个文本块 · "
            f"Embedding {result.get('embeddingStatus')}"
        ),
    )
    return result


def register_rag_domain(domains: argparse._SubParsersAction) -> None:
    rag = domains.add_parser("rag", help="管理本地 AI/RAG 索引")
    commands = rag.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild", help="从当前 story.db 手动完整重建 RAG")
    rebuild.set_defaults(handler=rag_rebuild_command)


def register_content_domains(domains: argparse._SubParsersAction) -> None:
    register_plot_domain(domains)
    register_entry_domain(domains)
    register_rag_domain(domains)
