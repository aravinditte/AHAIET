# Security

AHAIET is a local, single-user application: the backend binds to
loopback by default and there is no account system. This document is
the threat model for that deployment shape — what the code defends,
where, and what it deliberately does not claim.

## Assets

- Uploaded page images and everything derived from them (stored
  originals under the storage directory, OCR text, corrections,
  translations, history rows). For a scholar these can be unpublished
  research material, so they are treated as private content.
- The SQLite database (corpus, history, jobs, translation cache).
- The host machine the backend runs on (the backend executes local
  engine binaries, so code execution on the host is the worst case).

## Attacker inputs

Everything the HTTP API accepts is untrusted, including from a
"friendly" local network if the user rebinds the server:

1. Uploaded files (arbitrary bytes with a claimed image type).
2. JSON request bodies (text fields, ids, profile names).
3. Path parameters (upload ids, job ids, history ids).
4. HTTP headers (Origin, Content-Length, chunked bodies).

## Mitigations, mapped to code

| Threat | Mitigation | Where |
|---|---|---|
| Malformed/non-image upload, decompression bombs | Content is decoded and inspected with Pillow; the file extension is never trusted. Format allowlist (PNG/JPEG/TIFF/WEBP/BMP), byte cap, pixel cap (`Image.MAX_IMAGE_PIXELS`) | `backend/app/services/preprocessing/service.py` (`validate_and_decode`) |
| Oversized requests / memory exhaustion | App-level body ceiling (default: upload limit + 1 MiB) enforced by middleware before routing, including chunked bodies; 413 with the standard error envelope | `backend/app/core/security.py` (`BodySizeLimitMiddleware`), configured in `backend/app/core/config.py` (`AHAIET_REQUEST_MAX_BYTES`) |
| Request flooding of the expensive endpoints | Fixed-window per-client rate limits on `/api/uploads`, `/api/ocr`, `/api/translate`, `/api/process`; 429 with `Retry-After` and the standard error envelope | `backend/app/core/security.py` (`RateLimitMiddleware`), limits via `AHAIET_RATE_LIMIT_*_PER_MIN` |
| Clickjacking, MIME sniffing, referrer leakage, framing | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'` on every API response, including errors | `backend/app/core/security.py` (`SecurityHeadersMiddleware`) |
| Cross-origin abuse from arbitrary websites | CORS allows only the configured local frontend origins (default `http://localhost:3000`, `http://127.0.0.1:3000`); never a wildcard by default; extend only via `AHAIET_CORS_ORIGINS` | `backend/app/main.py`, `backend/app/core/config.py` |
| Path traversal via ids | Upload ids are server-generated SHA-256 hex; lookup validates the id shape (64 hex chars) before touching the filesystem | `backend/app/api/routes.py` (`_find_upload`) |
| SQL injection | All database access uses bound parameters | `backend/app/storage/db.py` and service modules |
| Command injection via engine invocation | Engine binaries (Tesseract, Kraken/ketos, Moses, Marian) are invoked with argument lists, never through a shell; user text reaches decoders via stdin/files inside the storage area, never as command-line arguments | `backend/app/services/ocr/`, `backend/app/services/translation/` adapters |
| Stale private data accumulating forever | Retention maintenance deletes uploads, history, jobs, and cache rows older than `AHAIET_RETENTION_DAYS` (see below) | `backend/app/maintenance.py` |
| History the user does not want kept | `AHAIET_HISTORY_ENABLED=false` makes history writes no-ops and `GET /api/history` return an explicit disabled state | `backend/app/api/routes.py`, `backend/app/core/config.py` |

## Retention and deletion

```powershell
cd backend
python -m app.maintenance --dry-run   # report counts only, delete nothing
python -m app.maintenance             # perform the sweep
```

The sweep deletes upload files and database rows (history, jobs,
translation cache) older than the retention window and reports counts
and reclaimed bytes as JSON metadata (never content). It can also run
once at backend startup with `AHAIET_RETENTION_SWEEP_ON_STARTUP=true`
(off by default, so startup stays predictable).

Secure delete: by default files are removed with a plain unlink.
Setting `AHAIET_SECURE_DELETE_OVERWRITE=true` overwrites each file
with zeros once before unlinking. Honest limits: **neither unlink nor
a single overwrite guarantees unrecoverability** — journaling and
copy-on-write filesystems, SSD wear-levelling, snapshots, and backups
can all retain copies. Treat the overwrite as best-effort hygiene, not
as a forensic guarantee.

## Logging policy

