from __future__ import annotations

import unittest
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from storyteller.domain.world_schema import (
    STORAGE_REGISTRY_PATH,
    entity_schema,
    inspect_storage_schema,
    load_storage_registry,
    public_world_schema,
    sync_storage_registry,
    validate_world_schema,
)
from storyteller.domain.world_reader import WorldReader
from storyteller.exports.markdown import MarkdownExporter
from storyteller.rag.documents import build_documents
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class WorldSchemaTests(unittest.TestCase):
    def test_registry_matches_current_sqlite_schema_without_unreviewed_fields(self):
        self.assertEqual([], validate_world_schema(load_storage_registry()))

    def test_new_sqlite_column_is_unreviewed_until_semantics_are_declared(self):
        changed = deepcopy(inspect_storage_schema())
        changed["tables"]["relationships"]["columns"]["trust_score"] = {
            "storageType": "INTEGER", "required": True, "primaryKey": False,
        }
        with patch("storyteller.domain.world_schema.inspect_storage_schema", return_value=changed):
            generated = sync_storage_registry()
        self.assertEqual(
            "TODO",
            generated["tables"]["relationships"]["columns"]["trust_score"]["review"],
        )

    def test_removed_semantic_mapping_returns_the_physical_column_to_todo(self):
        from storyteller.domain.world_schema import semantic_sources

        sources = semantic_sources()
        sources.pop(("relationships", "from_impression"))
        with patch("storyteller.domain.world_schema.semantic_sources", return_value=sources):
            generated = sync_storage_registry()
        self.assertEqual(
            "TODO",
            generated["tables"]["relationships"]["columns"]["from_impression"]["review"],
        )

    def test_one_physical_json_column_can_declare_multiple_domain_fields(self):
        generated = sync_storage_registry()
        fields = generated["tables"]["entities"]["columns"]["extra_json"]["fields"]
        self.assertIn("character.destinyOutline", fields)
        self.assertIn("fragment.fragmentType", fields)
        self.assertIn("fragment.parentFragmentId", fields)
        self.assertIn("fragment.chapterNumber", fields)

    def test_bootstrap_cannot_bypass_review_after_registry_exists(self):
        self.assertTrue(STORAGE_REGISTRY_PATH.exists())
        with self.assertRaisesRegex(ValueError, "只能用于首次建立基线"):
            sync_storage_registry(bootstrap=True)

    def test_public_schema_exposes_business_semantics_but_hides_graph_controls(self):
        schema = public_world_schema()
        relationship = schema["entityKinds"]["relationship"]
        self.assertEqual("from-to", relationship["fields"]["fromImpression"]["direction"])
        self.assertNotIn("graphScope", relationship["fields"])
        fragment = schema["entityKinds"]["fragment"]
        self.assertEqual("confirmed", fragment["certainty"])
        self.assertEqual("unplaced", fragment["timelineStatus"])
        self.assertTrue(fragment["includedByDefault"])

    def test_registered_main_table_field_flows_to_mcp_rag_and_markdown_without_repository_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "demo"
            root.mkdir()
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", root / "legacy.db")
            V3Migrator(root / "legacy.db", "demo").migrate_to(root / "story.db")
            database = Database(root)
            with database.write() as connection:
                connection.execute("ALTER TABLE characters ADD COLUMN secrecy_level INTEGER NOT NULL DEFAULT 0")
                connection.execute("UPDATE characters SET secrecy_level=73 WHERE entity_id='character:1'")
            character_schema = deepcopy(public_world_schema()["entityKinds"]["character"])
            character_schema["fields"]["secrecyLevel"] = {
                "label": "秘密程度", "type": "integer", "source": "characters.secrecy_level",
                "aiVisible": True, "searchable": True, "exportable": True,
            }
            def schema_for(kind):
                return character_schema if kind == "character" else entity_schema(kind)

            with patch("storyteller.domain.world_schema.entity_schema", side_effect=schema_for):
                entity = WorldReader(database, "demo").entity("character:1")
                self.assertEqual(73, entity["data"]["secrecyLevel"])
                documents, _edges, _revision = build_documents(WorldReader(database, "demo").repository)
                document = next(item for item in documents if item.entity_id == "character:1")
                self.assertIn("秘密程度：73", document.content)
                exported = MarkdownExporter(database, "demo").render()
                character_file = next(value for name, value in exported.items() if name.startswith("characters/1-"))
                self.assertIn("secrecyLevel: 73", character_file.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
