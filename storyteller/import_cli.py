from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from storyteller.fragment_cli import ApiClient, CliError, emit


HARD_CONFLICTS = {"chapterNumber", "ambiguousReference"}


@dataclass(frozen=True, slots=True)
class LocalMarkdownFile:
    source: Path
    import_path: str

    def payload(self) -> dict[str, Any]:
        try:
            stat = self.source.stat()
            text = self.source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise CliError(
                f"无法读取 Markdown：{self.source}（{error}）",
                code="file_error",
                exit_code=2,
            ) from error
        return {
            "path": self.import_path,
            "text": text,
            "modifiedAt": int(stat.st_mtime),
        }


def _relative_import_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise CliError(
            f"导入文件必须位于 --root 内：{path}",
            code="invalid_import_path",
            exit_code=2,
        ) from error
    value = relative.as_posix()
    if not value.startswith(("plots/", "fragments/")):
        raise CliError(
            f"导入路径必须位于 plots/ 或 fragments/：{value}",
            code="invalid_import_path",
            exit_code=2,
        )
    return value


def collect_markdown_files(
    sources: Iterable[str],
    *,
    root: str,
    recursive: bool,
) -> list[LocalMarkdownFile]:
    bundle_root = Path(root).expanduser().resolve()
    if not bundle_root.is_dir():
        raise CliError(f"导入根目录不存在：{bundle_root}", code="file_error", exit_code=2)

    discovered: dict[Path, LocalMarkdownFile] = {}
    for raw in sources:
        candidate = Path(raw).expanduser()
        candidate = candidate if candidate.is_absolute() else Path.cwd() / candidate
        candidate = candidate.resolve()
        if candidate.is_dir():
            iterator = candidate.rglob("*.md") if recursive else candidate.glob("*.md")
            paths = sorted((item.resolve() for item in iterator if item.is_file()), key=str)
            if not paths:
                suffix = "（可用 --recursive 扫描子目录）" if not recursive else ""
                raise CliError(
                    f"目录中没有 Markdown 文件：{candidate}{suffix}",
                    code="no_markdown_files",
                    exit_code=2,
                )
        elif candidate.is_file():
            paths = [candidate]
        else:
            raise CliError(f"导入源不存在：{candidate}", code="file_error", exit_code=2)

        for path in paths:
            if path.suffix.lower() != ".md":
                raise CliError(f"只支持 .md 文件：{path}", code="invalid_import_path", exit_code=2)
            discovered[path] = LocalMarkdownFile(path, _relative_import_path(path, bundle_root))

    if not discovered:
        raise CliError("至少提供一个 Markdown 文件或目录", code="no_markdown_files", exit_code=2)
    return sorted(discovered.values(), key=lambda item: item.import_path)


def _payload(files: Iterable[LocalMarkdownFile]) -> list[dict[str, Any]]:
    return [item.payload() for item in files]


def _conflict_types(preview: dict[str, Any]) -> set[str]:
    return {
        str(conflict)
        for item in preview.get("conflicts", [])
        for conflict in item.get("conflicts", [])
    }


def _preview_summary(preview: dict[str, Any]) -> str:
    imports = sum(1 for item in preview.get("items", []) if item.get("action") == "import")
    skipped = sum(1 for item in preview.get("items", []) if item.get("action") == "skip")
    conflicts = len(preview.get("conflicts", []))
    return f"预览完成：{imports} 个待导入，{skipped} 个重复跳过，{conflicts} 个冲突。"


def _confirm(message: str) -> bool:
    if not sys.stdin.isatty():
        raise CliError("非交互环境应用导入必须添加 --yes", code="confirmation_required", exit_code=2)
    return input(f"{message} [y/N] ").strip().lower() in {"y", "yes"}


def markdown_import_command(client: ApiClient, args: argparse.Namespace) -> dict[str, Any]:
    files = collect_markdown_files(args.sources, root=args.root, recursive=args.recursive)
    _meta, snapshot = client.prepare_write()
    preview = client.request(
        "POST",
        client.project_path("imports/markdown/preview"),
        payload={
            "baseRevision": snapshot["project"]["revision"],
            "files": _payload(files),
        },
        mutation=True,
    )
    conflict_types = _conflict_types(preview)
    hard = sorted(conflict_types & HARD_CONFLICTS)
    if hard:
        raise CliError(
            f"导入存在必须先解决的冲突：{', '.join(hard)}",
            code="import_conflict",
            exit_code=5,
            details={"preview": preview},
        )
    if "title" in conflict_types and not args.allow_title_conflicts:
        raise CliError(
            "导入存在同名内容；确认需要同名导入后添加 --allow-title-conflicts",
            code="title_conflict",
            exit_code=5,
            details={"preview": preview},
        )

    if args.check:
        result = {"ok": True, "project": client.project, "mode": "preview", "preview": preview}
        emit(result, json_output=args.json_output, human=_preview_summary(preview))
        return result

    if not args.yes and not _confirm(_preview_summary(preview) + " 确认应用导入？"):
        result = {"ok": True, "project": client.project, "mode": "cancelled", "preview": preview}
        emit(result, json_output=args.json_output, human="已取消导入，数据库未修改。")
        return result

    # Re-read every source after confirmation. The server compares this bundle with
    # the preview fingerprint, so an editor save during the prompt cannot slip in.
    response = client.request(
        "POST",
        client.project_path("imports/markdown/apply"),
        payload={
            "baseRevision": preview["baseRevision"],
            "files": _payload(files),
            "allowConflicts": bool(args.allow_title_conflicts),
            "previewFingerprint": preview["fingerprint"],
        },
        mutation=True,
    )
    imported = response.get("import", {})
    result = {
        "ok": True,
        "project": client.project,
        "mode": "applied",
        "revision": response.get("projectRevision"),
        "preview": preview,
        "import": imported,
        "operation": response.get("operation"),
        "warnings": response.get("warnings", []),
    }
    emit(
        result,
        json_output=args.json_output,
        human=(
            f"导入完成：新增 {imported.get('count', 0)} 个，"
            f"跳过 {imported.get('skipped', 0)} 个；当前 revision {response.get('projectRevision')}。"
        ),
    )
    return result


def register_import_domain(domains: argparse._SubParsersAction) -> None:
    import_domain = domains.add_parser("import", help="从外部文件预览并原子导入内容")
    formats = import_domain.add_subparsers(dest="import_format", required=True)
    markdown = formats.add_parser("markdown", help="导入 plots/ 与 fragments/ Markdown bundle")
    markdown.add_argument("sources", nargs="+", help="Markdown 文件或目录")
    markdown.add_argument(
        "--root",
        default=".",
        help="bundle 根目录；导入路径必须位于其 plots/ 或 fragments/ 下（默认当前目录）",
    )
    markdown.add_argument("--recursive", action="store_true", help="递归扫描目录下的 .md 文件")
    markdown.add_argument("--check", action="store_true", help="只预览和校验，不写数据库")
    markdown.add_argument("--yes", action="store_true", help="跳过应用前的交互确认")
    markdown.add_argument(
        "--allow-title-conflicts",
        action="store_true",
        help="显式允许与已有内容同名；章号和歧义引用冲突仍会阻止导入",
    )
    markdown.set_defaults(handler=markdown_import_command)
