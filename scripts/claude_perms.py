#!/usr/bin/env python3
"""Manage Claude Code permission rules in a settings.json allow-list.

Claude Code prompts before running a command unless a matching rule exists in
``permissions.allow``. This tool adds / removes / tidies those rules so common
commands run without a prompt.

Rule syntax (examples):
    Bash(pytest:*)        any command starting with "pytest"
    Bash(git push *)      any "git push ..." command
    Read(//path/**)       read any file under //path
    PowerShell(Get-ChildItem *)
Docs: https://docs.claude.com/en/docs/claude-code/settings#permissions

Usage:
    py scripts/claude_perms.py list
    py scripts/claude_perms.py add "Bash(pytest:*)" "Bash(ruff *)"
    py scripts/claude_perms.py remove "Bash(git push *)"
    py scripts/claude_perms.py clean                 # dedupe + sort in place
    py scripts/claude_perms.py add --local "Bash(ls:*)"
    py scripts/claude_perms.py add --global "Bash(py:*)"

By default this edits the project file (<repo>/.claude/settings.json). Use
--local for .claude/settings.local.json, --global for ~/.claude/settings.json,
or --file PATH for an explicit target.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def repo_root() -> Path:
    """Repo root, assuming this script lives in <root>/scripts/."""
    return Path(__file__).resolve().parent.parent


def resolve_path(args: argparse.Namespace) -> Path:
    if args.file:
        return Path(args.file).expanduser()
    if args.global_:
        return Path.home() / ".claude" / "settings.json"
    if args.local:
        return repo_root() / ".claude" / "settings.local.json"
    return repo_root() / ".claude" / "settings.json"


def load(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"error: {path} is not valid JSON: {exc}")


def allow_list(data: dict) -> list:
    return data.setdefault("permissions", {}).setdefault("allow", [])


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cmd_list(path: Path, data: dict, args: argparse.Namespace) -> None:
    rules = allow_list(data)
    if not rules:
        print(f"(no allow rules in {path})")
        return
    print(f"{len(rules)} allow rule(s) in {path}:")
    for rule in rules:
        print(f"  {rule}")


def cmd_add(path: Path, data: dict, args: argparse.Namespace) -> None:
    rules = allow_list(data)
    existing = set(rules)
    added = [r for r in args.rules if r not in existing]
    data["permissions"]["allow"] = sorted(existing | set(added))
    save(path, data)
    if added:
        print(f"added {len(added)} rule(s) to {path}:")
        for r in added:
            print(f"  + {r}")
    else:
        print("nothing to add (all rules already present)")


def cmd_remove(path: Path, data: dict, args: argparse.Namespace) -> None:
    rules = allow_list(data)
    targets = set(args.rules)
    removed = [r for r in rules if r in targets]
    data["permissions"]["allow"] = [r for r in rules if r not in targets]
    save(path, data)
    if removed:
        print(f"removed {len(removed)} rule(s) from {path}:")
        for r in removed:
            print(f"  - {r}")
    else:
        print("nothing matched")


def cmd_clean(path: Path, data: dict, args: argparse.Namespace) -> None:
    rules = allow_list(data)
    before = len(rules)
    cleaned = sorted(set(rules))
    data["permissions"]["allow"] = cleaned
    save(path, data)
    print(f"{path}: {before} -> {len(cleaned)} rule(s) (deduped + sorted)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude_perms.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    target = common.add_mutually_exclusive_group()
    target.add_argument("--local", action="store_true",
                        help="edit .claude/settings.local.json")
    target.add_argument("--global", dest="global_", action="store_true",
                        help="edit ~/.claude/settings.json")
    target.add_argument("--file", help="edit an explicit settings.json path")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", parents=[common], help="show current allow rules").set_defaults(func=cmd_list)
    p_add = sub.add_parser("add", parents=[common], help="add one or more allow rules")
    p_add.add_argument("rules", nargs="+", help="rule string(s), e.g. 'Bash(pytest:*)'")
    p_add.set_defaults(func=cmd_add)
    p_rm = sub.add_parser("remove", parents=[common], help="remove one or more allow rules")
    p_rm.add_argument("rules", nargs="+", help="exact rule string(s) to remove")
    p_rm.set_defaults(func=cmd_remove)
    sub.add_parser("clean", parents=[common], help="dedupe + sort the allow list").set_defaults(func=cmd_clean)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    path = resolve_path(args)
    data = load(path)
    args.func(path, data, args)


if __name__ == "__main__":
    main()
