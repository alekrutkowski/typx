# Release guide

GitHub Actions is configured so that a version tag is the publication trigger.

## 1. Prepare the version

Update both:

- `pyproject.toml`;
- `src/typx/constants.py`.

Update `CHANGELOG.md` with the release date and noteworthy changes.

Check consistency:

```bash
python3 scripts/check_version.py
```

## 2. Run the release checks locally

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

## 3. Commit the release preparation

```bash
git add .
git commit -m "Prepare typx 0.3.2"
git push origin main
```

Wait for the normal CI workflow to pass.

## 4. Tag the exact commit

For version `0.3.2`:

```bash
git tag -a v0.3.2 -m "typx 0.3.2"
git push origin v0.3.2
```

The release workflow checks that `v0.3.2` exactly matches the package version `0.3.2`. A mismatched tag fails before publication.

## 5. What GitHub Actions publishes

A successful tagged build publishes these assets:

```text
typx-0.3.2.pyz
typx-0.3.2-source.zip
typx-0.3.2-bundle.zip
SHA256SUMS.txt
```

The GitHub Release notes are generated automatically from the repository history and the categories in `.github/release.yml`.

## Manual build workflow

The Release workflow also supports `workflow_dispatch`. A manual run performs tests and produces downloadable workflow artifacts but does not create a GitHub Release because there is no authoritative version tag.

## Action versions

The workflows intentionally use tagged major versions of official GitHub actions rather than branch names. Dependabot is configured to propose GitHub Actions updates.
