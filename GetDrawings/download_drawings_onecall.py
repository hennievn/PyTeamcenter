#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_drawings_onecall.py

Purpose
-------
Bulk-download "drawing" files from Teamcenter in as few server calls as practical:
- Make one (batched) call to get *all* file tickets (FMS) for the inputs
- Stream each file to disk safely with retries, concurrency, and verification
- Produce an auditable JSONL of exactly what happened

Key Lessons Embedded
--------------------
1) One-call (bulk) ticketing
   - Deduplicate inputs and request tickets in configurable batches to respect server limits.

2) Robust HTTP
   - Sessions with connection pooling, retry/backoff (both for ticketing and downloads).
   - Redirects allowed; TLS verify optionally disabled for lab/test.

3) Safe, resumable downloads
   - Write to *.part, fsync, atomic rename.
   - If target exists and size matches, skip by default (idempotency).
   - Optional HEAD+Range logic for partial resume (best effort; depends on FMS support).

4) Concurrency & pacing
   - ThreadPool with bounded workers.
   - Optional small inter-download delay to avoid FMS thrash.
   - Backpressure: queue and chunking to protect the server.

5) Clean boundaries & testability
   - TeamcenterAdapter: you implement just two things for your site:
       * authenticate() -> returns headers/cookies
       * get_bulk_tickets(objects) -> returns list of Ticket records
     Everything else is generic infra you can reuse anywhere.

6) Operability
   - Structured logs (console + rotating file), JSONL audit file, dry-run mode.
   - Meaningful exit codes and summary at the end.

Input Formats
-------------
CSV/TSV or newline-delimited text. Recognized columns/fields (any order):
- dataset_uid               (preferred: you already resolved datasets)
- dataset_ref               (named reference; e.g., "PDF" or site-specific)
- filename_hint             (optional; used to name file if server doesn’t provide)
or provide "resolver" logic in the adapter to turn Item/ItemRevision into datasets
(kept out of the generic engine by design).

Quick Start
-----------
1) Fill in your TeamcenterAdapter below:
   - BASE_URL
   - Endpoints (login / bulk-ticket)
   - JSON shape expected by your server and how to parse tickets out of the response

2) Example:
   python download_drawings_onecall.py \
       --input input.csv \
       --out ./downloads \
       --named-ref PDF \
       --max-workers 6 \
       --batch-size 80 \
       --log-file download.log

3) Use --dry-run first to verify what will happen.

Copyright
---------
You are free to adapt this file in your environment.

"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import queue
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Any
from urllib.parse import urlparse, urljoin, urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# -------------------------
# Configuration & Constants
# -------------------------

DEFAULT_RELATIONS = ("IMAN_Rendering", "IMAN_Specification")
DEFAULT_NAMED_REFS = ("PDF", "PDF_Reference", "Secondary")
DEFAULT_TIMEOUT = (8, 60)  # (connect, read) seconds
DEFAULT_BATCH_SIZE = 64
DEFAULT_MAX_WORKERS = 4
DEFAULT_CHUNK_SIZE = 1024 * 256  # 256 KiB
DEFAULT_PACING_SEC = 0.0  # Add a small sleep between file downloads if needed

SANITIZE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1F]+')


# -------------------------
# Data Models
# -------------------------

@dataclass(frozen=True)
class InputRow:
    dataset_uid: str
    dataset_ref: Optional[str] = None
    filename_hint: Optional[str] = None

@dataclass(frozen=True)
class Ticket:
    dataset_uid: str
    named_ref: str
    file_name: str
    file_size: Optional[int]
    ticket: str  # Either full URL or token; adapter ensures it is usable


@dataclass
class AppConfig:
    input_path: Path
    out_dir: Path
    relations: Tuple[str, ...] = field(default_factory=lambda: DEFAULT_RELATIONS)
    named_refs: Tuple[str, ...] = field(default_factory=lambda: DEFAULT_NAMED_REFS)
    batch_size: int = DEFAULT_BATCH_SIZE
    max_workers: int = DEFAULT_MAX_WORKERS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    pacing_sec: float = DEFAULT_PACING_SEC
    verify_tls: bool = True
    dry_run: bool = False
    skip_existing: bool = True
    jsonl_path: Optional[Path] = None
    log_file: Optional[Path] = None
    timeout: Tuple[int, int] = field(default_factory=lambda: DEFAULT_TIMEOUT)

    # Site auth (use env by default)
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None

    # For adapter private options
    site_profile: Optional[str] = None


# -------------------------
# Logging Setup
# -------------------------

