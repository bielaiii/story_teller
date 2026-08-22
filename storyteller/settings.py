from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def require_loopback(host: str) -> str:
    value = str(host or "").strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        if value.lower() == "localhost":
            return value
        raise ValueError("Story Teller 只允许监听 localhost") from error
    if not address.is_loopback:
        raise ValueError("Story Teller 只允许监听 loopback 地址")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    content_root: Path
    frontend_root: Path
    default_project: str = ""
    enabled_projects: tuple[str, ...] = ()
    host: str = "127.0.0.1"
    port: int = 4187

    @classmethod
    def create(
        cls,
        root: Path,
        content_root: Path | None = None,
        frontend_root: Path | None = None,
        default_project: str = "",
        enabled_projects: tuple[str, ...] | list[str] = (),
        host: str = "127.0.0.1",
        port: int = 4187,
    ) -> "Settings":
        resolved_root = Path(root).resolve()
        resolved_content = Path(content_root or resolved_root / "content").resolve()
        resolved_frontend = Path(frontend_root or resolved_root / "dist").resolve()
        clean_project = str(default_project or "").strip()
        if clean_project and not PROJECT_PATTERN.fullmatch(clean_project):
            raise ValueError("默认项目名称不合法")
        clean_enabled = tuple(dict.fromkeys(str(item).strip() for item in enabled_projects if str(item).strip()))
        if any(not PROJECT_PATTERN.fullmatch(item) for item in clean_enabled):
            raise ValueError("启用的项目名称不合法")
        if clean_project and clean_enabled and clean_project not in clean_enabled:
            raise ValueError("默认项目不在启用项目列表中")
        safe_host = require_loopback(host)
        safe_port = int(port)
        if not 1 <= safe_port <= 65535:
            raise ValueError("端口不合法")
        return cls(
            root=resolved_root,
            content_root=resolved_content,
            frontend_root=resolved_frontend,
            default_project=clean_project,
            enabled_projects=clean_enabled,
            host=safe_host,
            port=safe_port,
        )

    def project_root(self, project: str) -> Path:
        project_id = str(project or "").strip()
        if not PROJECT_PATTERN.fullmatch(project_id):
            raise ValueError("项目名称不合法")
        if self.enabled_projects and project_id not in self.enabled_projects:
            raise ValueError(f"项目 {project_id} 当前未启用")
        root = (self.content_root / project_id).resolve()
        if self.content_root != root.parent:
            raise ValueError("项目路径超出内容目录")
        return root
