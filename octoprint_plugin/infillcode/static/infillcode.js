/* InfillCode OctoPrint sidebar JS */
(function () {
  "use strict";

  function InfillCodeViewModel(parameters) {
    var self = this;
    self.settings = parameters[0];

    // ── Post-print state ──────────────────────────────────────────────────
    self.layerInfo   = ko.observable(null);
    self.resumeInfo  = ko.observable(null);
    self.resumeError = ko.observable(null);
    self.errorMsg    = ko.observable(null);

    // ── Auto-process notification ─────────────────────────────────────────
    self.autoProcessMsg = ko.observable(null);
    self.dismissAutoProcess = function () { self.autoProcessMsg(null); };

    // ── Startup bed scan ──────────────────────────────────────────────────
    self.startupScan = ko.observable(null);

    self.startupScanTitle = ko.computed(function () {
      var s = self.startupScan();
      if (!s) return "";
      return s.found
        ? "Interrupted print detected on bed"
        : "Bed scan: no fingerprint found";
    });

    self.startupScanClass = ko.computed(function () {
      var s = self.startupScan();
      if (!s) return "";
      return s.found ? "infillcode-startup-found" : "infillcode-startup-clear";
    });

    // ── Mid-print fingerprint validation ──────────────────────────────────
    self.fingerprintCheckMsg   = ko.observable(null);
    self.fingerprintCheckClass = ko.observable("infillcode-check-ok");
    self.healthScore           = ko.observable(null);   // 0-100 or null
    self.healthHistory         = ko.observableArray([]); // array of bools

    self.healthScoreClass = ko.computed(function () {
      var s = self.healthScore();
      if (s === null) return "";
      if (s >= 75)   return "infillcode-health-good";
      if (s >= 40)   return "infillcode-health-warn";
      return "infillcode-health-bad";
    });

    // ── Main status (post-print) ──────────────────────────────────────────
    self.statusLabel = ko.computed(function () {
      if (self.errorMsg())  return "Error: " + self.errorMsg();
      if (self.layerInfo()) {
        var li = self.layerInfo();
        return "Layer " + li.layer_idx + " / " + li.total_layers
               + " — Z " + li.z_height_mm + " mm"
               + (li.pct_complete != null ? " (" + li.pct_complete + "%)" : "");
      }
      return "Waiting for print event…";
    });

    self.statusClass = ko.computed(function () {
      if (self.errorMsg())    return "infillcode-error";
      if (self.resumeInfo())  return "infillcode-resume-ready";
      if (self.layerInfo())   return "infillcode-ok";
      return "infillcode-pending";
    });

    // ── One-click resume ──────────────────────────────────────────────────

    /** Queue and immediately start printing a resume file. */
    function _queueFile(relPath) {
      if (!relPath) {
        alert("InfillCode: resume file path not available.");
        return;
      }
      OctoPrint.files.select("local", relPath, /* print= */ true)
        .fail(function () {
          alert("InfillCode: could not queue " + relPath + ".\n"
                + "Select it manually from the file list.");
        });
    }

    self.queueResume = function () {
      var info = self.resumeInfo();
      if (info) _queueFile(info.resume_rel_path);
    };

    self.queueStartupResume = function () {
      var s = self.startupScan();
      if (s) _queueFile(s.resume_rel_path);
    };

    // ── Plugin message handler ────────────────────────────────────────────

    self.onDataUpdaterPluginMessage = function (plugin, data) {
      if (plugin !== "infillcode") return;

      switch (data.type) {

        // ── Post-print layer identification ──────────────────────────
        case "layer_identified":
          self.errorMsg(null);
          self.layerInfo(data);
          if (data.resume_file) {
            self.resumeInfo(data);
            self.resumeError(null);
          } else if (data.resume_error) {
            self.resumeInfo(null);
            self.resumeError(data.resume_error);
          } else {
            self.resumeInfo(null);
            self.resumeError(null);
          }
          break;

        case "error":
          self.layerInfo(null);
          self.resumeInfo(null);
          self.resumeError(null);
          self.errorMsg(data.message);
          break;

        // ── .aw.gcode auto-processing ────────────────────────────────
        case "auto_process_started":
          self.autoProcessMsg("Processing " + data.source_file + "…");
          break;

        case "auto_process_complete":
          self.autoProcessMsg(
            data.source_file + " encoded \u2192 " + data.output_file
            + "  (" + data.encoded_count + "/" + data.total_layers + " layers)"
          );
          break;

        case "auto_process_error":
          self.autoProcessMsg(
            "Auto-process failed (" + (data.source_file || "") + "): " + data.message
          );
          break;

        // ── Startup bed scan ─────────────────────────────────────────
        case "startup_scan_result":
          self.startupScan(data);
          break;

        // ── Mid-print fingerprint validation ─────────────────────────
        case "fingerprint_check_passed":
          self.fingerprintCheckClass("infillcode-check-ok");
          self.fingerprintCheckMsg(
            "\u2713 Fingerprint OK at " + data.progress + "%"
            + (data.layer_idx != null
               ? "  (layer " + data.layer_idx + "/" + data.total_layers + ")"
               : "")
          );
          self._updateHealth(data);
          break;

        case "fingerprint_check_failed":
          self.fingerprintCheckClass("infillcode-check-fail");
          var failMsg = "\u26a0 Fingerprint check failed at " + data.progress + "%: "
                        + data.message;
          if (data.consecutive_failures > 1) {
            failMsg += "  (" + data.consecutive_failures + " in a row)";
          }
          self.fingerprintCheckMsg(failMsg);
          self._updateHealth(data);
          break;

        case "auto_paused":
          self.fingerprintCheckClass("infillcode-check-fail");
          self.fingerprintCheckMsg(
            "\u23f8 Print paused — " + data.consecutive_failures
            + " consecutive fingerprint failures at " + data.progress + "%"
          );
          break;
      }
    };

    self._updateHealth = function (data) {
      if (data.health_score != null) self.healthScore(data.health_score);
      if (Array.isArray(data.health_history)) self.healthHistory(data.health_history);
    };
  }

  OCTOPRINT_VIEWMODELS.push({
    construct: InfillCodeViewModel,
    dependencies: ["settingsViewModel"],
    elements: ["#infillcode_sidebar"],
  });
})();
