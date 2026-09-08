"""Entity-aware merge planning. Plans contain rows, never write user data."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from typing import Any

from storyteller.domain.errors import DomainError
from storyteller.domain.uow import canonical_json

VERSIONS = "_entityVersionsV1"
OWNER = {
    "entities": "id", "plots": "entity_id", "fragments": "entity_id",
    "plot_tags": "plot_id", "plot_characters": "plot_id", "plot_entries": "plot_id",
    "plot_timeline_lines": "plot_id", "fragment_tags": "fragment_id",
    "entity_references": "source_entity_id", "assets": "entity_id",
}


def owned(table: str, row: dict, identifier: str) -> bool:
    return table in OWNER and row.get(OWNER[table]) == identifier


def bundle(snapshot: dict, identifier: str) -> list[dict]:
    return [dict(table=t, key=json.loads(k), row=json.loads(v))
            for (t, k), v in sorted(snapshot.items()) if owned(t, json.loads(v), identifier)]


def entity_of(version: list[dict]) -> dict:
    return next((item["row"] for item in version if item["table"] == "entities"), {})


def supported(versions: dict | None) -> bool:
    if not versions:
        return False
    for side in ("ours", "theirs"):
        e = entity_of(versions.get(side, []))
        if e.get("kind") not in {"plot", "fragment"} or e.get("deleted_at") is not None:
            return False
        # A line is a container, not a standalone alternative manuscript.
        if e["kind"] == "fragment" and json.loads(e.get("extra_json", "{}")).get("fragmentType") == "line":
            return False
    return True


def new_id(identifier: str, seed: str) -> str:
    return identifier.split(":")[0] + ":merge-" + uuid.uuid5(uuid.NAMESPACE_URL, seed + identifier).hex[:20]


def available_title(title: str, occupied: set[str]) -> str:
    if title not in occupied:
        return title
    candidate = title + "（远程版本）"
    index = 2
    while candidate in occupied:
        candidate = f"{title}（远程版本 {index}）"
        index += 1
    return candidate


def remap_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [remap_value(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: remap_value(v, mapping) for k, v in value.items()}
    return value


def remap_row(table: str, row: dict, mapping: dict[str, str]) -> dict:
    result = {k: remap_value(v, mapping) if k.endswith("_id") or k in {"id", "marker"} else v
              for k, v in row.items()}
    if table == "entities" and row["id"] in mapping:
        result["stable_id"] = result["id"].split(":", 1)[1]
    if "extra_json" in result:
        result["extra_json"] = canonical_json(remap_value(json.loads(result["extra_json"]), mapping))
    return result


def remap_independent_fragments(base: dict, ours: dict, theirs: dict, seed: str) -> dict:
    mapping = {}
    for (table, key), raw in theirs.items():
        if table != "entities" or (table, key) in base or (table, key) not in ours:
            continue
        e = json.loads(raw)
        if e.get("kind") == "fragment" and bundle(ours, e["id"]) != bundle(theirs, e["id"]):
            mapping[e["id"]] = new_id(e["id"], seed)
    # Equal child rows can still belong to two independently created containers.
    changed = True
    while changed:
        changed = False
        for (table, key), raw in theirs.items():
            if table != "entities" or (table, key) in base or (table, key) not in ours:
                continue
            e = json.loads(raw)
            if e.get("kind") != "fragment" or e["id"] in mapping:
                continue
            if json.loads(e.get("extra_json", "{}")).get("parentFragmentId") in mapping:
                mapping[e["id"]] = new_id(e["id"], seed)
                changed = True
    titles = {json.loads(v)["title"] for (t, _), v in ours.items() if t == "entities" and json.loads(v).get("kind") == "fragment"}
    result = {}
    max_ref = max([json.loads(v)["id"] for s in (base, ours, theirs) for (t, _), v in s.items() if t == "entity_references"] or [0])
    for (table, key), raw in theirs.items():
        row = remap_row(table, json.loads(raw), mapping)
        keys = json.loads(key)
        if table == "entities" and json.loads(raw)["id"] in mapping:
            row["title"] = available_title(row["title"], titles)
            titles.add(row["title"])
        # Auto-increment reference IDs are also local to each checkout.
        if table == "entity_references" and (table, key) not in base and (table, key) in ours and canonical_json(row) != ours[(table, key)]:
            max_ref += 1
            row["id"] = max_ref
        result[(table, canonical_json({k: row[k] for k in keys}))] = canonical_json(row)
    # Newly inserted children are independent manuscripts, even when their local
    # chapter/order counters happened to use the same slot in a shared line.
    occupied_numbers: dict[str, set[int]] = {}
    occupied_orders: dict[str, set[int]] = {}
    for (table, _), raw in ours.items():
        e = json.loads(raw)
        if table != "entities" or e.get("kind") != "fragment" or e.get("deleted_at") is not None:
            continue
        extra = json.loads(e.get("extra_json", "{}"))
        parent = extra.get("parentFragmentId")
        if parent:
            occupied_orders.setdefault(parent, set()).add(int(extra.get("fragmentOrder") or 0))
            if extra.get("chapterNumber") is not None:
                occupied_numbers.setdefault(parent, set()).add(int(extra["chapterNumber"]))
    incoming = []
    for (table, key), raw in result.items():
        if table != "entities" or (table, key) in ours or (table, key) in base:
            continue
        e = json.loads(raw)
        if e.get("kind") == "fragment" and e.get("deleted_at") is None:
            incoming.append((key, e, json.loads(e.get("extra_json", "{}"))))
    for key, e, extra in sorted(incoming, key=lambda item: (str(item[2].get("parentFragmentId") or ""), int(item[2].get("fragmentOrder") or 0), item[0])):
        parent = extra.get("parentFragmentId")
        if not parent:
            continue
        orders = occupied_orders.setdefault(parent, set())
        order = int(extra.get("fragmentOrder") or 0)
        while order in orders:
            order += 1
        extra["fragmentOrder"] = order
        orders.add(order)
        if extra.get("chapterNumber") is not None:
            numbers = occupied_numbers.setdefault(parent, set())
            number = int(extra["chapterNumber"])
            while number in numbers:
                number += 1
            extra["chapterNumber"] = number
            numbers.add(number)
        e["extra_json"] = canonical_json(extra)
        result[("entities", key)] = canonical_json(e)
    return result


def attach_versions(conflicts: list, snapshots: tuple) -> dict[str, dict]:
    """Attach exact side snapshots, before auto-merge can mix their metadata."""
    versions = {}
    content_ids = set()
    ignored = {"revision", "created_at", "updated_at", "sort_key", "story_sort_key", "chapter_number"}
    for conflict in conflicts:
        if conflict.table not in {"entities", "plots", "fragments"}:
            continue
        ours = json.loads(conflict.ours or "{}")
        theirs = json.loads(conflict.theirs or "{}")
        if any(ours.get(k) != theirs.get(k) for k in set(ours) | set(theirs) if k not in ignored):
            content_ids.add(conflict.entity_id)
    for conflict in conflicts:
        identifier = conflict.entity_id
        if identifier in content_ids and identifier not in versions and identifier and identifier.split(":")[0] in {"plot", "fragment"}:
            value = {side: bundle(s, identifier) for side, s in zip(("base", "ours", "theirs"), snapshots)}
            if supported(value):
                versions[identifier] = value
    return versions


def replace_bundle(snapshot: dict, identifier: str, version: list[dict]) -> None:
    for key, raw in list(snapshot.items()):
        if owned(key[0], json.loads(raw), identifier):
            del snapshot[key]
    for item in version:
        snapshot[(item["table"], canonical_json(item["key"]))] = canonical_json(item["row"])


def retain_both(snapshot: dict, identifier: str, versions: dict, seed: str, copies_mapping: dict | None = None) -> dict:
    if not supported(versions):
        raise DomainError("这项冲突没有完整的两侧内容，不能保留为两份")
    duplicate = new_id(identifier, seed)
    if ("entities", canonical_json({"id": duplicate})) in snapshot:
        raise DomainError("保留两份的目标编号已存在，请重新预览")
    replace_bundle(snapshot, identifier, versions["ours"])
    copied = deepcopy(versions["theirs"])
    mapping = copies_mapping or {identifier: duplicate}
    ours_entity = entity_of(versions["ours"])
    max_ref = max([json.loads(v)["id"] for (t, _), v in snapshot.items() if t == "entity_references"] or [0])
    filenames = {}
    for item in copied:
        row = remap_row(item["table"], item["row"], mapping)
        if item["table"] == "entity_references":
            max_ref += 1
            row["id"] = max_ref
        if item["table"] == "assets":
            row["id"] = uuid.uuid5(uuid.NAMESPACE_URL, seed + str(row["id"])).hex
            old = row["filename"]
            stem, dot, suffix = old.rpartition(".")
            row["filename"] = (stem if dot else old) + "-" + row["id"][:12] + (dot + suffix if dot else "")
            filenames[old] = row["filename"]
        if item["table"] == "entities":
            row["revision"] = 1
            occupied = {json.loads(raw)["title"] for (table, _), raw in snapshot.items()
                        if table == "entities" and json.loads(raw)["kind"] == row["kind"]}
            row["title"] = available_title(row["title"], occupied)
        item["row"] = row
        item["key"] = {k: row[k] for k in item["key"]}
    for item in copied:
        for column in ("body_markdown", "summary"):
            if column in item["row"]:
                for old, new in filenames.items():
                    item["row"][column] = item["row"][column].replace(old, new)
    replace_bundle(snapshot, duplicate, copied)
    return {"entityId": identifier, "newEntityId": duplicate,
            "title": entity_of(copied)["title"], "kind": ours_entity["kind"]}


def arrange_copies(snapshot: dict, copies: list[dict]) -> None:
    rows = {json.loads(v)["id"]: json.loads(v) for (t, _), v in snapshot.items() if t == "entities"}
    plots = {json.loads(v)["entity_id"]: json.loads(v) for (t, _), v in snapshot.items() if t == "plots"}
    plot_copies = {x["newEntityId"] for x in copies if x["kind"] == "plot"}
    active = sorted([p for id, p in plots.items() if rows[id]["deleted_at"] is None and id not in plot_copies], key=lambda p: (p["sort_key"], p["entity_id"]))
    for copy in copies:
        identifier, duplicate = copy["entityId"], copy["newEntityId"]
        if copy["kind"] == "plot":
            p = plots[duplicate]
            anchor = next(i for i, row in enumerate(active) if row["entity_id"] == identifier)
            p["chapter_number"] = (active[anchor]["chapter_number"] or anchor + 1) + 1
            p["chapter_id"] = active[anchor]["chapter_id"]
            active.insert(anchor + 1, p)
            number = p["chapter_number"]
            for after in active[anchor + 2:]:
                if after["chapter_number"] != number:
                    break
                after["chapter_number"] += 1
                number += 1
            if number > 99999:
                raise DomainError("双保留后的章号超过 99999，请先调整章号")
        else:
            original = json.loads(rows[identifier].get("extra_json", "{}"))
            extra = json.loads(rows[duplicate].get("extra_json", "{}"))
            same_parent = extra.get("parentFragmentId") == original.get("parentFragmentId")
            parent = extra.get("parentFragmentId")
            if parent and (parent not in rows or rows[parent]["deleted_at"] is not None or json.loads(rows[parent].get("extra_json", "{}")).get("fragmentType") != "line"):
                raise DomainError("副本所属的剧情线不存在，请先调整关联冲突的选择")
            extra["fragmentOrder"] = int(original.get("fragmentOrder") or 0) + 1 if same_parent else int(extra.get("fragmentOrder") or 0)
            for e in rows.values():
                if e["kind"] != "fragment" or e["id"] == duplicate or e["deleted_at"] is not None:
                    continue
                data = json.loads(e.get("extra_json", "{}"))
                if data.get("parentFragmentId") == extra.get("parentFragmentId") and int(data.get("fragmentOrder") or 0) >= extra["fragmentOrder"]:
                    data["fragmentOrder"] = int(data.get("fragmentOrder") or 0) + 1
                    e["extra_json"] = canonical_json(data)
            if same_parent and original.get("chapterNumber") is not None:
                extra["chapterNumber"] = int(original["chapterNumber"]) + 1
            if extra.get("chapterNumber") is not None:
                siblings = sorted([e for e in rows.values() if e["kind"] == "fragment" and e["id"] != duplicate and e["deleted_at"] is None], key=lambda e: json.loads(e.get("extra_json", "{}")).get("chapterNumber") or 0)
                n = extra["chapterNumber"]
                for sibling in siblings:
                    data = json.loads(sibling.get("extra_json", "{}"))
                    if data.get("parentFragmentId") == extra.get("parentFragmentId") and data.get("chapterNumber") == n:
                        data["chapterNumber"] = n + 1
                        sibling["extra_json"] = canonical_json(data)
                        n += 1
            rows[duplicate]["extra_json"] = canonical_json(extra)
    if plot_copies:
        # Normalize reading ranks only. Independent story-time anchors remain intact.
        for index, p in enumerate(active, 1):
            p["sort_key"] = f"{index * 10**12:024d}"
            title = rows[p["entity_id"]]["title"]
            if re.fullmatch(r"第\s*\d+\s*章(?:（远程版本）)?", title):
                rows[p["entity_id"]]["title"] = f"第 {p['chapter_number']} 章"
        for copy in copies:
            if copy["kind"] != "plot":
                continue
            p = plots[copy["newEntityId"]]
            anchor = plots[copy["entityId"]]
            # Keep explicit story timing near the remote version's original slot;
            # follow-reading copies go just after the current version.
            origin = anchor if p["story_order_mode"] == "follow_reading" else p
            lower = int(origin["story_sort_key"])
            higher = [int(v["story_sort_key"]) for v in plots.values() if str(v["story_sort_key"]).isdigit() and int(v["story_sort_key"]) > lower and v is not p]
            higher += [int(json.loads(v)["story_sort_key"]) for (t, _), v in snapshot.items() if t == "plot_timeline_lines" and str(json.loads(v)["story_sort_key"]).isdigit() and int(json.loads(v)["story_sort_key"]) > lower]
            upper = min(higher) if higher else lower + 10**12
            if upper - lower < 2:
                raise DomainError("故事时间排序位置不足，请先整理时间线")
            p["story_sort_key"] = f"{(lower + upper)//2:024d}"
            for key, raw in list(snapshot.items()):
                row = json.loads(raw)
                if key[0] == "plot_timeline_lines" and row["plot_id"] == p["entity_id"]:
                    row["story_sort_key"] = p["story_sort_key"]
                    snapshot[key] = canonical_json(row)
    for identifier, e in rows.items():
        snapshot[("entities", canonical_json({"id": identifier}))] = canonical_json(e)
    for identifier, p in plots.items():
        snapshot[("plots", canonical_json({"entity_id": identifier}))] = canonical_json(p)


def token_for(revision: int, conflicts: list) -> str:
    return hashlib.sha256(canonical_json([revision, [dict(r) for r in conflicts]]).encode()).hexdigest()
