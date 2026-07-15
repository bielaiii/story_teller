import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendNavigationTests(unittest.TestCase):
    def test_place_workspace_keeps_tools_outside_scrollable_content(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        entries_source = (ROOT / "src" / "views" / "entries.js").read_text(encoding="utf-8")
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertRegex(markup, re.compile(r'class="place-rail-tools".*id="placeList"', re.DOTALL))
        self.assertIn('class="entry-tag-panel"', markup)
        self.assertIn('id="entryTagCount"', markup)
        self.assertIn('class="place-detail-toolbar"', entries_source)
        self.assertRegex(styles, re.compile(r"\.place-detail-toolbar\s*\{[^}]*position:\s*sticky", re.DOTALL))

    def test_character_detail_entry_stays_in_graph_profile_card(self):
        graph_source = (ROOT / "src" / "views" / "graph.js").read_text(encoding="utf-8")
        bootstrap_source = (ROOT / "src" / "bootstrap.js").read_text(encoding="utf-8")
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("person-node-detail", graph_source)
        self.assertIn('class="profile-detail-btn icon-action"', markup)
        self.assertIn("openCharacterDetail(state.selected)", bootstrap_source)

    def test_editing_ui_does_not_reload_or_replace_the_page(self):
        forbidden = {
            "location.reload": re.compile(r"\blocation\.reload\s*\("),
            "location.href assignment": re.compile(r"\blocation\.href\s*="),
            "location.assign": re.compile(r"\blocation\.assign\s*\("),
            "location.replace": re.compile(r"\blocation\.replace\s*\("),
        }
        violations = []
        for path in sorted((ROOT / "src").rglob("*.js")):
            source = path.read_text(encoding="utf-8")
            for label, pattern in forbidden.items():
                if pattern.search(source):
                    violations.append(f"{path.relative_to(ROOT)}: {label}")
        self.assertEqual([], violations, "编辑功能不得依赖整页刷新或页面替换：\n" + "\n".join(violations))

    def test_delete_failure_is_visible_outside_the_editor_dialog(self):
        source = (ROOT / "src" / "features" / "content-manager.js").read_text(encoding="utf-8")
        self.assertIn("const dialogWasOpen = dialog.open;", source)
        self.assertIn("if (!dialogWasOpen) window.alert(error.message);", source)
        self.assertIn("if (dialogWasOpen && dialog.open) dialog.close();", source)

    def test_fragment_page_has_no_redundant_english_label(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        story_source = (ROOT / "src" / "views" / "story.js").read_text(encoding="utf-8")
        fragment_page = re.search(
            r'<section class="fragment-page[\s\S]*?</section>',
            markup,
        )
        fragment_filters = re.search(
            r"function renderFragmentFilters\(\)[\s\S]*?\n}\n\nfunction renderFragments",
            story_source,
        )
        self.assertIsNotNone(fragment_page)
        self.assertIsNotNone(fragment_filters)
        self.assertNotIn(">Fragments<", fragment_page.group(0))
        self.assertIn("<h2>灵感碎片箱</h2>", fragment_page.group(0))
        self.assertNotIn('label: "标签"', fragment_filters.group(0))

    def test_timeline_editor_keeps_a_virtualized_focus_preview(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "src" / "views" / "timeline.js").read_text(encoding="utf-8")
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="timelineEditorPreviewViewport"', markup)
        self.assertIn('id="timelineEditorPreview"', markup)
        map_column = re.search(r'<aside class="timeline-editor-map">(.*?)</aside>', markup, re.S)
        details_column = re.search(r'<aside class="timeline-editor-details">(.*?)</aside>', markup, re.S)
        self.assertIsNotNone(map_column)
        self.assertIsNotNone(details_column)
        self.assertNotIn('id="timelineEditorLineList"', map_column.group(1))
        self.assertIn('id="timelineEditorLineList"', details_column.group(1))
        self.assertIn('id="timelineEditorInspector"', details_column.group(1))
        self.assertIn("function focusTimelineEditorPreview", source)
        self.assertIn("visibleStart", source)
        self.assertIn('type: "delete"', source)
        self.assertIn("receivingLine", source)
        self.assertIn(".timeline-editor-preview-lane.is-removing", styles)
        self.assertIn(".timeline-editor-preview-lane.is-receiving", styles)

    def test_fragment_editor_stays_in_fragments_until_explicit_conversion(self):
        source = (ROOT / "src" / "features" / "content-manager.js").read_text(encoding="utf-8")
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn("is-fragment-writer", source)
        self.assertIn("保存后仍只在碎片箱中", source)
        self.assertIn('id="fragmentEditorPreview"', source)
        self.assertIn("renderFragmentEditorPreview", source)
        self.assertIn("syncFragmentEditorScroll", source)
        self.assertIn("setFragmentWriterImmersive", source)
        self.assertIn('id="contentEditorFullscreen"', source)
        self.assertIn("fragment-immersive-record", (ROOT / "src" / "views" / "story.js").read_text(encoding="utf-8"))
        self.assertIn("{ immersive: true }", (ROOT / "src" / "views" / "story.js").read_text(encoding="utf-8"))
        self.assertIn(".fragment-editor-workspace", styles)
        self.assertIn(".fragment-editor-preview", styles)
        self.assertIn(".content-editor-dialog.is-fragment-writer.is-immersive", styles)

    def test_story_card_tags_use_plot_accent_instead_of_gray(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        rule = re.search(r"\.plot-card \.tag-badge\s*\{(.*?)\}", styles, re.S)
        self.assertIsNotNone(rule)
        self.assertIn("var(--accent)", rule.group(1))
        self.assertIn("color-mix", rule.group(1))

    def test_destructive_confirmations_use_the_app_dialog(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        shared = (ROOT / "src" / "shared" / "ui.js").read_text(encoding="utf-8")
        plot_detail = (ROOT / "src" / "views" / "plot-detail.js").read_text(encoding="utf-8")
        content_manager = (ROOT / "src" / "features" / "content-manager.js").read_text(encoding="utf-8")
        self.assertIn('id="appConfirmDialog"', markup)
        self.assertIn("function showAppConfirm", shared)
        self.assertIn("await showAppConfirm", plot_detail)
        self.assertIn("await showAppConfirm", content_manager)
        self.assertNotIn("window.confirm", plot_detail)
        self.assertNotIn("window.confirm", content_manager)


if __name__ == "__main__":
    unittest.main()
