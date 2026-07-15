"""Static contracts for the shared Primus management-v2 setup UI."""

import json
import os
import shutil
import subprocess
import unittest


SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(SENDER_DIR, "web")


def _read(relative_path):
    with open(os.path.join(WEB_DIR, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class ManagementUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = _read("js/device-conn.js")
        cls.devices_app = _read("js/app-devices.js")
        cls.primus_app = _read("js/app-primus.js")
        cls.devices = _read("index-devices.html")
        cls.primus = _read("index-primus.html")
        cls.radius = _read("index.html")
        cls.css = _read("css/style.css")

    def test_shared_store_owns_management_routes_and_validation(self):
        for route in (
            "/api/device_full_config",
            "/api/refresh_device_full_config",
            "/api/apply_device_output_descriptor",
            "/api/set_device_telemetry_target",
            "/api/enter_device_production_mode",
            "/api/unlock_device_boot_window",
            "/api/output_presets",
        ):
            self.assertIn(route, self.conn)
        for field in (
            "physical_pixels",
            "rows",
            "columns",
            "traversal_axis",
            "scan_pattern",
            "start_corner",
            "virtual_pixels",
        ):
            self.assertIn(field, self.conn)
        self.assertIn("product of 1 to 170", self.conn)
        self.assertIn("ArtDmx remains physical-wire order", self.conn)
        self.assertIn("readback_pending", self.conn)
        self.assertIn("Applied; awaiting refresh", self.conn)

    def test_both_setup_apps_keep_stable_off_slots_recoverable(self):
        for markup in (self.devices, self.primus):
            self.assertIn("$store.conn.physicalOutputs(", markup)
            self.assertIn('<option value="off">Off</option>', markup)
            self.assertIn('<option value="linear">Strip</option>', markup)
            self.assertIn('<option value="grid">Grid</option>', markup)
            self.assertIn("Apply descriptor", markup)
            self.assertIn("Apply preset", markup)
        self.assertNotIn("x-for=\"(o, oi) in entry.dev.outputs\"", self.devices)
        self.assertNotIn("x-for=\"(o, oi) in dev.outputs\"", self.primus)

    def test_descriptor_editors_are_created_only_after_drafts_exist(self):
        self.assertIn(
            '<template x-if="$store.conn.descriptorEditorOpen(entry._index, oi)">',
            self.devices,
        )
        self.assertIn(
            '<template x-if="$store.conn.descriptorEditor">',
            self.primus,
        )
        self.assertNotIn(
            'x-show="$store.conn.descriptorEditorOpen(entry._index, oi)"',
            self.devices,
        )
        self.assertNotIn(
            'x-show="$store.conn.descriptorEditor"',
            self.primus,
        )

    def test_telemetry_and_lock_recovery_are_visible_in_both_apps(self):
        for markup in (self.devices, self.primus):
            self.assertIn("telemetryHealthLabel", markup)
            self.assertIn("telemetryDiagnostics", markup)
            self.assertIn("telemetryBatterySummary", markup)
            self.assertIn("clearTelemetryTarget", markup)
            self.assertIn("enterProductionMode", markup)
            self.assertIn("requestBootWindowUnlock", markup)
            self.assertIn("Hello", markup)
        self.assertIn("never learned from ArtDmx or EOS traffic", self.devices)
        self.assertIn("ArtDmx/EOS never changes it", self.primus)
        self.assertIn("V3 recovery: hold D1", self.conn)
        self.assertIn("first 60 seconds", self.conn)

    def test_both_setup_apps_generation_gate_state_fetches(self):
        for script in (self.devices_app, self.primus_app):
            self.assertIn("async fetchState(shouldApply = null)", script)
            self.assertIn("_stateFetchGeneration", script)
            self.assertIn("_stateFetchAppliedGeneration", script)
            self.assertIn("generation < this._stateFetchAppliedGeneration", script)
            self.assertIn('typeof shouldApply === "function" && !shouldApply()', script)
        self.assertIn("refreshTelemetrySubmission", self.conn)
        self.assertIn("fetchState: false", self.conn)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for UI store runtime coverage")
    def test_rejected_newer_guard_does_not_suppress_older_valid_fetch(self):
        app_paths = [
            os.path.join(WEB_DIR, "js", "app-devices.js"),
            os.path.join(WEB_DIR, "js", "app-primus.js"),
        ]
        script = f"""
const fs = require("fs");
const vm = require("vm");
const appPaths = {json.dumps(app_paths)};
function response(state) {{
  return {{
    ok: true,
    status: 200,
    statusText: "OK",
    async text() {{ return JSON.stringify(state); }},
  }};
}}
(async () => {{
  for (const appPath of appPaths) {{
    const resolvers = [];
    const stores = {{
      conn: {{
        syncShowInfoDrafts() {{}},
        syncReceiveConfigDrafts() {{}},
        syncVirtualConfigDrafts() {{}},
        syncManagementUi() {{}},
      }},
    }};
    const context = {{
      console,
      URLSearchParams,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      fetch() {{ return new Promise(resolve => resolvers.push(resolve)); }},
      window: {{
        location: {{search: ""}},
        localStorage: {{getItem() {{ return null; }}, setItem() {{}}}},
      }},
      document: {{
        title: "",
        dispatchEvent() {{}},
        addEventListener(name, callback) {{
          if (name === "alpine:init") callback();
        }},
      }},
      CustomEvent: function CustomEvent() {{}},
      Alpine: {{
        store(name, value) {{
          if (arguments.length === 2) stores[name] = value;
          return stores[name];
        }},
      }},
    }};
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(appPath, "utf8"), context, {{filename: appPath}});
    const app = stores.app;
    const older = app.fetchState();
    const newer = app.fetchState(() => false);
    resolvers[1](response({{marker: "rejected-newer"}}));
    if (await newer) throw new Error(`${{appPath}} applied a rejected guarded fetch`);
    resolvers[0](response({{marker: "valid-older"}}));
    if (!(await older)) throw new Error(`${{appPath}} suppressed the older valid fetch`);
    if (app.state?.marker !== "valid-older" || app._stateFetchAppliedGeneration !== 1) {{
      throw new Error(`${{appPath}} advanced generation before guard acceptance`);
    }}
  }}
}})().catch(error => {{ console.error(error); process.exitCode = 1; }});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_radius_and_mobile_surfaces_do_not_expose_primus_setup(self):
        self.assertIn("!$store.app.isRadiusDevice(entry.dev)", self.devices)
        self.assertIn("!$store.app.mobileView", self.devices)
        self.assertIn("!isRadiusDevice(dev) && !!dev?.management_supported", self.conn)
        self.assertNotIn("apply_device_output_descriptor", self.radius)
        self.assertNotIn("enter_device_production_mode", self.radius)

    def test_presets_and_compact_setup_styles_are_present(self):
        self.assertIn("window.confirm(`Delete output preset", self.conn)
        self.assertIn("preset.built_in", self.devices)
        self.assertIn("selectedPreset(entry._index, oi)?.deletable", self.devices)
        self.assertIn("bulkApplyDescriptor", self.conn)
        for selector in (
            ".device-management-panel",
            ".device-descriptor-editor",
            ".device-descriptor-modal",
            ".device-telemetry-stats",
            ".device-order-preview",
        ):
            self.assertIn(selector, self.css)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for UI store runtime coverage")
    def test_shared_store_runtime_preserves_dirty_targets_and_rejects_fractions(self):
        conn_path = os.path.join(WEB_DIR, "js", "device-conn.js")
        script = f"""
const fs = require("fs");
const vm = require("vm");
global.window = {{}};
global.setTimeout = () => 0;
global.document = {{
  addEventListener(name, callback) {{ if (name === "alpine:init") callback(); }},
  dispatchEvent() {{}},
}};
const app = {{
  product: "primus",
  state: {{devices: []}},
  networkPrimaryInterface() {{ return {{source_ip: "127.0.0.9"}}; }},
  async fetchState() {{}},
  showNotice() {{}},
  showApiError(action, error) {{ throw error; }},
}};
global.Alpine = {{
  stores: {{app}},
  store(name, value) {{
    if (arguments.length === 2) this.stores[name] = value;
    return this.stores[name];
  }},
}};
global.api = async () => ({{ok: true}});
vm.runInThisContext(fs.readFileSync({json.dumps(conn_path)}, "utf8"), {{filename: "device-conn.js"}});
const conn = Alpine.store("conn");
function device(ip, target) {{
  return {{
    ip,
    telemetry_target: target,
    telemetry_configured: target !== "0.0.0.0",
    management_supported: true,
    capabilities: {{management: true}},
  }};
}}
(async () => {{
  app.state.devices = [device("127.0.0.2", "127.0.0.4")];
  conn.syncManagementUi();
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.4") throw new Error("initial target missing");
  conn.useSelectedSenderTelemetryTarget(0);
  app.state.devices[0].telemetry_target = "127.0.0.5";
  conn.syncManagementUi();
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.9") throw new Error("dirty draft overwritten");
  conn.resetTelemetryTargetDraft(0);
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.5") throw new Error("draft reset failed");
  conn.telemetryTargetDrafts[0] = "127.0.0.8";
  conn.markTelemetryTargetDirty(0);
  await conn.setTelemetryTarget(0);
  if (conn.telemetryTargetDirty[0]) throw new Error("successful apply left dirty state");
  conn.telemetryTargetDrafts[0] = "127.0.0.6";
  conn.markTelemetryTargetDirty(0);
  await conn.clearTelemetryTarget(0);
  if (conn.telemetryTargetDirty[0] || conn.telemetryTargetDrafts[0] !== "") {{
    throw new Error("successful clear retained draft state");
  }}
  let resolveApply;
  global.api = () => new Promise(resolve => {{ resolveApply = resolve; }});
  conn.telemetryTargetDrafts[0] = "127.0.0.10";
  conn.markTelemetryTargetDirty(0);
  const pendingApply = conn.setTelemetryTarget(0);
  conn.telemetryTargetDrafts[0] = "127.0.0.11";
  conn.markTelemetryTargetDirty(0);
  resolveApply({{ok: true}});
  await pendingApply;
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.11" || !conn.telemetryTargetDirty[0]) {{
    throw new Error("apply completion overwrote a newer edit");
  }}
  let resolveClear;
  global.api = () => new Promise(resolve => {{ resolveClear = resolve; }});
  const pendingClear = conn.clearTelemetryTarget(0);
  conn.telemetryTargetDrafts[0] = "127.0.0.12";
  conn.markTelemetryTargetDirty(0);
  resolveClear({{ok: true}});
  await pendingClear;
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.12" || !conn.telemetryTargetDirty[0]) {{
    throw new Error("clear completion overwrote a newer edit");
  }}
  let resolveReplacedDevice;
  global.api = () => new Promise(resolve => {{ resolveReplacedDevice = resolve; }});
  const replacedDeviceApply = conn.setTelemetryTarget(0);
  app.state.devices = [device("127.0.0.3", "127.0.0.7")];
  conn.syncManagementUi();
  resolveReplacedDevice({{ok: true}});
  await replacedDeviceApply;
  if (conn.telemetryTargetDrafts[0] !== "127.0.0.7" || conn.telemetryTargetDirty[0]) {{
    throw new Error("completed request mutated its replacement device");
  }}
  const mutationResolvers = [];
  const pendingFetches = [];
  global.api = () => new Promise(resolve => {{ mutationResolvers.push(resolve); }});
  app.fetchState = shouldApply => new Promise(resolve => {{
    pendingFetches.push({{
      resolveWith(target) {{
        const applied = typeof shouldApply !== "function" || shouldApply();
        if (applied) {{
          app.state = {{devices: [device("127.0.0.3", target)]}};
          conn.syncManagementUi();
        }}
        resolve(applied);
      }},
    }});
  }});
  conn.telemetryTargetDrafts[0] = "127.0.0.20";
  conn.markTelemetryTargetDirty(0);
  const olderRequest = conn.setTelemetryTarget(0);
  mutationResolvers[0]({{ok: true}});
  await Promise.resolve();
  await Promise.resolve();
  if (pendingFetches.length !== 1) throw new Error("older guarded fetch did not start");
  conn.telemetryTargetDrafts[0] = "127.0.0.21";
  conn.markTelemetryTargetDirty(0);
  const newerRequest = conn.setTelemetryTarget(0);
  mutationResolvers[1]({{ok: true}});
  await Promise.resolve();
  await Promise.resolve();
  if (pendingFetches.length !== 2) throw new Error("newer guarded fetch did not start");
  pendingFetches[1].resolveWith("127.0.0.21");
  await newerRequest;
  pendingFetches[0].resolveWith("127.0.0.20");
  await olderRequest;
  if (app.state.devices[0].telemetry_target !== "127.0.0.21"
      || conn.telemetryTargetDrafts[0] !== "127.0.0.21"
      || conn.telemetryTargetDirty[0]) {{
    throw new Error("out-of-order stale fetch replaced the newest telemetry state");
  }}
  global.api = async () => ({{ok: true}});
  app.fetchState = async () => {{}};
  const linear = {{
    enabled: true, layout: "linear", physical_pixels: 30.5, virtual_pixels: 30,
  }};
  if (conn.validateDescriptorDraft(linear).valid) throw new Error("fractional length accepted");
  const grid = {{
    enabled: true, layout: "grid", rows: 2.5, columns: 8,
    traversal_axis: "row_major", scan_pattern: "progressive",
    start_corner: "top_left", virtual_pixels: 10,
  }};
  if (conn.validateDescriptorDraft(grid).valid) throw new Error("fractional rows accepted");
  grid.rows = 4;
  grid.columns = 8.5;
  if (conn.validateDescriptorDraft(grid).valid) throw new Error("fractional columns accepted");
  grid.columns = 8;
  grid.virtual_pixels = 3.5;
  if (conn.validateDescriptorDraft(grid).valid) throw new Error("fractional virtual accepted");
}})().catch(error => {{ console.error(error); process.exitCode = 1; }});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
