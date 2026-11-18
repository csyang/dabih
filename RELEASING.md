# Dabih — Release Process

This document describes the full process for building and publishing a Dabih release to the shared NFS drive.

---

## Who does releases

Any engineer with:
- A working Python ≥ 3.11 installation
- The Dabih source tree on their local machine
- The NFS share mounted (for publishing)

Releases are built locally and copied to the NFS share. Colleagues install directly from the share — no accounts are required to fetch the release files.

---

## One-time setup

### 1. Install dependencies

```bash
cd dabih
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This installs Dabih in editable mode together with `pytest` and `build`.

### 2. Configure your NFS path

Copy the example environment file and set your NFS mount point:

```bash
cp .release.env.example .release.env
```

Edit `.release.env`:

```bash
# Set this to the path where the NFS share is mounted on your machine
NFS_RELEASE_PATH=/mnt/nfs/releases/dabih
```

The NFS path will differ by machine depending on how your share is mounted. Ask a colleague if you are unsure of the mount point. Common patterns:

| OS | Typical pattern |
|---|---|
| Linux | `/mnt/nfs/releases/dabih` or `/net/server/releases/dabih` |
| macOS | `/Volumes/Engineering/releases/dabih` |

`.release.env` is only read when publishing. `--dry-run` works without it.

### 3. Verify your setup with a dry run

```bash
./release.sh --dry-run
```

This runs the tests and builds every release file into `dist/` but copies nothing to the NFS share. Use this to confirm everything works before your first real release.

---

## Bumping the version

Before publishing a new release, update the version in `pyproject.toml`:

```toml
[project]
version = "0.1.1"
```

Choose the number as follows:

| Change | Bump | Example |
|---|---|---|
| Bug fixes | patch | 0.1.0 → 0.1.1 |
| New features, backward-compatible spec/result JSON | minor | 0.1.0 → 0.2.0 |
| Breaking change to the spec or result JSON format | major | 0.1.0 → 1.0.0 |

If the spec JSON `version` field changes, also add an entry to [docs/schema-changelog.md](docs/schema-changelog.md).

The release script reads the version from `pyproject.toml` — it is the single source of truth. The source archive name is derived from it (`0.1.0` → `dabih-v0_1_0-source.zip`).

---

## Building and publishing a release

```bash
./release.sh
```

The script will:

1. Check that the NFS share is reachable
2. Run the pytest suite
3. Build the wheel and sdist (`python -m build`)
4. Build the source archive `dabih-v<version>-source.zip`
5. Prompt you to confirm before copying anything
6. Copy the three files to `$NFS_RELEASE_PATH/<version>/`
7. Write a `release.json` manifest in the versioned directory
8. Update `latest.json` at the root of the release share

### Skipping steps

```bash
./release.sh --skip-tests    # do not run pytest (not recommended for a real release)
./release.sh --skip-wheel    # source zip only; no wheel or sdist
```

### The source archive layout

`dabih-v0_1_0-source.zip` always unpacks to a single `dabih/` folder (the version lives in the file name, not the folder name). Caches, `dist/`, `build/`, `*.egg-info/` and `.release.env` are never included. The layout is documented in the [README](README.md#project-structure).

---

## NFS share structure

After publishing, the NFS share looks like this:

```
$NFS_RELEASE_PATH/
├── latest.json                          ← always points to the newest version
├── 0.1.0/
│   ├── release.json                     ← metadata for this release
│   ├── dabih-v0_1_0-source.zip          ← full source: code, tests, docs, examples
│   ├── dabih-0.1.0-py3-none-any.whl     ← installable wheel
│   └── dabih-0.1.0.tar.gz               ← sdist
├── 0.1.1/
│   ├── release.json
│   └── ...
```

Previous versions are kept on the share indefinitely. Do not delete old versions without checking with colleagues who may be on an older install.

---

## What colleagues do to install

Point colleagues at the NFS share. They:

1. Navigate to `$NFS_RELEASE_PATH/` on the share
2. Open the folder for the latest version (or check `latest.json`)
3. Either:
   - **Install the wheel** (CLI + library only):
     ```bash
     pip install /path/to/dabih-0.1.0-py3-none-any.whl
     ```
   - **Or unpack the source archive** (code, tests, docs, examples):
     ```bash
     unzip dabih-v0_1_0-source.zip
     cd dabih
     pip install -e ".[dev]"
     pytest
     ```
4. Check the install with `dabih --help`

Dabih depends on `pyslang`. `pip` fetches it from whatever package index the machine is configured to use. On a machine with no index access, make a `pyslang` wheel available first (for example from an internal mirror, or with `pip download pyslang -d wheelhouse/` on a connected machine followed by `pip install --no-index --find-links wheelhouse/ ...`).

---

## Troubleshooting

### `Cannot reach NFS share`

The NFS share is not mounted. Mount it before running the release script:

```bash
# Linux example
sudo mount -t nfs server:/exports/releases /mnt/nfs/releases

# macOS example — usually auto-mounted via Finder → Go → Connect to Server
open "nfs://server/releases"
```

### `The 'build' package is not installed`

Install the dev extras:

```bash
pip install -e ".[dev]"
```

### `No release files found`

The build ran but produced unexpected output. Check `dist/` manually:

```bash
ls -lh dist/
```

### Test failures

Run the suite in isolation to see the full output:

```bash
pytest -q
```

### `permission denied` on NFS copy

Your user account does not have write permission to the NFS share. Ask your system administrator to grant write access to the `releases/dabih` directory.

---

## Keeping old releases

The release script never deletes old versions. The NFS share will accumulate a directory per version. A rough retention policy suggestion:

- Keep all releases from the current minor version
- Keep the last release from each previous minor version
- Archive (compress and keep) anything older than 6 months

There is no automated cleanup — this is a manual housekeeping task.

---

## Making a release from scratch (checklist)

```
□ Ensure all changes are working (pytest passes)
□ Update REQUIREMENTS.md — move In Progress items to Accomplished
□ Update the test count in README.md and web/landing.html if it changed
□ Bump version in pyproject.toml
□ Confirm NFS share is mounted
□ ./release.sh --dry-run    (confirm no errors)
□ ./release.sh              (confirm, publish)
□ Notify colleagues of the new version and NFS path
```
