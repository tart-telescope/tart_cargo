"""
Release automation for tart_cargo: invoke tasks backed by plumbum.

    invoke --list
    invoke test                                # YAML + stimela dry-runs
    invoke test --with-image                   # + AGENTS.md command check
    invoke smoke                               # end-to-end basics example, really runs
    invoke tools_test                          # build the tools image locally + stimela gates
    invoke tools_release --dry-run
    invoke release --dry-run
    invoke release --yes --tools-tag=v1.2.4    # what disko's chain runs

tart_cargo releases are the package tags: bump pyproject, keep CHANGES.md in
step, tag v<X.Y.Z> and push — .github/workflows/deploy_module.yaml publishes
to PyPI on that tag (nothing publishes from here, so never tag casually).

**Both releases are controlled by this script**: the tools image release
(`tools_release`, below) and this package's (`release`). The tools release
builds the Docker container **locally** and tests it with **this script's
stimela gates** — the dry-run suite, the cab-command check inside the local
image, and the end-to-end `smoke` pipeline run against the local build —
before tagging; CI then builds the multi-arch image for GHCR.

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
    3. smoke       run the radio-imaging `basics` example for real
                   (`simple_recipe.yml`, i.e. `make TART=<tart>`) in a scratch
                   dir: builds an MS from TART visibilities and images with
                   spotless and disko, failing the release if any step errors
                   or the expected outputs are missing. Defaults to the mz-up
                   station on the committed pre-downloaded
                   `testdata/mz-up-vis.hdf` — the recipe's download step
                   skips itself when `<tart>-vis.hdf` already exists, so the
                   default gate needs no TART API access. Needs
                   apptainer/singularity (network only for other stations).
    4. version     release the current pyproject version if it has no tag yet
                   (the CHANGES entry for it is usually already written),
                   otherwise bump level.
    5. publish     commit (pyproject + CHANGES + genesis) + tag v<version> +
                   push -> CI publishes to PyPI; --wait watches that run.

Invoked from disko's release chain as
`invoke -r <this repo> release --level=patch --yes --tools-tag=<new tag>`
(and stage 4 as `invoke -r <this repo> tools_release --disko-version=<new>`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from invoke import Exit, task
from plumbum import FG, colors, local
from plumbum.commands.processes import ProcessExecutionError

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


def _genesis_registry() -> str:
    """The container registry shared by every cab image (genesis vars)."""
    data = yaml.safe_load(GENESIS.read_text()) or {}
    images = (((data.get("vars") or {}).get("tart-cargo") or {}).get("images") or {})
    registry = images.get("registry")
    if not registry:
        raise Exit(f"no registry: in {GENESIS}")
    return registry


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
    """(path, recipe_name, recipes_in_file) for every recipe in examples/.

    A file may define more than one recipe — make-movie.yml defines
    `tart-movie` and `loop-make-images` — in which case stimela needs the
    recipe name on the command line to know which one to run.
    """
    recipes = []
    for path in sorted((ROOT / "examples").glob("*.yml")):
        doc = yaml.safe_load(path.read_text()) or {}
        names = [
            key
            for key, value in doc.items()
            if key not in ("opts", "_include")
            and isinstance(value, dict)
            and ("steps" in value or "inputs" in value)
        ]
        for name in names:
            recipes.append((path, name, len(names)))
    return recipes


def _needs_value(spec) -> bool:
    """Does a recipe input need a value for a dry-run?

    stimela's inputs come in two shapes: the long mapping
    (`{dtype: str, required: true, info: …}`) and the shorthand type
    annotation (`hdf-files: List[str]`). It calls an input required when it
    has no default and is not explicitly optional, so treat a missing
    `required` as required and anything with a `default` as satisfied.
    """
    if isinstance(spec, dict):
        if spec.get("required") is False or "default" in spec:
            return False
        return bool(spec.get("required", True))
    return True  # shorthand annotation, e.g. "List[str]"


def _required_inputs(recipe_path: Path, recipe_name: str) -> dict:
    """Inputs of one named recipe that still need a value."""
    spec = yaml.safe_load(recipe_path.read_text()).get(recipe_name) or {}
    return {
        name: value
        for name, value in (spec.get("inputs") or {}).items()
        if _needs_value(value)
    }


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
    for path, recipe_name, count in _example_recipes():
        required = _required_inputs(path, recipe_name)
        missing = [name for name in required if name not in _DRY_RUN_INPUTS]
        if missing:
            print(_yellow(f"  skip {path.name}:{recipe_name} — no dry-run value for {missing}"))
            skipped += 1
            continue
        args = [f"{name}={_DRY_RUN_INPUTS[name]}" for name in required]
        # stimela refuses multi-recipe files without an explicit selector
        selector = [recipe_name] if count > 1 else []
        # tuple display, not `UV[..., *selector, *args]` — starred subscripts
        # are 3.11+ syntax (PEP 646) and the gate must run on the 3.10 floor
        _run(UV[("run", "stimela", "run", "-d", str(path), *selector, *args)])
        ran += 1
    print(f"  {ran} recipes prevalidated, {skipped} skipped")

    if with_image:
        _banner(f"test: cab commands exist in their images (tools {image_version()})")
        registry = _genesis_registry()
        default_version = image_version()
        by_image = {}
        for path in sorted((ROOT / "tartcargo").glob("*.yml")):
            for spec in (yaml.safe_load(path.read_text()) or {}).get("cabs", {}).values():
                img = spec.get("image") or {}
                # `_use: vars.tart-cargo.images` supplies registry + the shared
                # default version; a cab may name a different image and pin its
                # own version (tartball does both).
                ref = "{}/{}:{}".format(
                    registry,
                    img.get("name", "tools"),
                    img.get("version", default_version),
                )
                by_image.setdefault(ref, set()).add(spec["command"])
        for ref in sorted(by_image):
            commands = sorted(by_image[ref])
            script = "; ".join(f"which {cmd} || echo MISSING:{cmd}" for cmd in commands)
            rc, out, _ = _capture(
                local["docker"]["run", "--rm", "--entrypoint", "", ref, "sh", "-c", script]
            )
            missing = [line.replace("MISSING:", "") for line in out.splitlines() if line.startswith("MISSING:")]
            if rc != 0 or missing:
                raise Exit(f"missing executables in {ref}: " + ", ".join(missing))
            print(f"  {ref}: all {len(commands)} commands present")

    print(_green("\ntest: OK"))


# --------------------------------------------------------------- smoke test

# The radio-imaging "basics" example this gate runs; equivalent to
# `make TART=<tart>` in that directory.
_EXAMPLE_RECIPE = "simple_recipe.yml"
# Outputs the recipe must produce for the run to count as a pass.
_EXAMPLE_OUTPUTS = (
    "{tart}-spotless.sphere",
    "{tart}-disko.sphere",
    "spotless-{tart}.svg",
    "disko-{tart}.svg",
)

# Pre-downloaded visibility data from the mz-up TART
# (https://api.elec.ac.nz/tart/mz-up, sha256-checked by tart_download_data
# when it was fetched). Committed so the release smoke gate runs offline:
# the basics recipe's download-hdf step is `skip: =EXISTS(recipe.hdf)`, so a
# `<tart>-vis.hdf` present in the working directory is used as-is.
_MZUP_HDF = ROOT / "testdata" / "mz-up-vis.hdf"


def _basics_example_dir(example_dir: str | None) -> Path:
    """Locate the radio-imaging basics checkout holding simple_recipe.yml."""
    candidates = []
    if example_dir:
        candidates.append(Path(example_dir))
    else:
        env = os.environ.get("RADIO_IMAGING_BASICS")
        if env:
            candidates.append(Path(env))
        candidates.append(ROOT.parent / "radio-imaging" / "basics")
    for cand in candidates:
        if (cand / _EXAMPLE_RECIPE).is_file():
            return cand.resolve()
    raise Exit(
        f"radio-imaging basics checkout not found (looked for {_EXAMPLE_RECIPE} in "
        + ", ".join(str(c) for c in candidates)
        + "); pass --example-dir or set RADIO_IMAGING_BASICS, or release with --skip-smoke"
    )


@task(
    help={
        "tart": "TART station to image (default: ghana; mz-up runs offline on the committed data)",
        "example_dir": "radio-imaging basics dir (default: $RADIO_IMAGING_BASICS or <sibling>/radio-imaging/basics)",
        "nvis": "override the recipe's nvis (default: as shipped, 1000); lower it on machines with <32 GB RAM or the disko step gets OOM-killed",
        "hdf": "pre-downloaded <tart>-vis.hdf to image instead of downloading (default for tart=mz-up: testdata/mz-up-vis.hdf)",
        "keep": "keep the scratch working dir for inspection",
    }
)
def smoke(c, tart="ghana", example_dir=None, nvis=None, hdf=None, keep=False):
    """Actually run the radio-imaging basics example end-to-end.

    The dry-runs in `test` only prove the YAML prevalidates; this builds a
    measurement set from real TART visibilities and images it with spotless
    and disko — the same work `make TART=<tart>` does in the radio-imaging
    repo. With `tart=mz-up` (what `release` uses) it runs offline on the
    committed `testdata/mz-up-vis.hdf`: a `<tart>-vis.hdf` present in the
    working directory makes the recipe's download step skip itself. Any
    other station downloads from the TART API. It needs
    apptainer/singularity, and takes several minutes (image pull on first
    run).
    """
    src = _basics_example_dir(example_dir)
    if hdf is None and tart == "mz-up":
        if _MZUP_HDF.is_file():
            hdf = _MZUP_HDF
        else:
            print(_yellow(f"  {_MZUP_HDF} is missing — the recipe will download from the TART API instead"))
    if hdf is not None:
        hdf = Path(hdf).expanduser().resolve()
        if not hdf.is_file():
            raise Exit(f"--hdf: no such file: {hdf}")
        # The recipe only skips download-hdf on EXISTS(<tart>-vis.hdf), so a
        # mismatched name would silently re-download instead of running offline.
        expected = f"{tart}-vis.hdf"
        if hdf.name != expected:
            raise Exit(f"--hdf must be named {expected} for tart={tart} (got {hdf.name})")
    _banner(f"smoke: end-to-end basics example (tart={tart}, image {image_version()})")
    print(f"  recipe: {src / _EXAMPLE_RECIPE}")
    if hdf is not None:
        print(f"  pre-downloaded visibilities: {hdf} (download step will skip)")

    workdir = Path(tempfile.mkdtemp(prefix=f"tart-cargo-smoke-{tart}-"))
    print(f"  scratch dir: {workdir}")
    try:
        recipe_text = (src / _EXAMPLE_RECIPE).read_text()
        if nvis is not None:
            # nvis is a step param, not a recipe input, so patch the copied
            # YAML rather than passing it on the command line.
            recipe_text, patched = re.subn(r"nvis: \d+", f"nvis: {nvis}", recipe_text)
            if not patched:
                raise Exit(f"no `nvis: <number>` line found in {src / _EXAMPLE_RECIPE} to override")
        (workdir / _EXAMPLE_RECIPE).write_text(recipe_text)
        if hdf is not None:
            shutil.copy2(hdf, workdir / f"{tart}-vis.hdf")
        # --project keeps tart_cargo's uv env while stimela runs with cwd set
        # to the scratch dir, so every output lands there.
        cmd = UV["run", "--project", str(ROOT), "stimela", "run", _EXAMPLE_RECIPE, f"tart={tart}"]
        print(_paint(colors.light_blue, f"+ (cd {workdir} && {cmd})"), flush=True)
        try:
            with local.cwd(workdir):
                cmd & FG
        except ProcessExecutionError as exc:
            raise Exit(f"smoke run failed (stimela exit code {exc.retcode}); see the log above")

        missing = [name.format(tart=tart) for name in _EXAMPLE_OUTPUTS if not (workdir / name.format(tart=tart)).is_file()]
        if missing:
            raise Exit(f"smoke run finished but expected outputs are missing: {', '.join(missing)}")
        for name in _EXAMPLE_OUTPUTS:
            path = workdir / name.format(tart=tart)
            print(f"  {path.name}: {path.stat().st_size} bytes")
        print(_green(f"\nsmoke: OK (tart={tart})"))
    finally:
        if keep:
            print(_yellow(f"  keeping {workdir}"))
        else:
            shutil.rmtree(workdir, ignore_errors=True)


# ------------------------------------------------------------ tools image

# The tools repo builds the container every cab above runs in. Its release
# lives in this script so both releases (tools image and this package) are
# controlled here; the checkout is a sibling by default (override with
# TART_CARGO_TOOLS_REPO).
TOOLS_REPO = Path(os.environ.get("TART_CARGO_TOOLS_REPO", ROOT.parent / "tools"))
TOOLS_DOCKERFILE = TOOLS_REPO / "Dockerfile"
_DISKO_PIN = re.compile(r'"disko[^"]*"')
_SIMG_DIR = Path("~/.singularity").expanduser()


def _tools_git(*args):
    rc, out, err = local["git"][list(args)].run(retcode=None, cwd=str(TOOLS_REPO))
    return rc, out.strip(), err.strip()


def _tools_latest_tag() -> str:
    rc, out, _ = _tools_git("describe", "--tags", "--abbrev=0")
    return out if rc == 0 else ""


def _tools_next_tag(level: str) -> str:
    latest = _tools_latest_tag()
    if not latest:
        raise Exit(f"no tags in {TOOLS_REPO} — nothing to bump from")
    return "v" + bump_version(latest.lstrip("v"), level)


def _assert_tools_clean() -> None:
    rc, out, err = _tools_git("status", "--porcelain")
    if rc != 0:
        raise Exit(f"git status (tools) failed: {err}")
    modified = [line for line in out.splitlines() if not line.startswith("??")]
    if modified:
        raise Exit("tools working tree has modified files; commit or stash them:\n  " + "\n  ".join(modified))


def _pypi_has(package: str, version: str) -> bool:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.load(response)["info"]["version"] == version
    except urllib.error.URLError as exc:
        raise Exit(f"cannot reach PyPI ({exc})") from exc
    except (json.JSONDecodeError, KeyError):
        return False


def _wait_for_pypi(package: str, version: str, timeout_s: int = 900, poll_s: int = 15) -> None:
    print(_paint(colors.light_blue, f"  waiting for {package} {version} on PyPI ..."))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _pypi_has(package, version):
            print(_green(f"  PyPI has {package} {version}"))
            return
        time.sleep(poll_s)
    raise Exit(f"timed out after {timeout_s}s waiting for {package} {version}")


def _set_disko_pin(version: str) -> bool:
    """Pin `disko==version` exactly: releases must be reproducible."""
    text = TOOLS_DOCKERFILE.read_text()
    matches = _DISKO_PIN.findall(text)
    if len(matches) != 1:
        raise Exit(f"expected exactly one disko pin in the Dockerfile, found {len(matches)}")
    new_pin = f'"disko=={version}"'
    if matches[0] == new_pin:
        print(f"  Dockerfile already pinned {new_pin}")
        return False
    TOOLS_DOCKERFILE.write_text(_DISKO_PIN.sub(new_pin, text, count=1))
    print(_green(f"  Dockerfile pin {matches[0]} -> {new_pin}"))
    return True


def _build_tools_image(tag: str) -> None:
    """Build the tools container locally, tagged as the release candidate."""
    if not TOOLS_REPO.is_dir():
        raise Exit(f"tools checkout not found at {TOOLS_REPO} (set TART_CARGO_TOOLS_REPO)")
    if not shutil.which("docker"):
        raise Exit("docker not found on PATH — the tools release builds the image locally")
    ref = f"{TOOLS_IMAGE}:{tag}"
    _banner(f"tools: local docker build ({ref})")
    _run(local["docker"]["build", "--progress=plain", "-t", ref, "."], cwd=str(TOOLS_REPO))


def _seed_simg(tag: str) -> Path:
    """Convert the local docker build into the .simg the stimela gates run.

    stimela's singularity backend converts `docker://<ref>` **from the
    registry** and only reuses `~/.singularity/<ref>.simg` when that file
    already exists — so without this the smoke gate would silently test the
    published image instead of the local build. `docker-daemon:` reads the
    image just built.
    """
    ref = f"{TOOLS_IMAGE}:{tag}"
    simg = _SIMG_DIR / (ref.replace("/", "-") + ".simg")
    runtime = "apptainer" if shutil.which("apptainer") else "singularity"
    if not shutil.which(runtime):
        raise Exit(f"neither apptainer nor singularity found — cannot convert {ref} for the stimela gates")
    _SIMG_DIR.mkdir(exist_ok=True)
    if simg.exists():
        simg.unlink()
    _banner(f"tools: converting the local build for stimela ({simg.name})")
    _run(local[runtime]["build", str(simg), f"docker-daemon:{ref}"])
    return simg


def _stimela_gates_on_local_image(c, tag: str, skip_smoke: bool = False) -> None:
    """This script's stimela gates against a locally built tools image.

    The gates resolve the image from the genesis pointer, so it is pointed at
    `tag` for the duration and restored afterwards — `test --with-image` then
    `docker run`s the local build, and `smoke` runs the pipeline from the
    .simg seeded above (offline, on the committed mz-up data).
    """
    old = image_version()
    print(_yellow(f"  genesis temporarily at {tag} for the local-image gates (restored after)"))
    set_image_version(tag)
    try:
        test(c, with_image=True)
        if not skip_smoke:
            smoke(c, tart="mz-up")
    finally:
        if image_version() != old:
            set_image_version(old)


@task(
    help={
        "tag": "image tag to build and test (default: the next release tag)",
        "quick": "image already built; only convert it and run the stimela gates",
        "skip_smoke": "skip the end-to-end smoke gate (not for routine use)",
    }
)
def tools_test(c, tag=None, quick=False, skip_smoke=False):
    """Build the tools image locally and test it with this script's stimela gates."""
    tag = tag or _tools_next_tag("patch")
    _banner(f"tools test: {TOOLS_IMAGE}:{tag} (local build)")
    if not quick:
        _build_tools_image(tag)
    _seed_simg(tag)
    _stimela_gates_on_local_image(c, tag, skip_smoke=skip_smoke)
    print(_green(f"\ntools test: OK ({TOOLS_IMAGE}:{tag}, local build)"))


