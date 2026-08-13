from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from storyteller.hub_contract import (
    WORKER_CAPABILITIES,
    WORKER_PROTOCOL_MAJOR,
    WORKER_SERVICE,
    worker_manifest,
)


ROOT = Path(__file__).resolve().parents[2]


class HubWorkerContractTests(unittest.TestCase):
    def test_worker_manifest_exposes_stable_facade_contract(self) -> None:
        manifest = worker_manifest(ROOT)

        self.assertEqual(manifest["service"], WORKER_SERVICE)
        self.assertEqual(manifest["protocolMajor"], WORKER_PROTOCOL_MAJOR)
        self.assertEqual(set(manifest["capabilities"]), set(WORKER_CAPABILITIES))
        self.assertEqual(len(manifest["runtimeIdentity"]), 64)
        self.assertIsInstance(manifest["dirty"], bool)

    def test_worker_manifest_command_outputs_one_json_document(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "storyteller.hub_worker", "manifest"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        manifest = json.loads(completed.stdout)
        self.assertEqual(manifest["service"], WORKER_SERVICE)
        self.assertEqual(manifest["protocolMajor"], 1)


if __name__ == "__main__":
    unittest.main()
