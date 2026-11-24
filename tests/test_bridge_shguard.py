"""Exercise sh-guard through the controller listener, separately from the MCP listener."""
import gc
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
from test_connected_mvp import ServiceHarness, request


def guard_bridge(case, directory, release=None):
    """Real authenticated HTTP, with the service host's tool directory kept separate."""
    state = tempfile.TemporaryDirectory(prefix="aitl-guard-test-")
    case.addCleanup(state.cleanup)
    store = a.BridgeStore(state.name, uuid.uuid4().hex)
    harness = ServiceHarness(store, *store.issue("CONTROLLER"), *store.issue("AI"))
    case.addCleanup(harness.close)
    harness.service.service_directory = directory
    if release:
        case.enterContext(mock.patch.object(a, "RISK_RELEASES", {release.target: release}))
    # The controller still uses BridgeGuardClient and real HTTP for every operation.
    owned = SimpleNamespace(profile=harness.profile, instance=store.instance, close=lambda: None)
    case.enterContext(mock.patch.object(a, "LocalBridgeProcess", return_value=owned))
    return harness


class BridgeGuardContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "bridge-tools"
        self.bridge = guard_bridge(self, self.directory)
        self.client = a.BridgeHTTP(self.bridge.profile)

    def test_inspect_without_install_and_controller_only_management(self):
        state = self.client.request("GET", a.SH_GUARD_PATH)
        self.assertEqual(state["state"], "INSTALL_CONFIRM")
        self.assertFalse(self.directory.exists())
        headers = {"Authorization": "Bearer " + self.bridge.ai}
        for path in (a.SH_GUARD_PATH, a.SH_GUARD_PATH + "/setup", a.SH_GUARD_PATH + "/analyze"):
            method = "GET" if path == a.SH_GUARD_PATH else "POST"
            self.assertEqual(request(self.bridge.profile.url, method, path, headers=headers)[0], 401)
        self.assertEqual(request(self.bridge.mcp_url, "POST", a.SH_GUARD_PATH + "/setup", {})[0], 404)
        self.assertTrue(all("guard" not in tool["name"] for tool in a.BRIDGE_TOOLS))

    def test_stale_instance_generation_and_unknown_operations_are_rejected(self):
        status = self.client.request("GET", a.SH_GUARD_PATH)
        setup = {"version": 1, "instance": status["instance"], "generation": 0, "action": "check"}
        self.client.request("POST", a.SH_GUARD_PATH + "/setup", setup)
        for edits in ({"action": "install"}, {"instance": "0"*32}, {"action": "unlisted"},
                      {"binary": "/somewhere"}):
            with self.subTest(edits=edits), self.assertRaises(a.TransportError):
                self.client.request("POST", a.SH_GUARD_PATH + "/setup", dict(setup, **edits))
        self.assertFalse(self.directory.exists())

    def test_older_bridge_reports_upgrade_while_the_paired_connection_remains_usable(self):
        self.bridge.service.routes["CONTROLLER"].pop(a.SH_GUARD_PATH)
        endpoint = a.BridgeGuardClient(self.bridge.profile, self.bridge.store.instance, None)
        try:
            deadline = time.monotonic() + 5
            while endpoint.status["state"] == "CHECKING_TOOL" and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertEqual(endpoint.status.get("error"), "risk_bridge_update_required")
            self.assertEqual(self.client.request("GET", "/v1/status")["instance"], self.bridge.store.instance)
            a.LocalBridgeProcess.assert_not_called()
        finally:
            endpoint.close()
            endpoint.thread.join(5)

    def test_saved_local_opt_in_does_not_send_to_a_remote_or_fall_back(self):
        preferences = a.PreferenceStore(Path(self.temp.name) / "controller")
        preferences.save_command_risk(True)
        profile = dict(url="https://127.0.0.1:8443", pin="1"*64, token="2"*64,
                       conversation="3"*32, controller_id="4"*32, mode="REMOTE")
        connections = mock.Mock()
        connections.load_connection.return_value = {"profile": profile, "qrexec": {"target": "analysis", "port": 8443}}
        core = a.AppCore(preferences, connections)
        self.addCleanup(core.close)
        self.assertFalse(core.risk_requested)
        core.request_command_risk(True)
        self.assertEqual(core.command_risk_snapshot().error, "risk_bridge_disconnected")
        a.LocalBridgeProcess.assert_not_called()
        self.assertEqual(core.guard_location()[1], "analysis")
        # Even copies of a paired profile in two Qubes have distinct destinations.
        core.saved_connection["qrexec"]["target"] = "analysis-two"
        core.guard_status()
        self.assertFalse(core.risk_requested)
        a.LocalBridgeProcess.assert_not_called()

    def test_oversized_and_output_requests_never_reach_the_cli(self):
        status = self.client.request("GET", a.SH_GUARD_PATH)
        data = {"version": 1, "instance": status["instance"], "generation": 0, "review_id": uuid.uuid4().hex,
                "revision": 1, "final_return": False, "text": "x"*4097, "sha256": "0"*64}
        with mock.patch.object(a, "run_command_risk") as scan:
            for changes in ({}, {"text": "printf x", "direction": "TO_OUTPUT_SINK"}):
                with self.assertRaises(a.TransportError):
                    self.client.request("POST", a.SH_GUARD_PATH + "/analyze", dict(data, **changes))
            scan.assert_not_called()