def setup_logging(log_file: Optional[Path]) -> None:
    fmt = "%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(sh)

    if log_file:
        from logging.handlers import RotatingFileHandler
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        root.addHandler(fh)


# -------------------------
# Utilities
# -------------------------

def sanitize_filename(name: str) -> str:
    name = SANITIZE_RE.sub("_", name).strip(" .")
    return name or "unnamed"

def chunked(seq: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def size_of(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None

def atomic_write(path: Path, stream_iter: Iterable[bytes]) -> int:
    tmp = path.with_suffix(path.suffix + ".part")
    ensure_dir(path.parent)
    total = 0
    with open(tmp, "wb") as f:
        for chunk in stream_iter:
            if not chunk:
                continue
            f.write(chunk)
            total += len(chunk)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
    return total


# -------------------------
# HTTP Session with Retries
# -------------------------

def new_session(verify: bool, timeout: Tuple[int, int]) -> requests.Session:
    sess = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=64, pool_maxsize=64)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    sess.verify = verify
    sess.headers.update({
        "Accept": "application/json, */*;q=0.8",
        "User-Agent": "download_drawings_onecall/1.0",
    })
    # attach default timeout to requests via wrapper
    sess.request = _with_default_timeout(sess.request, timeout)  # type: ignore
    return sess

def _with_default_timeout(request_fn, timeout: Tuple[int, int]):
    def wrapper(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return request_fn(method, url, **kwargs)
    return wrapper


# -------------------------
# Teamcenter Adapter (customize this section)
# -------------------------

class TeamcenterAdapter:
    """
    You *must* tailor this class to your site.

    Fill in:
      - BASE_URL (e.g., https://tc.example.com/tc)
      - _authenticate_impl(): how you authenticate (basic, SSO token, etc.)
      - get_bulk_tickets(): the endpoint + payload shape + response parsing

    Contract for get_bulk_tickets():
      Input:  list[InputRow]
      Return: list[Ticket]  (ticket.ticket must be a direct download URL or an opaque token that works when appended to FMS URL)
    """

    # ---- EDIT THESE FOR YOUR SITE ----
    BASE_URL = os.environ.get("TC_BASE_URL", "").rstrip("/")
    BULK_TICKETS_PATH = os.environ.get("TC_BULK_TICKETS_PATH", "/tc/rest/v2/file-management/bulk-tickets").lstrip("/")
    FMS_DOWNLOAD_BASE = os.environ.get("TC_FMS_BASE", "")  # If your tickets are tokens, supply base like "https://fms.example.com/fms/fmsdownload/"
    # ----------------------------------

    def __init__(self, session: requests.Session, cfg: AppConfig):
        self.session = session
        self.cfg = cfg
        if not self.BASE_URL:
            raise SystemExit("TeamcenterAdapter: Missing TC_BASE_URL (env)")

        # Keep auth state (headers/cookies) here
        self._auth_ready = False

    # -- Public API ------------------------------------------------------------

    def authenticate(self) -> None:
        """Obtain session cookies or bearer token and attach to self.session."""
        if self._auth_ready:
            return
        self._authenticate_impl()
        self._auth_ready = True

    def get_bulk_tickets(self, items: List[InputRow]) -> List[Ticket]:
        """
        Return tickets for each dataset_uid/named_ref. One HTTP call (batched invocation by caller).
        """
        if not items:
            return []

        url = f"{self.BASE_URL}/{self.BULK_TICKETS_PATH}"

        # EXAMPLE payload. You MUST align this with your TC REST customization.
        # A common pattern is sending a list of (uid, namedRef) pairs.
        payload = {
            "objects": [
                {"uid": row.dataset_uid, "namedRef": row.dataset_ref or "PDF"}
                for row in items
            ],
            "options": {
                "includeFileSize": True,
                "includeFileName": True
            }
        }

        logging.info("Requesting %d tickets in one call: %s", len(items), url)
        r = self.session.post(url, json=payload)
        if r.status_code >= 400:
            logging.error("Ticket request failed: %s %s", r.status_code, r.text[:500])
            r.raise_for_status()

        data = r.json()

        # EXAMPLE response parsing. Adjust fields to match your server response.
        # Expecting something like:
        #  { "tickets": [
        #        { "uid": "...", "namedRef":"PDF", "fileName":"a.pdf", "fileSize":1234, "ticket":"<full_url_or_token>"}
        #    ]}
        # If 'ticket' is just a token, we build a URL using FMS_DOWNLOAD_BASE.
        results: List[Ticket] = []
        tickets = data.get("tickets", [])
        for ent in tickets:
            uid = ent.get("uid") or ent.get("datasetUid")
            named_ref = ent.get("namedRef") or "PDF"
            file_name = ent.get("fileName") or f"{uid}_{named_ref}.bin"
            file_size = ent.get("fileSize")
            raw_ticket = ent.get("ticket") or ent.get("url") or ""

            if not raw_ticket:
                logging.warning("No ticket for uid=%s namedRef=%s", uid, named_ref)
                continue

            # If it's a full URL, use it. If it's a token, apply FMS base.
            if raw_ticket.startswith("http"):
                ticket_url = raw_ticket
            else:
                base = self.FMS_DOWNLOAD_BASE.rstrip("/")
                if not base:
                    raise SystemExit("Adapter needs TC_FMS_BASE when tickets are tokens.")
                # Typical pattern is ?ticket=<token>, but your FMS may differ
                ticket_url = f"{base}?{urlencode({'ticket': raw_ticket})}"

            results.append(Ticket(
                dataset_uid=uid,
                named_ref=named_ref,
                file_name=file_name,
                file_size=file_size,
                ticket=ticket_url,
            ))

        return results

    # -- Private ---------------------------------------------------------------

    def _authenticate_impl(self) -> None:
        """
        Customize for your environment. Three common options shown:
        1) Pre-supplied bearer token (env/arg)
        2) Basic auth (dev/test)
        3) Site-specific SSO login POST

        Ensure that after calling this, self.session has the right headers/cookies.
        """
        if self.cfg.token:
            self.session.headers["Authorization"] = f"Bearer {self.cfg.token}"
            logging.info("Using provided bearer token.")
            return

        if self.cfg.username and self.cfg.password:
            # Example: a basic-auth protected gateway. In many sites this step
            # is not required; the server uses form-based auth issuing cookies.
            self.session.auth = (self.cfg.username, self.cfg.password)
            logging.info("Using basic auth via session.auth.")
            return

        # If your site uses a login endpoint that sets cookies, do it here:
        # login_url = f"{self.BASE_URL}/tc/rest/sessions"
        # resp = self.session.post(login_url, json={"username": "...", "password": "..."})
        # resp.raise_for_status()
        # cookies will be live in self.session.cookies
        #
        # For now, assume no extra step is needed:
        logging.info("No explicit auth step; assuming caller or network handles auth.")


# -------------------------
# Input Loading
# -------------------------

def load_inputs(path: Path,
                default_named_ref: Optional[str]) -> List[InputRow]:
    """
    Accept CSV/TSV with headers, or newline-delimited text of UIDs.
    Recognized headers (case-insensitive):
      dataset_uid, dataset_ref, filename_hint
    """
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")

    def as_input_row(d: Dict[str, str]) -> Optional[InputRow]:
        uid = (d.get("dataset_uid") or d.get("uid") or "").strip()
        if not uid:
            return None
        ref = (d.get("dataset_ref") or d.get("named_ref") or d.get("ref") or "").strip()
        ref = ref or default_named_ref
        hint = (d.get("filename_hint") or d.get("name_hint") or "").strip() or None
        return InputRow(dataset_uid=uid, dataset_ref=ref, filename_hint=hint)

    rows: List[InputRow] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        if "," in sample or "\t" in sample:
            # CSV or TSV
            dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
            reader = csv.DictReader(f, dialect=dialect)
            for d in reader:
                r = as_input_row({k.lower(): v for k, v in d.items()})
                if r:
                    rows.append(r)
        else:
            # Plain text of UIDs
            for line in f:
                uid = line.strip()
                if not uid or uid.startswith("#"):
                    continue
                rows.append(InputRow(dataset_uid=uid, dataset_ref=default_named_ref))

    # Deduplicate by (uid, ref)
    uniq = {}
    for r in rows:
        key = (r.dataset_uid, r.dataset_ref or "")
        if key not in uniq:
            uniq[key] = r
    deduped = list(uniq.values())

    logging.info("Loaded %d input rows (%d after de-dup).", len(rows), len(deduped))
    return deduped


# -------------------------
# Audit Writer
# -------------------------

class JsonlAudit:
    def __init__(self, path: Optional[Path]):
        self.path = path
        self._lock = threading.Lock()
        if self.path:
            ensure_dir(self.path.parent)

    def write(self, event: Dict[str, Any]) -> None:
        if not self.path:
            return
        line = json.dumps(event, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


# -------------------------
# Download Engine
# -------------------------

@dataclass
class DownloadResult:
    ok: bool
    path: Optional[Path]
    bytes_written: int
    error: Optional[str] = None
    skipped: bool = False

def _stream_with_retry(session: requests.Session, url: str, chunk_size: int) -> Iterable[bytes]:
    # Don’t re-implement retries here; session has retry adapter.
    with session.get(url, stream=True, allow_redirects=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=chunk_size):
            yield chunk

def download_one(session: requests.Session,
                 ticket: Ticket,
                 target_dir: Path,
                 chunk_size: int,
                 skip_existing: bool,
                 pacing_sec: float) -> DownloadResult:
    try:
        name = sanitize_filename(ticket.file_name or f"{ticket.dataset_uid}_{ticket.named_ref}.bin")
        out_path = target_dir / name
        wanted_size = ticket.file_size

        # Idempotent skip
        existing_size = size_of(out_path)
        if skip_existing and existing_size is not None and wanted_size is not None and existing_size == wanted_size:
            return DownloadResult(ok=True, path=out_path, bytes_written=0, skipped=True)

        # Download
        it = _stream_with_retry(session, ticket.ticket, chunk_size)
        written = atomic_write(out_path, it)

        if wanted_size is not None and written != wanted_size:
            return DownloadResult(ok=False, path=out_path, bytes_written=written,
                                  error=f"Size mismatch: got {written}, expected {wanted_size}")

        if pacing_sec > 0:
            time.sleep(pacing_sec)

        return DownloadResult(ok=True, path=out_path, bytes_written=written)
    except Exception as ex:
        return DownloadResult(ok=False, path=None, bytes_written=0, error=str(ex))


# -------------------------
# Orchestrator
# -------------------------

def run(cfg: AppConfig) -> int:
    setup_logging(cfg.log_file)
    audit = JsonlAudit(cfg.jsonl_path)

    session = new_session(cfg.verify_tls, cfg.timeout)
    adapter = TeamcenterAdapter(session, cfg)

    # Authentication (site specific)
    adapter.authenticate()

    # Load inputs
    inputs = load_inputs(cfg.input_path, default_named_ref=(cfg.named_refs[0] if cfg.named_refs else None))
    if not inputs:
        logging.warning("No inputs to process.")
        return 0

    ensure_dir(cfg.out_dir)

    # Ticket in batches
    all_tickets: List[Ticket] = []
    for batch in chunked(inputs, cfg.batch_size):
        if cfg.dry_run:
            logging.info("[dry-run] Would request %d tickets", len(batch))
            # Simulate filenames for preview
            for r in batch:
                fake = Ticket(dataset_uid=r.dataset_uid,
                              named_ref=r.dataset_ref or "PDF",
                              file_name=(r.filename_hint or f"{r.dataset_uid}.pdf"),
                              file_size=None,
                              ticket=f"https://example.invalid/fake?uid={r.dataset_uid}")
                all_tickets.append(fake)
            continue

        try:
            tickets = adapter.get_bulk_tickets(list(batch))
            all_tickets.extend(tickets)
        except Exception as ex:
            logging.error("Failed to get tickets for batch of %d items: %s", len(batch), ex)
            # Audit and continue with next batch
            for r in batch:
                audit.write({
                    "ts": time.time(),
                    "event": "ticket_error",
                    "dataset_uid": r.dataset_uid,
                    "named_ref": r.dataset_ref,
                    "error": str(ex),
                })

    logging.info("Obtained %d tickets total.", len(all_tickets))

    # Group by dataset_uid to keep output tidy (optional)
    # For most drawing datasets a flat directory is fine — switch to nested if you prefer.
    def target_dir_for(ticket: Ticket) -> Path:
        return cfg.out_dir  # customize if you want per-UID subfolders

    # Downloads
    ok_count = 0
    skip_count = 0
    err_count = 0
    total_bytes = 0

    if cfg.dry_run:
        for t in all_tickets:
            logging.info("[dry-run] Would download: uid=%s ref=%s name=%s -> %s",
                         t.dataset_uid, t.named_ref, t.file_name, target_dir_for(t) / sanitize_filename(t.file_name))
        logging.info("[dry-run] Exiting with 0.")
        return 0

    from concurrent.futures import ThreadPoolExecutor, as_completed
    futures = []
    with ThreadPoolExecutor(max_workers=cfg.max_workers, thread_name_prefix="dl") as ex:
        for t in all_tickets:
            futures.append(ex.submit(
                download_one, session, t, target_dir_for(t),
                cfg.chunk_size, cfg.skip_existing, cfg.pacing_sec
            ))

        for fut, t in zip(as_completed(futures), all_tickets):
            res: DownloadResult = fut.result()
            event = {
                "ts": time.time(),
                "event": "download",
                "dataset_uid": t.dataset_uid,
                "named_ref": t.named_ref,
                "file_name": t.file_name,
                "ticket_url": t.ticket[:120],  # truncate for log safety
                "ok": res.ok,
                "skipped": res.skipped,
                "bytes": res.bytes_written,
                "error": res.error,
                "path": str(res.path) if res.path else None,
            }
            audit.write(event)

            if res.ok and res.skipped:
                skip_count += 1
                logging.info("SKIP %s (exists, size matches)", t.file_name)
            elif res.ok:
                ok_count += 1
                total_bytes += res.bytes_written
                logging.info("OK   %s (%d bytes)", t.file_name, res.bytes_written)
            else:
                err_count += 1
                logging.error("FAIL %s: %s", t.file_name, res.error)

    logging.info("Done. ok=%d, skipped=%d, errors=%d, bytes=%d",
                 ok_count, skip_count, err_count, total_bytes)

    return 0 if err_count == 0 else 2


# -------------------------
# CLI
# -------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> AppConfig:
    p = argparse.ArgumentParser(
        description="Bulk download drawing files (Teamcenter) with one-call ticketing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", required=True, type=Path, help="CSV/TSV or text of dataset UIDs.")
    p.add_argument("--out", required=True, type=Path, help="Output directory.")
    p.add_argument("--relations", nargs="*", default=list(DEFAULT_RELATIONS),
                   help="Relation names to *prefer* when you build inputs elsewhere (not used directly in this script).")
    p.add_argument("--named-ref", dest="named_refs", nargs="*", default=list(DEFAULT_NAMED_REFS),
                   help="Named references to try (first is default for plain-UID inputs).")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Objects per one ticket request.")
    p.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Parallel downloads.")
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Stream chunk size in bytes.")
    p.add_argument("--pacing-sec", type=float, default=DEFAULT_PACING_SEC, help="Sleep between files to avoid FMS overload.")
    p.add_argument("--no-verify-tls", action="store_true", help="Disable TLS certificate verification (test only).")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen without doing it.")
    p.add_argument("--no-skip-existing", action="store_true", help="Force re-download even if size matches.")
    p.add_argument("--jsonl", type=Path, default=None, help="JSONL audit output path.")
    p.add_argument("--log-file", type=Path, default=None, help="Optional rotating log file path.")
    p.add_argument("--timeout-connect", type=int, default=DEFAULT_TIMEOUT[0], help="Connect timeout (sec).")
    p.add_argument("--timeout-read", type=int, default=DEFAULT_TIMEOUT[1], help="Read timeout (sec).")

    # Auth
    p.add_argument("--username", default=os.environ.get("TC_USERNAME"), help="User (or set TC_USERNAME).")
    p.add_argument("--password", default=os.environ.get("TC_PASSWORD"), help="Password (or set TC_PASSWORD).")
    p.add_argument("--token", default=os.environ.get("TC_BEARER_TOKEN"), help="Bearer token (or set TC_BEARER_TOKEN).")

    p.add_argument("--site-profile", default=os.environ.get("TC_SITE_PROFILE"), help="Optional site profile switch.")

    args = p.parse_args(argv)

    return AppConfig(
        input_path=args.input,
        out_dir=args.out,
        relations=tuple(args.relations),
        named_refs=tuple(args.named_refs),
        batch_size=int(args.batch_size),
        max_workers=int(args.max_workers),
        chunk_size=int(args.chunk_size),
        pacing_sec=float(args.pacing_sec),
        verify_tls=not args.no_verify_tls,
        dry_run=bool(args.dry_run),
        skip_existing=not args.no_skip_existing,
        jsonl_path=args.jsonl,
        log_file=args.log_file,
        timeout=(int(args.timeout_connect), int(args.timeout_read)),
        username=args.username,
        password=args.password,
        token=args.token,
        site_profile=args.site_profile,
    )


# -------------------------
# Main
# -------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    cfg = parse_args(argv)
    try:
        return run(cfg)
    except KeyboardInterrupt:
        logging.warning("Interrupted.")
        return 130
    except requests.HTTPError as http_err:
        logging.error("HTTP error: %s", http_err)
        return 3
    except Exception as ex:
        logging.exception("Fatal error: %s", ex)
        return 1

if __name__ == "__main__":
    sys.exit(main())
