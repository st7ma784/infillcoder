"""InfillCode OctoPrint Plugin — GCode layer fingerprinting for print recovery."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import octoprint.plugin


# ---------------------------------------------------------------------------
# Ensure the shared core/ library is importable in all install modes
# (editable dev install, tarball install, OctoPrint Plugin Manager install)
# ---------------------------------------------------------------------------

from ._bundled_core_compat import ensure_core_importable
ensure_core_importable()


class InfillCodePlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ProgressPlugin,
):

    def initialize(self) -> None:
        self._state_lock = threading.RLock()
        self._last_fingerprint_check_pct: Optional[int] = None
        self._fingerprint_history: List[bool] = []
        self._consecutive_failures: int = 0

    _HEALTH_WINDOW = 20   # how many recent checks to score

    def get_settings_defaults(self) -> Dict[str, Any]:
        return {
            "db_path": "",                   # path to companion SQLite file
            "snapshot_url": "",              # OctoPrint webcam snapshot URL
            "nominal_spacing_mm": 0.0,       # 0 → auto-detect from DB
            "spacing_tolerance": 0.15,       # fractional tolerance for spacing decode
            "auto_resume": True,             # auto-generate remainder GCode on failure

            # Workflow settings
            "auto_process_aw_gcode": True,   # encode .aw.gcode files on upload
            "auto_scan_on_startup": True,    # scan bed fingerprint when OctoPrint starts
            "fingerprint_check_interval": 25,  # mid-print check every N % (0 = off)
            "auto_pause_consecutive_failures": 0,  # pause after N consecutive failures (0 = off)

            # Resume GCode settings
            "z_hop_mm": 2.0,                 # nozzle lift during resume init
            "prime_length_mm": 20.0,         # purge extrusion before resuming
            "park_x": -1.0,                  # park X during heat-up (-1 = disabled)
            "park_y": -1.0,                  # park Y during heat-up (-1 = disabled)
        }

    def get_assets(self) -> Dict[str, List[str]]:
        return {
            "js":  ["static/infillcode.js"],
            "css": ["static/infillcode.css"],
        }

    def get_template_configs(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "sidebar",
                "name": "InfillCode",
                "template": "infillcode_sidebar.jinja2",
                "custom_bindings": False,
            },
            {
                "type": "settings",
                "template": "infillcode_settings.jinja2",
                "custom_bindings": False,
            },
        ]

    def on_after_startup(self) -> None:
        """Validate configuration and start optional background tasks."""
        # Validate configuration
        validation_errors = self._validate_configuration()
        if validation_errors:
            for error in validation_errors:
                self._logger.warning("InfillCode configuration issue: %s", error)
            self._send_message("config_validation_warning", {
                "errors": validation_errors,
            })
        
        # Start auto-scan if configured
        if not self._settings.get(["auto_scan_on_startup"]):
            return
        t = threading.Timer(15.0, self._startup_bed_scan)
        t.daemon = True
        t.start()

    def _validate_configuration(self) -> list[str]:
        """
        Validate plugin configuration at startup.
        
        Returns:
            List of configuration issues (empty if all valid)
        """
        errors = []
        
        # Check database path if auto_process_aw_gcode is enabled
        if self._settings.get(["auto_process_aw_gcode"]):
            db_path = self._settings.get(["db_path"])
            if not db_path:
                errors.append("Database path not configured but auto_process_aw_gcode is enabled")
            elif not os.path.isfile(db_path):
                errors.append(f"Database file not found at {db_path}")
        
        # Check snapshot URL if auto_scan_on_startup or fingerprint checks are enabled
        if self._settings.get(["auto_scan_on_startup"]) or self._settings.get(["fingerprint_check_interval"]):
            snapshot_url = self._settings.get(["snapshot_url"])
            if not snapshot_url:
                errors.append("Webcam snapshot URL not configured but fingerprint checks are enabled")
            elif not (snapshot_url.startswith("http://") or snapshot_url.startswith("https://")):
                errors.append(f"Invalid snapshot URL (must be http:// or https://): {snapshot_url}")
        
        return errors

    def _startup_bed_scan(self) -> None:
        try:
            result = self._scan_and_decode_fingerprint()
        except Exception as exc:
            self._logger.exception("InfillCode: startup scan error: %s", exc)
            return

        if result is None:
            # Vision or decode failed – bed likely clear or webcam unavailable.
            self._send_message("startup_scan_result", {
                "found": False,
                "message": "No fingerprint detected on bed.",
            })
            return

        row, decoded = result
        pct = None
        if row["total_layers"]:
            pct = round(100.0 * row["layer_idx"] / row["total_layers"], 1)

        info: Dict[str, Any] = {
            "found": True,
            "filename":        row["filename"],
            "layer_idx":       row["layer_idx"],
            "total_layers":    row["total_layers"],
            "z_height_mm":     row["z_height_mm"],
            "pct_complete":    pct,
            "cumulative_e_mm": row["cumulative_e_mm"],
        }

        if self._settings.get(["auto_resume"]):
            resume_info = self._build_resume_file(row, {})
            if resume_info:
                info.update(resume_info)

        self._send_message("startup_scan_result", info)

    def on_print_progress(self, storage: str, path: str, progress: int) -> None:
        interval = int(self._settings.get(["fingerprint_check_interval"]) or 0)
        if interval <= 0 or progress <= 0:
            return

        bucket = (progress // interval) * interval
        with self._state_lock:
            if bucket == 0 or bucket == self._last_fingerprint_check_pct:
                return
            self._last_fingerprint_check_pct = bucket
        threading.Thread(
            target=self._mid_print_fingerprint_check,
            args=(progress,),
            daemon=True,
        ).start()

    def _mid_print_fingerprint_check(self, progress: int) -> None:
        try:
            result = self._scan_and_decode_fingerprint()
        except Exception as exc:
            self._logger.warning("InfillCode: mid-print check error: %s", exc)
            self._record_check_result(passed=False)
            self._send_message("fingerprint_check_failed", {
                "progress":            progress,
                "message":             f"Vision error: {exc}",
                "consecutive_failures": self._consecutive_failures,
                "health_score":        self._health_score(),
                "health_history":      list(self._fingerprint_history),
            })
            self._maybe_auto_pause(progress)
            return

        if result is None:
            self._record_check_result(passed=False)
            self._send_message("fingerprint_check_failed", {
                "progress":            progress,
                "message":             "Fingerprint not readable — possible layer shift or detachment.",
                "consecutive_failures": self._consecutive_failures,
                "health_score":        self._health_score(),
                "health_history":      list(self._fingerprint_history),
            })
            self._maybe_auto_pause(progress)
            return

        row, decoded = result
        pct_encoded = None
        if row["total_layers"]:
            pct_encoded = round(100.0 * row["layer_idx"] / row["total_layers"], 1)

        self._record_check_result(passed=True)
        self._send_message("fingerprint_check_passed", {
            "progress":      progress,
            "layer_idx":     row["layer_idx"],
            "total_layers":  row["total_layers"],
            "pct_encoded":   pct_encoded,
            "filename":      row["filename"],
            "health_score":  self._health_score(),
            "health_history": list(self._fingerprint_history),
        })

    def _record_check_result(self, passed: bool) -> None:
        with self._state_lock:
            self._fingerprint_history.append(passed)
            if len(self._fingerprint_history) > self._HEALTH_WINDOW:
                self._fingerprint_history.pop(0)
            if passed:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

    def _health_score(self) -> Optional[int]:
        with self._state_lock:
            if not self._fingerprint_history:
                return None
            return round(100 * sum(self._fingerprint_history) / len(self._fingerprint_history))

    def _maybe_auto_pause(self, progress: int) -> None:
        with self._state_lock:
            threshold = int(self._settings.get(["auto_pause_consecutive_failures"]) or 0)
            if threshold <= 0 or self._consecutive_failures < threshold:
                return
            consecutive_failures = self._consecutive_failures
        self._logger.warning(
            "InfillCode: %d consecutive fingerprint failures at %d%% — pausing print.",
            consecutive_failures, progress,
        )
        try:
            self._printer.pause_print()
        except Exception as exc:
            self._logger.error("InfillCode: could not pause print: %s", exc)
        self._send_message("auto_paused", {
            "progress":            progress,
            "consecutive_failures": consecutive_failures,
        })

    def _reset_print_state(self) -> None:
        with self._state_lock:
            self._last_fingerprint_check_pct = None
            self._fingerprint_history = []
            self._consecutive_failures = 0

    def on_event(self, event: str, payload: Dict[str, Any]) -> None:
        if event in {"PrintFailed", "PrintDone", "PrintCancelled"}:
            threading.Thread(
                target=self._analyse_snapshot,
                args=(event, payload),
                daemon=True,
            ).start()
            self._reset_print_state()

        if event == "PrintStarted":
            self._reset_print_state()

        if event == "FileAdded":
            name = payload.get("name", "")
            if name.endswith(".aw.gcode") and self._settings.get(["auto_process_aw_gcode"]):
                threading.Thread(
                    target=self._auto_process_aw_gcode,
                    args=(payload,),
                    daemon=True,
                ).start()

    def _auto_process_aw_gcode(self, payload: Dict[str, Any]) -> None:
        try:
            self._run_aw_gcode_pipeline(payload)
        except Exception as exc:
            self._logger.exception("InfillCode: auto-process error: %s", exc)
            self._send_message("auto_process_error", {
                "message": str(exc),
                "source_file": payload.get("name", ""),
            })

    def _run_aw_gcode_pipeline(self, payload: Dict[str, Any]) -> None:
        try:
            from core.pipeline import run_pipeline
            from core.database import open_db
        except ImportError as exc:
            self._send_message("auto_process_error", {
                "message": f"Missing dependency: {exc}",
                "source_file": payload.get("name", ""),
            })
            return

        db_path = self._settings.get(["db_path"])
        if not db_path or not os.path.isfile(db_path):
            self._send_message("auto_process_error", {
                "message": "DB path not configured or file missing.",
                "source_file": payload.get("name", ""),
            })
            return

        storage  = payload.get("storage", "local")
        rel_path = payload.get("path", "")
        name     = payload.get("name", "")

        full_path = self._file_manager.path_on_disk(storage, rel_path)
        if not full_path or not os.path.isfile(full_path):
            self._send_message("auto_process_error", {
                "message": f"Cannot locate uploaded file: {name}",
                "source_file": name,
            })
            return

        self._send_message("auto_process_started", {"source_file": name})
        self._logger.info("InfillCode: auto-processing %s", name)

        try:
            gcode_text = Path(full_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._send_message("auto_process_error", {"message": str(exc), "source_file": name})
            return

        conn = open_db(db_path)
        try:
            result = run_pipeline(gcode_text, name, conn)
        except Exception as exc:
            conn.close()
            self._logger.error("InfillCode: pipeline error for %s: %s", name, exc)
            self._send_message("auto_process_error", {"message": str(exc), "source_file": name})
            return
        conn.close()

        out_name = name[: -len(".aw.gcode")] + ".gcode"
        out_dir  = os.path.dirname(full_path)
        out_path = os.path.join(out_dir, out_name)

        try:
            Path(out_path).write_text(result.modified_gcode, encoding="utf-8")
        except OSError as exc:
            self._send_message("auto_process_error", {"message": f"Write failed: {exc}", "source_file": name})
            return

        self._logger.info(
            "InfillCode: %s → %s (%d layers, %d encoded)",
            name, out_name, result.total_layers, result.encoded_count,
        )
        self._send_message("auto_process_complete", {
            "source_file":        name,
            "output_file":        out_name,
            "file_id":            result.file_id,
            "total_layers":       result.total_layers,
            "encoded_count":      result.encoded_count,
            "skipped_count":      result.skipped_count,
            "nominal_spacing_mm": result.nominal_spacing_mm,
        })

    def _scan_and_decode_fingerprint(
        self,
    ) -> Optional[Tuple[Dict[str, Any], Any]]:
        db_path      = self._settings.get(["db_path"])
        snapshot_url = self._settings.get(["snapshot_url"])
        nominal      = float(self._settings.get(["nominal_spacing_mm"]) or 0)
        tolerance    = float(self._settings.get(["spacing_tolerance"]) or 0.15)

        if not db_path or not os.path.isfile(db_path):
            return None
        if not snapshot_url:
            return None

        try:
            from .vision import extract_spacings
            from core.decoder import full_decode
            from core.database import open_db, lookup_by_payload, lookup_by_raw_payload
        except ImportError:
            return None

        spacings = extract_spacings(
            snapshot_url,
            nominal_spacing_mm=nominal if nominal > 0 else None,
            tolerance=tolerance,
        )
        if spacings is None:
            return None

        result = full_decode(spacings, nominal=nominal if nominal > 0 else None)
        if result is None:
            return None

        conn = open_db(db_path)
        row = (
            lookup_by_payload(conn, result.correlated_payload)
            or lookup_by_raw_payload(conn, result.payload_bits)
        )
        conn.close()

        if row is None:
            return None

        return dict(row), result

    def _analyse_snapshot(self, event: str, payload: Dict[str, Any]) -> None:
        try:
            self._run_vision_pipeline(event, payload)
        except Exception as exc:
            self._logger.exception("InfillCode vision pipeline error: %s", exc)

    def _run_vision_pipeline(self, event: str, payload: Dict[str, Any]) -> None:
        db_path      = self._settings.get(["db_path"])
        snapshot_url = self._settings.get(["snapshot_url"])
        nominal      = float(self._settings.get(["nominal_spacing_mm"]) or 0)
        tolerance    = float(self._settings.get(["spacing_tolerance"]) or 0.15)
        auto_resume  = bool(self._settings.get(["auto_resume"]))

        if not db_path or not os.path.isfile(db_path):
            self._logger.warning("InfillCode: db_path not set or file missing.")
            self._send_message("error", {"message": "DB path not configured."})
            return

        if not snapshot_url:
            self._logger.warning("InfillCode: snapshot_url not set.")
            self._send_message("error", {"message": "Snapshot URL not configured."})
            return

        try:
            from .vision import extract_spacings
            from core.decoder import full_decode
            from core.database import open_db, lookup_by_payload, lookup_by_raw_payload
        except ImportError as exc:
            self._logger.error("InfillCode: import error — %s", exc)
            self._send_message("error", {"message": f"Missing dependency: {exc}"})
            return

        spacings = extract_spacings(
            snapshot_url,
            nominal_spacing_mm=nominal if nominal > 0 else None,
            tolerance=tolerance,
        )
        if spacings is None:
            self._send_message("error", {"message": "Could not extract spacings from snapshot."})
            return

        result = full_decode(spacings, nominal=nominal if nominal > 0 else None)
        if result is None:
            self._send_message("error", {"message": "Could not decode InfillCode from snapshot."})
            return

        conn = open_db(db_path)
        row = (
            lookup_by_payload(conn, result.correlated_payload)
            or lookup_by_raw_payload(conn, result.payload_bits)
        )
        conn.close()

        if row is None:
            self._send_message("error", {
                "message": f"Decoded file_id={result.file_id} layer={result.layer_idx} "
                           "but not found in DB.",
            })
            return

        pct = None
        if row["total_layers"]:
            pct = round(100.0 * row["layer_idx"] / row["total_layers"], 1)

        layer_info = {
            "event":           event,
            "filename":        row["filename"],
            "layer_idx":       row["layer_idx"],
            "total_layers":    row["total_layers"],
            "z_height_mm":     row["z_height_mm"],
            "pct_complete":    pct,
            "cumulative_e_mm": row["cumulative_e_mm"],
        }

        if event == "PrintFailed" and auto_resume:
            resume_info = self._build_resume_file(row, payload)
            if resume_info:
                layer_info.update(resume_info)

        self._send_message("layer_identified", layer_info)

    def _build_resume_file(
        self,
        db_row,
        event_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        try:
            from core.resume import build_resume_gcode, ResumeError
        except ImportError as exc:
            self._logger.error("InfillCode: cannot import resume module: %s", exc)
            return None

        z_hop      = float(self._settings.get(["z_hop_mm"]) or 2.0)
        prime_len  = float(self._settings.get(["prime_length_mm"]) or 20.0)
        park_x     = float(self._settings.get(["park_x"]) or -1.0)
        park_y     = float(self._settings.get(["park_y"]) or -1.0)

        original_path = self._locate_gcode_file(db_row["filename"], event_payload)
        if original_path is None:
            self._logger.warning(
                "InfillCode: cannot find original GCode file %r for resume generation.",
                db_row["filename"],
            )
            return {"resume_error": f"Cannot find original file: {db_row['filename']}"}

        try:
            original_gcode = Path(original_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._logger.error("InfillCode: cannot read %s: %s", original_path, exc)
            return {"resume_error": str(exc)}

        try:
            resume_result = build_resume_gcode(
                original_gcode=original_gcode,
                last_good_layer_idx=db_row["layer_idx"],
                original_filename=db_row["filename"],
                z_hop_mm=z_hop,
                prime_length_mm=prime_len,
                park_x=park_x if park_x >= 0 else None,
                park_y=park_y if park_y >= 0 else None,
            )
        except Exception as exc:
            self._logger.error("InfillCode: resume build failed: %s", exc)
            return {"resume_error": str(exc)}

        save_path = self._save_resume_file(
            resume_result.resume_gcode,
            resume_result.suggested_filename,
            original_path,
        )
        if save_path is None:
            return {"resume_error": "Failed to write resume file."}

        self._logger.info(
            "InfillCode: resume GCode saved to %s (%d layers remaining)",
            save_path,
            resume_result.layers_remaining,
        )

        resume_rel_path = None
        try:
            uploads_root = self._file_manager.path_on_disk("local", "")
            resume_rel_path = os.path.relpath(save_path, uploads_root)
        except Exception:
            pass

        return {
            "resume_file":       resume_result.suggested_filename,
            "resume_file_path":  save_path,
            "resume_rel_path":   resume_rel_path,
            "resume_layer_idx":  resume_result.resume_layer_idx,
            "resume_z_mm":       resume_result.resume_z_mm,
            "layers_remaining":  resume_result.layers_remaining,
        }

    def _locate_gcode_file(
        self,
        filename: str,
        event_payload: Dict[str, Any],
    ) -> Optional[str]:
        event_path = event_payload.get("path") or event_payload.get("file", {}).get("path")
        if event_path:
            uploads = self._file_manager.path_on_disk("local", event_path)
            if uploads and os.path.isfile(uploads):
                return uploads

        try:
            uploads_root = self._file_manager.path_on_disk("local", "")
            for dirpath, _, filenames in os.walk(uploads_root):
                for fname in filenames:
                    if fname == filename or fname == Path(filename).name:
                        return os.path.join(dirpath, fname)
        except Exception:
            pass

        db_path = self._settings.get(["db_path"])
        if db_path:
            candidate = os.path.join(os.path.dirname(db_path), filename)
            if os.path.isfile(candidate):
                return candidate

        return None

    def _save_resume_file(
        self,
        resume_gcode: str,
        suggested_filename: str,
        original_path: str,
    ) -> Optional[str]:
        for candidate_dir in [
            os.path.dirname(original_path),
            self._file_manager.path_on_disk("local", ""),
        ]:
            if not candidate_dir:
                continue
            out_path = os.path.join(candidate_dir, suggested_filename)
            try:
                Path(out_path).write_text(resume_gcode, encoding="utf-8")
                return out_path
            except OSError:
                continue
        return None

    def get_api_commands(self) -> Dict[str, List[str]]:
        return {"status": []}

    def on_api_command(self, command: str, data: Dict[str, Any]):
        return {"status": "ok"}

    def _send_message(self, msg_type: str, payload: Dict[str, Any]) -> None:
        self._plugin_manager.send_plugin_message(
            self._identifier,
            {"type": msg_type, **payload},
        )


__plugin_name__           = "InfillCode"
__plugin_version__        = "0.2.0"
__plugin_pythoncompat__   = ">=3.7"
__plugin_description__    = "GCode layer fingerprinting via infill line spacing modulation — auto-resume, bed scanning, and mid-print health monitoring."
__plugin_author__         = "Dr Steve Mander"
__plugin_url__            = "https://github.com/st7ma784/infillcoder"
__plugin_license__        = "MIT"
__plugin_hooks__          = {}
__plugin_implementation__ = InfillCodePlugin()
