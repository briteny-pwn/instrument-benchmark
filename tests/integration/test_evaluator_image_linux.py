from __future__ import annotations

import os
import platform
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.evaluator_image import EvaluatorImageBuilder  # noqa: E402


@unittest.skipUnless(
    os.environ.get("IAB_RUN_DOCKER_TESTS") == "1" and platform.system() == "Linux",
    "evaluator image integration requires native Linux Docker",
)
class EvaluatorImageLinuxTests(unittest.TestCase):
    def test_real_image_is_offline_non_root_and_contains_private_runtime(self) -> None:
        evaluator = Path(
            os.environ.get("IAB_EVALUATOR_CHECKOUT", ROOT.parent / "evaluator")
        ).resolve()
        evidence = EvaluatorImageBuilder(
            assets_root=ROOT / "container"
        ).build(evaluator, run_id="image-integration")
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--entrypoint=python",
                    evidence.reference,
                    "-c",
                    (
                        "import os,pyvisa,pyvisa_sim; "
                        "import shutil,subprocess; "
                        "from evaluators.pyvisa_dut_validation_v1 import scoring,worlds; "
                        "assert os.getuid()==11001; "
                        "assert not os.path.exists('/build/evaluator/.git'); "
                        "assert shutil.which('docker')=='/usr/local/bin/docker'; "
                        "assert subprocess.run(['docker','--version']).returncode==0"
                    ),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(evidence.platform, "linux/amd64")
            self.assertEqual(evidence.user, "11001:11001")
        finally:
            subprocess.run(
                ["docker", "image", "rm", "--force", evidence.reference],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__ == "__main__":
    unittest.main()
