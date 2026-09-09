from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from storyteller.fragment_cli import (
    ApiClient,
    CliError,
    SelectionError,
    default_web_url,
    discover_workspace,
    emit,
    format_time,
    normalize_global_options,
    resolve_item,
    resolve_person,
    resolve_reference,
    select_project,
)


CHARACTER_KINDS = {"character", "relationship"}
VISIBLE_ROLES = ("主角", "反派", "中立", "配角")
CHARACTER_SCOPES = ("主线人物", "常驻人物", "一次性角色", "待定角色")


class StoryArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliError(message, code="invalid_argument", exit_code=2)


def visible_role(character: dict[str, Any]) -> str:
    if character.get("narrativeRole") == "主角":
        return "主角"
    side = character.get("side")
    if side == "反派方":
        return "反派"
    if side == "中立":
        return "中立"
    return "配角"


def stored_classification(role: str) -> dict[str, str]:
    if role == "主角":
        return {"narrativeRole": "主角", "side": "主角方"}
    if role == "反派":
        return {"narrativeRole": "配角", "side": "反派方"}
    if role == "中立":
        return {"narrativeRole": "配角", "side": "中立"}
    return {"narrativeRole": "配角", "side": "主角方"}


def character_label(item: dict[str, Any]) -> str:
    return (
        f"{item.get('name', item.get('title', ''))}"
        f"  [{visible_role(item)} · {item.get('characterScope', '—')} · {item.get('entityId', '')}]"
    )


def relationship_label(item: dict[str, Any], names: dict[str, str]) -> str:
    source = names.get(str(item.get("from")), str(item.get("from") or "?"))
    target = names.get(str(item.get("to")), str(item.get("to") or "?"))
    label = str(item.get("label") or item.get("type") or "未命名关系")
    return f"{source} ↔ {target} · {label}  [{item.get('entityId', '')}]"


def resolve_relationship(snapshot: dict[str, Any], selector: str) -> dict[str, Any]:
    return resolve_item(
        snapshot.get("relationships", []),
        selector,
        noun="人物关系",
        title_keys=("label", "type"),
    )


