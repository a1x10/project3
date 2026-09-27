import hashlib
import json
import os
import sys
import time
from pathlib import Path, PurePosixPath

from . import config

SCAN_DIRS = ("app", "deploy")
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".tmp", ".swp", ".db", ".db-wal", ".db-shm", ".db-journal")
CHUNK = 1 << 16


def _skipped(name: str) -> bool:
    return name.endswith(SKIP_SUFFIXES) or name.endswith("~")


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _walk(root: Path) -> list[str]:
    found = []
    for top in SCAN_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for folder, dirs, files in os.walk(base, onerror=lambda _: None):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in files:
                path = Path(folder) / name
                if not _skipped(name) and _is_file(path):
                    found.append(path.relative_to(root).as_posix())
    return sorted(found)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_digest(files: dict[str, str]) -> str:
    lines = "".join(f"{files[name]}  {name}\n" for name in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _safe(rel) -> bool:
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        return False
    path = PurePosixPath(rel)
    parts = path.parts
    return bool(parts) and not path.is_absolute() and ".." not in parts and parts[0] in SCAN_DIRS


def build(root: Path) -> dict:
    root = Path(root)
    files = {}
    for rel in _walk(root):
        try:
            files[rel] = sha256(root / rel)
        except OSError:
            continue
    return {"version": config.VERSION, "created": time.time(), "files": files}


def _expected(manifest) -> dict[str, str] | None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        return None
    return {k: str(v).lower() for k, v in manifest["files"].items() if isinstance(v, str)}


def verify(root: Path, manifest: dict | None) -> dict:
    root = Path(root)
    expected = _expected(manifest)
    current, unreadable = {}, []
    present = _walk(root)
    names = set(present) | {k for k in (expected or {}) if _safe(k)}
    for rel in sorted(names):
        try:
            if (root / rel).is_file():
                current[rel] = sha256(root / rel)
        except OSError:
            unreadable.append(rel)
    result = {"status": "unknown", "files": len(current), "changed": [], "missing": [],
              "added": [], "unreadable": unreadable, "digest": _tree_digest(current),
              "expected": None, "version": None, "created": None}
    if expected is None:
        return result
    changed, missing = [], []
    for rel, digest in sorted(expected.items()):
        if not _safe(rel):
            changed.append(rel)
        elif rel in unreadable:
            continue
        elif rel not in current:
            missing.append(rel)
        elif current[rel] != digest:
            changed.append(rel)
    added = sorted(set(present) - set(expected))
    result.update(
        files=len(expected), changed=changed + unreadable, missing=missing, added=added,
        expected=_tree_digest({k: v for k, v in expected.items() if _safe(k)}),
        version=manifest.get("version") if isinstance(manifest.get("version"), str) else None,
        created=manifest.get("created") if isinstance(manifest.get("created"), (int, float)) else None,
    )
    result["status"] = "changed" if changed or missing or added or unreadable else "ok"
    return result


def load(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if _expected(data) is not None else None


def check(root: Path | None = None, manifest_file: Path | None = None) -> dict:
    root = Path(root or config.APP_ROOT)
    return verify(root, load(Path(manifest_file or config.MANIFEST_FILE)))


def _usage() -> int:
    print("использование: python -m app.integrity build [КОРЕНЬ] | verify [КОРЕНЬ] [МАНИФЕСТ]", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("build", "verify"):
        return _usage()
    root = Path(argv[1] if len(argv) > 1 else config.APP_ROOT)
    if not root.is_dir():
        print(f"нет каталога: {root}", file=sys.stderr)
        return 2
    if argv[0] == "build":
        manifest = build(root)
        if not manifest["files"]:
            print(f"в {root} нет файлов app/ и deploy/", file=sys.stderr)
            return 1
        print(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    manifest_file = Path(argv[2]) if len(argv) > 2 else root / "manifest.json"
    report = verify(root, load(manifest_file))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
