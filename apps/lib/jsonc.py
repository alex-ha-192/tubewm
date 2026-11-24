#!/usr/bin/env python3
"""Merge keys into a JSON-with-comments settings file (VSCode style).

    python3 jsonc.py merge  TARGET PATCH.json [--force KEY,KEY] [--state STATE.json]
    python3 jsonc.py remove TARGET PATCH.json [--state STATE.json]

merge adds the patch's keys that TARGET doesn't set yet, and overwrites only
the --force keys (the theme itself), so the user's own choices win. It prints
the keys it wrote, one per line, and records in STATE what each key held
before the first write.

remove undoes that: every key recorded in STATE whose value is still the
patch value is restored to what it was, or deleted if it was unset. Without
STATE it deletes every key that still has the patch value.

The target gets a timestamped backup next to it before any write. Comments
in the target are not preserved by a rewrite; the backup still has them.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, respecting strings."""
    out, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(ch)
            i += 1
    s = "".join(out)
    # trailing commas: a comma followed only by whitespace before } or ]
    res, in_str, i = [], False, 0
    while i < len(s):
        ch = s[i]
        if in_str:
            res.append(ch)
            if ch == "\\" and i + 1 < len(s):
                res.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            res.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in "}]":
                i += 1
                continue
            res.append(ch)
        else:
            res.append(ch)
        i += 1
    return "".join(res)


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(strip_jsonc(text))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level is not an object")
    return data


def backup(path: Path, suffix: str = "tubewm") -> Path | None:
    if not path.exists():
        return None
    stem = f"{path.name}.{suffix}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest, n = path.with_name(stem + ".bak"), 1
    while dest.exists():
        n += 1
        dest = path.with_name(f"{stem}-{n}.bak")
    shutil.copy2(path, dest)
    return dest


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tubewm-tmp")
    tmp.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def merge(target: Path, patch: dict, force: set[str] = frozenset()) -> list[str]:
    data = load(target)
    changed = [k for k, v in patch.items() if (k not in data or k in force) and data.get(k) != v]
    if not changed:
        return []
    b = backup(target)
    data.update({k: patch[k] for k in changed})
    write(target, data)
    if b:
        print(f"backup: {b}", file=sys.stderr)
    return changed


def remove(target: Path, patch: dict, state: dict | None = None) -> list[str]:
    data = load(target)
    if state is None:
        owned = {k: v for k, v in patch.items()}
    else:
        owned = {k: rec.get("wrote", patch.get(k)) for k, rec in state.items()}
    gone = [k for k, v in owned.items() if k in data and data[k] == v]
    if not gone:
        return []
    b = backup(target)
    for k in gone:
        prev = (state or {}).get(k) or {}
        if prev.get("had"):
            data[k] = prev.get("value")
        else:
            del data[k]
    write(target, data)
    if b:
        print(f"backup: {b}", file=sys.stderr)
    return gone


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("op", choices=("merge", "remove"))
    ap.add_argument("target", type=Path)
    ap.add_argument("patch", type=Path)
    ap.add_argument("--force", default="")
    ap.add_argument("--state", type=Path, default=None)
    args = ap.parse_args(argv)
    target = args.target
    patch = json.loads(strip_jsonc(args.patch.read_text(encoding="utf-8")))
    state = None
    if args.state and args.state.is_file():
        state = json.loads(args.state.read_text(encoding="utf-8"))
    try:
        if args.op == "merge":
            before = load(target)
            keys = merge(target, patch, {k for k in args.force.split(",") if k})
            if args.state and keys:
                state = state or {}
                for k in keys:
                    state.setdefault(k, {"had": k in before, "value": before.get(k)})
                    state[k]["wrote"] = patch[k]
                write(args.state, state)
        else:
            keys = remove(target, patch, {} if (args.state and state is None) else state)
            if args.state and args.state.exists():
                args.state.unlink()
    except (ValueError, json.JSONDecodeError) as e:
        print(f"jsonc.py: cannot parse {target}: {e}; left it untouched", file=sys.stderr)
        return 1
    for k in keys:
        print(k)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
