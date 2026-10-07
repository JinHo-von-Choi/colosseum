"""User-supplied materials: snapshot them into the run and check quotes against them.

A material is a local file, every text file in a local directory, a URL, or pasted text.
Files and text are copied into <run>/materials/ with their SHA-256, so the review reads a
fixed version even if the original changes later. URLs are read by the workflow.

Participants cite a file or text material as url "material:M1". check_graph() re-checks
those quotes against the snapshot with the quote matcher, so their status never depends
on a model's copy of the text.
"""
import hashlib
import json
import os

try:
    from . import quote_match as Q
except ImportError:
    import quote_match as Q

MAX_FILE_BYTES = 300000
MAX_TOTAL_BYTES = 2000000
MAX_ITEMS = 30
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next",
             ".cache", "target", ".idea", ".vscode"}
PREFIX = "material:"


class MaterialError(ValueError):
    pass


def _is_text(raw):
    return b"\x00" not in raw[:8192]


def _expand(spec):
    """(kind, source, title, path_or_none, text_or_none) items for one request entry."""
    if not isinstance(spec, dict):
        raise MaterialError("each material must be an object with path, url or text")
    if spec.get("path"):
        path = os.path.abspath(os.path.expanduser(str(spec["path"])))
        if os.path.isdir(path):
            out = []
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
                for name in sorted(files):
                    if name.startswith("."):
                        continue
                    out.append(("file", os.path.join(root, name), os.path.relpath(os.path.join(root, name), path), None))
            return [(k, s, spec.get("title") and "%s: %s" % (spec["title"], t) or t, None) for k, s, t, _ in out]
        if not os.path.isfile(path):
            raise MaterialError("not a file or directory: %s" % spec["path"])
        return [("file", path, spec.get("title") or os.path.basename(path), None)]
    if spec.get("url"):
        url = str(spec["url"])
        if not url.startswith(("http://", "https://")):
            raise MaterialError("url must start with http:// or https://: %s" % url)
        return [("url", url, spec.get("title") or url, None)]
    if spec.get("text"):
        return [("text", "pasted text", spec.get("title") or "pasted text", str(spec["text"]))]
    raise MaterialError("a material needs path, url or text")


def add(run_dir, specs, write_private, secure_dir):
    """Snapshot the requested materials into run_dir/materials and return the manifest."""
    if not isinstance(specs, list) or not specs:
        raise MaterialError("give a non-empty \"materials\" list")
    mdir = secure_dir(os.path.join(run_dir, "materials"))
    manifest_path = os.path.join(run_dir, "materials.json")
    manifest = load(run_dir)
    total = sum(m.get("bytes", 0) for m in manifest)
    skipped = []
    for spec in specs:
        for kind, source, title, text in _expand(spec):
            if len(manifest) >= MAX_ITEMS:
                skipped.append({"source": source, "reason": "more than %d materials" % MAX_ITEMS})
                continue
            mid = "M%d" % (len(manifest) + 1)
            entry = {"id": mid, "kind": kind, "title": title, "source": source}
            if kind == "url":
                entry["url"] = source
                manifest.append(entry)
                continue
            if kind == "file":
                with open(source, "rb") as f:
                    raw = f.read(MAX_FILE_BYTES + 1)
                if not _is_text(raw):
                    skipped.append({"source": source, "reason": "not a text file"})
                    continue
            else:
                raw = text.encode("utf-8")
            truncated = len(raw) > MAX_FILE_BYTES
            raw = raw[:MAX_FILE_BYTES]
            if total + len(raw) > MAX_TOTAL_BYTES:
                skipped.append({"source": source, "reason": "total size limit of %d bytes reached" % MAX_TOTAL_BYTES})
                continue
            body = raw.decode("utf-8", errors="ignore")
            snap = os.path.join(mdir, mid + ".txt")
            write_private(snap, body)
            total += len(raw)
            entry.update(path=snap, sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(), bytes=len(raw),
                         truncated=truncated)
            manifest.append(entry)
    if not manifest:
        raise MaterialError("no usable material: %s" % "; ".join("%s (%s)" % (s["source"], s["reason"]) for s in skipped))
    write_private(manifest_path, json.dumps(manifest, indent=1, ensure_ascii=False))
    return {"materials": manifest, "skipped": skipped}


def load(run_dir):
    p = os.path.join(run_dir, "materials.json")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def check_graph(doc, run_dir):
    """Re-check every quote cited as material:Mn against the snapshot. Returns (doc, changes)."""
    by_id = {m["id"]: m for m in load(run_dir)}
    if not by_id:
        return doc, []
    changes = []
    texts = {}
    for e in doc.get("evidence", []):
        url = str(e.get("url") or "")
        if not url.startswith(PREFIX):
            continue
        mid = url[len(PREFIX):]
        m = by_id.get(mid)
        before = e.get("quote_status")
        if not m or not m.get("path"):
            after, reason = "u", "unknown material %s" % mid
        else:
            if mid not in texts:
                with open(m["path"], encoding="utf-8") as f:
                    texts[mid] = f.read()
            r = Q.match(e.get("quote", ""), texts[mid])
            after, reason = r["status"], r.get("reason")
        e["quote_status"] = after
        e["acquisition"] = "material"
        e.setdefault("origin", url)
        if before != after:
            changes.append({"evidence": e["id"], "material": mid, "before": before, "after": after, "reason": reason})
    return doc, changes
