from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, replace as dataclass_replace
from pathlib import Path
from typing import Any


HUB_PROTOCOL_VERSION = 3
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def default_hub_state_dir() -> Path:
    configured = str(os.environ.get("STORY_WORLD_HUB_STATE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".story-teller" / "hub").resolve()


@dataclass(frozen=True, slots=True)
class WorkspaceRegistration:
    workspace_id: str
    display_name: str
    project: str
    repository_root: str
    content_root: str
    framework_root: str
    registered_at: int
    last_seen_at: int
    independent_mcp: bool = False
    managed_web: bool = False
    disabled_projects: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "displayName": self.display_name,
            "project": self.project,
            "repositoryRoot": self.repository_root,
            "contentRoot": self.content_root,
            "registeredAt": self.registered_at,
            "lastSeenAt": self.last_seen_at,
            "independentMcp": self.independent_mcp,
            "managedWeb": self.managed_web,
        }


class HubRegistry:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._lock = threading.RLock()
        self._records: dict[str, WorkspaceRegistration] = {}
        self._load()

    @staticmethod
    def _workspace_id(content_root: Path) -> str:
        digest = hashlib.sha256(str(content_root).encode("utf-8")).hexdigest()[:16]
        return f"workspace-{digest}"

    @staticmethod
    def _paths(value: dict[str, Any]) -> tuple[Path, Path, Path, str]:
        repository_root = Path(str(value.get("repositoryRoot") or "")).expanduser().resolve()
        content_root = Path(str(value.get("contentRoot") or "")).expanduser().resolve()
        framework_root = Path(str(value.get("frameworkRoot") or "")).expanduser().resolve()
        project = str(value.get("project") or "").strip()
        if not PROJECT_PATTERN.fullmatch(project):
            raise ValueError("项目名称不合法")
        if not repository_root.is_dir() or not (repository_root / ".git").exists():
            raise ValueError(f"不是可用的 Git 仓库：{repository_root}")
        if content_root == repository_root or repository_root not in content_root.parents:
            raise ValueError("contentRoot 必须位于当前 Git 仓库内")
        if not (content_root / project / "story.db").is_file():
            raise ValueError(f"项目没有 story.db：{content_root / project}")
        allowed_frameworks = {
            repository_root.resolve(),
            (repository_root / "story_teller").resolve(),
        }
        if framework_root not in allowed_frameworks:
            raise ValueError("frameworkRoot 必须是当前仓库或其 story_teller 子模块")
        if not (framework_root / "scripts" / "python.sh").is_file():
            raise ValueError("Story Teller Python 启动器不存在")
        if not (framework_root / "storyteller" / "rag" / "stdio.py").is_file():
            raise ValueError("当前 Story Teller 不支持 stdio worker")
        return repository_root, content_root, framework_root, project

    def prepare(self, value: dict[str, Any]) -> WorkspaceRegistration:
        repository_root, content_root, framework_root, project = self._paths(value)
        now = int(time.time())
        identifier = self._workspace_id(content_root)
        existing = self._records.get(identifier)
        return WorkspaceRegistration(
            workspace_id=identifier,
            display_name=str(value.get("displayName") or repository_root.name or project).strip(),
            project=project,
            repository_root=str(repository_root),
            content_root=str(content_root),
            framework_root=str(framework_root),
            registered_at=existing.registered_at if existing else now,
            last_seen_at=now,
            independent_mcp=existing.independent_mcp if existing else False,
            managed_web=existing.managed_web if existing else False,
            disabled_projects=existing.disabled_projects if existing else (),
        )

    def upsert(self, record: WorkspaceRegistration) -> None:
        with self._lock:
            self._records[record.workspace_id] = record
            self._save()

    def remove(self, workspace_id: str) -> None:
        with self._lock:
            if self._records.pop(workspace_id, None):
                self._save()

    def records(self, *, valid_only: bool = True) -> list[WorkspaceRegistration]:
        with self._lock:
            values = list(self._records.values())
        if valid_only:
            values = [record for record in values if self.is_valid(record)]
        return sorted(values, key=lambda item: (item.display_name.casefold(), item.workspace_id))

    @staticmethod
    def all_projects(record: WorkspaceRegistration) -> list[str]:
        content_root = Path(record.content_root)
        if not content_root.is_dir():
            return []
        return sorted(
            path.name
            for path in content_root.iterdir()
            if path.is_dir()
            and PROJECT_PATTERN.fullmatch(path.name)
            and (path / "story.db").is_file()
        )

    @classmethod
    def projects(cls, record: WorkspaceRegistration) -> list[str]:
        disabled = set(record.disabled_projects)
        return [project for project in cls.all_projects(record) if project not in disabled]

    def set_independent_mcp(self, workspace_id: str, enabled: bool) -> WorkspaceRegistration:
        with self._lock:
            current = self._records.get(workspace_id)
            if current is None:
                raise ValueError(f"工作区不存在：{workspace_id}")
            updated = dataclass_replace(current, independent_mcp=bool(enabled), last_seen_at=int(time.time()))
            self._records[workspace_id] = updated
            self._save()
            return updated

    def set_managed_web(self, workspace_id: str, enabled: bool) -> WorkspaceRegistration:
        with self._lock:
            current = self._records.get(workspace_id)
            if current is None:
                raise ValueError(f"工作区不存在：{workspace_id}")
            updated = dataclass_replace(
                current, managed_web=bool(enabled), last_seen_at=int(time.time())
            )
            self._records[workspace_id] = updated
            self._save()
            return updated

    def set_project_enabled(self, workspace_id: str, project: str, enabled: bool) -> WorkspaceRegistration:
        if not PROJECT_PATTERN.fullmatch(project):
            raise ValueError("项目名称不合法")
        with self._lock:
            current = self._records.get(workspace_id)
            if current is None:
                raise ValueError(f"工作区不存在：{workspace_id}")
            if project not in self.all_projects(current):
                raise ValueError(f"项目不存在：{project}")
            disabled = set(current.disabled_projects)
            if enabled:
                disabled.discard(project)
            else:
                disabled.add(project)
            updated = dataclass_replace(
                current,
                disabled_projects=tuple(sorted(disabled)),
                last_seen_at=int(time.time()),
            )
            self._records[workspace_id] = updated
            self._save()
            return updated

    def default_project(self, record: WorkspaceRegistration) -> str:
        projects = self.projects(record)
        workspace_matches = [
            project for project in projects
            if project.casefold() == record.display_name.casefold()
        ]
        if len(workspace_matches) == 1:
            return workspace_matches[0]
        if len(projects) == 1:
            return projects[0]
        return ""

    def resolve_project(self, record: WorkspaceRegistration, selector: str = "") -> str:
        projects = self.projects(record)
        clean = str(selector or "").strip()
        if clean:
            if clean in projects:
                return clean
            raise ValueError(
                f"工作区 {record.display_name} 中不存在项目 {clean}；"
                f"当前可用：{', '.join(projects) or '无'}"
            )
        default = self.default_project(record)
        if default:
            return default
        raise ValueError(
            f"工作区 {record.display_name} 包含多个项目，请指定 project："
            f"{', '.join(projects) or '无'}"
        )

    def public_dict(self, record: WorkspaceRegistration) -> dict[str, Any]:
        projects = self.projects(record)
        default = self.default_project(record)
        return {
            **record.public_dict(),
            "registeredProject": record.project,
            "projects": projects,
            "allProjects": self.all_projects(record),
            "disabledProjects": list(record.disabled_projects),
            "defaultProject": default,
            "requiresProjectSelection": not bool(default) and len(projects) > 1,
        }

    def resolve(self, selector: str = "") -> WorkspaceRegistration:
        records = self.records()
        clean = str(selector or "").strip()
        if not clean:
            if len(records) == 1:
                return records[0]
            choices = ", ".join(record.display_name for record in records)
            raise ValueError(f"请指定 workspace；当前可用：{choices or '无'}")
        exact = [
            record for record in records
            if clean in {record.workspace_id, record.display_name}
        ]
        if not exact:
            # Preserve the original single-project selector as a compatibility alias.
            exact = [record for record in records if clean == record.project]
        if len(exact) == 1:
            return exact[0]
        if not exact:
            raise ValueError(f"工作区不存在：{clean}")
        raise ValueError(f"工作区名称不唯一，请使用 workspaceId：{clean}")

    @classmethod
    def is_valid(cls, record: WorkspaceRegistration) -> bool:
        try:
            repository_root = Path(record.repository_root).expanduser().resolve()
            content_root = Path(record.content_root).expanduser().resolve()
            framework_root = Path(record.framework_root).expanduser().resolve()
            if not repository_root.is_dir() or not (repository_root / ".git").exists():
                return False
            if content_root == repository_root or repository_root not in content_root.parents:
                return False
            if not cls.all_projects(record):
                return False
            if framework_root not in {
                repository_root,
                (repository_root / "story_teller").resolve(),
            }:
                return False
            if not (framework_root / "scripts" / "python.sh").is_file():
                return False
            if not (framework_root / "storyteller" / "rag" / "stdio.py").is_file():
                return False
        except (OSError, ValueError):
            return False
        return True

    def prune(self) -> list[str]:
        with self._lock:
            removed = [identifier for identifier, record in self._records.items() if not self.is_valid(record)]
            for identifier in removed:
                self._records.pop(identifier, None)
            if removed:
                self._save()
            return removed

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Hub 注册表损坏：{self.path}") from error
        stored_version = int(payload.get("protocolVersion", 0))
        if stored_version not in {1, 2, HUB_PROTOCOL_VERSION}:
            raise ValueError("Hub 注册表协议版本不兼容")
        for value in payload.get("workspaces", []):
            try:
                value = dict(value)
                value.setdefault("independent_mcp", False)
                value.setdefault("managed_web", False)
                value.setdefault("disabled_projects", ())
                value["disabled_projects"] = tuple(value["disabled_projects"])
                record = WorkspaceRegistration(**value)
            except (TypeError, ValueError):
                continue
            expected_id = self._workspace_id(Path(record.content_root).expanduser().resolve())
            if record.workspace_id != expected_id:
                record = dataclass_replace(record, workspace_id=expected_id)
            self._records[record.workspace_id] = record

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = {
            "protocolVersion": HUB_PROTOCOL_VERSION,
            "workspaces": [asdict(record) for record in self.records(valid_only=False)],
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
