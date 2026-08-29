from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class OpenApiContractGenerationTests(unittest.TestCase):
    def test_generated_types_are_deterministic_and_include_migrated_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "openapi.ts"
            command = [
                str(ROOT / "scripts/python.sh"),
                str(ROOT / "scripts/generate_openapi_contracts.py"),
                "--output",
                str(output),
            ]
            generated = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, generated.returncode, generated.stderr)
            content = output.read_text(encoding="utf-8")
            for operation in (
                "createCharacter",
                "updateCharacter",
                "createPlot",
                "updatePlot",
                "demotePlotToFragment",
                "createEntry",
                "updateEntry",
                "createFragment",
                "updateFragment",
                "importFragmentsFromClipboard",
                "promoteFragmentToPlot",
                "createRelationship",
                "updateRelationship",
                "updateChapters",
                "reorderPlots",
                "updateStoryStructure",
                "updateTimeline",
                "updateGraph",
                "deleteEntity",
                "restoreEntity",
                "undoOperation",
            ):
                self.assertIn(f'"{operation}": {{', content)
            self.assertIn('requestBody: components["schemas"]["FragmentCreate"]', content)
            self.assertIn('response: components["schemas"]["MutationOutcome"]', content)

            checked = subprocess.run(
                [*command, "--check"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)

            output.write_text(content + "// drift\n", encoding="utf-8")
            drifted = subprocess.run(
                [*command, "--check"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, drifted.returncode)
            self.assertIn("契约已漂移", drifted.stdout)


if __name__ == "__main__":
    unittest.main()