class LocalGuardCompatibilityTests(unittest.TestCase):
    def test_unsafe_tool_directory_does_not_interrupt_local_bridge_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            actual, link = base / "actual", base / "alias"
            actual.mkdir(mode=0o700)
            link.symlink_to(actual, target_is_directory=True)
            bridge = a.LocalBridgeProcess(link)
            try:
                client = a.BridgeHTTP(bridge.profile)
                self.assertEqual(client.request("GET", "/v1/status")["instance"], bridge.instance)
                status = client.request("GET", a.SH_GUARD_PATH)
                self.assertEqual((status["state"], status["error"]), ("UNAVAILABLE", "risk_directory"))
                self.assertFalse((actual / "tools").exists())
            finally:
                bridge.close()


@unittest.skipUnless(os.environ.get("DISPLAY"), "controlled Tk display not supplied")
class BridgeManagementTests(unittest.TestCase):
    def test_general_owns_pairing_and_services_keep_their_own_settings(self):
        from tkinter import ttk
        with tempfile.TemporaryDirectory() as directory:
            store = a.BridgeStore(Path(directory), uuid.uuid4().hex)
            self.addCleanup(store.close)
            pin = "ab" * 32
            build = mock.Mock(side_effect=lambda parent: a.build_guard_settings(parent, "bridge-test",
                lambda: {"state": "INSTALL_CONFIRM", "instance": store.instance}, mock.Mock(), english=True))
            window = a.show_bridge_management(None, lambda: "bridge-test",
                lambda: "PAIRED" if store.controller_paired() else "UNPAIRED",
                build, pairing=(pin, store.open_pair), english=True)
            try:
                window.update()
                tabs = window.children["tabs"]
                general, services = tabs.children["general"], tabs.children["services"]
                self.assertEqual([tabs.tab(page, "text") for page in tabs.tabs()], ["General", "Services"])
                self.assertEqual(tabs.select(), str(general))
                self.assertEqual(general.children["status"].cget("text"), "Awaiting pairing")
                build.assert_not_called()
                self.assertIsNone(store.pair)
                button, = [w for w in general.winfo_children() if isinstance(w, ttk.Button)]
                self.assertEqual(button.cget("text"), "Pair main application")
                with mock.patch("tkinter.messagebox.showinfo") as dialog:
                    button.invoke()
                message = dialog.call_args.args[1]
                self.assertIn(pin, message)
                code = message.split("\n\n")[1]
                claim = store.claim({"code": code, "request_id": uuid.uuid4().hex})
                store.confirm(claim["token"])
                tabs.select(services)
                window.update()
                build.assert_called_once_with(services)
                panel, = services.winfo_children()
                self.assertIn("Install on bridge-test", panel.buttons["install"].cget("text"))
                self.assertNotIn(pin, panel.details.get("1.0", "end"))
                self.assertNotIn(code, panel.details.get("1.0", "end"))
                tabs.select(general)
                window.update()
                self.assertEqual(general.children["status"].cget("text"), "Paired")
                self.assertEqual(button.cget("text"), "Pair main application again")
                self.assertIsNone(store.pair)
            finally:
                window.destroy()
                window = tabs = general = services = panel = button = build = None
                gc.collect()


