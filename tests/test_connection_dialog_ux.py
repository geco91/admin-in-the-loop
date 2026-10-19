"""Real Tk widgets; Qubes/network transitions are explicitly controlled fixtures."""
import gc
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a


@unittest.skipUnless(os.environ.get("DISPLAY"), "Tk display required")
class ConnectionUXTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory()
        self.core = a.AppCore(connection_store=a.ConnectionStore(Path(self.temp.name) / "config"))
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *_: self.errors.append("callback")
        self.ui = a.ReviewUI(self.root, self.core)
        with mock.patch.object(a, "qubes_detected", return_value=True), \
                mock.patch.object(a, "source_qube_name", return_value="personal"):
            self.dialog = self.ui.connection_settings()
        self.root.update()

    def tearDown(self):
        self.core.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.ui = self.dialog = self.root = self.core = None
        gc.collect()
        self.temp.cleanup()
        self.assertFalse(self.errors)

    def test_every_qubes_page_keeps_navigation_visible_at_small_and_normal_sizes(self):
        dialog = self.dialog
        dialog.location.set("QREXEC")
        dialog.fields["qrexec_target"].set("ai-bridge")
        for size in ("640x480", "860x780"):
            dialog.window.geometry(size)
            for page in range(5):
                dialog.wizard_goto(page)
                self.root.update()
                navigation = (dialog.buttons["wizard_back"],) if page == 4 else (
                    dialog.buttons["wizard_back"], dialog.buttons["wizard_next"])
                for button in navigation:
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                         dialog.window.winfo_rooty()+dialog.window.winfo_height())
                dialog.canvas.yview_moveto(1)
                self.root.update()
                self.assertGreaterEqual(dialog.navigation.winfo_rooty(),
                                        dialog.canvas.winfo_rooty()+dialog.canvas.winfo_height())

    def test_copy_command_tracks_custom_port_and_navigation_does_not_connect(self):
        dialog = self.dialog
        with mock.patch.object(self.core, "verify_qrexec_connection") as check, \
                mock.patch.object(self.core, "hello_bridge") as hello:
            dialog.location.set("QREXEC")
            dialog.fields["qrexec_target"].set("ai-bridge")
            dialog.fields["qrexec_port"].set("9443")
            dialog.wizard_next()
            self.root.update()
            self.assertTrue(dialog.buttons["wizard_next"].instate(["disabled"]))
            dialog.buttons["qrexec_copy_command"].invoke()
            command = self.root.clipboard_get()
            self.assertEqual(command, "python3 ./admin_in_the_loop.py --bridge --port 9443")
            self.assertIn(command, dialog.qrexec_command_box.text.get("1.0", "end"))
            check.assert_not_called()
            hello.assert_not_called()

    def test_recovery_guidance_uses_saved_qube_and_does_not_start_from_observation(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.connection_store.save_connection(profile, None, {"target": "ai-bridge", "port": 8443})
        self.dialog.window.destroy()
        self.core.saved_connection = self.core.connection_store.load_connection()
        self.core.recovery_state = "NEEDS_ATTENTION"
        self.core.recovery_error = "qrexec_target_unreachable"
        with mock.patch.object(a, "qubes_detected", return_value=True), \
                mock.patch.object(self.core, "retry_connection_recovery") as retry, \
                mock.patch.object(self.core, "hello_bridge") as hello:
            dialog = self.dialog = self.ui.connection_settings()
            self.root.update()
            self.assertTrue(dialog.recovery_panel.winfo_ismapped())
            self.assertIn("bereits eingerichtet", dialog.recovery_notice.get())
            dialog.buttons["recovery_setup"].invoke()
            self.assertEqual(dialog.fields["qrexec_target"].get(), "ai-bridge")
            self.assertEqual(dialog.wizard_index, 1)
            self.root.update()
            self.assertFalse(dialog.recovery_panel.winfo_ismapped())
            retry.assert_not_called()
            hello.assert_not_called()
            dialog.buttons["recovery_retry"].invoke()
            retry.assert_called_once()

    def test_layer_status_does_not_claim_verified_ai_from_tunnel_or_chat_code(self):
        self.core.bridge_profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.bridge_state, self.core.bridge_instance = "CONNECTED", "e"*32
        self.core.remote_tunnel = {"phase": "connected"}
        self.core.chat_binding = {"code": "ABCDEFGH", "generation": 1, "status": "ACTIVE", "server_time": 100,
                                  "expires_at": 86500, "retry_at": None, "restriction_scope": None}
        self.core.chat_binding_received_at = time.monotonic()
        self.dialog.render_connection_layers(self.core.bridge_snapshot())
        self.assertEqual(self.dialog.layer_labels["Bridge"].cget("text"), "Bridge: verbunden")
        self.assertEqual(self.dialog.layer_labels["Secure Tunnel"].cget("text"), "Secure Tunnel: verbunden")
        self.assertIn("im Chat prüfen", self.dialog.layer_labels["Chat"].cget("text"))
        self.core.chat_binding["status"] = "EXPIRED"
        self.dialog.render_connection_layers(self.core.bridge_snapshot())
        self.assertNotIn("Code bereit", self.dialog.layer_labels["Chat"].cget("text"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