Runtime code logs metadata only — ids, sizes, durations, counts,
statuses. It must never log request text, OCR text, corrected text,
translations, or file contents. The audit behind this policy: the
backend package contains no content-bearing logging; the only `print`
calls in the package are in the setup-only corpus importer CLI
(`app/corpus/import_morphhb.py`), which prints counts and metadata
about public-domain corpus data. Two guardrails keep it that way:

- `python -m app.offline_check` (see OFFLINE_OPERATION.md) scans the
  package for outbound-call constructs; reviewers should apply the
  same scrutiny to new logging in review.
- The security tests (`backend/tests/test_security.py`) pin the
  headers/CORS/rate-limit/retention behaviour described above.

## Residual risks (accepted, stated plainly)

- **No authentication.** Anyone who can reach the backend port can use
  the API. The mitigation is deployment shape: bind to loopback (the
  default), do not expose the port, and do not rebind to a LAN address
  unless the network is trusted. Rate limits blunt, but do not stop, a
  determined local abuser.
- **Rate limiting is per-process, in-memory.** It resets on restart
  and does not coordinate across multiple backend processes. It is a
  guardrail for a local app, not a distributed defence.
- **The body ceiling buffers the request body in memory** up to the
  configured limit before rejecting it; the limit itself is the bound.
- **Local engine binaries are trusted code.** Tesseract, ketos, Moses,
  and Marian run with the user's privileges; provision them only from
  the documented sources (docs/OCR.md, docs/TRAINING.md).
- **Uploads are stored unencrypted** in the configured storage
  directory. Disk encryption is the operating system's job.
- **SQLite file permissions** follow the OS defaults of the data
  directory; restrict the directory if the machine is shared.

## Persistence settings: persist_results vs history_enabled (AHAIET-015)

Two independent switches:

| Setting | Controls | Off behaviour |
|---|---|---|
| `AHAIET_PERSIST_RESULTS` (default on) | Durability of jobs, job results, and the translation cache | Jobs are in-memory ephemeral with a TTL (`AHAIET_JOB_RESULT_TTL_S`); **no source or translation text is written to SQLite** (asserted by `test_persist_results_disabled` in `backend/tests/test_remediation.py`); the translation cache is disabled |
| `AHAIET_HISTORY_ENABLED` (default on) | The `/api/history` record of completed jobs | History writes are no-ops and `GET /api/history` returns an explicit disabled state |

Turning history off alone does NOT stop job persistence; turning
persistence off also disables history (there is nothing durable to
list). Uploads are always stored (they are the working input) and are
covered by retention below.

## Scheduled retention (AHAIET-016/017)

The startup sweep (`AHAIET_RETENTION_SWEEP_ON_STARTUP`) remains
available but is no longer the recommended mechanism: schedule the
sweep instead.

- Windows: `scripts\install-retention-task.ps1` registers a daily
  Task Scheduler task running `python -m app.maintenance`.
- Linux: a systemd timer or a cron line running the same module from
  `backend/` once a day.

Every sweep records a row in the `maintenance_runs` table; the latest
is exposed at `GET /api/capabilities` -> `retention.last_sweep`. A
startup sweep that fails is logged structurally and sets
`retention.degraded: true` in capabilities — it is never silently
swallowed, and it never blocks startup.

## Local-only posture and the access token (AHAIET-045)

The backend binds to loopback by default; keep it that way
(`AHAIET_BIND` / the uvicorn `--host` in the start scripts stays
`127.0.0.1`). An upload id is a content hash: it is a **locator, not
an authorization credential** — anyone who learns an id can fetch that
image in local mode. That is acceptable for a single-operator local
tool and nothing else. If the service is ever exposed beyond loopback,
set `AHAIET_ACCESS_TOKEN`: upload reads (`GET /api/uploads/{id}`) and
history (`GET /api/history`) then require the
`X-AHAIET-Access-Token` header. Since the re-review remediation
(NEW-12) the guard covers the full document/result matrix: uploads
read, process submission, job read/result/cancel, and history
read/delete (see docs/API.md). The browser UI keeps the token only
in sessionStorage — never in a build-time variable or a URL — and
sends it as a header on API calls; the image preview is fetched as a
Blob through an authenticated request because an <img> tag cannot
send headers (NEW-11). For real remote deployment, put the
service behind external authentication as well; the token is a
minimal local safeguard, not an auth system.

Error responses are sanitized (AHAIET-031): adapter and engine errors
never include absolute system paths or unbounded binary stderr — only
a bounded, path-stripped excerpt.
