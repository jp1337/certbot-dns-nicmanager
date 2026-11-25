"""docs/ is for whoever runs the plugin and ships to PyPI; docs-tech/ never does.

The boundary is checked on the artefact, not on MANIFEST.in: the test builds the
real sdist and reads its file list, so a `graft .`, an `include docs-tech/...`
or a setuptools default that starts picking up Markdown fails here whatever the
manifest seems to say.
"""

import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_BUILD_SDIST = "import sys, setuptools.build_meta as b; print(b.build_sdist(sys.argv[1]))"

# The sdist ships tests/ but not docs-tech/, so these checks only mean something
# in a git checkout; a packager running the suite from the sdist skips them.
pytestmark = pytest.mark.skipif(
    not (ROOT / ".git").exists(), reason="needs a git checkout of the repository"
)


def _sdist_names(tmp_path: Path) -> list[str]:
    # Build from the repository's files (tracked, or new and not ignored), as CI
    # does from a fresh checkout. In the
    # working tree setuptools would reuse a stale *.egg-info/SOURCES.txt and ship
    # whatever an earlier build listed there.
    src = tmp_path / "src"
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    for rel in filter(None, tracked):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, src / rel)
    out = tmp_path / "dist"
    name = (
        subprocess.run(
            [
                sys.executable,
                "-c",
                _BUILD_SDIST,
                str(out),
            ],
            cwd=src,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )
    with tarfile.open(out / name) as sdist:
        # Drop the "certbot_dns_nicmanager-X.Y.Z/" prefix.
        return [m.split("/", 1)[1] for m in sdist.getnames() if "/" in m]


def test_the_technical_docs_are_not_published(tmp_path):
    tech = [p for p in (ROOT / "docs-tech").rglob("*.md")]
    assert tech, "docs-tech/ is missing or empty: maintainer docs belong there"

    names = _sdist_names(tmp_path)
    assert "docs/TROUBLESHOOTING.md" in names, "the operator docs no longer ship"
    leaked = [n for n in names if n.startswith("docs-tech")]
    assert not leaked, f"maintainer docs ship to PyPI: {leaked}"


def test_no_maintainer_docs_hide_under_docs():
    for name in ("docs-tech", "decisions", "ARCHITECTURE.md"):
        assert not (ROOT / "docs" / name).exists(), (
            f"docs/{name} exists — everything under docs/ ships to PyPI; "
            f"maintainer documentation goes in docs-tech/"
        )


def test_operator_docs_do_not_point_into_docs_tech():
    # A published page that depends on an unpublished one is a dead end in the sdist.
    for page in (ROOT / "docs").rglob("*.md"):
        links = re.findall(r"\]\(([^)]*docs-tech[^)]*)\)", page.read_text())
        assert not links, f"{page.relative_to(ROOT)} links into docs-tech/: {links}"


# -- links ------------------------------------------------------------------

_REPO = "jp1337/certbot-dns-nicmanager"
# A link into this repository: a file on main (blob/tree/raw), or the front page
# itself (which GitHub renders from README.md). Other repository URLs — issues,
# security advisories, releases — are not files and stay out of scope.
_SELF = re.compile(
    rf"https://(?:github\.com/{_REPO}(?:/(?:blob|tree)/main/(?P<path>[^)\s\"#]*)|(?=[#)\s\"]|$))"
    rf"|raw\.githubusercontent\.com/{_REPO}/main/(?P<raw>[^)\s\"#]*))(?P<anchor>#[^)\s\"]*)?"
)
_LINK = re.compile(r"\]\(([^)\s]+)\)|(?:href|src)=\"([^\"]+)\"")


def _slug(heading: str) -> str:
    # GitHub's anchor rule: lower-case, drop punctuation except - and _, spaces to -.
    text = re.sub(r"[`*]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(page: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", page.read_text(), flags=re.S)
    return {_slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, flags=re.M)}


def _markdown_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return [ROOT / p for p in out]


def _resolve(page: Path, link: str) -> tuple[Path, str] | None:
    """The local file and anchor a link points at, or None if it is not ours."""
    own = _SELF.fullmatch(link)
    if own:
        rel = own.group("path") if own.group("path") is not None else own.group("raw")
        target = ROOT / rel if rel is not None else ROOT / "README.md"
        return target, own.group("anchor") or ""
    if re.match(r"[a-z]+:", link):
        return None
    path, _, frag = link.partition("#")
    return (page.parent / path) if path else page, f"#{frag}" if frag else ""


def test_link_resolution_covers_the_repository_front_page():
    # The front page is README.md: an anchor on it is checked like any other.
    # Missed until 1.1.3, so a broken "#compared-to-lego" passed the suite.
    readme = ROOT / "README.md"
    front = f"https://github.com/{_REPO}"
    assert _resolve(readme, f"{front}#compared-to-lego") == (readme, "#compared-to-lego")
    assert _resolve(readme, front) == (readme, "")
    assert _resolve(readme, f"{front}/blob/main/docs/README.md") == (
        ROOT / "docs/README.md",
        "",
    )
    assert _resolve(readme, f"{front}/issues") is None
    assert _resolve(readme, f"{front}/security/advisories/new") is None
    assert _resolve(readme, "https://example.com/x#y") is None


def test_every_link_and_anchor_resolves():
    broken = []
    for page in _markdown_files():
        text = re.sub(r"```.*?```", "", page.read_text(), flags=re.S)
        for m in _LINK.finditer(text):
            link = m.group(1) or m.group(2)
            resolved = _resolve(page, link)
            if resolved is None:
                continue  # another site, or a repository page that is no file
            target, anchor = resolved
            rel = page.relative_to(ROOT)
            if not target.exists():
                broken.append(f"{rel}: {link} (no such file)")
            elif anchor and target.suffix == ".md" and anchor[1:] not in _anchors(target):
                broken.append(f"{rel}: {link} (no such heading)")
    assert not broken, "broken links:\n  " + "\n  ".join(broken)


def test_every_doc_page_is_reachable_from_its_index():
    for folder in ("docs", "docs-tech"):
        index = (ROOT / folder / "README.md").read_text()
        for page in (ROOT / folder).glob("*.md"):
            if page.name != "README.md":
                assert f"({page.name})" in index, (
                    f"{folder}/README.md does not link {page.name}"
                )


def test_diagrams_say_the_same_in_svg_and_drawio_model():
    # A .drawio.svg holds the picture twice: the drawn SVG that GitHub and PyPI
    # show, and the draw.io model that editing opens. Edit one by hand and the
    # README shows something the source no longer says.
    import xml.etree.ElementTree as ET

    svg_ns = "{http://www.w3.org/2000/svg}"
    for path in (ROOT / "docs").rglob("*.drawio.svg"):
        root = ET.parse(path).getroot()
        drawn = {t.text for t in root.iter(svg_ns + "text")}
        model = {
            c.get("value") for c in ET.fromstring(root.get("content")).iter("mxCell")
        } - {None}
        assert drawn == model, (
            f"{path.name}: drawn vs draw.io model differ: {drawn ^ model}"
        )
