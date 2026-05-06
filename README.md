# pyholman

Typed Python client for Holman's Customer Data API.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
![Typed (PEP 561)](https://img.shields.io/badge/typed-PEP%20561-blueviolet)

Pre-1.0. The public API is stable; endpoint coverage is still expanding.
Five of Holman's query endpoints are supported today, with additional
endpoints in active development.

## What pyholman does and why it exists

Holman's Customer Data API is the corporate-fleet data layer behind their
managed-fleet program — a REST surface exposing roughly a dozen query
endpoints across vehicles, maintenance, contacts, telematics, and
operational records. pyholman wraps the parts of that surface a typical
analytics pipeline actually has to deal with: typed Pydantic response
models for every endpoint, OAuth2 client-credentials authentication with
proactive token refresh, a retry-aware HTTP transport that honors server
`Retry-After` headers, atomic Parquet and CSV writers, and a declarative
YAML schema that drives both full-refresh and incremental pulls. Each
written file gets a JSON metadata sidecar recording the run mode, record
count, watermark timestamp, and filter hash, so subsequent runs can resume
from the right cursor without re-pulling history.

The package exists because every analytics project that touches Holman
data ends up reimplementing the same three pieces: an OAuth flow that
caches tokens, a retry layer that survives corporate proxies, and a
typed parsing layer that does not silently lose fields when the source
adds them. pyholman does that work once so downstream projects don't.
It deliberately does one thing — fetch verified, typed records and put
them on disk — and stops there. Cleaning, joining, modeling, and
downstream serving are the consumer's decisions; pyholman delivers the
raw data and stays out of the way.

## Why use it

- Typed Pydantic models for every response shape; full IDE autocomplete on every record returned.
- OAuth2 client-credentials flow with in-memory token caching and proactive refresh ahead of expiry.
- Retry-aware HTTP transport: honors server `Retry-After` on rate-limit responses, falls back to capped exponential backoff, retries 5xx, 429, and connection-level errors.
- Atomic Parquet and CSV writes via `atomicwrites`; a crash mid-write leaves the prior file intact.
- Incremental refresh built on per-resource metadata sidecars that record run mode, watermark, record count, and filter hash.
- Automatic deduplication of byte-identical records returned by the API.
- Programmatic single-endpoint pulls return a pandas DataFrame via `fetch` — no YAML, no disk I/O.
- Strict configuration: YAML or filter-field typos raise `pydantic.ValidationError` at config load, before any HTTP request.
- Engineered for corporate-network constraints: TLS-inspecting proxies (Zscaler and similar), flaky links, and restricted PyPI access.

## Quickstart

The primary entry point is `Orchestrator(config_path).run()`. Configuration
lives in YAML; the same file describes which endpoints to pull, where to
write them, and how incremental refresh should behave. The three layers
below build on each other — start at Layer 1 and add only the sections a
deployment actually needs.

Every example assumes the client secret is exported in the environment:

```bash
# bash / zsh
export HOLMAN_CLIENT_SECRET='your-client-secret-here'
```

```powershell
# PowerShell (Windows)
$env:HOLMAN_CLIENT_SECRET = 'your-client-secret-here'
```

pyholman refuses to load a config that carries `credentials.client_secret`
in the YAML; the secret is environment-only by design.

### Layer 1 — minimal

The smallest config that produces a working pull. `credentials.client_id`,
`fleet.lessee_codes`, and one `resources` entry. Every other section
defaults: API base URL is production, working directory becomes
`<cwd>/pyholman_data`, output is Snappy-compressed Parquet, the logger
stays at `WARNING`, retry uses five attempts with a sixty-second backoff
cap.

```yaml
# config.yaml
credentials:
  client_id: 'cust-api.org-XXXX.user-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

fleet:
  lessee_codes:
    - 'ABCD'

resources:
  - name: vehicles
```

```python
from pyholman import Orchestrator

Orchestrator(config_path='config.yaml').run()
```

After the run, data lands at `./pyholman_data/vehicles/vehicles.parquet`
alongside `./pyholman_data/vehicles/metadata.parquet.json`. The sidecar
filename is per-format (`metadata.parquet.json`, `metadata.csv.json`)
so a resource written under both formats keeps both sidecars beside
both data files without one clobbering the other.

### Layer 2 — production shape

Add the sections a scheduled job that pulls deltas would set explicitly.
`working_directory` puts data somewhere stable rather than wherever the
job happens to be invoked. `output` pins format and compression. `incremental`
defines how far back each pull reaches and the floor below which the
window will never slide. The `vehicles` resource is flipped to incremental
so subsequent runs only fetch records modified since the last watermark.

```yaml
credentials:
  client_id: 'cust-api.org-XXXX.user-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

fleet:
  organization_id: XXXX
  lessee_codes:
    - 'ABCD'

working_directory: '/var/data/pyholman'

output:
  format: parquet
  compression: snappy

incremental:
  lookback_days: 7
  earliest_date: 2024-01-01

resources:
  - name: vehicles
    incremental: true
```

On Windows, paths in YAML strings need either escaped backslashes
(`'C:\\Users\\you\\pyholman_data'`) or forward slashes
(`'C:/Users/you/pyholman_data'`); a single backslash is a YAML escape
character.

`organization_id` is optional but commonly required: Holman rejects queries
that send only child lessee codes without their parent, and pyholman merges
the org ID into the lessee-codes list at load time. `lookback_days`
defaults to 7; the refresh window anchors on the most recent record on
disk, not today's date, so a missed cron still catches every record on
the next successful run. `earliest_date` is a hard floor below which the
window never slides.

### Layer 3 — environment tuning

Layer on the knobs that corporate environments tend to need. `use_truststore`
routes TLS verification through the OS trust store, which is what makes
Zscaler and similar TLS-inspecting proxies work without disabling
verification. `retry` exposes the attempt count and backoff cap. `logger`
opts into INFO-level console output and a rotating-friendly log file.

```yaml
credentials:
  client_id: 'cust-api.org-XXXX.user-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

api:
  use_truststore: true

fleet:
  organization_id: XXXX
  lessee_codes:
    - 'ABCD'

working_directory: '/var/data/pyholman'

output:
  format: parquet
  compression: snappy

incremental:
  lookback_days: 7
  earliest_date: 2024-01-01

retry:
  max_attempts: 5
  backoff_max_seconds: 60.0

logger:
  console_level: INFO
  file_path: '/var/log/pyholman/pyholman.log'

resources:
  - name: vehicles
    incremental: true
```

Most deployments will not need all three blocks. Corporate environments
behind a TLS-inspecting proxy will need at least the truststore line; the
companion install command is `pip install 'pyholman[system-certs]'`.

For the full annotated reference — every key, every default, every
validation rule — see [`user_config.example.yaml`](./user_config.example.yaml).

## Endpoint coverage

Five endpoints are supported today. **Vehicles** returns the full vehicle
record (100+ fields covering identification, lease, telematics, location,
and assignment), with incremental refresh keyed on `lastChangeDate`.
**Maintenance purchase orders** returns line-grained records for closed
work orders — one row per PO line, joined back to a vehicle by
`holmanVehicleNumber`. **Contacts** returns the per-vehicle assigned
driver and contact details, also incremental-capable. **Odometer** and
**engine hours** return the latest reading per vehicle as snapshot-only
endpoints (no per-record watermark, full refresh every run).

Additional endpoints are in active development and will land as endpoint
modules over the coming releases.

For a per-field reference of every supported endpoint, see
[docs/endpoints.md](docs/endpoints.md).

## Programmatic use with `fetch`

`fetch` is the alternative entry point for callers that want a DataFrame
in memory rather than a file on disk. No YAML, no incremental, no filters
— a one-shot pull collected into a single pandas DataFrame and returned.

```python
import pandas as pd

from pyholman import fetch

dataframe: pd.DataFrame = fetch(
    endpoint='vehicles',
    client_id='cust-api.org-XXXX.user-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    client_secret='your-client-secret-here',
    lessee_codes=['ABCD'],
)
```

`endpoint` accepts any of the registered names (`vehicles`,
`maintenance_purchase_orders`, `contacts`, `odometer`, `engine_hours`).
The returned DataFrame's columns and dtypes are declared by the
endpoint's response model; an empty result set returns a zero-row
DataFrame with the same typed columns. `use_truststore=True` enables OS
trust-store verification for callers behind a TLS-inspecting proxy.

`fetch` does not configure logging — programmatic callers own their
logging policy — and does not write to disk. For scheduled jobs that
need either, use `Orchestrator`.

## Environment notes

**Corporate TLS-inspecting proxies.** Tools like Zscaler intercept
outbound TLS and re-encrypt traffic with a corporate Root CA that lives
in the Windows or macOS trust store but is unknown to the bundled
`certifi` roots Python ships with. Without a workaround, `httpx` raises
`SSLCertVerificationError` on every request. pyholman supports this case
through the `truststore` package: install with `pip install
'pyholman[system-certs]'` and set `api.use_truststore: true`. Verification
then runs against the OS-native trust store, which sees the corporate
root, and connections succeed without weakening TLS. Works on Windows,
macOS, and Linux.

**Flaky networks.** Connection errors, read timeouts, and 5xx responses
are retried up to `retry.max_attempts` times (default 5). Wait between
retries grows exponentially and is clamped to `retry.backoff_max_seconds`
(default 60). On HTTP 429, pyholman parses the `Retry-After` header — both
the delta-seconds form and the RFC 7231 HTTP-date form — and waits for
the server-supplied window plus a small buffer before retrying. The
retry exception types (`HolmanError`, `TransientHolmanError`,
`RateLimitError`) are public; catch the parent class to handle every
retry-exhausted failure uniformly.

## Incremental refresh and filter changes

Incremental resources stamp a metadata sidecar after every successful run.
The sidecar carries a hash of the filter configuration that produced the
on-disk data. When the orchestrator runs against a resource that already
has a sidecar, it compares the current filter hash against the stored
one before issuing any HTTP request.

If the hashes differ, the orchestrator refuses to proceed and raises a
`FilterHashMismatchError`. The error names the resource, the on-disk
data path, and the recovery action; the message is intended to be read
top-to-bottom and acted on without consulting source.

This is a deliberate design choice, not a limitation. The on-disk data
reflects the prior filter configuration; if the orchestrator silently
appended new rows fetched under a different filter, the resulting
dataset would mix two filter regimes and be effectively impossible to
reason about downstream — joins, deduplications, and incremental
windows would all behave inconsistently across the boundary. Refusing
the run forces the user to make the choice explicit.

**Recovery.** Two options:

- **Revert the filter change.** Restore the prior `filters:` block to
  match what produced the existing on-disk state. The next run resumes
  steady-state incremental.
- **Force a fresh bootstrap.** Delete or rename the resource directory
  (the per-resource folder under `working_directory` containing the
  data file and the metadata sidecar). The next run, finding no prior
  metadata, performs a bootstrap pull under the new filter
  configuration.

Renaming preserves the prior dataset for comparison or rollback;
deletion is the simpler choice if the prior data is no longer wanted.
Either way, the resource starts cleanly under the new filter regime
with no mixing of the two.

This applies to any change in the `filters:` block, including
`last_change_date`, `status_codes`, and any future filter field. The
hash covers the canonical form of the entire filter model — a tuple
reorder or a single-field tweak both invalidate the prior state.

## Design choices

pyholman is query-only — there are no submit, create, update, or delete
operations against Holman, and adding them is out of scope for this
project. The package is scoped to Holman's Customer Data API specifically
rather than offering a generic fleet-data abstraction; mapping pyholman
onto a different vendor's API is not supported. Pagination is request /
response only — no streaming, no webhooks, no long-poll. Each endpoint
walks pages serially until the server signals the last page or returns
an empty envelope. The implementation is synchronous and single-threaded:
a single `Orchestrator.run()` call iterates resources sequentially, and
the `TokenManager` is not safe to share across threads.

A narrow surface is what makes the strong typing, retry, and on-disk
guarantees easy to reason about. The synchronous design is the current
best fit because no measurement has shown it to be a bottleneck; if and
when testing shows otherwise, an async path is on the table. The
query-only and single-vendor scope are durable choices.

## Installation

Pre-PyPI; install from GitHub.

```bash
pip install 'git+https://github.com/andrewjordan3/pyholman.git'
```

For corporate environments behind a TLS-inspecting proxy, add the
`system-certs` extra:

```bash
pip install 'git+https://github.com/andrewjordan3/pyholman.git#egg=pyholman[system-certs]'
```

Python 3.12 or newer is required. `uv` is the recommended environment
manager for development (`uv pip install ...` works with both commands
above), but any pip-compatible installer is fine.

## Contributing

pyholman is in active development. Issues and pull requests are welcome.
For substantial changes — new endpoints, new config sections, anything
touching the public surface — open an issue first to discuss the shape
of the change before writing the patch.

## License

Licensed under the Apache License 2.0. See [LICENSE](./LICENSE) for the full text and [NOTICE](./NOTICE) for attribution.
