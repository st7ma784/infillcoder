/* InfillCode OctoPrint sidebar JS */
(function () {
  "use strict";

  function InfillCodeViewModel(parameters) {
    var self = this;
    self.settings = parameters[0];

    self.layerInfo  = ko.observable(null);
    self.resumeInfo = ko.observable(null);
    self.resumeError = ko.observable(null);
    self.errorMsg   = ko.observable(null);

    self.statusLabel = ko.computed(function () {
      if (self.errorMsg())   return "Error: " + self.errorMsg();
      if (self.layerInfo()) {
        var li = self.layerInfo();
        return "Layer " + li.layer_idx + " / " + li.total_layers
               + " — Z " + li.z_height_mm + " mm"
               + (li.pct_complete != null ? " (" + li.pct_complete + "%)" : "");
      }
      return "Waiting for print event…";
    });

    self.statusClass = ko.computed(function () {
      if (self.errorMsg())   return "infillcode-error";
      if (self.resumeInfo()) return "infillcode-resume-ready";
      if (self.layerInfo())  return "infillcode-ok";
      return "infillcode-pending";
    });

    // Listen for plugin messages from the server
    self.onDataUpdaterPluginMessage = function (plugin, data) {
      if (plugin !== "infillcode") return;

      if (data.type === "layer_identified") {
        self.errorMsg(null);
        self.layerInfo(data);

        if (data.resume_file) {
          self.resumeInfo({
            resume_layer_idx: data.resume_layer_idx,
            resume_z_mm:      data.resume_z_mm,
            layers_remaining: data.layers_remaining,
            resume_file:      data.resume_file,
            resume_file_path: data.resume_file_path,
          });
          self.resumeError(null);
        } else if (data.resume_error) {
          self.resumeInfo(null);
          self.resumeError(data.resume_error);
        } else {
          self.resumeInfo(null);
          self.resumeError(null);
        }

      } else if (data.type === "error") {
        self.layerInfo(null);
        self.resumeInfo(null);
        self.resumeError(null);
        self.errorMsg(data.message);
      }
    };
  }

  OCTOPRINT_VIEWMODELS.push({
    construct: InfillCodeViewModel,
    dependencies: ["settingsViewModel"],
    elements: ["#infillcode_sidebar"],
  });
})();
