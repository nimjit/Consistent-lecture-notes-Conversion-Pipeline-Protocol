#!/usr/bin/env python3
"""
nb2md — convert a Jupyter notebook to clean markdown.
Usage: python3 nb2md.py notebook.ipynb [output.md]
Images are extracted to assets/ next to the output file.
"""
import sys, os
import nbformat
from nbconvert import MarkdownExporter

if len(sys.argv) < 2:
    print("Usage: nb2md.py <file.ipynb> [output.md]", file=sys.stderr)
    sys.exit(1)

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".ipynb", ".md")

with open(src) as f:
    nb = nbformat.read(f, as_version=4)

body, resources = MarkdownExporter().from_notebook_node(nb)

os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
with open(dst, "w") as f:
    f.write(body)

if resources.get("outputs"):
    assets = os.path.join(os.path.dirname(os.path.abspath(dst)), "assets")
    os.makedirs(assets, exist_ok=True)
    for name, data in resources["outputs"].items():
        with open(os.path.join(assets, name), "wb") as f:
            f.write(data)
    print(f"  assets → {assets}/")

print(f"→ {dst}")