@task(
    help={
        "level": "patch | minor | major for the image tag (default: patch)",
        "yes": "skip the confirmation prompt",
        "disko_version": "pin the Dockerfile to exactly this disko release (verified on PyPI first)",
        "skip_tests": "skip the stimela gates (not for routine use)",
        "wait": "wait for the GHCR image to exist (default)",
        "dry_run": "print the plan and exit",
    }
)
def tools_release(c, level="patch", yes=False, disko_version=None, skip_tests=False, wait=True, dry_run=False):
    """pin -> build the container locally -> stimela gates -> tag -> CI multi-arch -> wait GHCR."""
    planned = _tools_next_tag(level)

    if dry_run:
        _banner("tools release plan (dry run)")
        if disko_version:
            print(f"  1. pin        Dockerfile: disko=={disko_version} (verified on PyPI first)")
        print(f"  2. build      docker build -t {TOOLS_IMAGE}:{planned}  (local)")
        if skip_tests:
            print("  3. gates      [skipped]")
        else:
            print(f"  3. gates      stimela on the local build: dry-runs + cab commands + smoke (offline mz-up)")
        print(f"  4. tag        {_tools_latest_tag()} -> {planned}, push -> docker-publish.yml -> GHCR")
        if wait:
            print(f"  5. wait       poll until {TOOLS_IMAGE}:{planned} exists")
        print(_yellow("  dry run: nothing executed"))
        return

    _banner("tools release (this script controls both the tools and tart_cargo releases)")
    _assert_tools_clean()

    if disko_version:
        # The caller's disko publish may only just have landed.
        _wait_for_pypi("disko", disko_version)
        _set_disko_pin(disko_version)

    # Build first: the local build is what the gates run below, and it
    # proves the (possibly just-changed) Dockerfile pins still resolve.
    _build_tools_image(planned)
    if not skip_tests:
        _seed_simg(planned)
        _stimela_gates_on_local_image(c, planned)
    else:
        print(_yellow("  --skip-tests: stimela gates skipped (the build itself validated the pins)"))

    _confirm(f"Tag {planned} and push (CI builds and pushes the image)?", yes)

    _run(GIT["add", str(TOOLS_DOCKERFILE)], cwd=str(TOOLS_REPO))
    rc, _, _ = local["git"]["diff", "--cached", "--quiet"].run(retcode=None, cwd=str(TOOLS_REPO))
    if rc != 0:
        _run(
            GIT["commit", "-m", f"Release {planned}" + (f": pin disko=={disko_version}" if disko_version else "")],
            cwd=str(TOOLS_REPO),
        )
    else:
        print("  nothing to commit; tagging the current commit")
    _run(GIT["tag", "-a", planned, "-m", f"Release {planned}"], cwd=str(TOOLS_REPO))
    _run(GIT["push", "--follow-tags", "origin", "HEAD"], cwd=str(TOOLS_REPO))

    if wait:
        _wait_for_image(planned)
    else:
        print(_yellow("  not waiting for GHCR; tart_cargo must not bump to this tag yet"))

    print(_green(f"\ntools release {planned} complete"))
    print(f"  next: invoke release --tools-tag={planned}  (bump the base image + release this package)")


