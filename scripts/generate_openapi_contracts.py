#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storyteller.app import create_app
from storyteller.settings import Settings


DEFAULT_OUTPUT = ROOT / "frontend/src/api/generated/openapi.ts"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def property_name(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def reference_type(reference: str) -> str:
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        return "unknown"
    name = reference.removeprefix(prefix).replace("~1", "/").replace("~0", "~")
    return f"components[\"schemas\"][{property_name(name)}]"


def render_object(schema: dict[str, Any], level: int) -> str:
    properties = schema.get("properties") or {}
    additional = schema.get("additionalProperties")
    if not properties:
        if isinstance(additional, dict):
            return f"Record<string, {render_type(additional, level)}>"
        if additional is False:
            return "Record<string, never>"
        return "Record<string, unknown>"

    required = set(schema.get("required") or [])
    indent = "  " * level
    child_indent = "  " * (level + 1)
    rows = ["{"]
    for name in sorted(properties):
        optional = "" if name in required else "?"
        rendered = render_type(properties[name], level + 1)
        rows.append(f"{child_indent}{property_name(name)}{optional}: {rendered};")
    rows.append(f"{indent}}}")
    value = "\n".join(rows)
    if isinstance(additional, dict):
        return f"({value} & Record<string, {render_type(additional, level)}>)"
    return value


def render_type(schema: Any, level: int = 0) -> str:
    if not isinstance(schema, dict) or not schema:
        return "unknown"
    if "$ref" in schema:
        value = reference_type(str(schema["$ref"]))
    elif "const" in schema:
        value = json.dumps(schema["const"], ensure_ascii=False)
    elif schema.get("enum") is not None:
        choices = schema.get("enum") or []
        value = " | ".join(json.dumps(item, ensure_ascii=False) for item in choices) or "never"
    elif schema.get("oneOf"):
        value = " | ".join(render_type(item, level) for item in schema["oneOf"])
    elif schema.get("anyOf"):
        value = " | ".join(render_type(item, level) for item in schema["anyOf"])
    elif schema.get("allOf"):
        value = " & ".join(render_type(item, level) for item in schema["allOf"])
    else:
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            value = " | ".join(
                render_type({**schema, "type": item}, level) for item in schema_type
            )
        elif schema_type == "string":
            value = "string"
        elif schema_type in {"integer", "number"}:
            value = "number"
        elif schema_type == "boolean":
            value = "boolean"
        elif schema_type == "null":
            value = "null"
        elif schema_type == "array":
            item = render_type(schema.get("items") or {}, level)
            value = f"Array<{item}>"
        elif schema_type == "object" or "properties" in schema or "additionalProperties" in schema:
            value = render_object(schema, level)
        else:
            value = "unknown"
    if schema.get("nullable") and "null" not in value.split(" | "):
        value = f"{value} | null"
    return value


def response_schema(operation: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses") or {}
    preferred = ["200", "201", "202", "204"]
    for status in [*preferred, *sorted(responses)]:
        response = responses.get(status)
        if not isinstance(response, dict):
            continue
        content = response.get("content") or {}
        for content_type in ("application/json", "text/plain"):
            media = content.get(content_type)
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return media["schema"]
        if status == "204":
            return {"type": "null"}
    return {}


def request_schema(operation: dict[str, Any]) -> dict[str, Any]:
    content = (operation.get("requestBody") or {}).get("content") or {}
    media = content.get("application/json")
    return media.get("schema") if isinstance(media, dict) else {}


def parameter_type(
    operation: dict[str, Any],
    location: str,
    level: int,
) -> str:
    parameters = [
        item for item in operation.get("parameters") or []
        if isinstance(item, dict) and item.get("in") == location
    ]
    if not parameters:
        return "Record<string, never>"
    required = {str(item["name"]) for item in parameters if item.get("required")}
    properties = {
        str(item["name"]): item.get("schema") or {}
        for item in parameters
    }
    return render_object(
        {"type": "object", "properties": properties, "required": sorted(required)},
        level,
    )


def build_contract(schema: dict[str, Any]) -> str:
    lines = [
        "// This file is generated by scripts/generate_openapi_contracts.py.",
        "// Do not edit it by hand; run `npm run contract:generate`.",
        "",
        "export interface components {",
        "  schemas: {",
    ]
    schemas = (schema.get("components") or {}).get("schemas") or {}
    for name in sorted(schemas):
        rendered = render_type(schemas[name], 2)
        lines.append(f"    {property_name(name)}: {rendered};")
    lines.extend(["  };", "}", "", "export interface operations {"])

    operations: list[tuple[str, str, str, dict[str, Any]]] = []
    for path, path_item in sorted((schema.get("paths") or {}).items()):
        if not isinstance(path_item, dict):
            continue
        inherited = path_item.get("parameters") or []
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict) or not operation.get("operationId"):
                continue
            merged = dict(operation)
            merged["parameters"] = [*inherited, *(operation.get("parameters") or [])]
            operations.append((str(operation["operationId"]), method, path, merged))

    for operation_id, method, path, operation in sorted(operations):
        lines.extend([
            f"  {property_name(operation_id)}: {{",
            f"    method: {property_name(method.upper())};",
            f"    path: {property_name(path)};",
            f"    pathParameters: {parameter_type(operation, 'path', 2)};",
            f"    queryParameters: {parameter_type(operation, 'query', 2)};",
            f"    headerParameters: {parameter_type(operation, 'header', 2)};",
            f"    requestBody: {render_type(request_schema(operation), 2)};",
            f"    response: {render_type(response_schema(operation), 2)};",
            "  };",
        ])
    lines.extend(["}", "", "export type OperationId = keyof operations;", ""])
    return "\n".join(lines)


def openapi_schema() -> dict[str, Any]:
    settings = Settings.create(
        ROOT,
        content_root=ROOT / "build/contract-content",
        frontend_root=ROOT / "build/contract-frontend",
        default_project="contract",
    )
    return create_app(settings).openapi()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 FastAPI OpenAPI 的 TypeScript 契约")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    generated = build_contract(openapi_schema())
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current == generated:
            print(f"OpenAPI TypeScript 契约已同步：{display_path(output)}")
            return 0
        print("".join(difflib.unified_diff(
            current.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=str(output),
            tofile="generated",
        )))
        print("契约已漂移，请运行 npm run contract:generate")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generated, encoding="utf-8")
    print(f"已生成 OpenAPI TypeScript 契约：{display_path(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
