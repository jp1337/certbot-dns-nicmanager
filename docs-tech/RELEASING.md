# Releasing, CI and dependencies

## Cutting a release

1. Branch, bump `version` in `pyproject.toml`, move `[Unreleased]` in
   `CHANGELOG.md` to the new version with today's date, add the compare link.
2. Pull request; merge once CI is green.
3. Tag `main` and push the tag:
   ```bash
   git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z
   ```
4. `publish.yml` runs: tag must equal `v` + the `pyproject.toml` version (else it
   stops), tests, builds sdist + wheel, `twine check`, publishes via PyPI
   Trusted Publishing (environment `pypi`, no token in the repository).
5. GitHub release with the changelog section as notes:
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z — <summary>" \
     --notes "$(awk '/^## \[X.Y.Z\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md)"
   ```

6. AUR: in [`packaging/aur/`](../packaging/aur/PKGBUILD) set `pkgver`, reset
   `pkgrel=1`, put the new sdist's sha256 (PyPI shows it) into `PKGBUILD` and
   `.SRCINFO`, then push both to `ssh://aur@aur.archlinux.org/certbot-dns-nicmanager.git`.

Versioning: SemVer. A dependency floor raised to fix a bug is a patch release.

## CI (`.github/workflows/ci.yml`)

| Job | Runs |
| --- | --- |
| `test` | `pytest` on every Python version in the matrix, newest dependency versions |
| `lint` | `ruff check`, `ruff format --check`, `mypy` |

Triggers: push to `main`, pull requests, manual, and **weekly** (Monday 04:17
UTC). The weekly run exists because the runtime dependencies are open `>=`
floors: a breaking upstream release reaches users without any change here.
pyotp 2.12 did exactly that. GitHub disables scheduled workflows after 60 days
without repository activity; re-enable it under *Actions* if that happens.

`main` is protected by the ruleset "protect main": no deletion, no force push.

## Dependencies

- Runtime floors in `pyproject.toml` are the oldest versions known to work. To
  check them, run the suite against exactly those versions (certbot 2.0.0 needs
  the libraries of its time):
  ```bash
  uv venv --python 3.10 /tmp/floor
  VIRTUAL_ENV=/tmp/floor uv pip install --exclude-newer 2022-12-01 \
    --exclude-newer-package pyotp=2030-01-01 --exclude-newer-package requests=2030-01-01 \
    --exclude-newer-package requests-mock=2030-01-01 \
    'certbot==2.0.0' 'acme==2.0.0' 'requests==2.32.0' 'pyotp==2.12.1' \
    pytest pytest-cov requests-mock
  /tmp/floor/bin/python -m pytest --no-cov --deselect tests/test_docs_boundary.py
  ```
- **Renovate** ([`renovate.json`](../renovate.json)) raises the pull requests:
  GitHub Actions pinned to commit digests, pre-commit hooks, security fixes at
  any time. Actions and hook updates below major merge themselves once CI is
  green; runtime dependencies and majors wait for review. The Dependency
  Dashboard (an issue) can trigger a run immediately.
- Dependabot is off for updates; its security *alerts* stay on, Renovate reads
  them.
