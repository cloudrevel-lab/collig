#!/usr/bin/env python3
"""
Publish one Collig personality to cloudrevel-lab/collig-personas.

The flow is deliberately test-first:

1. validate the local persona (required files, slug, secrets);
2. clone or use a checkout of the market repo;
3. copy the persona, regenerate index.json;
4. run the market validator and tests;
5. create a branch, push it and open a pull request with gh.

Examples:
    uv run python scripts/push_persona.py --personality ~/.collig/personalities/鲁迅
    uv run python scripts/push_persona.py --personality ... --dry-run
    uv run python scripts/push_persona.py --personality ... --repo-dir /tmp/collig-personas

The GitHub CLI must be authenticated for the real push:
    gh auth login
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_REPO = "cloudrevel-lab/collig-personas"
DEFAULT_BASE = "main"
REQUIRED_FILES = ("PERSONALITY.md", "meta.json")
ALLOWED_FILES = {"PERSONALITY.md", "meta.json", "sources.md"}
MAX_BYTES = {"PERSONALITY.md": 512 * 1024, "meta.json": 128 * 1024, "sources.md": 1024 * 1024}
SECRET_PATTERNS = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


class PublishError(RuntimeError):
    pass


def run(command, cwd=None, check=True, capture=True, env=None):
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=capture,
        env=env,
    )
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise PublishError("command failed: " + " ".join(command) + "\n" + output)
    return result


def safe_slug(value: str) -> str:
    slug = str(value or "").strip()
    if not slug or slug in {".", ".."} or slug.startswith("."):
        raise PublishError("invalid persona slug")
    if len(slug) > 80 or "/" in slug or "\\" in slug or any(ord(c) < 32 for c in slug):
        raise PublishError("invalid persona slug")
    return slug


def assess_persona(path: Path) -> dict:
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise PublishError("personality folder not found: " + str(path))
    slug = safe_slug(path.name)
    entries = {item.name: item for item in path.iterdir()}
    for item in entries.values():
        if item.is_symlink():
            raise PublishError("symlinks are not allowed: " + item.name)
        if item.name not in ALLOWED_FILES:
            raise PublishError("unexpected file in persona: " + item.name)
    for name in REQUIRED_FILES:
        if name not in entries or not entries[name].is_file():
            raise PublishError("missing required file: " + name)
    total = 0
    for name, item in entries.items():
        if not item.is_file():
            continue
        size = item.stat().st_size
        if size > MAX_BYTES.get(name, 1024 * 1024):
            raise PublishError("file is too large: " + name)
        total += size
        try:
            text = item.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PublishError(name + " is not valid UTF-8") from exc
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise PublishError(name + " appears to contain a " + label)
    if total > 2 * 1024 * 1024:
        raise PublishError("persona is too large")

    try:
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishError("meta.json is not valid JSON: " + str(exc)) from exc
    if not isinstance(meta, dict):
        raise PublishError("meta.json must be an object")
    if str(meta.get("slug") or "") != slug:
        raise PublishError("meta.json slug must match the folder name " + repr(slug))
    if not str(meta.get("name") or "").strip():
        raise PublishError("meta.json has no name")
    if not str(meta.get("updated_at") or "").strip():
        raise PublishError("meta.json has no updated_at")
    dossier = (path / "PERSONALITY.md").read_text(encoding="utf-8").lstrip("\ufeff").strip()
    if not dossier.startswith("# "):
        raise PublishError("PERSONALITY.md must start with a level-1 heading")
    return {
        "path": path,
        "slug": slug,
        "name": str(meta.get("display_name") or meta.get("name") or slug),
        "files": sorted(entries),
    }


def copy_persona(source: Path, repo_dir: Path) -> Path:
    target = repo_dir / "personas" / source.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in source.iterdir():
        if item.is_file() and not item.is_symlink():
            shutil.copy2(item, target / item.name)
            os.chmod(target / item.name, 0o644)
    return target


def run_repo_checks(repo_dir: Path) -> dict:
    python = sys.executable
    outputs = {}
    commands = [
        ("index", [python, "scripts/build_index.py", "--write"]),
        ("validate", [python, "scripts/validate_personas.py", "--check-index"]),
        ("tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]),
    ]
    for name, command in commands:
        result = run(command, cwd=repo_dir, check=False)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        outputs[name] = output
        if result.returncode != 0:
            raise PublishError(name + " failed:\n" + output[-4000:])
    return outputs


def gh_ready() -> bool:
    if shutil.which("gh") is None:
        return False
    result = run(["gh", "auth", "status"], check=False)
    return result.returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Publish a Collig persona as a pull request")
    parser.add_argument("--personality", required=True, help="path to ~/.collig/personalities/<slug>")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo (owner/name)")
    parser.add_argument("--base", default=DEFAULT_BASE, help="base branch")
    parser.add_argument("--repo-dir", help="use an existing market checkout instead of cloning")
    parser.add_argument("--dry-run", action="store_true", help="validate and test, do not commit/push")
    parser.add_argument("--keep", action="store_true", help="keep the temporary checkout")
    args = parser.parse_args(argv)

    temp_root = None
    try:
        persona = assess_persona(Path(args.personality))
        print("Persona: " + persona["name"] + " (" + persona["slug"] + ")")
        print("Source:  " + str(persona["path"]))
        if not args.dry_run and not gh_ready():
            raise PublishError(
                "gh is not authenticated. Run gh auth login (or set GH_TOKEN) and retry. "
                "Nothing was copied, committed or pushed."
            )
        if not args.dry_run:
            run(["gh", "auth", "setup-git"], check=False)

        if args.repo_dir:
            repo_dir = Path(args.repo_dir).expanduser().resolve()
            if not (repo_dir / "scripts" / "validate_personas.py").is_file():
                raise PublishError("not a collig-personas checkout: " + str(repo_dir))
        else:
            temp_root = Path(tempfile.mkdtemp(prefix="collig-personas-push-"))
            repo_dir = temp_root / "repo"
            print("Cloning " + args.repo + "...", flush=True)
            run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    args.base,
                    "https://github.com/" + args.repo + ".git",
                    str(repo_dir),
                ]
            )

        copy_persona(persona["path"], repo_dir)
        print("Copied persona into " + str(repo_dir / "personas" / persona["slug"]))
        checks = run_repo_checks(repo_dir)
        print(checks["validate"])
        print(checks["tests"][-2000:])

        branch = "persona/" + persona["slug"] + "-" + time.strftime("%Y%m%d%H%M%S", time.gmtime())
        status = run(["git", "status", "--short"], cwd=repo_dir)
        if not status.stdout.strip():
            print("No changes: the market already has this persona version.")
            return 0
        print(status.stdout)

        if args.dry_run:
            print("Dry run complete; no commit or push.")
            return 0

        run(["git", "checkout", "-b", branch], cwd=repo_dir)
        run(["git", "add", "personas/" + persona["slug"], "index.json"], cwd=repo_dir)
        diff = run(["git", "diff", "--cached", "--stat"], cwd=repo_dir)
        print(diff.stdout)
        run(
            [
                "git",
                "-c",
                "user.name=Collig Persona Bot",
                "-c",
                "user.email=personas@collig.local",
                "commit",
                "-m",
                "Add/update persona " + persona["slug"],
            ],
            cwd=repo_dir,
        )

        print("Pushing " + branch + "...", flush=True)
        run(["git", "push", "-u", "origin", branch], cwd=repo_dir)

        body = (
            "Automated persona submission from Collig.\n\n"
            "- Persona: " + persona["name"] + " (" + persona["slug"] + ")\n"
            "- Source: " + str(persona["path"]) + "\n\n"
            "Validation and tests pass in this PR. Please review the dossier for voice quality, "
            "factual accuracy and safe content.\n"
        )
        result = run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                args.repo,
                "--base",
                args.base,
                "--head",
                branch,
                "--title",
                "Add persona: " + persona["name"],
                "--body",
                body,
            ],
            cwd=repo_dir,
            check=False,
        )
        if result.returncode != 0:
            raise PublishError("PR creation failed:\n" + (result.stderr or result.stdout))
        print(result.stdout.strip())
        return 0
    except PublishError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if temp_root is not None and not args.keep:
            shutil.rmtree(temp_root, ignore_errors=True)
        elif temp_root is not None:
            print("Kept checkout: " + str(temp_root))


if __name__ == "__main__":
    sys.exit(main())
