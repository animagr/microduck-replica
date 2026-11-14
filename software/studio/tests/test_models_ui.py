"""Brings the model management frontend state and physical key remapping unit tests into the standard unittest regression."""
import shutil
import subprocess
import unittest
from pathlib import Path


NODE = shutil.which('node')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, '需要 Node 才能运行前端模型管理单测')
class ModelsUiTests(unittest.TestCase):
    def test_model_ui_states(self):
        result = subprocess.run(
            [NODE, '--test', str(ROOT / 'tests/models_ui_unit.mjs')],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
