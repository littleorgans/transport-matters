# Release

Transport Matters releases are tag driven. Push an annotated `vX.Y.Z` tag and
`.github/workflows/release.yml` builds the web bundle, embeds it in the Python
wheel, publishes `transport-matters` to PyPI through trusted publishing, and
creates a GitHub Release with the wheel, sdist, checksums, and `install.sh`.

## Preconditions

- `main` is green in CI.
- PyPI trusted publishing is configured for project `transport-matters`,
  owner `littleorgans`, repo `transport-matters`, workflow `release.yml`, and
  environment `pypi`.
- The release tag is a semantic version in `vX.Y.Z` form.

## Cut a Release

From a clean `main` checkout:

```bash
just release 0.2.2
```

For a dry run:

```bash
just release --dry-run 0.2.2
```

The script validates the branch, verifies local `main` matches `origin/main`,
rejects duplicate tags, prints the commits since the previous release, creates
the annotated tag, and pushes it.

## Release Checks

The release workflow verifies:

- Frontend lint, typecheck, tests, and production build.
- Backend ruff, mypy, pytest coverage, wheel build, and sdist build.
- Clean venv install of `dist/transport_matters-*.whl`.
- Public CLI smoke for `transport-matters --version`, `version`, `paths`,
  `--help`, `claude --help`, and `doctor --help`.
- Embedded web bundle at `transport_matters/www/index.html`.
- GitHub Release checksums for `transport_matters-*` artifacts.

## Desktop Artifacts

Phase 2 verifies the Electron desktop package smoke locally, but it does not
ship signed or notarized desktop artifacts without human direction.

## Installer

The release attaches `install.sh`. It installs the PyPI package
`transport-matters`, verifies the `transport-matters` command, and supports
these product owned environment variables:

- `TRANSPORT_MATTERS_INSTALL_VERSION`
- `TRANSPORT_MATTERS_SKIP_UV_INSTALL`
