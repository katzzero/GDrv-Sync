#!/usr/bin/env python3
"""Dev-time i18n parity check (NOT shipped).

Asserts:
  1. set(pt keys) == set(en keys)  (full key parity between languages)
  2. no template contains leftover hardcoded Portuguese-accented UI strings
     outside app/i18n.py (grep heuristic for accented Portuguese literals),
     ignoring HTML comments.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.i18n import LANGS  # noqa: E402

failures = []

# ---- 1. key parity -----------------------------------------------------------
pt_keys = set(LANGS["pt"].keys())
en_keys = set(LANGS["en"].keys())
only_pt = pt_keys - en_keys
only_en = en_keys - pt_keys
if only_pt:
    failures.append(f"keys only in pt: {sorted(only_pt)}")
if only_en:
    failures.append(f"keys only in en: {sorted(only_en)}")
print(f"pt keys: {len(pt_keys)} | en keys: {len(en_keys)} | parity: {pt_keys == en_keys}")

# ---- 2. heuristic: accented Portuguese literals in templates ----------------
ACCENTED_PT = re.compile(r"[çãõáâêôúàéíóü]")

template_files = list((ROOT / "app" / "templates").glob("*.html"))

for f in template_files:
    rel = f.relative_to(ROOT)
    text = f.read_text(encoding="utf-8")
    # Remove HTML comments before scanning (comments may contain PT words).
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    for m in ACCENTED_PT.finditer(stripped):
        line_no = stripped[: m.start()].count("\n") + 1
        line = stripped.splitlines()[line_no - 1]
        if re.search(r"[çãõáâêôúàéíóü]", line):
            failures.append(f"{rel}:{line_no}: possible hardcoded PT string: {line.strip()[:90]}")

if failures:
    print("FAIL:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("check_i18n: OK")
sys.exit(0)
