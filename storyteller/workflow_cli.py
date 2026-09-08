from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from storyteller.fragment_cli import ApiClient, CliError, SelectionError, emit, format_time, resolve_item


SEARCH_KINDS = ("character", "plot", "entry", "fragment")
SEARCH_KIND_LABELS = {
    "character": "人物",
    "plot": "剧情",
    "entry": "设定",
    "fragment": "碎片",
}
RANK_STEP = 10**12


def _plain_markdown(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*_>#|~-]+", " ", value)).strip()


def _snippet(source: str, query: str, radius: int = 54) -> str:
    plain = _plain_markdown(source)
    if not plain:
        return ""
    index = plain.casefold().find(query.casefold())
    if index < 0:
        return plain[: radius * 2].rstrip() + ("…" if len(plain) > radius * 2 else "")
    start = max(0, index - radius)
    end = min(len(plain), index + len(query) + radius)
    return ("…" if start else "") + plain[start:end].strip() + ("…" if end < len(plain) else "")


def _search_candidates(snapshot: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for item in snapshot.get("characters", []):
        source = " ".join(str(value) for value in [
            item.get("name"), item.get("id"), *item.get("aliases", []), item.get("introPreview"),
        ] if value)
        yield {
            "kind": "character", "entityId": item["entityId"], "title": item.get("name", ""),
            "detail": f"人物 · {item.get('characterScope') or '未分类'} · ID {item.get('id') or '—'}",
            "preview": str(item.get("introPreview") or ""), "searchText": source,
        }
    for item in snapshot.get("plots", []):
        source = " ".join(str(value) for value in (
            item.get("title"), item.get("summary"), item.get("bodyPreview"),
        ) if value)
        yield {
            "kind": "plot", "entityId": item["entityId"], "title": item.get("title", ""),
            "detail": f"剧情 · 第 {item.get('chapterNumber') or item.get('sequence') or '—'} 篇",
            "preview": "\n".join(str(value) for value in (item.get("summary"), item.get("bodyPreview")) if value),
            "searchText": source,
        }
    for item in snapshot.get("entries", []):
        source = " ".join(str(value) for value in [
            item.get("name"), *item.get("aliases", []), *item.get("tags", []), item.get("bodyPreview"),
        ] if value)
        yield {
            "kind": "entry", "entityId": item["entityId"], "title": item.get("name", ""),
            "detail": f"设定 · {item.get('type') or '未分类'}", "preview": str(item.get("bodyPreview") or ""),
            "searchText": source,
        }
    for item in snapshot.get("fragments", []):
        source = " ".join(str(value) for value in (item.get("title"), item.get("bodyPreview")) if value)
        yield {
            "kind": "fragment", "entityId": item["entityId"], "title": item.get("title", ""),
            "detail": "灵感碎片", "preview": str(item.get("bodyPreview") or ""), "searchText": source,
        }


def search_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    query = args.query.strip()
    if not query:
        raise CliError("搜索词不能为空", code="invalid_argument", exit_code=2)
    allowed = set(args.kind or SEARCH_KINDS)
    folded = query.casefold()
    results = []
    for item in _search_candidates(client.snapshot()):
        if item["kind"] not in allowed or folded not in item.pop("searchText").casefold():
            continue
        title = str(item["title"])
        title_folded = title.casefold()
        item["match"] = _snippet(str(item.pop("preview")), query)
        item["score"] = 0 if title_folded == folded else 1 if title_folded.startswith(folded) else 2
        results.append(item)
    results.sort(key=lambda item: (item["score"], SEARCH_KINDS.index(item["kind"]), item["title"], item["entityId"]))
    results = results[: args.limit]
    for item in results:
        item.pop("score", None)
    if args.json_output:
        emit({"ok": True, "project": client.project, "query": query, "items": results}, json_output=True)
    elif not results:
        print("没有找到匹配内容。")
    else:
        for item in results:
            print(f"{item['title']}  [{item['detail']} · {item['entityId']}]")
            if item["match"]:
                print(f"  {item['match']}")
    return results


def _merge_state(client: ApiClient) -> dict[str, Any]:
    return client.request("GET", client.project_path("merge-conflicts"))


def _resolve_conflict(state: dict[str, Any], selector: str) -> dict[str, Any]:
    value = selector.strip()
    candidates = [item for item in state.get("items", []) if value in {
        str(item.get("id") or ""), str(item.get("entityId") or ""), str(item.get("title") or ""),
    }]
    if not candidates:
        folded = value.casefold()
        candidates = [item for item in state.get("items", []) if folded == str(item.get("title") or "").casefold()]
    if not candidates:
        raise SelectionError(f"找不到合并项：{value}")
    if len(candidates) > 1:
        identifiers = "、".join(str(item["id"]) for item in candidates[:8])
        raise SelectionError(f"合并项“{value}”不唯一，请改用冲突 ID：{identifiers}", code="ambiguous_selector")
    return candidates[0]


def _merge_public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"), "title": item.get("title"), "table": item.get("table"),
        "entityId": item.get("entityId"), "status": item.get("status"), "fields": item.get("fields", []),
    }


def merge_status_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    result = {"ok": True, "project": client.project, **state}
    if args.json_output:
        emit(result, json_output=True)
    elif not state.get("required"):
        print("当前没有待处理的数据库合并冲突。")
    else:
        session = state["session"]
        print(f"合并会话 {session['id']}：已选择 {session['resolvedFields']}/{session['totalFields']} 个字段")
        for item in state.get("items", []):
            marker = "✓" if item.get("status") == "resolved" else "·"
            print(f"{marker} {item['title']}  [{item['id']}] · {len(item.get('fields', []))} 个冲突字段")
    return result


def merge_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    if not state.get("required"):
        raise SelectionError("当前没有待处理的数据库合并冲突")
    item = _resolve_conflict(state, args.selector)
    result = {"ok": True, "project": client.project, "session": state.get("session"), "item": _merge_public_item(item)}
    if args.json_output:
        emit(result, json_output=True)
    else:
        print(f"{item['title']}  [{item['id']}] · {item['status']}")
        for field in item.get("fields", []):
            choice = (field.get("resolution") or {}).get("choice") or "未选择"
            print(f"{field['name']}（{field['label']}）· {choice}")
            print(f"  共同：{field.get('base')!r}")
            print(f"  本地：{field.get('ours')!r}")
            print(f"  远程：{field.get('theirs')!r}")
    return result


def _manual_value(args: argparse.Namespace) -> str | None:
    if args.manual_file is not None:
        try:
            return Path(args.manual_file).expanduser().read_text(encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法读取手动合并文件：{args.manual_file}（{error}）", code="file_error", exit_code=2) from error
    return args.manual


def merge_resolve_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    if not state.get("required"):
        raise SelectionError("当前没有待处理的数据库合并冲突")
    item = _resolve_conflict(state, args.selector)
    field = next((value for value in item.get("fields", []) if value.get("name") == args.field), None)
    if field is None:
        names = "、".join(str(value.get("name")) for value in item.get("fields", []))
        raise SelectionError(f"合并字段不存在：{args.field}；可选字段：{names}")
    manual = _manual_value(args)
    if manual is not None:
        if not field.get("manualAllowed"):
            raise CliError("这个字段不能手动编辑，请选择 --ours 或 --theirs", code="manual_not_allowed", exit_code=2)
        resolution = {"choice": "manual", "value": manual}
    else:
        resolution = {"choice": "ours" if args.ours else "theirs"}
    next_state = client.request(
        "PUT", client.project_path(f"merge-conflicts/{quote(str(item['id']), safe='')}"),
        payload={"resolutions": {args.field: resolution}}, mutation=True,
    )
    saved = _resolve_conflict(next_state, str(item["id"]))
    result = {
        "ok": True, "project": client.project, "session": next_state.get("session"),
        "item": _merge_public_item(saved), "resolvedField": args.field, "resolution": resolution,
    }
    emit(result, json_output=args.json_output, human=f"已保存“{field['label']}”的合并选择。")
    return result


def merge_resolve_all_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    if not state.get("required"):
        raise SelectionError("当前没有待处理的数据库合并冲突")
    item = _resolve_conflict(state, args.selector)
    choice = "both" if getattr(args, "both", False) else "ours" if args.ours else "theirs"
    resolutions = {str(field["name"]): {"choice": choice} for field in item.get("fields", [])}
    next_state = client.request(
        "PUT", client.project_path(f"merge-conflicts/{quote(str(item['id']), safe='')}"),
        payload={"resolutions": resolutions}, mutation=True,
    )
    saved = _resolve_conflict(next_state, str(item["id"]))
    result = {"ok": True, "project": client.project, "session": next_state.get("session"), "item": _merge_public_item(saved)}
    emit(result, json_output=args.json_output, human=f"已保存“{item['title']}”的选择：{'两个都保留' if choice == 'both' else '本地' if args.ours else '远程'}。")
    return result


def merge_preview_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    if not state.get("session"):
        raise SelectionError("当前没有待处理的数据库合并冲突")
    result = client.request("GET", client.project_path(f"merge-conflicts/{quote(str(state['session']['id']), safe='')}/preview"))
    emit(result, json_output=args.json_output, human="合并预览：\n" + json.dumps(result, ensure_ascii=False, indent=2))
    return result


def merge_finalize_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    state = _merge_state(client)
    if not state.get("required") or not state.get("session"):
        raise SelectionError("当前没有待处理的数据库合并冲突")
    session = state["session"]
    if session["resolvedFields"] != session["totalFields"]:
        raise CliError(
            f"仍有 {session['totalFields'] - session['resolvedFields']} 个字段未选择",
            code="merge_incomplete", exit_code=2,
        )
    if not args.yes:
        raise CliError("完成合并会写入最终选择，请添加 --yes 确认", code="confirmation_required", exit_code=2)
    response = client.request(
        "POST", client.project_path(f"merge-conflicts/{quote(str(session['id']), safe='')}/finalize"), mutation=True,
        payload={"previewToken": args.preview_token} if getattr(args, "preview_token", None) else None,
    )
    result = {
        "ok": True, "project": client.project, "sessionId": session["id"],
        "revision": response.get("projectRevision"), "operation": response.get("operation"),
        "warnings": response.get("warnings", []),
    }
    emit(result, json_output=args.json_output, human="数据库冲突已验证并完成合并。")
    return result


def _resolve_line(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("timeline", {}).get("lines", []), selector, noun="剧情线", title_keys=("name",))


def _resolve_plot(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(snapshot.get("plots", []), selector, noun="剧情")


def _timeline_assignments(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    nodes_by_plot: dict[str, list[dict[str, Any]]] = {}
    for node in snapshot.get("timeline", {}).get("nodes", []):
        nodes_by_plot.setdefault(str(node["plotId"]), []).append(node)
    assignments = []
    main_line = str(snapshot.get("timeline", {}).get("mainLineId") or "")
    for plot in snapshot.get("plots", []):
        nodes = nodes_by_plot.get(str(plot["entityId"]), [])
        assignments.append({
            "plotId": plot["entityId"],
            "lineIds": list(dict.fromkeys(str(node["lineId"]) for node in nodes)) or ([main_line] if main_line else []),
            "storySortKey": min((str(node["storySortKey"]) for node in nodes), default=str(plot.get("storySortKey") or plot.get("sortKey") or "")),
            "storyOrderMode": plot.get("storyOrderMode") or "follow_reading",
        })
    return assignments


def _timeline_lines(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "entityId": line["entityId"], "stableId": line.get("id", ""), "name": line.get("name", ""),
        "color": line.get("color", "#3f7fc1"), "side": line.get("side", "right"),
        "startPlotId": line.get("startPlotId"), "endPlotId": line.get("endPlotId"),
    } for line in snapshot.get("timeline", {}).get("lines", [])]


def _timeline_payload(
    snapshot: dict[str, Any], *, lines: list[dict[str, Any]] | None = None,
    assignments: list[dict[str, Any]] | None = None, main_line_id: str | None = None,
    line_replacements: dict[str, str] | None = None,
    chapter_numbers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timeline = snapshot["timeline"]
    payload: dict[str, Any] = {
        "baseRevision": snapshot["project"]["revision"],
        "mainLineId": main_line_id or timeline["mainLineId"],
        "lineSpacing": timeline["lineSpacing"], "topPadding": timeline["topPadding"],
        "sidePadding": timeline["sidePadding"], "pixelsPerStoryUnit": timeline["pixelsPerStoryUnit"],
        "lines": lines if lines is not None else _timeline_lines(snapshot),
        "assignments": assignments if assignments is not None else _timeline_assignments(snapshot),
        "lineReplacements": line_replacements or {},
    }
    if chapter_numbers is not None:
        payload["chapterNumbers"] = chapter_numbers
    return payload


def _save_timeline(client: ApiClient, snapshot: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return client.request("PUT", client.project_path("timeline"), payload=_timeline_payload(snapshot, **changes), mutation=True)


def timeline_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    assignments = _timeline_assignments(snapshot)
    line_names = {line["entityId"]: line["name"] for line in snapshot["timeline"]["lines"]}
    plots = {plot["entityId"]: plot for plot in snapshot.get("plots", [])}
    nodes = []
    for index, item in enumerate(sorted(assignments, key=lambda value: value["storySortKey"]), start=1):
        plot = plots[item["plotId"]]
        nodes.append({
            **item, "storyOrder": index, "title": plot.get("title"), "chapterNumber": plot.get("chapterNumber"),
            "lineNames": [line_names.get(line_id, line_id) for line_id in item["lineIds"]],
        })
    result = {"ok": True, "project": client.project, "timeline": snapshot["timeline"], "assignments": nodes}
    if args.json_output:
        emit(result, json_output=True)
    else:
        print(f"主线：{line_names.get(snapshot['timeline']['mainLineId'], snapshot['timeline']['mainLineId'])}")
        print(f"{len(line_names)} 条剧情线 · {len(nodes)} 个剧情节点")
        for node in nodes:
            print(f"{node['storyOrder']:>3}  第 {node['chapterNumber']} 章 · {node['title']} · {'、'.join(node['lineNames'])}")
    return result


def timeline_line_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    timeline = client.snapshot()["timeline"]
    counts: dict[str, int] = {}
    for node in timeline.get("nodes", []):
        counts[str(node["lineId"])] = counts.get(str(node["lineId"]), 0) + 1
    items = [{**line, "main": line["entityId"] == timeline["mainLineId"], "nodeCount": counts.get(line["entityId"], 0)} for line in timeline["lines"]]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    else:
        for line in items:
            print(f"{'*' if line['main'] else ' '} {line['name']}  [{line['entityId']}] · {line['side']} · {line['nodeCount']} 个节点")
    return items


def timeline_line_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    stable_id = args.stable_id or f"line-{secrets.token_hex(6)}"
    entity_id = f"timeline_line:{stable_id}"
    if any(line.get("entityId") == entity_id for line in snapshot["timeline"]["lines"]):
        raise CliError(f"剧情线稳定 ID 已存在：{stable_id}", code="duplicate_id", exit_code=2)
    lines = _timeline_lines(snapshot)
    lines.append({
        "entityId": "", "stableId": stable_id, "name": args.name, "color": args.color,
        "side": "center" if args.main else args.side, "startPlotId": None, "endPlotId": None,
    })
    response = _save_timeline(client, snapshot, lines=lines, main_line_id=entity_id if args.main else None)
    saved = next((line for line in response.get("structures", {}).get("timeline", {}).get("lines", []) if line.get("entityId") == entity_id), None)
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": saved}
    emit(result, json_output=args.json_output, human=f"已创建剧情线：{args.name}")
    return result


def timeline_line_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    target = _resolve_line(snapshot, args.selector)
    if args.name is None and args.color is None and args.side is None:
        raise CliError("没有提供需要修改的剧情线字段", code="no_changes", exit_code=2)
    lines = _timeline_lines(snapshot)
    for line in lines:
        if line["entityId"] == target["entityId"]:
            if args.name is not None:
                line["name"] = args.name
            if args.color is not None:
                line["color"] = args.color
            if args.side is not None:
                if target["entityId"] == snapshot["timeline"]["mainLineId"] and args.side != "center":
                    raise CliError("主线的位置固定为 center；请先用 timeline main 更换主线", code="invalid_argument", exit_code=2)
                line["side"] = args.side
    response = _save_timeline(client, snapshot, lines=lines)
    saved = next(line for line in response["structures"]["timeline"]["lines"] if line["entityId"] == target["entityId"])
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": saved}
    emit(result, json_output=args.json_output, human=f"已更新剧情线：{saved['name']}")
    return result


def timeline_main_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    target = _resolve_line(snapshot, args.selector)
    response = _save_timeline(client, snapshot, main_line_id=target["entityId"])
    saved = next(
        line for line in response["structures"]["timeline"]["lines"]
        if line["entityId"] == target["entityId"]
    )
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "mainLineId": target["entityId"], "item": saved}
    emit(result, json_output=args.json_output, human=f"已设为主线：{target['name']}")
    return result


def timeline_line_delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    target = _resolve_line(snapshot, args.selector)
    if len(snapshot["timeline"]["lines"]) <= 1:
        raise CliError("时间线至少需要保留一条剧情线", code="last_timeline_line", exit_code=2)
    replacement = _resolve_line(snapshot, args.replacement)
    if replacement["entityId"] == target["entityId"]:
        raise CliError("接收剧情线不能是待删除线本身", code="invalid_argument", exit_code=2)
    if not args.yes:
        raise CliError("删除剧情线会转移其节点并进入回收站，请添加 --yes 确认", code="confirmation_required", exit_code=2)
    lines = [line for line in _timeline_lines(snapshot) if line["entityId"] != target["entityId"]]
    assignments = _timeline_assignments(snapshot)
    for item in assignments:
        item["lineIds"] = list(dict.fromkeys(replacement["entityId"] if value == target["entityId"] else value for value in item["lineIds"]))
    main_line = replacement["entityId"] if snapshot["timeline"]["mainLineId"] == target["entityId"] else snapshot["timeline"]["mainLineId"]
    response = _save_timeline(
        client, snapshot, lines=lines, assignments=assignments, main_line_id=main_line,
        line_replacements={target["entityId"]: replacement["entityId"]},
    )
    result = {
        "ok": True, "project": client.project, "revision": response.get("projectRevision"),
        "removedEntityId": target["entityId"], "replacementEntityId": replacement["entityId"],
    }
    emit(result, json_output=args.json_output, human=f"已删除“{target['name']}”，节点已转移到“{replacement['name']}”。")
    return result


def timeline_node_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    snapshot = client.snapshot()
    selected_line = _resolve_line(snapshot, args.line)["entityId"] if args.line else None
    line_names = {line["entityId"]: line["name"] for line in snapshot["timeline"]["lines"]}
    plots = {plot["entityId"]: plot for plot in snapshot["plots"]}
    items = []
    for index, assignment in enumerate(sorted(_timeline_assignments(snapshot), key=lambda value: value["storySortKey"]), start=1):
        if selected_line and selected_line not in assignment["lineIds"]:
            continue
        plot = plots[assignment["plotId"]]
        items.append({
            **assignment, "storyOrder": index, "title": plot["title"], "chapterNumber": plot.get("chapterNumber"),
            "lineNames": [line_names.get(value, value) for value in assignment["lineIds"]],
        })
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    else:
        for item in items:
            print(f"{item['storyOrder']:>3}  第 {item['chapterNumber']} 章 · {item['title']}  [{item['plotId']}] · {'、'.join(item['lineNames'])}")
    return items


def _normalize_line_bounds(lines: list[dict[str, Any]], assignments: list[dict[str, Any]], main_line_id: str) -> None:
    ordered = sorted(assignments, key=lambda item: item["storySortKey"])
    for line in lines:
        if line["entityId"] == main_line_id:
            continue
        plots = [item["plotId"] for item in ordered if line["entityId"] in item["lineIds"]]
        line["startPlotId"] = plots[0] if plots else None
        line["endPlotId"] = plots[-1] if len(plots) > 1 else None


def timeline_node_assign_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    plot = _resolve_plot(snapshot, args.plot)
    line_ids = list(dict.fromkeys(_resolve_line(snapshot, value)["entityId"] for value in args.line))
    assignments = _timeline_assignments(snapshot)
    target = next(item for item in assignments if item["plotId"] == plot["entityId"])
    target["lineIds"] = line_ids
    lines = _timeline_lines(snapshot)
    _normalize_line_bounds(lines, assignments, snapshot["timeline"]["mainLineId"])
    response = _save_timeline(client, snapshot, lines=lines, assignments=assignments)
    saved_nodes = [node for node in response["structures"]["timeline"]["nodes"] if node["plotId"] == plot["entityId"]]
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "plotId": plot["entityId"], "nodes": saved_nodes}
    emit(result, json_output=args.json_output, human=f"已更新“{plot['title']}”的剧情线归属。")
    return result


def timeline_node_move_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    plot = _resolve_plot(snapshot, args.plot)
    assignments = sorted(_timeline_assignments(snapshot), key=lambda item: item["storySortKey"])
    original_ids = [item["plotId"] for item in assignments]
    original_keys = [item["storySortKey"] for item in assignments]
    chapter_by_plot = {item["entityId"]: int(item.get("chapterNumber") or item.get("sequence") or 0) for item in snapshot["plots"]}
    original_chapters = [chapter_by_plot[plot_id] for plot_id in original_ids]
    current = original_ids.index(plot["entityId"])
    moving = assignments.pop(current)
    if args.before is not None:
        reference = _resolve_plot(snapshot, args.before)
        if reference["entityId"] == plot["entityId"]:
            raise CliError("不能把剧情移动到自身之前", code="invalid_argument", exit_code=2)
        target = next(index for index, item in enumerate(assignments) if item["plotId"] == reference["entityId"])
    elif args.after is not None:
        reference = _resolve_plot(snapshot, args.after)
        if reference["entityId"] == plot["entityId"]:
            raise CliError("不能把剧情移动到自身之后", code="invalid_argument", exit_code=2)
        target = next(index for index, item in enumerate(assignments) if item["plotId"] == reference["entityId"]) + 1
    else:
        target = args.index - 1
        if not 0 <= target <= len(assignments):
            raise CliError(f"故事位置必须在 1 到 {len(assignments) + 1} 之间", code="invalid_argument", exit_code=2)
    assignments.insert(target, moving)
    next_ids = [item["plotId"] for item in assignments]
    if next_ids == original_ids:
        result = {"ok": True, "project": client.project, "revision": snapshot["project"]["revision"], "changed": False, "plotId": plot["entityId"], "storyOrder": current + 1}
        emit(result, json_output=args.json_output, human="剧情已经位于目标故事位置。")
        return result
    for index, item in enumerate(assignments):
        item["storySortKey"] = original_keys[index] if original_keys[index].isdigit() else f"{(index + 1) * RANK_STEP:024d}"
        if item["plotId"] != original_ids[index]:
            item["storyOrderMode"] = "fixed"
    chapter_numbers = [
        {"plotId": item["plotId"], "chapterNumber": original_chapters[index]}
        for index, item in enumerate(assignments)
    ]
    lines = _timeline_lines(snapshot)
    _normalize_line_bounds(lines, assignments, snapshot["timeline"]["mainLineId"])
    response = _save_timeline(client, snapshot, lines=lines, assignments=assignments, chapter_numbers=chapter_numbers)
    result = {
        "ok": True, "project": client.project, "revision": response.get("projectRevision"),
        "plotId": plot["entityId"], "storyOrder": target + 1,
        "chapterNumber": original_chapters[target], "operation": response.get("operation"),
    }
    emit(result, json_output=args.json_output, human=f"已将“{plot['title']}”移动到故事位置 {target + 1}，并同步沿途章号。")
    return result


def timeline_history_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("operations"), query={"limit": args.limit})
    items = [item for item in response.get("items", []) if item.get("entityKind") == "timeline_line"]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    else:
        for item in items:
            state = "可撤销" if item.get("canUndo") else str(item.get("undoBlockedReason") or "不可撤销")
            print(f"{item['id']:>5}  {item['label']} · {state} · {format_time(item.get('createdAt'))}")
    return items


def timeline_undo_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    history = client.request("GET", client.project_path("operations"), query={"limit": 300})
    operation = next((item for item in history.get("items", []) if int(item.get("id") or 0) == args.operation_id), None)
    if operation is None:
        raise SelectionError(f"找不到仍在保留期内的操作：{args.operation_id}", code="operation_not_found")
    if operation.get("entityKind") != "timeline_line":
        raise CliError(f"操作 {args.operation_id} 不属于时间线", code="wrong_operation_kind", exit_code=2)
    if not operation.get("canUndo"):
        raise CliError(str(operation.get("undoBlockedReason") or "当前不可撤销"), code="undo_blocked")
    response = client.mutate("POST", "operations/undo", {"operationId": args.operation_id})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "operationId": args.operation_id}
    emit(result, json_output=args.json_output, human=f"已撤销时间线操作 {args.operation_id}。")
    return result


def register_workflow_domains(domains: argparse._SubParsersAction) -> None:
    search = domains.add_parser("search", help="全局搜索人物、剧情、设定和碎片")
    search.add_argument("query")
    search.add_argument("--kind", action="append", choices=SEARCH_KINDS, help="限制内容类型；可重复")
    search.add_argument("--limit", type=int, default=12)
    search.set_defaults(handler=search_command)

    merge = domains.add_parser("merge", help="逐字段处理 Git 数据库合并冲突")
    merge_commands = merge.add_subparsers(dest="command", required=True)
    status = merge_commands.add_parser("status", help="查看合并会话、进度和冲突项")
    status.set_defaults(handler=merge_status_command)
    show = merge_commands.add_parser("show", help="查看某个冲突项的共同、本地和远程版本")
    show.add_argument("selector", help="冲突 ID、entityId 或唯一标题")
    show.set_defaults(handler=merge_show_command)
    resolve = merge_commands.add_parser("resolve", help="保存一个冲突字段的选择")
    resolve.add_argument("selector")
    resolve.add_argument("field", help="merge show 显示的字段名")
    choices = resolve.add_mutually_exclusive_group(required=True)
    choices.add_argument("--ours", action="store_true", help="保留当前电脑版本")
    choices.add_argument("--theirs", action="store_true", help="采用远程版本")
    choices.add_argument("--manual", help="手动合并文本")
    choices.add_argument("--manual-file", help="从 UTF-8 文件读取手动合并文本")
    resolve.set_defaults(handler=merge_resolve_command)
    resolve_all = merge_commands.add_parser("resolve-all", help="将一个冲突项的全部字段选为同一侧")
    resolve_all.add_argument("selector")
    all_choices = resolve_all.add_mutually_exclusive_group(required=True)
    all_choices.add_argument("--ours", action="store_true")
    all_choices.add_argument("--theirs", action="store_true")
    all_choices.add_argument("--both", action="store_true", help="保留剧情或碎片的两个完整版本")
    resolve_all.set_defaults(handler=merge_resolve_all_command)
    preview = merge_commands.add_parser("preview", help="检查合并结果和章号变化，取得预览凭证")
    preview.set_defaults(handler=merge_preview_command)
    finalize = merge_commands.add_parser("finalize", help="完整性检查通过后完成合并")
    finalize.add_argument("--yes", action="store_true")
    finalize.add_argument("--preview-token", help="merge preview 返回的 token；双保留时必填")
    finalize.set_defaults(handler=merge_finalize_command)

    timeline = domains.add_parser("timeline", help="管理剧情线、主线、节点归属与故事顺序")
    timeline_commands = timeline.add_subparsers(dest="command", required=True)
    show_timeline = timeline_commands.add_parser("show", help="查看完整时间线摘要")
    show_timeline.set_defaults(handler=timeline_show_command)
    line = timeline_commands.add_parser("line", aliases=["lines"], help="管理剧情线")
    line_commands = line.add_subparsers(dest="line_command", required=True)
    line_list = line_commands.add_parser("list")
    line_list.set_defaults(handler=timeline_line_list_command)
    line_add = line_commands.add_parser("add")
    line_add.add_argument("name")
    line_add.add_argument("--id", dest="stable_id")
    line_add.add_argument("--color", default="#3ba878")
    line_add.add_argument("--side", choices=("left", "right"), default="right")
    line_add.add_argument("--main", action="store_true")
    line_add.set_defaults(handler=timeline_line_add_command)
    line_edit = line_commands.add_parser("edit")
    line_edit.add_argument("selector")
    line_edit.add_argument("--name")
    line_edit.add_argument("--color")
    line_edit.add_argument("--side", choices=("left", "right"))
    line_edit.set_defaults(handler=timeline_line_edit_command)
    line_delete = line_commands.add_parser("delete")
    line_delete.add_argument("selector")
    line_delete.add_argument("--replacement", required=True, help="接收原有节点的剧情线")
    line_delete.add_argument("--yes", action="store_true")
    line_delete.set_defaults(handler=timeline_line_delete_command)
    main = timeline_commands.add_parser("main", help="设置主线")
    main.add_argument("selector")
    main.set_defaults(handler=timeline_main_command)
    node = timeline_commands.add_parser("node", aliases=["nodes"], help="管理剧情节点归属和故事顺序")
    node_commands = node.add_subparsers(dest="node_command", required=True)
    node_list = node_commands.add_parser("list")
    node_list.add_argument("--line")
    node_list.set_defaults(handler=timeline_node_list_command)
    assign = node_commands.add_parser("assign", help="用一组剧情线替换节点当前归属")
    assign.add_argument("plot")
    assign.add_argument("--line", action="append", required=True)
    assign.set_defaults(handler=timeline_node_assign_command)
    move = node_commands.add_parser("move", help="移动故事位置，并按 Web 语义同步沿途章号")
    move.add_argument("plot")
    destination = move.add_mutually_exclusive_group(required=True)
    destination.add_argument("--before")
    destination.add_argument("--after")
    destination.add_argument("--index", type=int, help="从 1 开始的故事位置")
    move.set_defaults(handler=timeline_node_move_command)
    history = timeline_commands.add_parser("history")
    history.add_argument("--limit", type=int, default=100)
    history.set_defaults(handler=timeline_history_command)
    undo = timeline_commands.add_parser("undo")
    undo.add_argument("operation_id", type=int)
    undo.set_defaults(handler=timeline_undo_command)
