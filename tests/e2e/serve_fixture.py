import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import server as server_module  # noqa: E402
from server import StoryTellerHandler, StoryTellerServer  # noqa: E402


runtime_root = ROOT / "tests" / "e2e" / ".runtime-content"
project_root = runtime_root / "novel"
if runtime_root.exists():
    shutil.rmtree(runtime_root)
for directory in ("characters", "plots", "entries", "fragments", "relationships"):
    (project_root / directory).mkdir(parents=True, exist_ok=True)
server_module.STATE_ROOT = runtime_root / ".state"
server_module.UNDO_PATH = server_module.STATE_ROOT / "last-refactor.json"

(project_root / "manifest.md").write_text(
    "---\ntitle: 浏览器测试作品\neyebrow: Story Teller\nchapters: [act1]\nchapterAct1: 第一篇\n---\n",
    encoding="utf-8",
)
(project_root / "timeline.md").write_text(
    "---\nversion: 2\nmainLine: 主线\nlineSpacing: 72\ntopPadding: 54\nsidePadding: 34\npixelsPerStoryUnit: 760\n---\n\n## Lines\n\n- name: 主线\n  color: \"#d65f8f\"\n  side: center\n  order: 1\n",
    encoding="utf-8",
)
(project_root / "graph-layout.md").write_text(
    "---\nnodeSpacing: 116\nrelationshipDistance: 250\nleafDistanceExtra: 48\ncenterStrength: 1\ngroupStrength: 1\nleafStrength: 1\n---\n",
    encoding="utf-8",
)
(project_root / "characters" / "1-沈清妙.md").write_text(
    "---\nid: 1\nname: 沈清妙\nnarrativeRole: 主角\ncharacterScope: 主线人物\nside: 主角方\nmainPlotImpact: 100\ncolor: \"#d65f8f\"\n---\n旧人物设定\n",
    encoding="utf-8",
)
(project_root / "characters" / "2-陆沉舟.md").write_text(
    "---\nid: 2\nname: 陆沉舟\nnarrativeRole: 配角\ncharacterScope: 常驻人物\nside: 主角方\nmainPlotImpact: 70\ncolor: \"#3f7fc1\"\n---\n可以恢复的人物设定\n",
    encoding="utf-8",
)
(project_root / "relationships" / "1-沈清妙__2-陆沉舟.md").write_text(
    "---\npeople:\n  - id: 1\n    role: 盟友\n  - id: 2\n    role: 盟友\nlabel: 复杂同盟\ntype: 情感\ncolor: \"#3f7fc1\"\n---\n",
    encoding="utf-8",
)
(project_root / "plots" / "001-初见.md").write_text(
    "---\nid: 1\nsequence: 1\nchapter: act1\ntitle: 初见\nsummary: 沈清妙与陆沉舟见面。\npeople: [1, 2]\nlanes: [主线]\nstatus: 草稿\naccent: \"#d65f8f\"\n---\n沈清妙与陆沉舟在旧港见面。\n",
    encoding="utf-8",
)

from server import build_content_index, write_content_index  # noqa: E402

write_content_index(project_root, build_content_index(project_root))
server = StoryTellerServer(("127.0.0.1", 4191), StoryTellerHandler, content_root=runtime_root, default_project="novel")
server.serve_forever()
