"""Smoke tests — run the generator on a small spec and assert it writes a
validation report with PASS."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXECUTION = ROOT / "execution"
EXAMPLES = ROOT / "examples"


def _run_generator(spec_path: Path, out_dir: Path) -> dict:
    """Invoke generate_folie.py and return the resolved validation report."""
    subprocess.run(
        [
            sys.executable,
            str(EXECUTION / "generate_folie.py"),
            "--spec",
            str(spec_path),
            "--out",
            str(out_dir),
        ],
        check=True,
        capture_output=True,
    )
    # The generator uses spec["name"] if set, otherwise the file stem.
    with open(spec_path) as f:
        name = json.load(f).get("name") or spec_path.stem
    validation_path = out_dir / f"{name}.validation.json"
    with open(validation_path) as f:
        return json.load(f)


def test_folie_compound_passes(tmp_path):
    report = _run_generator(EXAMPLES / "folie-compound.json", tmp_path)
    assert report["passed"], f"validation failed: {report['summary']}"


def test_folie_field_4x4_passes(tmp_path):
    report = _run_generator(EXAMPLES / "folie-field-4x4.json", tmp_path)
    assert report["passed"], f"field validation failed: {report['summary']}"


def test_glb_exported(tmp_path):
    spec = EXAMPLES / "folie-compound.json"
    _run_generator(spec, tmp_path)
    with open(spec) as f:
        name = json.load(f).get("name") or spec.stem
    glb = tmp_path / f"{name}.glb"
    assert glb.exists(), "no .glb file was written"
    assert glb.stat().st_size > 1000, ".glb is unexpectedly small"
