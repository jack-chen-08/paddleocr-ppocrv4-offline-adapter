#!/usr/bin/env bash
# 交付证据：一条命令产出可贴进 PR / 验收单的三样东西
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs/evidence
{
  echo "# 环境"
  python -V
  pip list 2>/dev/null | grep -Ei "fastapi|sqlalchemy|pytest|pydantic|redis" || true
  echo
  echo "# 用例"
  python -m pytest -q 2>&1 | tail -n 20
} | tee docs/evidence/pytest.txt
python -m pytest -q --json-report --json-report-file=docs/evidence/pytest.json >/dev/null 2>&1 || true
echo "证据已写入 docs/evidence/pytest.txt"
