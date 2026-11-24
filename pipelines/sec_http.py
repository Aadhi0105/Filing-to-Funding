"""HTTP capture shared by the local SEC ingestion commands."""

import fcntl
import math
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from pipelines.load_pilot import ROOT

REQUEST_BUDGET = Path(os.environ.get("FILING_SEC_REQUEST_BUDGET") or ROOT / ".local/sec-request-budget.lock")
REQUEST_INTERVAL = 0.5
RETRY_DELAY = 2
MAX_INLINE_WAIT = 5
BLOCK_COOLDOWN = 600
RETRY_STATUSES = {"408", "500", "502", "503", "504"}
RETRY_TRANSPORT_CODES = {5, 6, 7, 18, 28, 52, 55, 56}
ACCESS_BLOCKS = {"403", "429"}


class EdgarDownloadError(ValueError):
    def __init__(self, url, status):
        self.status = status
        super().__init__(f"EDGAR download failed for {url} (HTTP {status if status and status != '000' else 'unavailable'})")


def sec_contact():
    contact = os.environ.get("SEC_CONTACT_EMAIL", "")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact):
        raise ValueError("Set SEC_CONTACT_EMAIL to an authorized project contact for EDGAR requests")
    return contact


def retry_after_seconds(value):
    if not value:
        return 0
    if value.isascii() and value.isdecimal() and len(value) <= 10:
        return int(value)
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.utcoffset() is not None:
            return max(0, deadline.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        pass
    return 0


def curl_attempt(url, contact, max_bytes):
    with TemporaryDirectory(prefix="ftf-sec-") as directory:
        body = Path(directory) / "response"
        headers = Path(directory) / "headers"
        request = subprocess.run([
            "curl", "--disable", "--silent", "--show-error", "--fail",
            "--proto", "=https", "--connect-timeout", "10", "--max-time", "35", "--max-filesize", str(max_bytes),
            "--user-agent", f"Filing-to-Funding {contact}", "--output", str(body),
            "--dump-header", str(headers), "--write-out", "%{http_code}", "--", url,
        ], capture_output=True, text=True)
        status = request.stdout.strip()
        status = status if re.fullmatch(r"[0-9]{3}", status) else ""
        retry_after = ""
        if headers.exists():
            for line in reversed(headers.read_text(encoding="iso-8859-1").splitlines()):
                name, _, value = line.partition(":")
                if name.lower() == "retry-after":
                    retry_after = value.strip()
                    break
                if line.startswith("HTTP/"):
                    break
        data = None
        if not request.returncode and status == "200":
            with body.open("rb") as handle:
                data = handle.read(max_bytes + 1)
            if not data or len(data) > max_bytes:
                raise ValueError(f"Unexpected EDGAR response size for {url}")
        return status, request.returncode, data, retry_after


def set_request_deadline(lock, deadline):
    lock.seek(0)
    lock.write(f"{deadline:.6f}\n")
    lock.truncate()
    lock.flush()
    os.fsync(lock.fileno())


def budgeted_attempt(url, contact, max_bytes):
    REQUEST_BUDGET.parent.mkdir(parents=True, exist_ok=True)
    REQUEST_BUDGET.touch(exist_ok=True)
    with REQUEST_BUDGET.open("r+", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous_deadline = float(lock.read().strip() or 0)
        if not math.isfinite(previous_deadline):
            raise ValueError("Invalid local SEC request deadline")
        delay = previous_deadline - time.time()
        if delay > MAX_INLINE_WAIT:
            until = datetime.fromtimestamp(previous_deadline, timezone.utc).isoformat(timespec="seconds")
            raise ValueError(f"SEC requests paused locally until {until}")
        if delay > 0:
            time.sleep(delay)
        set_request_deadline(lock, time.time() + REQUEST_INTERVAL)
        status, returncode, data, retry_after = curl_attempt(url, contact, max_bytes)
        finished = time.time()
        retryable = status in RETRY_STATUSES or (
            status in {"", "000", "200"} and returncode in RETRY_TRANSPORT_CODES
        )
        wait = REQUEST_INTERVAL
        if status in ACCESS_BLOCKS:
            wait = max(BLOCK_COOLDOWN, retry_after_seconds(retry_after))
        elif retryable:
            wait = max(RETRY_DELAY, retry_after_seconds(retry_after))
        set_request_deadline(lock, finished + wait)
        return status, data, retryable, datetime.fromtimestamp(finished, timezone.utc).isoformat()


def download_edgar(url, contact, max_bytes):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.query or parts.fragment or not (
        (parts.netloc == "data.sec.gov" and parts.path.startswith(("/submissions/", "/api/xbrl/companyfacts/")))
        or (parts.netloc == "www.sec.gov" and parts.path.startswith("/Archives/edgar/data/"))
    ):
        raise ValueError("EDGAR downloads require an official SEC source URL")
    for attempt in range(2):
        status, data, retryable, retrieved_at = budgeted_attempt(url, contact, max_bytes)
        if data is not None:
            return data, retrieved_at
        if not retryable or attempt == 1:
            raise EdgarDownloadError(url, status)
