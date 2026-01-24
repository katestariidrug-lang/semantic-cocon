# scripts/smoke_post_check.ps1
# Smoke-test: post-check must be deterministic (format + exit codes).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/smoke_post_check.ps1 <merge_id>

param(
  [Parameter(Mandatory=$true)]
  [string]$merge_id
)

function Assert-ExitCode($expected) {
  if ($LASTEXITCODE -ne $expected) {
    Write-Host "[FAIL] DELIVERABLES_CHECK_FAILED: expected exit code $expected, got $LASTEXITCODE"
    exit 1
  }
}

# 1) PASS path
python scripts\check_deliverables.py $merge_id
Assert-ExitCode 0

# 2) BLOCKER: missing args
python scripts\check_deliverables.py
Assert-ExitCode 2

# 3) BLOCKER: missing merge-state
python scripts\check_deliverables.py DOES_NOT_EXIST
Assert-ExitCode 2

Write-Host "[PASS] OK: smoke_post_check OK"
exit 0
