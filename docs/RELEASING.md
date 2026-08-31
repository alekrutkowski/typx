# Release guide

GitHub Actions publishes a rolling release automatically after every successful push to `main`.
No version tag or manual GitHub release command is required.

## Automatic publication

A push to `main` starts `.github/workflows/ci.yml`. After the complete CI test matrix and reproducible-build job succeed, CI calls `.github/workflows/release.yml` as a reusable workflow. The release workflow:

1. checks that `pyproject.toml` and `src/typx/constants.py` contain the same version;
2. rebuilds `dist/typx.pyz` and `dist/SHA256SUMS.txt` from the tested commit;
3. verifies the executable and its checksum;
4. rebuilds them again and checks reproducibility;
5. smoke-tests `dist/typx.pyz`;
6. confirms that the tested commit is still the head of `main`;
7. moves the lightweight `continuous` tag to that commit;
8. removes obsolete assets left by older versions of the rolling-release workflow;
9. updates the GitHub Release named **Latest main build**, replacing the current assets.

If a newer `main` commit arrives while an older run is finishing, the older run does not overwrite the rolling release.

The release is marked as the repository's latest release and contains only:

```text
typx.pyz
SHA256SUMS.txt
```

`typx.pyz` is deliberately not versioned in its filename. The `continuous` Release always represents the latest successful `main` build, so a stable filename gives users a permanent download target.

## Version metadata

The package version still lives in both:

- `pyproject.toml`;
- `src/typx/constants.py`.

Update these values when you intentionally change the software version. A version change is ordinary source metadata and is not a publication trigger. Every successful push to `main` is published regardless of whether the version changed.

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

The rolling Release contains exactly:

```text
typx.pyz
SHA256SUMS.txt
```

The checksum file contains one line for `typx.pyz`. The release workflow also removes legacy versioned `.pyz`, source ZIP, and bundle ZIP assets from the existing rolling Release on its next successful run.

## GitHub token and action permissions

The workflow grants only `contents: write`, which is required to move the `continuous` tag, remove obsolete release assets, and update the release. It uses GitHub's automatically provided workflow token; no personal access token and no locally installed GitHub CLI are required.

The workflow uses tagged major versions of its GitHub Actions dependencies. Dependabot is configured to propose GitHub Actions updates.
