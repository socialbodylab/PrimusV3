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

    def test_device_manager_monitor_groups_by_performer(self):
        # The Monitor tab is performer-first: one section per performer, then a
        # single Unassigned section. The old product/status bucketing
        # (Primus/Radius x Attention/Online/Offline) is gone as a LAYOUT
        # mechanism; status is expressed in place (pill, rollup badge, card
        # border tint).
        for member in (
            "get performerGroups()",
            "get unassignedEntries()",
            "get monitorSections()",
            "syncExpandedCards()",
            "saveIdentityEditor()",
            "_frozenGroupOrder",
        ):
            self.assertIn(member, self.devices_app)
        for helper in ("deviceKey(dev)", "performerKey(dev)", "hasPerformer(dev)"):
            self.assertIn(helper, self.conn)
        # Sections and cards are keyed by stable identity, never array index,
        # so DOM (and expand state) survives device removal and re-sync...
        self.assertIn(
            'x-for="section in $store.app.monitorSections" :key="section.key"',
            self.devices,
        )
        self.assertIn('x-for="entry in section.entries" :key="entry.key"', self.devices)
        self.assertNotIn(':key="entry._index"', self.devices)
        # ...while device actions still address the backend by array index.
        self.assertIn("entry._index", self.devices)
        self.assertNotIn("productSectionList", self.devices)
        self.assertNotIn("'dm-card-' + entry._section", self.devices)
        # Identity editor + datalists of existing names.
        self.assertIn("dm-character-name-options", self.devices)
        self.assertIn("dm-performer-name-options", self.devices)
        self.assertIn("toggleIdentityEditor", self.devices)
        for selector in (
            ".dm-performer-section",
            ".dm-performer-grid",
            ".dm-identity-editor",
            ".dm-card-attention",
            ".dm-card-online",
            ".dm-card-offline",
        ):
            self.assertIn(selector, self.css)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for UI store runtime coverage")
    def test_performer_grouping_runtime_is_stable_and_index_preserving(self):
        app_path = os.path.join(WEB_DIR, "js", "app-devices.js")
        conn_path = os.path.join(WEB_DIR, "js", "device-conn.js")
        script = f"""
const fs = require("fs");
const vm = require("vm");
const stores = {{}};
const context = {{
  console,
  URLSearchParams,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  fetch() {{ return new Promise(() => {{}}); }},
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
vm.runInContext(fs.readFileSync({json.dumps(app_path)}, "utf8"), context, {{filename: "app-devices.js"}});
vm.runInContext(fs.readFileSync({json.dumps(conn_path)}, "utf8"), context, {{filename: "device-conn.js"}});
const app = stores.app;
const devices = [
  {{name: "zoe-led", ip: "10.0.0.2", performer_name: "Zoe", character_name: "Queen",
    receiver_online: true, capabilities: {{}}}},
  {{name: "zoe-audio", ip: "10.0.0.3", performer_name: "  zoe ", is_radius: true,
    receiver_online: false}},
  {{name: "amy-led", ip: "10.0.0.1", performer_name: "Amy", character_name: "Page",
    receiver_online: true, battery_pct: 5, capabilities: {{battery: true}}}},
  {{name: "fresh", ip: "10.0.0.9", receiver_online: true, capabilities: {{}}}},
];
app.state = {{devices}};
const groups = app.performerGroups;
if (groups.map(g => g.key).join(",") !== "amy,zoe") {{
  throw new Error("groups not sorted alphabetically: " + groups.map(g => g.key));
}}
const zoe = groups[1];
if (zoe.devices.map(e => e.key).join(",") !== "10.0.0.2,10.0.0.3") {{
  throw new Error("zoe devices not primus-first/key-ordered");
}}
if (zoe.devices.map(e => e._index).join(",") !== "0,1") {{
  throw new Error("entry._index not preserved for backend addressing");
}}
if (!zoe.hasPrimus || !zoe.hasRadius || zoe.performerName !== "Zoe") {{
  throw new Error("zoe group shape wrong (whitespace/case merge failed)");
}}
if (groups[0].worstStatus !== "attention" || zoe.worstStatus !== "offline") {{
  throw new Error("worstStatus rollup wrong");
}}
if (app.unassignedEntries.map(e => e.key).join(",") !== "10.0.0.9") {{
  throw new Error("unassigned bucket wrong");
}}
const sections = app.monitorSections;
if (sections.map(s => s.key).join(",") !== "perf:amy,perf:zoe,unassigned") {{
  throw new Error("monitor sections wrong: " + sections.map(s => s.key));
}}
// Flip every volatile status field and reverse backend order: positions
// must not move (stability contract).
const shuffled = [devices[3], devices[1], devices[0], devices[2]].map(d => ({{...d}}));
shuffled.forEach(d => {{ d.receiver_online = !d.receiver_online; }});
shuffled[3].battery_pct = 100;
shuffled[2].transport_error = "send failed";
app.state = {{devices: shuffled}};
const after = app.performerGroups;
if (after.map(g => g.key).join(",") !== "amy,zoe") {{
  throw new Error("group order changed after status flap/re-sync");
}}
if (after[1].devices.map(e => e.key).join(",") !== "10.0.0.2,10.0.0.3") {{
  throw new Error("device order changed after status flap/re-sync");
}}
if (after[1].devices.map(e => e._index).join(",") !== "2,1") {{
  throw new Error("entry._index did not track the new backend positions");
}}
// Expand state is keyed by device key and pruned by the reconciler.
app.expandedCards = {{"10.0.0.2": true, "10.9.9.9": true}};
app.syncExpandedCards();
if (!app.expandedCards["10.0.0.2"] || app.expandedCards["10.9.9.9"]) {{
  throw new Error("syncExpandedCards did not prune by stable key");
}}
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
