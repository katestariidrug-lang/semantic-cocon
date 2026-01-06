import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def run(cmd, cwd):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_full_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- minimal repo skeleton ---
        for d in [
            "state/snapshots",
            "state/approvals",
            "state/merges/by_run",
            "outputs/pass_2",
            "input",
            "scripts",
        ]:
            (tmp / d).mkdir(parents=True, exist_ok=True)

        # copy scripts (orchestrator + merge)
        shutil.copy(REPO_ROOT / "scripts/orchestrator.py", tmp / "scripts/orchestrator.py")
        shutil.copy(REPO_ROOT / "scripts/merge_pass2.py", tmp / "scripts/merge_pass2.py")
        shutil.copy(REPO_ROOT / "scripts/lifecycle.py", tmp / "scripts/lifecycle.py")
        shutil.copy(REPO_ROOT / "scripts/state_utils.py", tmp / "scripts/state_utils.py")

        # fake task.json
        task = {"task_id": "smoke_task"}
        (tmp / "input/task.json").write_text(json.dumps(task), encoding="utf-8")

        snapshot_id = "demo_snapshot__abc123"

        # --- snapshot ---
        snapshot = {"immutable_architecture": {"nodes": []}}
        snap_path = tmp / "state/snapshots" / f"{snapshot_id}.snapshot.json"
        snap_path.write_text(json.dumps(snapshot), encoding="utf-8")

        sha = "deadbeef" * 8
        (tmp / "state/snapshots" / f"{snapshot_id}.sha256").write_text(sha, encoding="utf-8")

        # --- approve ---
        (tmp / "state/approvals" / f"{sha}.approved").write_text("", encoding="utf-8")

        # --- execute core + anchors (simulated) ---
        out_dir = tmp / "outputs/pass_2" / snapshot_id
        core_dir = out_dir / "core"
        anchors_dir = out_dir / "anchors"
        core_dir.mkdir(parents=True)
        anchors_dir.mkdir(parents=True)

        # Minimal required deliverables for MERGE (deterministic stubs)
        (core_dir / "semantic_enrichment.json").write_text(
            json.dumps({"nodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (core_dir / "keywords.json").write_text(
            json.dumps({"nodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (core_dir / "patient_questions.json").write_text(
            json.dumps({"nodes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (anchors_dir / "anchors.json").write_text(
            json.dumps({"links": []}, ensure_ascii=False),
            encoding="utf-8",
        )

        # execution_result.json is required by merge_pass2 (signals PASS_2 execution happened)
        immutable_fp = "fp_smoke_0001"
        (core_dir / "execution_result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "stage": "core",
                    "snapshot_id": snapshot_id,
                    "immutable_fingerprint": immutable_fp,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (anchors_dir / "execution_result.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "stage": "anchors",
                    "snapshot_id": snapshot_id,
                    "immutable_fingerprint": immutable_fp,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


        # --- merge ---
        code, out, err = run(
            [
                sys.executable,
                "-m",
                "scripts.merge_pass2",
                "--core-snapshot-id",
                snapshot_id,
                "--anchors-snapshot-id",
                snapshot_id,
                "--outputs-dir",
                "outputs",
            ],
            cwd=tmp,
        )

        assert code == 0, f"MERGE failed: {out} {err}"

        # --- forbidden execute ---
        code, out, err = run(
            [
                sys.executable,
                "-m",
                "scripts.orchestrator",
                "execute",
                "--snapshot",
                f"state/snapshots/{snapshot_id}.snapshot.json",
            ],
            cwd=tmp,
        )

        assert code == 2, f"Expected exit code 2, got {code}\n{out}\n{err}"


if __name__ == "__main__":
    test_full_lifecycle()
    print("SMOKE TEST PASSED")