def read_file(path: str, label: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as error:
        raise CliError(f"无法读取{label}文件：{path}（{error}）", code="file_error", exit_code=2) from error


def parse_key_values(values: Sequence[str] | None, label: str) -> dict[str, str] | None:
    if values is None:
        return None
    result: dict[str, str] = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise CliError(f"{label}格式应为 名称=内容：{raw}", code="invalid_argument", exit_code=2)
        if key in result:
            raise CliError(f"{label}名称重复：{key}", code="invalid_argument", exit_code=2)
        result[key] = value
    return result


def parse_persona(
    notes: Sequence[str] | None,
    pairs: Sequence[str] | None,
    label: str,
) -> list[dict[str, str]] | None:
    if notes is None and pairs is None:
        return None
    result = [{"key": "", "value": value.strip()} for value in notes or [] if value.strip()]
    parsed = parse_key_values(pairs, label) or {}
    result.extend({"key": key, "value": value} for key, value in parsed.items())
    return result


def selected_references(snapshot: dict[str, Any], values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [str(resolve_reference(snapshot, value)["entityId"]) for value in values]


def optional_collection(
    payload: dict[str, Any],
    args: argparse.Namespace,
    argument: str,
    field: str,
    clear_argument: str,
) -> None:
    values = getattr(args, argument, None)
    clear = bool(getattr(args, clear_argument, False))
    if values is not None and clear:
        raise CliError(f"不能同时设置和清空 {field}", code="invalid_argument", exit_code=2)
    if clear:
        payload[field] = []
    elif values is not None:
        payload[field] = list(values)


def optional_text(
    payload: dict[str, Any],
    args: argparse.Namespace,
    argument: str,
    file_argument: str,
    clear_argument: str,
    field: str,
    label: str,
) -> None:
    inline = getattr(args, argument, None)
    filename = getattr(args, file_argument, None)
    clear = bool(getattr(args, clear_argument, False))
    count = int(inline is not None) + int(filename is not None) + int(clear)
    if count > 1:
        raise CliError(f"{label}只能在直接文本、文件和清空中选择一种", code="invalid_argument", exit_code=2)
    if clear:
        payload[field] = ""
    elif filename is not None:
        payload[field] = read_file(filename, label)
    elif inline is not None:
        payload[field] = inline


def character_payload(args: argparse.Namespace, snapshot: dict[str, Any], *, editing: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    scalar_fields = (
        ("name", "name"),
        ("stable_id", "stableId"),
        ("character_scope", "characterScope"),
        ("main_plot_impact", "mainPlotImpact"),
        ("color", "color"),
        ("gradient", "gradient"),
        ("group", "group"),
        ("graph_visible", "graphVisible"),
    )
    for argument, field in scalar_fields:
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    if getattr(args, "clear_group", False):
        if getattr(args, "group", None) is not None:
            raise CliError("不能同时设置和清空人物分组", code="invalid_argument", exit_code=2)
        payload["group"] = ""
    if getattr(args, "clear_gradient", False):
        if getattr(args, "gradient", None) is not None:
            raise CliError("不能同时设置和清空人物渐变色", code="invalid_argument", exit_code=2)
        payload["gradient"] = ""
    role = getattr(args, "role", None)
    if role is not None:
        payload.update(stored_classification(role))
    optional_text(payload, args, "intro", "intro_file", "clear_intro", "intro", "人物简介")
    optional_text(
        payload,
        args,
        "destiny_outline",
        "destiny_outline_file",
        "clear_destiny_outline",
        "destinyOutline",
        "人物大纲",
    )
    optional_collection(payload, args, "aliases", "aliases", "clear_aliases")
    optional_collection(payload, args, "markers", "markers", "clear_markers")
    optional_collection(payload, args, "supplements", "supplements", "clear_supplements")

    facts = parse_key_values(getattr(args, "facts", None), "人物档案")
    if facts is not None and getattr(args, "clear_facts", False):
        raise CliError("不能同时设置和清空人物档案", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_facts", False):
        payload["facts"] = {}
    elif facts is not None:
        payload["facts"] = facts

    for prefix, field, label in (
        ("core_persona", "corePersona", "核心人设"),
        ("supplement_persona", "supplementPersona", "补充人设"),
    ):
        persona = parse_persona(
            getattr(args, f"{prefix}_notes", None),
            getattr(args, f"{prefix}_pairs", None),
            label,
        )
        clear = bool(getattr(args, f"clear_{prefix}", False))
        if persona is not None and clear:
            raise CliError(f"不能同时设置和清空{label}", code="invalid_argument", exit_code=2)
        if clear:
            payload[field] = []
        elif persona is not None:
            payload[field] = persona

    core_requested = "corePersona" in payload
    intro_requested = "intro" in payload
    if core_requested and intro_requested:
        raise CliError(
            "人物简介与核心人设共用兼容存储，不能在同一次操作中同时修改；请分两次执行",
            code="invalid_argument",
            exit_code=2,
        )
    supplement_persona_requested = "supplementPersona" in payload
    supplements_requested = "supplements" in payload
    if supplement_persona_requested and supplements_requested:
        raise CliError(
            "旧式补充设定与补充人设共用兼容存储，不能在同一次操作中同时修改",
            code="invalid_argument",
            exit_code=2,
        )

    references = selected_references(snapshot, getattr(args, "references", None))
    if references is not None and getattr(args, "clear_references", False):
        raise CliError("不能同时设置和清空引用", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_references", False):
        payload["references"] = []
    elif references is not None:
        payload["references"] = references

    if editing and not payload:
        raise CliError("没有提供需要修改的字段", code="no_changes", exit_code=2)
    return payload


def character_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    items = list(client.snapshot().get("characters", []))
    if args.role:
        items = [item for item in items if visible_role(item) == args.role]
    if args.scope:
        items = [item for item in items if item.get("characterScope") == args.scope]
    if args.group:
        items = [item for item in items if item.get("group") == args.group]
    if args.query:
        query = args.query.casefold()
        items = [
            item for item in items
            if query in " ".join([
                str(item.get("name") or ""),
                str(item.get("id") or ""),
                *[str(value) for value in item.get("aliases", [])],
                *[str(value) for value in item.get("markers", [])],
                str(item.get("introPreview") or ""),
            ]).casefold()
        ]
    items.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("id") or "")))
    if args.limit:
        items = items[: args.limit]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有符合条件的人物。")
    else:
        for item in items:
            print(character_label(item))
    return items


def related_character_data(snapshot: dict[str, Any], entity_id: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "plots": [item for item in snapshot.get("plots", []) if entity_id in item.get("people", [])],
        "fragments": [
            item for item in snapshot.get("fragments", [])
            if entity_id in item.get("people", []) or entity_id in item.get("references", [])
        ],
        "entries": [
            item for item in snapshot.get("entries", [])
            if entity_id in item.get("people", [])
            or any(member.get("characterId") == entity_id for member in item.get("members", []))
        ],
        "relationships": [
            item for item in snapshot.get("relationships", [])
            if entity_id in {item.get("from"), item.get("to")}
        ],
    }


def character_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    character = resolve_person(snapshot, args.selector)
    detail = client.detail(character["entityId"])
    related = related_character_data(snapshot, character["entityId"])
    result = {"ok": True, "project": client.project, "item": detail, "related": related}
    if args.json_output:
        emit(result, json_output=True)
        return result
    data = detail["data"]
    print(character_label(data))
    print(f"分组：{data.get('group') or '—'} · 主线影响：{data.get('mainPlotImpact', 0)} · 图谱：{'显示' if data.get('graphVisible') else '隐藏'}")
    if data.get("aliases"):
        print("别名：" + "、".join(data["aliases"]))
    if data.get("markers"):
        print("标识：" + "、".join(data["markers"]))
    if data.get("intro"):
        print("\n" + str(data["intro"]).rstrip())
    if data.get("destinyOutline"):
        print("\n人物大纲\n" + str(data["destinyOutline"]).rstrip())
    counts = " · ".join(f"{label} {len(related[key])}" for key, label in (
        ("plots", "剧情"), ("fragments", "碎片"), ("entries", "设定/组织"), ("relationships", "关系")
    ))
    print(f"\n相关内容：{counts}")
    return result


def character_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    payload = character_payload(args, snapshot, editing=False)
    response = client.mutate("POST", "characters", payload, retry_create_conflict=True)
    created = [item for item in response.get("changed", {}).get("characters", []) if item.get("name") == args.name]
    detail = client.detail(created[-1]["entityId"]) if created else None
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已创建人物：{detail['data']['name'] if detail else args.name}")
    return result


def character_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    character = resolve_person(snapshot, args.selector)
    payload = character_payload(args, snapshot, editing=True)
    requested_name = str(payload.get("name") or "").strip()
    if requested_name and requested_name != str(character.get("name") or "").strip():
        sources = {
            item["entityId"] for item in snapshot.get("characters", [])
            if character["entityId"] in item.get("references", [])
        }
        for collection in ("plots", "entries", "fragments"):
            sources.update(
                item["entityId"] for item in snapshot.get(collection, [])
                if character["entityId"] in item.get("references", [])
                or character["entityId"] in item.get("people", [])
            )
        sources.update(
            item["entityId"] for item in snapshot.get("relationships", [])
            if character["entityId"] in item.get("references", [])
        )
        if not args.yes:
            if not sys.stdin.isatty():
                raise CliError(
                    f"重命名会同步更新 {len(sources)} 项稳定引用；非交互环境必须添加 --yes",
                    code="confirmation_required",
                    exit_code=2,
                )
            answer = input(
                f"将“{character['name']}”重命名为“{requested_name}”，并同步更新 {len(sources)} 项稳定引用？[y/N] "
            ).strip().lower()
            if answer not in {"y", "yes"}:
                result = {"ok": True, "cancelled": True, "item": character}
                emit(result, json_output=args.json_output, human="已取消。")
                return result
    payload["entityRevision"] = character["revision"]
    response = client.mutate("PATCH", f"characters/{quote(character['entityId'], safe='')}", payload)
    detail = client.detail(character["entityId"])
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已更新人物：{detail['data']['name']}")
    return result


def confirm_delete(title: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CliError("非交互环境删除时必须添加 --yes", code="confirmation_required", exit_code=2)
    return input(f"将“{title}”移入回收站？[y/N] ").strip().lower() in {"y", "yes"}


def delete_entity(client: ApiClient, entity: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    title = str(entity.get("name") or entity.get("label") or entity.get("title") or entity["entityId"])
    if not confirm_delete(title, args.yes):
        result = {"ok": True, "cancelled": True, "item": entity}
        emit(result, json_output=args.json_output, human="已取消。")
        return result
    response = client.mutate("DELETE", f"entities/{quote(entity['entityId'], safe='')}", {})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": entity}
    emit(result, json_output=args.json_output, human=f"已移入回收站：{title}")
    return result


def character_delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    return delete_entity(client, resolve_person(snapshot, args.selector), args)


def character_trash_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("trash"), query={"limit": args.limit})
    allowed = CHARACTER_KINDS if args.kind == "all" else {args.kind}
    items = [item for item in response.get("items", []) if item.get("kind") in allowed]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("回收站中没有人物或人物关系。")
    else:
        for item in items:
            kind = "人物" if item.get("kind") == "character" else "人物关系"
            print(f"{kind} · {item['title']}  [{item['entityId']}]  · 剩余 {item.get('daysRemaining', 0)} 天")
    return items


def character_restore_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    response = client.request("GET", client.project_path("trash"), query={"limit": 300})
    items = [item for item in response.get("items", []) if item.get("kind") in CHARACTER_KINDS]
    item = resolve_item(items, args.selector, noun="回收站人物内容")
    mutation = client.mutate("POST", f"entities/{quote(item['entityId'], safe='')}/restore", {})
    detail = client.detail(item["entityId"])
    result = {"ok": True, "project": client.project, "revision": mutation.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已恢复：{item['title']}")
    return result


def character_history_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    response = client.request("GET", client.project_path("operations"), query={"limit": args.limit})
    allowed = CHARACTER_KINDS if args.kind == "all" else {args.kind}
    items = [item for item in response.get("items", []) if item.get("entityKind") in allowed]
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有人物相关操作。")
    else:
        for item in items:
            state = "可撤销" if item.get("canUndo") else str(item.get("undoBlockedReason") or "不可撤销")
            print(f"{item['id']:>5}  {item['label']}  · {state} · {format_time(item.get('createdAt'))}")
    return items


def character_undo_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    history = client.request("GET", client.project_path("operations"), query={"limit": 300})
    operation = next((item for item in history.get("items", []) if int(item.get("id") or 0) == args.operation_id), None)
    if operation is None:
        raise SelectionError(f"找不到仍在保留期内的操作：{args.operation_id}", code="operation_not_found")
    if operation.get("entityKind") not in CHARACTER_KINDS:
        raise CliError(f"操作 {args.operation_id} 不属于人物或人物关系", code="wrong_operation_kind", exit_code=2)
    if not operation.get("canUndo"):
        raise CliError(str(operation.get("undoBlockedReason") or "当前不可撤销"), code="undo_blocked")
    response = client.mutate("POST", "operations/undo", {"operationId": args.operation_id})
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "operationId": args.operation_id}
    emit(result, json_output=args.json_output, human=f"已撤销操作 {args.operation_id}。")
    return result


def persona_markdown(title: str, values: list[dict[str, Any]]) -> str:
    if not values:
        return ""
    rows = [f"- {item.get('key') + '：' if item.get('key') else ''}{item.get('value', '')}" for item in values]
    return f"## {title}\n\n" + "\n".join(rows) + "\n\n"


def render_character_markdown(character: dict[str, Any]) -> str:
    lines = [f"# {character.get('name', '')}\n\n"]
    metadata = [
        ("人物定位", visible_role(character)),
        ("出场类型", str(character.get("characterScope") or "")),
        ("分组", str(character.get("group") or "")),
        ("别名", "、".join(character.get("aliases", []))),
        ("标识", "、".join(character.get("markers", []))),
    ]
    visible_metadata = [(key, value) for key, value in metadata if value]
    if visible_metadata:
        lines.append("## 基础资料\n\n" + "\n".join(f"- {key}：{value}" for key, value in visible_metadata) + "\n\n")
    if str(character.get("intro") or "").strip():
        lines.append("## 人物简介\n\n" + str(character["intro"]).strip() + "\n\n")
    if str(character.get("destinyOutline") or "").strip():
        lines.append("## 人物大纲\n\n" + str(character["destinyOutline"]).strip() + "\n\n")
    lines.append(persona_markdown("核心人设", character.get("corePersona", [])))
    lines.append(persona_markdown("补充人设", character.get("supplementPersona", [])))
    facts = character.get("facts", {})
    if facts:
        lines.append("## 人物档案\n\n" + "\n".join(f"- {key}：{value}" for key, value in facts.items()) + "\n\n")
    supplements = character.get("supplements", [])
    if supplements and not character.get("supplementPersona"):
        lines.append("## 补充设定\n\n" + "\n".join(f"- {value}" for value in supplements) + "\n")
    return "".join(lines).rstrip() + "\n"


def character_export_command(client: ApiClient, args: argparse.Namespace) -> str:
    snapshot = client.snapshot()
    characters = list(snapshot.get("characters", []))
    range_requested = args.from_character is not None or args.to_character is not None
    selected: list[dict[str, Any]]
    if args.all:
        if args.selector or range_requested:
            raise CliError("--all 不能与人物选择器或范围同时使用", code="invalid_argument", exit_code=2)
        selected = characters
    elif range_requested:
        if args.selector or args.from_character is None or args.to_character is None:
            raise CliError("范围导出必须同时提供 --from 和 --to，且不能再提供单项选择器", code="invalid_argument", exit_code=2)
        first = resolve_person(snapshot, args.from_character)
        last = resolve_person(snapshot, args.to_character)
        indexes = {item["entityId"]: index for index, item in enumerate(characters)}
        start, end = sorted((indexes[first["entityId"]], indexes[last["entityId"]]))
        selected = characters[start : end + 1]
    else:
        if not args.selector:
            raise CliError("请提供人物选择器，或使用 --all / --from 与 --to", code="invalid_argument", exit_code=2)
        selected = [resolve_person(snapshot, args.selector)]
    if not selected:
        raise CliError("没有可导出的人物", code="not_found", exit_code=4)
    details = [client.detail(item["entityId"])["data"] for item in selected]
    rendered = "\n\n---\n\n".join(render_character_markdown(detail).rstrip() for detail in details) + "\n"
    entity_ids = [str(detail["entityId"]) for detail in details]
    if args.output:
        target = Path(args.output).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")
        except OSError as error:
            raise CliError(f"无法写入导出文件：{target}（{error}）", code="file_error", exit_code=2) from error
        emit(
            {
                "ok": True,
                "project": client.project,
                "path": str(target.resolve()),
                "entityIds": entity_ids,
                "count": len(details),
            },
            json_output=args.json_output,
            human=f"已导出 {len(details)} 份人物档案：{target}",
        )
    elif args.json_output:
        emit({
            "ok": True,
            "project": client.project,
            "entityIds": entity_ids,
            "count": len(details),
            "markdown": rendered,
        }, json_output=True)
    else:
        sys.stdout.write(rendered)
    return rendered


def relationship_list_command(client: ApiClient, args: argparse.Namespace) -> list[dict[str, Any]]:
    snapshot = client.snapshot()
    items = list(snapshot.get("relationships", []))
    if args.character:
        character_id = resolve_person(snapshot, args.character)["entityId"]
        items = [item for item in items if character_id in {item.get("from"), item.get("to")}]
    if args.scope:
        items = [item for item in items if item.get("graphScope") == args.scope]
    names = {item["entityId"]: item["name"] for item in snapshot.get("characters", [])}
    if args.json_output:
        emit({"ok": True, "project": client.project, "items": items}, json_output=True)
    elif not items:
        print("没有符合条件的人物关系。")
    else:
        for item in items:
            print(relationship_label(item, names))
    return items


def relationship_show_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    snapshot = client.snapshot()
    relationship = resolve_relationship(snapshot, args.selector)
    detail = client.detail(relationship["entityId"])
    result = {"ok": True, "project": client.project, "item": detail}
    if args.json_output:
        emit(result, json_output=True)
    else:
        names = {item["entityId"]: item["name"] for item in snapshot.get("characters", [])}
        data = detail["data"]
        print(relationship_label(data, names))
        print(f"类型：{data.get('type') or '—'} · 图谱层级：{data.get('graphScope') or '—'} · 连线：{data.get('graphLineMode') or '—'}")
        if data.get("fromImpression"):
            print(f"{names.get(data.get('from'), data.get('from'))}的印象：{data['fromImpression']}")
        if data.get("toImpression"):
            print(f"{names.get(data.get('to'), data.get('to'))}的印象：{data['toImpression']}")
        if data.get("body"):
            print("\n" + str(data["body"]).rstrip())
    return result


def relationship_payload(args: argparse.Namespace, snapshot: dict[str, Any], *, editing: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if not editing:
        payload["fromCharacterId"] = resolve_person(snapshot, args.from_character)["entityId"]
        payload["toCharacterId"] = resolve_person(snapshot, args.to_character)["entityId"]
    for argument, field in (
        ("from_role", "fromRole"), ("to_role", "toRole"),
        ("from_impression", "fromImpression"), ("to_impression", "toImpression"),
        ("scope", "graphScope"), ("line_mode", "graphLineMode"),
        ("label", "label"), ("relationship_type", "type"),
        ("color", "color"), ("body", "body"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            payload[field] = value
    for argument, value_argument, field, label in (
        ("clear_from_role", "from_role", "fromRole", "起点角色"),
        ("clear_to_role", "to_role", "toRole", "终点角色"),
        ("clear_from_impression", "from_impression", "fromImpression", "起点人物印象"),
        ("clear_to_impression", "to_impression", "toImpression", "终点人物印象"),
        ("clear_label", "label", "label", "关系名称"),
        ("clear_type", "relationship_type", "type", "关系类型"),
        ("clear_body", "body", "body", "关系说明"),
    ):
        if getattr(args, argument, False):
            if getattr(args, value_argument, None) is not None:
                raise CliError(f"不能同时设置和清空{label}", code="invalid_argument", exit_code=2)
            payload[field] = ""
    references = selected_references(snapshot, getattr(args, "references", None))
    if references is not None and getattr(args, "clear_references", False):
        raise CliError("不能同时设置和清空引用", code="invalid_argument", exit_code=2)
    if getattr(args, "clear_references", False):
        payload["references"] = []
    elif references is not None:
        payload["references"] = references
    if editing and not payload:
        raise CliError("没有提供需要修改的字段", code="no_changes", exit_code=2)
    return payload


def relationship_add_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    payload = relationship_payload(args, snapshot, editing=False)
    existing = next((item for item in snapshot.get("relationships", []) if {
        item.get("from"), item.get("to")
    } == {payload["fromCharacterId"], payload["toCharacterId"]}), None)
    if existing:
        same_direction = existing.get("from") == payload["fromCharacterId"]
        if not same_direction:
            for left, right in (("fromRole", "toRole"), ("fromImpression", "toImpression")):
                left_present = left in payload
                right_present = right in payload
                left_value = payload.pop(left, None)
                right_value = payload.pop(right, None)
                if left_present:
                    payload[right] = left_value
                if right_present:
                    payload[left] = right_value
        payload.pop("fromCharacterId", None)
        payload.pop("toCharacterId", None)
        if not payload:
            detail = client.detail(existing["entityId"])
            result = {
                "ok": True,
                "project": client.project,
                "revision": snapshot["project"]["revision"],
                "item": detail,
                "unchanged": True,
            }
            emit(result, json_output=args.json_output, human=f"人物关系已存在，未修改：{existing['entityId']}")
            return result
        payload["entityRevision"] = existing["revision"]
        response = client.mutate("PATCH", f"relationships/{quote(existing['entityId'], safe='')}", payload)
        entity_id = existing["entityId"]
        action = "已更新已有关系"
    else:
        payload.setdefault("graphScope", "core")
        payload.setdefault("graphLineMode", "single")
        payload.setdefault("color", "#6f75c9")
        response = client.mutate("POST", "relationships", payload, retry_create_conflict=True)
        changed = response.get("changed", {}).get("relationships", [])
        entity_id = changed[-1]["entityId"] if changed else ""
        action = "已创建人物关系"
    detail = client.detail(entity_id) if entity_id else None
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": detail}
    detail_label = str(detail["data"].get("label") or entity_id) if detail else ""
    emit(result, json_output=args.json_output, human=f"{action}：{detail_label}")
    return result


def relationship_edit_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    relationship = resolve_relationship(snapshot, args.selector)
    payload = relationship_payload(args, snapshot, editing=True)
    payload["entityRevision"] = relationship["revision"]
    response = client.mutate("PATCH", f"relationships/{quote(relationship['entityId'], safe='')}", payload)
    detail = client.detail(relationship["entityId"])
    result = {"ok": True, "project": client.project, "revision": response.get("projectRevision"), "item": detail}
    emit(result, json_output=args.json_output, human=f"已更新人物关系：{detail['data'].get('label') or relationship['entityId']}")
    return result


def relationship_delete_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    _meta, snapshot = client.prepare_write()
    return delete_entity(client, resolve_relationship(snapshot, args.selector), args)


def add_character_fields(parser: argparse.ArgumentParser, *, editing: bool) -> None:
    if editing:
        parser.add_argument("--name")
    else:
        parser.add_argument("name")
        parser.add_argument("--id", dest="stable_id", help="稳定人物 ID；默认自动分配数字 ID")
    parser.add_argument("--role", choices=VISIBLE_ROLES, default=None if editing else "配角", help="网页中的戏份定位")
    parser.add_argument("--scope", dest="character_scope", choices=CHARACTER_SCOPES, default=None if editing else "常驻人物")
    parser.add_argument("--impact", dest="main_plot_impact", type=int, default=None if editing else 50, metavar="0-100")
    parser.add_argument("--color")
    parser.add_argument("--gradient")
    parser.add_argument("--clear-gradient", action="store_true")
    parser.add_argument("--group")
    parser.add_argument("--clear-group", action="store_true")
    visible = parser.add_mutually_exclusive_group()
    visible.add_argument("--graph-visible", dest="graph_visible", action="store_true", default=None if editing else False)
    visible.add_argument("--no-graph-visible", dest="graph_visible", action="store_false")
    parser.add_argument("--alias", dest="aliases", action="append")
    parser.add_argument("--clear-aliases", action="store_true")
    parser.add_argument("--marker", dest="markers", action="append")
    parser.add_argument("--clear-markers", action="store_true")
    parser.add_argument("--fact", dest="facts", action="append", metavar="NAME=VALUE")
    parser.add_argument("--clear-facts", action="store_true")
    parser.add_argument("--core-note", dest="core_persona_notes", action="append", metavar="TEXT")
    parser.add_argument("--core-persona", dest="core_persona_pairs", action="append", metavar="NAME=VALUE")
    parser.add_argument("--clear-core-persona", action="store_true")
    parser.add_argument("--supplement-note", dest="supplement_persona_notes", action="append", metavar="TEXT")
    parser.add_argument("--supplement-persona", dest="supplement_persona_pairs", action="append", metavar="NAME=VALUE")
    parser.add_argument("--clear-supplement-persona", action="store_true")
    parser.add_argument("--supplement", dest="supplements", action="append", metavar="TEXT")
    parser.add_argument("--clear-supplements", action="store_true")
    parser.add_argument("--reference", dest="references", action="append", metavar="SELECTOR")
    parser.add_argument("--clear-references", action="store_true")
    intro = parser.add_mutually_exclusive_group()
    intro.add_argument("--intro")
    intro.add_argument("--intro-file")
    intro.add_argument("--clear-intro", action="store_true")
    destiny = parser.add_mutually_exclusive_group()
    destiny.add_argument("--destiny-outline")
    destiny.add_argument("--destiny-outline-file")
    destiny.add_argument("--clear-destiny-outline", action="store_true")


def add_relationship_fields(parser: argparse.ArgumentParser, *, editing: bool) -> None:
    parser.add_argument("--from-role")
    parser.add_argument("--clear-from-role", action="store_true")
    parser.add_argument("--to-role")
    parser.add_argument("--clear-to-role", action="store_true")
    parser.add_argument("--from-impression")
    parser.add_argument("--clear-from-impression", action="store_true")
    parser.add_argument("--to-impression")
    parser.add_argument("--clear-to-impression", action="store_true")
    parser.add_argument("--label")
    parser.add_argument("--clear-label", action="store_true")
    parser.add_argument("--type", dest="relationship_type")
    parser.add_argument("--clear-type", action="store_true")
    parser.add_argument("--scope", choices=("core", "focus", "hidden"))
    parser.add_argument("--line-mode", choices=("single", "double"))
    parser.add_argument("--color")
    parser.add_argument("--body")
    parser.add_argument("--clear-body", action="store_true")
    parser.add_argument("--reference", dest="references", action="append", metavar="SELECTOR")
    parser.add_argument("--clear-references", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    from storyteller.content_cli import register_content_domains
    from storyteller.import_cli import register_import_domain
    from storyteller.workflow_cli import register_workflow_domains

    parser = StoryArgumentParser(
        prog="story-teller",
        description="通过唯一 Hub 自动复用 Content Worker，管理小说内容",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "常用帮助：\n"
            "  story-teller <命令域> --help\n"
            "  story-teller <命令域> <子命令> --help\n\n"
            "示例：\n"
            "  story-teller character list --json\n"
            "  story-teller plot add --help\n"
            "  story-teller import markdown --help\n\n"
            "完整功能索引：docs/cli-reference.md"
        ),
    )
    parser.add_argument("--project", default="", help="Project ID；通常可自动发现")
    parser.add_argument("--web-url", default="", help="Hub 工作区或 Worker 的基础 URL")
    parser.add_argument("--json", dest="json_output", action="store_true", help="输出稳定 JSON，供自动化使用")
    domains = parser.add_subparsers(dest="domain", required=True)
    character = domains.add_parser("character", aliases=["characters"], help="管理人物、人物关系与人物恢复记录")
    commands = character.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="列出和筛选人物")
    listing.add_argument("--role", choices=VISIBLE_ROLES)
    listing.add_argument("--scope", choices=CHARACTER_SCOPES)
    listing.add_argument("--group")
    listing.add_argument("--query", "-q")
    listing.add_argument("--limit", type=int, default=0)
    listing.set_defaults(handler=character_list_command)

    show = commands.add_parser("show", help="查看完整人物档案及相关内容统计")
    show.add_argument("selector", help="entityId、稳定 ID、唯一姓名或别名")
    show.set_defaults(handler=character_show_command)

    add = commands.add_parser("add", help="新建人物")
    add_character_fields(add, editing=False)
    add.set_defaults(handler=character_add_command)

    edit = commands.add_parser("edit", help="只修改明确提供的人物字段")
    edit.add_argument("selector")
    add_character_fields(edit, editing=True)
    edit.add_argument("--yes", action="store_true", help="确认人物重命名及稳定引用同步")
    edit.set_defaults(handler=character_edit_command)

    delete = commands.add_parser("delete", help="将人物移入回收站")
    delete.add_argument("selector")
    delete.add_argument("--yes", action="store_true")
    delete.set_defaults(handler=character_delete_command)

    trash = commands.add_parser("trash", help="列出人物和人物关系回收站")
    trash.add_argument("--kind", choices=("all", "character", "relationship"), default="all")
    trash.add_argument("--limit", type=int, default=100)
    trash.set_defaults(handler=character_trash_command)

    restore = commands.add_parser("restore", help="恢复人物或人物关系")
    restore.add_argument("selector")
    restore.set_defaults(handler=character_restore_command)

    history = commands.add_parser("history", help="列出人物和人物关系操作")
    history.add_argument("--kind", choices=("all", "character", "relationship"), default="all")
    history.add_argument("--limit", type=int, default=100)
    history.set_defaults(handler=character_history_command)

    undo = commands.add_parser("undo", help="撤销人物或人物关系操作")
    undo.add_argument("operation_id", type=int)
    undo.set_defaults(handler=character_undo_command)

    exporter = commands.add_parser("export", help="导出完整人物 Markdown")
    exporter.add_argument("selector", nargs="?")
    exporter.add_argument("--all", action="store_true", help="导出全部人物")
    exporter.add_argument("--from", dest="from_character", metavar="SELECTOR", help="范围起点（按当前人物顺序）")
    exporter.add_argument("--to", dest="to_character", metavar="SELECTOR", help="范围终点（按当前人物顺序）")
    exporter.add_argument("-o", "--output")
    exporter.set_defaults(handler=character_export_command)

    relationships = commands.add_parser("relationship", aliases=["relationships"], help="管理人物关系和双向印象")
    relationship_commands = relationships.add_subparsers(dest="relationship_command", required=True)
    relationship_list = relationship_commands.add_parser("list", help="列出人物关系")
    relationship_list.add_argument("--character")
    relationship_list.add_argument("--scope", choices=("core", "focus", "hidden"))
    relationship_list.set_defaults(handler=relationship_list_command)
    relationship_show = relationship_commands.add_parser("show", help="查看人物关系")
    relationship_show.add_argument("selector")
    relationship_show.set_defaults(handler=relationship_show_command)
    relationship_add = relationship_commands.add_parser("add", help="新建关系；同一人物对已存在时更新原关系")
    relationship_add.add_argument("from_character")
    relationship_add.add_argument("to_character")
    add_relationship_fields(relationship_add, editing=False)
    relationship_add.set_defaults(handler=relationship_add_command)
    relationship_edit = relationship_commands.add_parser("edit", help="编辑人物关系")
    relationship_edit.add_argument("selector")
    add_relationship_fields(relationship_edit, editing=True)
    relationship_edit.set_defaults(handler=relationship_edit_command)
    relationship_delete = relationship_commands.add_parser("delete", help="将人物关系移入回收站")
    relationship_delete.add_argument("selector")
    relationship_delete.add_argument("--yes", action="store_true")
    relationship_delete.set_defaults(handler=relationship_delete_command)
    register_content_domains(domains)
    register_workflow_domains(domains)
    register_import_domain(domains)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    args: argparse.Namespace | None = None
    try:
        args = parser.parse_args(normalize_global_options(raw_arguments))
        workspace = discover_workspace()
        project = select_project(workspace, args.project)
        client = ApiClient(default_web_url(workspace, args.web_url), project)
        client.meta()
        args.handler(client, args)
        return 0
    except CliError as error:
        json_output = bool(getattr(args, "json_output", False) or "--json" in raw_arguments)
        if json_output:
            payload = {"ok": False, "error": str(error), "code": error.code}
            if error.details:
                payload["details"] = error.details
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(f"story-teller: {error}", file=sys.stderr)
        return error.exit_code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
