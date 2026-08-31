# Release guide

GitHub Actions publishes a rolling release automatically after every successful push to `main`.
No version tag or manual GitHub release command is required.

## Automatic publication

A push to `main` starts `.github/workflows/ci.yml`. After the complete CI test matrix and reproducible-build job succeed, CI calls `.github/workflows/release.yml` as a reusable workflow. The release workflow:

1. checks that `pyproject.toml` and `src/typx/constants.py` contain the same version;
2. rebuilds the deterministic release artifacts from the tested commit;
3. verifies the artifacts and their checksums;
4. rebuilds them again and checks reproducibility;
5. smoke-tests `dist/typx.pyz`;
6. confirms that the tested commit is still the head of `main`;
7. moves the lightweight `continuous` tag to that commit;
8. updates the GitHub Release named **Latest main build**, replacing its previous assets.

If a newer `main` commit arrives while an older run is finishing, the older run does not overwrite the rolling release.

The release is marked as the repository's latest release. The stable download filename is:

```text
typx.pyz
```

The versioned `.pyz`, source ZIP, bundle ZIP, and checksum manifest are published alongside it.

## Version metadata

The package version still lives in both:

- `pyproject.toml`;
- `src/typx/constants.py`.

Update these values when you intentionally change the software version. A version change is ordinary source metadata and is not a publication trigger. Every push to `main` is published regardless of whether the version changed.

Check version consistency locally with:

```bash
python3 scripts/check_version.py
```

## Local release checks

Before pushing, the same core checks can be run locally:

```bash
python3 -m compileall -q src tests scripts
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build_release.py
python3 scripts/verify_release.py
```

Build a second time and compare the checksum manifest:

```bash
cp dist/SHA256SUMS.txt /tmp/typx-sha-before.txt
python3 scripts/build_release.py
diff -u /tmp/typx-sha-before.txt dist/SHA256SUMS.txt
```

On Windows, compare the two files with your preferred file or hash comparison tool.

## Published assets

For package version `0.3.2`, for example, the rolling release contains:

```text
typx.pyz
typx-0.3.2.pyz
typx-0.3.2-source.zip
typx-0.3.2-bundle.zip
SHA256SUMS.txt
```

`typx.pyz` and the versioned `.pyz` contain identical bytes. The stable name exists so users do not have to know the package version to download the current build.

## GitHub token and action permissions

The workflow grants only `contents: write`, which is required to move the `continuous` tag and update the release. It uses GitHub's automatically provided workflow token; no personal access token and no locally installed GitHub CLI are required.

The workflow uses tagged major versions of its GitHub Actions dependencies. Dependabot is configured to propose GitHub Actions updates.