@task(help={"level": "patch | minor | major for the package version (default: patch)", "dry_run": "show, don't write"})
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
        "skip_smoke": "skip the end-to-end basics example (not for routine use)",
        "smoke_tart": "TART station the smoke test images (default: mz-up — offline, on the committed pre-downloaded data)",
        "dry_run": "print the plan and exit",
    }
)
def release(c, level="patch", yes=False, tools_tag=None, wait=True, skip_tests=False, skip_smoke=False, smoke_tart="mz-up", dry_run=False):
    """base image -> test -> smoke (offline mz-up by default) -> version -> tag -> CI publishes to PyPI."""
    current = read_version()
    target = current if f"v{current}" not in tag_target_set() else bump_version(current, level)

    if dry_run:
        _banner("tart_cargo release plan (dry run)")
        if tools_tag:
            state = "exists" if _image_exists(tools_tag) else "not yet"
            print(f"  1. base image  genesis -> {tools_tag} (GHCR: {state})")
        print(f"  2. test        YAML + stimela dry-runs of {len(_example_recipes())} recipes")
        offline = ", offline on testdata/mz-up-vis.hdf" if smoke_tart == "mz-up" else ""
        print(f"  3. smoke       end-to-end basics example (tart={smoke_tart}{offline})" + ("  [skipped]" if skip_smoke else ""))
        note = " (already unreleased)" if target == current else f" ({level} bump)"
        print(f"  4. version     {current} -> {target}{note}")
        print(f"  5. publish     commit + tag v{target} + push -> deploy_module.yaml -> PyPI")
        print(_yellow("  dry run: nothing executed"))
        return

    _banner("tart_cargo release")
    _assert_clean()

    if tools_tag:
        if wait:
            _wait_for_image(tools_tag)
        elif not _image_exists(tools_tag):
            raise Exit(f"{tools_tag} is not on GHCR yet — refusing to bump ahead of the image (AGENTS.md)")

    # Gate on the image this release will point at: the current base may be
    # broken (v1.3.3 died on tools#5) and shipping the new tag is exactly the
    # fix, so testing the old image would reject the repairing release. GHCR
    # has the tag (waited above); the pointer change rides in the release
    # commit below. Restored if the gates fail, so a failed run leaves the
    # tree clean for a retry.
    previous_image = image_version()
    if tools_tag:
        set_image_version(tools_tag)

    try:
        if not skip_tests:
            test(c)
        if not skip_smoke:
            smoke(c, tart=smoke_tart)
        else:
            print(_yellow("  smoke: skipped (--skip-smoke)"))
    except BaseException:
        if image_version() != previous_image:
            print(_yellow(f"  gates failed — restoring base image to {previous_image}"))
            set_image_version(previous_image)
        raise

    write_version(target)
    _changes_for(target)

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