@unittest.skipUnless(os.environ.get("AITL_TEST_SH_GUARD_ARCHIVE"), "official sh-guard archive not supplied")
class PairedGuardTests(unittest.TestCase):
    def test_real_bridge_gui_and_pinned_https_analyze_only_on_the_paired_host(self):
        with tempfile.TemporaryDirectory() as directory:
            host, personal = Path(directory) / "bridge", Path(directory) / "personal"
            archive = Path(os.environ["AITL_TEST_SH_GUARD_ARCHIVE"]).read_bytes()
            installation = a.CommandRiskInstallation(host, a.command_risk_release())
            installation.install(threading.Event(), lambda _: None, lambda *_: archive)
            args = [sys.executable, "-I", a.__file__, "--bridge", "--bind", "127.0.0.1", "--port", "0",
                    "--state-dir", str(host), "--pair"]
            if os.environ.get("DISPLAY"):
                args.append("--gui")
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            core = a.AppCore(a.PreferenceStore(personal), a.ConnectionStore(personal))
            try:
                info = json.loads(child.stdout.readline())
                for line in child.stdout:
                    if line.startswith("PAIR CODE"):
                        code = line.split(": ", 1)[1].strip()
                        break
                else:
                    self.fail("Bridge did not open its pairing window")
                profile = core.pair_remote("https://127.0.0.1:%d" % info["port"], info["pin"], code)
                core.connect_profile(profile)
                def until(predicate):
                    deadline = time.monotonic() + 22
                    while time.monotonic() < deadline:
                        core.pump()
                        result = core.command_risk_snapshot()
                        if predicate(result):
                            return result
                        time.sleep(.05)
                    self.fail("Bridge review timed out: " + str(core.risk_setup_error))
                until(lambda _: core.bridge_state == "CONNECTED")
                review = core.review_command("printf hello")
                core.request_command_risk(True)
                first = until(lambda result: result.state == "RESULT")
                self.assertEqual(first.result.key.review_id, review.id)
                self.assertEqual(first.result.data["command"], review.text)
                edited = core.edit_review(review.id, "printf next", False)
                second = until(lambda result: result.state == "RESULT" and result.result.key.revision == edited.revision)
                self.assertEqual(second.result.data["command"], edited.text)
                self.assertFalse((personal / "tools").exists())
                self.assertEqual(core.review_state, "REVIEW")
                if os.environ.get("DISPLAY"):
                    # Opening management again must target the running service.
                    again = subprocess.run([*args[:args.index("--pair")], "--gui"], capture_output=True, timeout=10)
                    self.assertEqual(again.returncode, 0)
                    self.assertEqual(a.BridgeHTTP(profile).request("GET", a.SH_GUARD_PATH)["instance"], info["instance"])
                core.disconnect_bridge()
                self.assertEqual(core.command_risk_snapshot().error, "risk_bridge_disconnected")
                self.assertFalse((personal / "tools").exists())
            finally:
                core.close()
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                child.stdout.close()


if __name__ == "__main__":
    unittest.main()
