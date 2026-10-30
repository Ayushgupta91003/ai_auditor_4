"""
Autonomous File Watchdog for AI Invoice Auditor
Monitors incoming invoice directory for new or updated files, performs stability checks,
computes checksums, and automatically triggers the LangGraph audit pipeline.
"""

import os
import time
import logging
import hashlib
import threading
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
from typing import Dict, Any, List, Optional

from .graph.workflow import run_invoice_audit_pipeline
from .utils.db import audit_db

logger = logging.getLogger("invoice_watchdog")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".png", ".jpg", ".jpeg", ".tiff"}

def compute_checksum(filepath: str) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

class InvoiceWatchdog:
    """
    Autonomous background watchdog that polls the incoming directory,
    detects new invoices, verifies stability, and dispatches them to the audit pipeline.
    """

    def __init__(self, incoming_dir: Path, poll_interval: float = 4.0):
        self.incoming_dir = Path(incoming_dir)
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # In-memory tracking
        self._seen_files: Dict[str, Dict[str, Any]] = {}
        self._recent_events: deque = deque(maxlen=60)
        self._stats = {
            "is_running": False,
            "is_paused": False,
            "incoming_dir": str(self.incoming_dir),
            "poll_interval_seconds": self.poll_interval,
            "total_scans": 0,
            "total_detected": 0,
            "total_processed": 0,
            "total_skipped": 0,
            "total_errors": 0,
            "started_at": None,
            "last_scan_time": None
        }

    def _record_event(self, event_type: str, file_name: str, **kwargs):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "file": file_name,
            **kwargs
        }
        with self._lock:
            self._recent_events.appendleft(event)

    def start(self):
        """Starts the watchdog background daemon thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("Watchdog thread is already running.")
                return

            self._stop_event.clear()
            self._pause_event.set()
            self._stats["is_running"] = True
            self._stats["is_paused"] = False
            self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

            self._thread = threading.Thread(target=self._run_loop, name="InvoiceWatchdogWorker", daemon=True)
            self._thread.start()
            logger.info(f"Invoice Watchdog started. Monitoring: {self.incoming_dir} every {self.poll_interval}s")

    def stop(self):
        """Stops the watchdog background thread gracefully."""
        self._stop_event.set()
        self._pause_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        with self._lock:
            self._stats["is_running"] = False
            self._stats["is_paused"] = False
        logger.info("Invoice Watchdog stopped.")

    def pause(self):
        """Pauses directory polling."""
        self._pause_event.clear()
        with self._lock:
            self._stats["is_paused"] = True
        logger.info("Invoice Watchdog paused.")

    def resume(self):
        """Resumes directory polling."""
        self._pause_event.set()
        with self._lock:
            self._stats["is_paused"] = False
        logger.info("Invoice Watchdog resumed.")

    def toggle(self) -> Dict[str, Any]:
        """Toggles between paused and active monitoring."""
        if self._pause_event.is_set():
            self.pause()
        else:
            self.resume()
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """Returns current watchdog status, metrics, and recent events."""
        with self._lock:
            status = dict(self._stats)
            status["is_running"] = bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())
            status["is_paused"] = not self._pause_event.is_set()
            status["recent_events"] = list(self._recent_events)
            status["tracked_files_count"] = len(self._seen_files)
            return status

    def scan_cycle(self) -> List[Dict[str, Any]]:
        """
        Executes one full scan cycle over incoming_dir.
        Detects new files, checks stability, verifies checksum, and triggers the audit pipeline.
        """
        cycle_results = []
        if not self.incoming_dir.exists():
            try:
                self.incoming_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Cannot create or access incoming directory {self.incoming_dir}: {e}")
                return cycle_results

        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._stats["total_scans"] += 1
            self._stats["last_scan_time"] = now_iso

        try:
            candidates = [
                p for p in self.incoming_dir.iterdir()
                if p.is_file()
                and p.suffix.lower() in SUPPORTED_EXTENSIONS
                and not p.name.startswith(".")
            ]
        except Exception as e:
            logger.error(f"Error listing incoming directory {self.incoming_dir}: {e}")
            return cycle_results

        now = time.time()
        for filepath in sorted(candidates, key=lambda x: x.name):
            try:
                stat = filepath.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime
                file_key = str(filepath.resolve())

                # File stability check: ensure file is not currently being written
                # If newly appeared and modified less than 1.5 seconds ago, wait for next tick
                if file_key not in self._seen_files:
                    if (now - mtime) < 1.5:
                        self._seen_files[file_key] = {"size": file_size, "mtime": mtime, "stable": False}
                        logger.debug(f"[Watchdog] File {filepath.name} is writing or newly copied. Waiting for stability.")
                        continue
                    else:
                        self._seen_files[file_key] = {"size": file_size, "mtime": mtime, "stable": True}
                else:
                    prev = self._seen_files[file_key]
                    if prev.get("size") != file_size or prev.get("mtime") != mtime:
                        # File modified
                        prev["size"] = file_size
                        prev["mtime"] = mtime
                        prev["stable"] = False
                        continue
                    else:
                        prev["stable"] = True

                # File is stable. Compute checksum
                checksum = compute_checksum(str(filepath))
                prev_checksum = self._seen_files[file_key].get("checksum")

                if prev_checksum == checksum and self._seen_files[file_key].get("audited"):
                    # Already audited in this watchdog lifecycle
                    continue

                self._seen_files[file_key]["checksum"] = checksum

                # Check if checksum is already recorded in the audit database
                if audit_db.is_checksum_audited(checksum):
                    if not self._seen_files[file_key].get("audited"):
                        self._seen_files[file_key]["audited"] = True
                        with self._lock:
                            self._stats["total_skipped"] += 1
                        self._record_event(
                            "SKIPPED",
                            filepath.name,
                            reason="Already audited in database (checksum match)",
                            checksum=checksum[:12]
                        )
                        cycle_results.append({
                            "file": filepath.name,
                            "action": "skipped",
                            "reason": "checksum_exists",
                            "checksum": checksum[:12]
                        })
                    continue

                # Brand new invoice detected!
                with self._lock:
                    self._stats["total_detected"] += 1

                logger.info(f"[Watchdog] 🚀 Autonomous trigger: Processing new invoice '{filepath.name}'...")
                self._record_event("TRIGGERED", filepath.name, checksum=checksum[:12])

                try:
                    pipeline_state = run_invoice_audit_pipeline(str(filepath))
                    self._seen_files[file_key]["audited"] = True

                    if pipeline_state.get("skipped"):
                        with self._lock:
                            self._stats["total_skipped"] += 1
                        self._record_event(
                            "SKIPPED",
                            filepath.name,
                            reason=pipeline_state.get("skip_reason", "Skipped by pipeline"),
                            checksum=checksum[:12]
                        )
                        cycle_results.append({
                            "file": filepath.name,
                            "action": "skipped",
                            "reason": pipeline_state.get("skip_reason")
                        })
                    else:
                        with self._lock:
                            self._stats["total_processed"] += 1
                        v_status = pipeline_state.get("validation_status", "unknown")
                        recommendation = pipeline_state.get("recommendation", "review")
                        invoice_id = pipeline_state.get("invoice_id")

                        self._record_event(
                            "PROCESSED",
                            filepath.name,
                            validation_status=v_status,
                            recommendation=recommendation,
                            invoice_id=invoice_id,
                            checksum=checksum[:12]
                        )
                        cycle_results.append({
                            "file": filepath.name,
                            "action": "processed",
                            "validation_status": v_status,
                            "recommendation": recommendation,
                            "invoice_id": invoice_id
                        })
                        logger.info(f"[Watchdog] ✅ Finished invoice '{filepath.name}': Status={v_status}, Recommendation={recommendation}")

                except Exception as ex:
                    with self._lock:
                        self._stats["total_errors"] += 1
                    logger.error(f"[Watchdog] ❌ Pipeline failure for '{filepath.name}': {ex}", exc_info=True)
                    self._record_event("ERROR", filepath.name, error=str(ex))
                    cycle_results.append({
                        "file": filepath.name,
                        "action": "error",
                        "error": str(ex)
                    })

            except Exception as e:
                logger.error(f"[Watchdog] Error inspecting file {filepath}: {e}")

        return cycle_results

    def _run_loop(self):
        """Continuous polling worker loop."""
        logger.info(f"Watchdog worker thread started. Polling every {self.poll_interval}s...")
        while not self._stop_event.is_set():
            # Wait if paused
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            try:
                self.scan_cycle()
            except Exception as e:
                logger.error(f"Watchdog cycle error: {e}", exc_info=True)

            # Sleep in small slices to allow rapid shutdown response
            slept = 0.0
            while slept < self.poll_interval and not self._stop_event.is_set():
                time.sleep(0.5)
                slept += 0.5

        logger.info("Watchdog worker thread exited cleanly.")

# Global watchdog singleton
_watchdog_instance: Optional[InvoiceWatchdog] = None

def get_watchdog(incoming_dir: Optional[Path] = None, poll_interval: float = 4.0) -> InvoiceWatchdog:
    global _watchdog_instance
    if _watchdog_instance is None:
        if incoming_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            incoming_dir = base_dir / "data" / "incoming"
        _watchdog_instance = InvoiceWatchdog(incoming_dir=incoming_dir, poll_interval=poll_interval)
    return _watchdog_instance
