# Dabih Schema Changelog

Dabih has two JSON formats that cross a tool boundary. This document records
their history and what to do when a format changes.

---

## Spec file — `dabih spec` output

Read by `dabih expand`, `dabih report` and `dabih verify`. The file carries a
`version` field; `dabih.core.spec_io.SPEC_VERSION` is the version this release
reads and writes.

### Version 1  *(Dabih 0.1.0 — current)*

| Field | Type | Description |
|---|---|---|
| `version` | string | Always `"1"` |
| `name` | string | Human-readable BinSpace name |
| `coverpoints` | array | `[{name, bins}]` — ordered list of coverpoints |
| `declarations` | array | Symmetry declarations: `type` (`instance` / `cyclic` / `pairwise`), `instance_indices` or `pairs`, `block_size`, `group`, `n_generators` |
| `orbit_count` | integer | Number of equivalence classes |
| `total_bins` | integer | Raw bin-space size |
| `compression_ratio` | number | `total_bins / orbit_count` |
| `method` | string | `"polya"` or `"burnside"` |
| `representatives` | array | One label-tuple per orbit (pre-computed so `expand` need not re-run the symbolic engine) |

**Migration:** A spec file whose `version` differs from the one the installed
release supports is rejected with
`Unsupported spec version ... Re-run 'dabih spec' to regenerate.` Spec files are
derived data — regenerate them from the RTL; do not edit them by hand.

---

## Result file — `CoverageResult` JSON

Read by `dabih expand` and `dabih report`; produced by hand, by a testbench, or
by the Questa / VCS adapters. This format is **not versioned** — it has had one
shape since Dabih 0.1.0.

| Field | Required | Description |
|---|---|---|
| `hits` | yes | `[{"bin": [label, ...], "count": n}]`; `count` defaults to 1. Only hit bins appear — absent means zero. |
| `run_id` | no | Label for this simulation run (used by provenance tracking) |
| `simulator` | no | Free text, e.g. `"questa"` or `"vcs"` |
| `covergroup` | no | Covergroup the hits came from (documentation only) |
| `timestamp` | no | ISO-8601 string |

---

## Changing a format

1. Bump `SPEC_VERSION` in `dabih/core/spec_io.py` for any change that older
   readers cannot handle.
2. Add a new section above describing the change and how to migrate.
3. Bump the release version (see [RELEASING.md](../RELEASING.md)).
