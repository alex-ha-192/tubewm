#!/usr/bin/env python3
"""Small parsers the CI shell scripts lean on.

    parse.py jsonc FILE...          FILE parses as JSON with comments / trailing commas
    parse.py toml FILE...           FILE parses as TOML
    parse.py commands SWAYCONF [WAYBARCONF...]
                                    print, one per line, every program the sway
                                    and waybar configs will try to run
    parse.py gtk-css 3|4 FILE...    load FILE with GTK's own CSS parser; errors
                                    fail, deprecation warnings are printed
    parse.py keys-vs-help CONF HELP report config keys that HELP (a program's
                                    --help output) doesn't list as --options
"""

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "apps" / "lib"))


def load_jsonc(path: str):
    import jsonc  # apps/lib/jsonc.py, the same reader the installers use

    return json.loads(jsonc.strip_jsonc(Path(path).read_text(encoding="utf-8")))


def cmd_jsonc(files):
    for f in files:
        load_jsonc(f)
    return 0


def cmd_toml(files):
    import tomllib

    for f in files:
        with open(f, "rb") as fh:
            tomllib.load(fh)
    return 0


# ---------------------------------------------------------------- commands

SHELL_WORDS = {
    "sh", "bash", "exec", "env", "nohup", "setsid", "command", "true", "false",
    "test", "[", "if", "then", "else", "fi", "for", "do", "done", "while",
    "case", "esac", "!", "{", "}", "(", ")", "echo", "printf", "cd", "kill",
    "export", "sleep", "wait",
}


def first_programs(cmdline: str) -> list[str]:
    """Programs a shell command line runs, at the start of each pipeline stage."""
    out = []
    for part in re.split(r"\|\||&&|[|;&]", cmdline):
        try:
            words = shlex.split(part, comments=False, posix=True)
        except ValueError:
            words = part.split()
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words.pop(0)  # FOO=bar cmd
        while words and words[0] in ("exec", "env", "nohup", "setsid", "command"):
            words.pop(0)
            while words and (words[0].startswith("-") or "=" in words[0]):
                words.pop(0)
        if words and words[0] not in SHELL_WORDS and not words[0].startswith("$"):
            out.append(words[0])
    return out


def sway_lines(path: Path, seen: set) -> list[str]:
    """Logical lines of a sway config, with continuations joined and includes
    followed (sway expands ~ and globs in include)."""
    if path in seen or not path.is_file():
        return []
    seen.add(path)
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"include\s+(.+)$", line)
        if m:
            pat = os.path.expanduser(m.group(1).strip().strip("'\""))
            if not os.path.isabs(pat):
                pat = str(path.parent / pat)
            for inc in sorted(glob.glob(pat)):
                lines += sway_lines(Path(inc), seen)
            continue
        lines.append(line)
    return lines


def sway_commands(conf: Path) -> list[str]:
    lines = sway_lines(conf, set())
    variables = {}
    for line in lines:
        m = re.match(r"set\s+(\$\S+)\s+(.*)$", line)
        if m:
            variables[m.group(1)] = m.group(2).strip()

    def expand(s):
        for k in sorted(variables, key=len, reverse=True):
            s = s.replace(k, variables[k])
        return s

    progs = []
    for line in lines:
        line = expand(line)
        m = re.match(r"(?:exec|exec_always)\s+(?:--no-startup-id\s+)?(.*)$", line)
        if not m:
            m = re.match(r"(?:bindsym|bindcode|bindgesture|bindswitch)\s+(?:--\S+\s+)*\S+\s+"
                         r"(?:exec|exec_always)\s+(.*)$", line)
        if m:
            cmd = m.group(1)
            progs += first_programs(cmd)
            # swayidle / similar take shell commands as quoted arguments
            try:
                args = shlex.split(cmd)
            except ValueError:
                args = []
            for a in args[1:]:
                if " " in a or a.startswith("tube-"):
                    progs += first_programs(a)
            continue
        m = re.match(r"(?:swaybar_command|status_command)\s+(.*)$", line)
        if m:
            progs += first_programs(m.group(1))
    return progs


def waybar_commands(conf: Path) -> list[str]:
    data = load_jsonc(str(conf))
    bars = data if isinstance(data, list) else [data]
    progs = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and (k.startswith("on-") or k in ("exec", "exec-if", "exec-on-event")):
                    progs.extend(first_programs(v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for bar in bars:
        walk(bar)
    return progs


def cmd_commands(args):
    progs = sway_commands(Path(args[0]))
    for w in args[1:]:
        if Path(w).is_file():
            progs += waybar_commands(Path(w))
    for p in sorted(set(progs)):
        print(p)
    return 0


# ---------------------------------------------------------------- GTK CSS

def cmd_gtk_css(args):
    major, files = args[0], args[1:]
    import gi

    gi.require_version("Gtk", f"{major}.0")
    from gi.repository import Gtk

    bad = 0
    for f in files:
        errors, warnings = [], []
        provider = Gtk.CssProvider()

        def on_error(_prov, section, error, errors=errors, warnings=warnings):
            if major == "4":
                start = section.get_start_location()
                where = f"{start.lines + 1}:{start.line_chars + 1}"
                file = section.get_file()
            else:
                where = f"{section.get_start_line() + 1}:{section.get_start_position() + 1}"
                file = section.get_file()
            name = file.get_path() if file else f
            msg = f"{name}:{where}: {error.message}"
            # GTK 4 reports deprecations and other warnings through the same
            # signal, under its own error domain.
            (warnings if "warning" in str(error.domain) else errors).append(msg)

        provider.connect("parsing-error", on_error)
        try:
            provider.load_from_path(f)
        except Exception as e:  # GTK 3 also raises on the first error
            if not errors:
                errors.append(f"{f}: {e}")
        for w in warnings:
            print(f"warning: {w}")
        for e in errors:
            print(f"error: {e}")
        bad += bool(errors)
    return 1 if bad else 0


# ---------------------------------------------------------------- keys

def cmd_keys_vs_help(args):
    conf, helptext = Path(args[0]), Path(args[1]).read_text()
    known = set(re.findall(r"--([a-z][a-z0-9-]*)", helptext))
    unknown = []
    for n, raw in enumerate(conf.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key not in known:
            unknown.append(f"{conf}:{n}: unknown option '{key}'")
    print("\n".join(unknown))
    return 1 if unknown else 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    fn = {"jsonc": cmd_jsonc, "toml": cmd_toml, "commands": cmd_commands,
          "gtk-css": cmd_gtk_css, "keys-vs-help": cmd_keys_vs_help}.get(cmd)
    if not fn:
        print(f"parse.py: unknown command {cmd}", file=sys.stderr)
        return 2
    try:
        return fn(rest)
    except Exception as e:  # noqa: BLE001 - report any parse failure as one line
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
