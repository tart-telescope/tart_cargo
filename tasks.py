"""
Release automation for tart_cargo: invoke tasks backed by plumbum.

    invoke --list
    invoke test                                # YAML + stimela dry-runs
    invoke test --with-image                   # + AGENTS.md command check
    invoke release --dry-run
    invoke release --yes --tools-tag=v1.2.4    # what disko's chain runs

tart_cargo releases are the package tags: bump pyproject, keep CHANGES.md in
step, tag v<X.Y.Z> and push — .github/workflows/deploy_module.yaml publishes
to PyPI on that tag (nothing publishes from here, so never tag casually).

`release` stages:

    1. base image  with --tools-tag, point tartcargo/genesis/tart-cargo-base.yml
                   at that tag, first polling GHCR until the image actually
                   exists (AGENTS.md: never bump ahead of a pushed image tag —
                   the tools stage of the chain builds it, and arm64 runs on a
                   self-hosted runner). Omitted for a package-only release.
    2. test        every cab/recipe YAML parses, and each example recipe
                   prevalidates with `stimela run -d` (nothing executes);
                   --with-image additionally checks every cab's `command`
                   exists inside the configured tools image.
    3. version     release the current pyproject version if it has no tag yet
                   (the CHANGES entry for it is usually already written),
                   otherwise bump level.
    4. publish     commit (pyproject + CHANGES + genesis) + tag v<version> +
                   push -> CI publishes to PyPI; --wait watches that run.

Invoked from disko's release chain as
`invoke -r <this repo> release --level=patch --yes --tools-tag=<new tag>`.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from invoke import Exit, task
from plumbum import colors, local

ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGES = ROOT / "CHANGES.md"
GENESIS = ROOT / "tartcargo" / "genesis" / "tart-cargo-base.yml"
TOOLS_IMAGE = "ghcr.io/tart-telescope/tools"
REPO = "tart-telescope/tart_cargo"

UV = local["uv"]
GIT = local["git"]

_LEVELS = ("patch", "minor", "major")
_VERSION_RE = re.compile(r'^version = "(?P<v>[^"]+)"', re.M)
_IMAGE_VERSION_RE = re.compile(r"(?m)^(?P<indent>[ \t]*version:[ \t]*)(?P<v>\S+)")

# Inputs the example recipes need to prevalidate (nothing actually runs, but
# stimela still type-checks required inputs).
_DRY_RUN_INPUTS = {"tart": "mu-udm", "pw": "dry-run-password"}


# ---------------------------------------------------------------- helpers

def _run(cmd, **kwargs):
    print(_paint(colors.light_blue, f"+ {cmd}"), flush=True)
    kwargs.setdefault("cwd", str(ROOT))  # the chain may be invoked from anywhere
    return cmd.run(**kwargs)


def _capture(cmd):
    return cmd.run(retcode=None, cwd=str(ROOT))


def _paint(style, text: str) -> str:
    """plumbum 2 applies styles with `text | style` (plain text off a tty)."""
    return text | style


def _green(text):
    return _paint(colors.green, text)


def _yellow(text):
    return _paint(colors.yellow, text)


def _banner(text):
    print(_paint(colors.bold, f"\n=== {text}"), flush=True)


def _git(*args):
    rc, out, err = local["git"][list(args)].run(retcode=None, cwd=str(ROOT))
    if rc != 0:
        raise Exit(f"git {' '.join(args)} failed: {err.strip()}")
    return out.strip()


def _confirm(message: str, assume_yes: bool) -> None:
    if assume_yes:
        print(_yellow(f"{message} (--yes: proceeding)"))
        return
    if input(f"{message} [y/N] ").strip().lower() not in ("y", "yes"):
        raise Exit("aborted")


def read_version() -> str:
    match = _VERSION_RE.search(PYPROJECT.read_text())
    if not match:
        raise Exit(f"no version line in {PYPROJECT}")
    return match.group("v")


def write_version(version: str) -> None:
    text = PYPROJECT.read_text()
    PYPROJECT.write_text(_VERSION_RE.sub(f'version = "{version}"', text, count=1))


def bump_version(version: str, level: str) -> str:
    if level not in _LEVELS:
        raise Exit(f"--level must be one of {_LEVELS}, got {level!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def last_tag() -> str:
    rc, out, _ = _capture(GIT["describe", "--tags", "--abbrev=0"])
    return out.strip() if rc == 0 else ""


def image_version() -> str:
    """The tools tag currently configured in tart-cargo-base.yml."""
    match = _IMAGE_VERSION_RE.search(GENESIS.read_text())
    if not match:
        raise Exit(f"no version: line in {GENESIS}")
    return match.group("v")


def set_image_version(tag: str) -> bool:
    text = GENESIS.read_text()
    old = image_version()
    if old == tag:
        print(f"  base image already at {tag}")
        return False
    GENESIS.write_text(_IMAGE_VERSION_RE.sub(lambda m: f"{m.group('indent')}{tag}", text, count=1))
    print(_green(f"  base image {old} -> {tag}"))
    return True


def _changes_for(version: str) -> None:
    """Keep a `## <version>` section: reuse it if already curated (the usual
    case — entries are written as the work lands), else draft one from git."""
    text = CHANGES.read_text()
    if re.search(rf"^## {re.escape(version)}\b", text, re.M):
        print(f"  CHANGES.md already documents {version}")
        return
    rc, out, _ = _capture(GIT["log", f"{last_tag()}..HEAD", "--pretty=%s"])
    bullets = "\n".join(f"- {line}" for line in out.splitlines() if line.strip())
    section = f"## {version}\n\n{bullets or '- Release ' + version + '.'}\n"
    head, sep, rest = text.partition("\n")
    CHANGES.write_text(f"{head}\n{sep}{section}\n{rest.lstrip()}\n")
    print(_yellow(f"  CHANGES.md: drafted a {version} section from git history — please review"))


def _assert_clean() -> None:
    modified, untracked = [], []
    for line in _git("status", "--porcelain").splitlines():
        if not line.strip():
            continue
        (untracked if line.startswith("??") else modified).append(line)
    if untracked:
        print(_yellow(f"  ignoring {len(untracked)} untracked path(s)"))
    if modified:
        raise Exit("working tree has modified files; commit or stash them:\n  " + "\n  ".join(modified))


# --------------------------------------------------------------- external

def _image_exists(tag: str) -> bool:
    # local.which() raises when missing and returns a path when present, so
    # detect with shutil.which and build the command with local[...].
    if shutil.which("docker"):
        rc, _, _ = _capture(local["docker"]["manifest", "inspect", f"{TOOLS_IMAGE}:{tag}"])
        if rc == 0:
            return True
    token_url = "https://ghcr.io/token?scope=repository:tart-telescope/tools:pull&service=ghcr.io"
    try:
        with urllib.request.urlopen(token_url, timeout=20) as response:
            token = json.load(response).get("token", "")
        request = urllib.request.Request(
            "https://ghcr.io/v2/tart-telescope/tools/tags/list",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return tag in (json.load(response).get("tags") or [])
    except (urllib.error.URLError, json.JSONDecodeError):
        return False


def _wait_for_image(tag: str, timeout_s: int = 3600, poll_s: int = 30) -> None:
    print(_paint(colors.light_blue, f"  waiting for {TOOLS_IMAGE}:{tag} on GHCR ..."))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _image_exists(tag):
            print(_green(f"  GHCR has {TOOLS_IMAGE}:{tag}"))
            return
        time.sleep(poll_s)
    raise Exit(f"timed out after {timeout_s}s waiting for {TOOLS_IMAGE}:{tag}")


def _wait_for_publish(tag: str, timeout_s: int = 1800, poll_s: int = 20) -> None:
    if shutil.which("gh") is None:
        raise Exit("gh CLI is required to wait for the publish (or pass --no-wait)")
    gh = local["gh"]
    print(_paint(colors.light_blue, f"  waiting for the deploy_module run on {tag} ..."))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rc, out, _ = _capture(
            gh[
                "run", "list", "--repo", REPO, "--workflow", "deploy_module.yaml",
                "--limit", "10", "--json", "headBranch,status,conclusion,url",
            ]
        )
        if rc == 0 and out.strip() and out.strip() != "[]":
            for run in json.loads(out):
                if run.get("headBranch") == tag and run.get("status") == "completed":
                    if run.get("conclusion") == "success":
                        print(_green(f"  PyPI publish OK: {run['url']}"))
                        return
                    raise Exit(f"publish workflow failed: {run['url']}")
        time.sleep(poll_s)
    raise Exit(f"timed out after {timeout_s}s waiting for the publish run on {tag}")


# ------------------------------------------------------------------- tasks

def _example_recipes():
    return sorted((ROOT / "examples").glob("*.yml"))


def _required_inputs(recipe_path: Path) -> dict:
    """Required inputs of the single recipe defined in the file."""
    doc = yaml.safe_load(recipe_path.read_text()) or {}
    for key, value in doc.items():
        if key in ("opts", "_include") or not isinstance(value, dict):
            continue
        return {
            name: spec
            for name, spec in (value.get("inputs") or {}).items()
            if isinstance(spec, dict) and spec.get("required")
        }
    return {}


@task(help={"with_image": "also check every cab command exists in the tools image"})
def test(c, with_image=False):
    """Parse every cab/recipe YAML and prevalidate each example recipe."""
    _banner("test: YAML")
    files = sorted((ROOT / "tartcargo").glob("*.yml")) + sorted(
        path for path in (ROOT / "examples").rglob("*.yml") if "logs" not in path.parts
    )
    for path in files:
        yaml.safe_load(path.read_text())
    print(f"  {len(files)} YAML files parse")

    _banner("test: stimela dry-runs (prevalidation only, nothing executes)")
    ran = skipped = 0
    for recipe in _example_recipes():
        required = _required_inputs(recipe)
        missing = [name for name in required if name not in _DRY_RUN_INPUTS]
        if missing:
            print(_yellow(f"  skip {recipe.name}: no dry-run value for {missing}"))
            skipped += 1
            continue
        args = [f"{name}={_DRY_RUN_INPUTS[name]}" for name in required]
        _run(UV["run", "stimela", "run", "-d", str(recipe), *args])
        ran += 1
    print(f"  {ran} recipes prevalidated, {skipped} skipped")

    if with_image:
        _banner(f"test: cab commands exist in {TOOLS_IMAGE}:{image_version()}")
        commands = sorted(
            {
                spec["command"]
                for path in (ROOT / "tartcargo").glob("*.yml")
                for spec in (yaml.safe_load(path.read_text()) or {}).get("cabs", {}).values()
            }
        )
        script = "; ".join(f"which {cmd} || echo MISSING:{cmd}" for cmd in commands)
        rc, out, _ = _capture(
            local["docker"]["run", "--rm", "--entrypoint", "", f"{TOOLS_IMAGE}:{image_version()}", "sh", "-c", script]
        )
        missing = [line for line in out.splitlines() if line.startswith("MISSING:")]
        if rc != 0 or missing:
            raise Exit("missing executables in the image: " + ", ".join(m.replace("MISSING:", "") for m in missing))
        print(f"  all {len(commands)} commands present")

    print(_green("\ntest: OK"))


@task(help={"level": "patch | minor | major (default: patch)", "dry_run": "show, don't write"})
def bump(c, level="patch", dry_run=False):
    """Show (or apply) the next package version and its CHANGES section."""
    _banner("bump")
    current = read_version()
    tag = last_tag()
    target = current if f"v{current}" not in tag_target_set() else bump_version(current, level)
    print(f"  version {current} -> {target} (last tag: {tag or '(none)'})")
    if dry_run:
        print(_yellow("  dry run: nothing written"))
        return target
    write_version(target)
    _changes_for(target)
    return target


def tag_target_set() -> set:
    rc, out, _ = _capture(GIT["tag", "--list"])
    return set(out.split()) if rc == 0 else set()


@task(
    help={
        "level": "patch | minor | major for the package version (default: patch)",
        "yes": "skip the confirmation prompt",
        "tools_tag": "bump the base image to this tools tag first",
        "wait": "wait for GHCR (with --tools-tag) and for the PyPI run (default)",
        "skip_tests": "skip the YAML/stimela checks (not for routine use)",
        "dry_run": "print the plan and exit",
    }
)
def release(c, level="patch", yes=False, tools_tag=None, wait=True, skip_tests=False, dry_run=False):
    """base image -> test -> version -> tag -> CI publishes to PyPI."""
    current = read_version()
    target = current if f"v{current}" not in tag_target_set() else bump_version(current, level)

    if dry_run:
        _banner("tart_cargo release plan (dry run)")
        if tools_tag:
            state = "exists" if _image_exists(tools_tag) else "not yet"
            print(f"  1. base image  genesis -> {tools_tag} (GHCR: {state})")
        print(f"  2. test        YAML + stimela dry-runs of {len(_example_recipes())} recipes")
        note = " (already unreleased)" if target == current else f" ({level} bump)"
        print(f"  3. version     {current} -> {target}{note}")
        print(f"  4. publish     commit + tag v{target} + push -> deploy_module.yaml -> PyPI")
        print(_yellow("  dry run: nothing executed"))
        return

    _banner("tart_cargo release")
    _assert_clean()

    if tools_tag:
        if wait:
            _wait_for_image(tools_tag)
        elif not _image_exists(tools_tag):
            raise Exit(f"{tools_tag} is not on GHCR yet — refusing to bump ahead of the image (AGENTS.md)")

    if not skip_tests:
        test(c)

    write_version(target)
    _changes_for(target)
    if tools_tag:
        set_image_version(tools_tag)

    _confirm(f"Release tart_cargo {target} + tag v{target} (CI publishes to PyPI)?", yes)

    _run(GIT["add", str(PYPROJECT), str(CHANGES), str(GENESIS)])
    if _capture(GIT["diff", "--cached", "--quiet"])[0] != 0:
        _run(GIT["commit", "-m", f"Release {target}" + (f" (tools {tools_tag})" if tools_tag else "")])
    else:
        print("  nothing to commit; tagging the current commit")
    _run(GIT["tag", "-a", f"v{target}", "-m", f"Release {target}"])
    _run(GIT["push", "--follow-tags", "origin", "HEAD"])

    if wait:
        _wait_for_publish(f"v{target}")
    else:
        print(_yellow("  not waiting for CI; verify the deploy_module run yourself"))

    print(_green(f"\ntart_cargo release {target} complete"))


@task
def status(c):
    """Show package version, tags and the configured tools image."""
    _banner("status")
    print(f"  package   version={read_version()}  last tag={last_tag() or '(none)'}")
    print(f"  base image {image_version()} ({TOOLS_IMAGE})")
    dirty = [line for line in _git("status", "--porcelain").splitlines() if not line.startswith("??")]
    print(f"  dirty tracked files: {len(dirty)}")
