"""Copy the shared colosseum-lib and colosseum-runtime blocks from workflows/debate.js
into every other workflow. Workflow scripts cannot import files, so each one carries
its own copy; tests/test_js_parity.py fails when a copy drifts.

Usage: python3 tools/sync_workflow_blocks.py
"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "workflows", "debate.js")
BLOCKS = ("colosseum-lib", "colosseum-runtime")


def block_re(name):
    return re.compile(r"// ==== %s begin ====.*?// ==== %s end ====" % (name, name), re.DOTALL)


def main():
    with open(SOURCE, encoding="utf-8") as f:
        src = f.read()
    blocks = {name: block_re(name).search(src).group(0) for name in BLOCKS}
    for path in sorted(glob.glob(os.path.join(ROOT, "workflows", "*.js"))):
        if path == SOURCE:
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = text
        for name, body in blocks.items():
            new = block_re(name).sub(lambda _m, b=body: b, new)
        if new != text:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print("synced", os.path.relpath(path, ROOT))


if __name__ == "__main__":
    main()
