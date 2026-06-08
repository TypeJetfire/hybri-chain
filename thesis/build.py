#!/usr/bin/env python3
"""Build script: XeLaTeX + BibTeX + patch bbl labels + XeLaTeX x2"""
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).parent
BBL = ROOT / "main.bbl"
AUX = ROOT / "main.aux"

def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def patch_bbl():
    """Replace author-year labels in bbl with sequential [1], [2], ..."""
    text = BBL.read_text(encoding="utf-8")

    # Match full \bibitem[label]{key} and replace label only
    counter = [0]
    def replacer(m):
        counter[0] += 1
        key = m.group(2)
        return f"\\bibitem[{counter[0]}]{{{key}}}"

    new_text = re.sub(r'\\bibitem\[([^\]]+)\]\{([^}]+)\}', replacer, text)

    # Fix thebibliography width
    def fix_width(m):
        return m.group(1) + str(counter[0]) + m.group(2)
    new_text = re.sub(
        r'(\\begin\{thebibliography\}\{)[0-9]+(\})',
        fix_width, new_text, count=1
    )

    BBL.write_text(new_text, encoding="utf-8")
    print(f"  Patched {counter[0]} bibitem labels → [1]..[{counter[0]}]")

# Step 1: XeLaTeX (to generate aux with \bibdata)
rc, _, _ = run(["xelatex", "-interaction=nonstopmode", "main.tex"])
print(f"  XeLaTeX 1: {'OK' if rc == 0 else 'FAIL'}")

# Step 2: BibTeX
rc, out, err = run(["bibtex", "main.aux"])
print(f"  BibTeX: {'OK' if rc == 0 else 'FAIL'}")
if rc != 0:
    print("  STDERR:", err[:300])

# Step 3: Patch bbl labels
if BBL.exists():
    patch_bbl()
else:
    print("  WARNING: main.bbl not found!")

# Step 4-5: XeLaTeX x2
for i in [2, 3]:
    rc, _, _ = run(["xelatex", "-interaction=nonstopmode", "main.tex"])
    print(f"  XeLaTeX {i}: {'OK' if rc == 0 else 'FAIL'}")

print("\nDone. PDF: main.pdf")
