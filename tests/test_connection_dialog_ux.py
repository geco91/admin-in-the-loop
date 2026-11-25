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
            self.dialog = self.ui.open_bridge_management()
        self.remote = self.dialog.core
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
            for page in range(3):
                dialog.wizard_goto(page)
                self.root.update()
                navigation = (dialog.buttons["wizard_back"],) if page == 2 else (
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
        with mock.patch.object(self.remote, "verify_qrexec_connection") as check, \
                mock.patch.object(self.remote, "hello_bridge") as hello:
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
        self.remote.saved_connection = self.core.connection_store.load_connection()
        self.remote.recovery_state = "NEEDS_ATTENTION"
        self.remote.recovery_error = "qrexec_target_unreachable"
        with mock.patch.object(a, "qubes_detected", return_value=True), \
                mock.patch.object(self.remote, "retry_connection_recovery") as retry, \
                mock.patch.object(self.remote, "hello_bridge") as hello:
            dialog = self.dialog = self.ui.open_bridge_management()
            self.root.update()
            self.assertTrue(dialog.recovery_panel.winfo_ismapped())
            self.assertIn("Gespeicherte Einrichtung gefunden" if a.UI_LANGUAGE == "de" else "Saved setup found",
                          dialog.recovery_notice.get())
            with mock.patch.object(dialog.core, "retry_connection_recovery",
                                   side_effect=a.ProbeError("setup_busy")):
                dialog.run("bridge", dialog.core.retry_connection_recovery)
            self.root.update()
            error_labels = [widget for widget in dialog.recovery_panel.winfo_children()
                            if "textvariable" in widget.keys()
                            and str(widget.cget("textvariable")) == str(dialog.errors["bridge"])]
            self.assertTrue(error_labels)
            self.assertTrue(error_labels[0].winfo_ismapped())
            self.assertIn("Einrichtung läuft", dialog.errors["bridge"].get())
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
        self.dialog.window.destroy()
        self.dialog = self.ui.connection_settings()
        self.dialog.render_connection_layers(self.core.bridge_snapshot())
        self.assertEqual(self.dialog.layer_labels["Bridge"].cget("text"), "Bridge: verbunden")
        self.assertEqual(self.dialog.layer_labels["Secure Tunnel"].cget("text"), "Secure Tunnel: verbunden")
        self.assertIn("im Chat prüfen", self.dialog.layer_labels["Chat"].cget("text"))
        self.core.chat_binding["status"] = "EXPIRED"
        self.dialog.window.destroy()
        self.dialog = self.ui.connection_settings()
        self.dialog.render_connection_layers(self.core.bridge_snapshot())
        self.assertNotIn("Code bereit", self.dialog.layer_labels["Chat"].cget("text"))

    def test_retry_button_keeps_repeated_failure_visible_in_dialog_and_sidebar(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.connection_store.save_connection(profile)
        self.dialog.window.destroy()
        self.dialog = self.ui.open_bridge_management()
        with mock.patch.object(self.remote, "connect_profile", side_effect=a.ProbeError("network_unavailable")):
            for attempt in (1, 2):
                self.dialog.buttons["recovery_retry"].invoke()
                self.root.update()
                self.assertTrue(self.dialog.recovery_panel.winfo_ismapped())
                self.assertIn("Versuch %d: fehlgeschlagen" % attempt, self.dialog.recovery_notice.get())
                self.assertIn("Gateway/Bridge nicht erreichbar", self.dialog.recovery_notice.get())
                self.assertIn("offline", self.ui.bridge_footer_status.get())
                self.assertEqual(self.core.recovery_attempt, 0)


class LanguagePreferenceTests(unittest.TestCase):
    def test_location_update_preserves_another_services_saved_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            prefs = a.PreferenceStore(Path(directory) / "settings")
            prefs._save({"output-review": "REMOTE"}, "service-locations.json")
            prefs.save_service_location("sh-guard", "LOCAL")
            self.assertEqual(prefs.service_locations(), {"output-review": "REMOTE", "sh-guard": "LOCAL"})

    def tearDown(self):
        a.configure_ui_language()

    def test_locale_precedence_and_english_fallback(self):
        for env, expected in (({'LANG': 'de_DE.UTF-8'}, 'de'),
                              ({'LANG': 'de-CH'}, 'de'),
                              ({'LANG': 'fr_FR.UTF-8'}, 'en'),
                              ({'LANG': 'de_DE', 'LC_MESSAGES': 'en_GB'}, 'en'),
                              ({'LANG': 'en_US', 'LC_ALL': 'de_AT'}, 'de'),
                              ({'LANG': 'de_DE', 'LC_ALL': 'C.UTF-8'}, 'en')):
            with self.subTest(env=env):
                self.assertEqual(a.system_ui_language(env), expected)

    def test_language_round_trip_preserves_existing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            store = a.PreferenceStore(Path(directory) / 'config')
            self.assertEqual(store.load_language(), 'system')
            store.save(False, 'LARGE')
            store.save_text_review(True, 'output')
            store.save_language('de')
            reloaded = a.PreferenceStore(store.directory)
            self.assertEqual(reloaded.load_language(), 'de')
            self.assertEqual(reloaded.load(), (False, 'LARGE'))
            self.assertTrue(reloaded.load_text_review('output'))
            with self.assertRaises(a.ProbeError):
                store.save_language('fr')

    def test_catalog_preserves_format_fields_and_unrecognized_payload(self):
        import re
        pattern = r'%(?:[0-9.]*[dsfX])'
        for source, translated in a.UI_ENGLISH.items():
            self.assertEqual(re.findall(pattern, source), re.findall(pattern, translated), source)
        for language in ('de', 'en'):
            a.configure_ui_language(language)
            payload = "printf 'untranslated payload ä\\n'"
            self.assertEqual(a.tr(payload), payload)


@unittest.skipUnless(os.environ.get('DISPLAY'), 'Tk display required')
class LanguageUITests(unittest.TestCase):
    def test_both_languages_orange_gate_and_saved_choice_preserve_review(self):
        import tkinter as tk
        for language, expected, clipboard in (('en', 'Command proposal available', 'Clipboard'),
                                               ('de', 'Command-Vorschlag vorhanden', 'Zwischenablage')):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                store = a.PreferenceStore(Path(directory) / 'config')
                store.save_language(language)
                core = a.AppCore(preference_store=store)
                root = tk.Tk()
                errors = []
                root.report_callback_exception = lambda *args: errors.append(args)
                try:
                    ui = a.ReviewUI(root, core)
                    root.update()
                    self.assertEqual(ui.output_mode.get(), clipboard)
                    core.connection = "STARTING_SHELL"
                    core._event({"type": "ready", "session": "a" * 36})
                    ui.render()
                    ui.output_mode.set('Last 20' if language == 'en' else 'Letzte 20')
                    ui.change_output_mode()
                    self.assertEqual(core.output_mode, 'LAST_20')
                    ui.command_target.set(clipboard)
                    ui.change_command_target()
                    self.assertEqual(core.output_mode, 'CLIPBOARD')
                    ui.provider_picker.set('Local AI')
                    with mock.patch.object(ui.messagebox, 'showinfo') as unavailable:
                        ui.change_ai_provider()
                        unavailable.assert_called_once_with('Local AI', 'Not implemented yet.' if language == 'en'
                                                            else 'Noch nicht implementiert.', parent=root)
                    self.assertEqual(ui.provider_picker.get(), 'ChatGPT Secure MCP')
                    dialog = ui.connection_settings()
                    root.update()
                    if language == 'en':
                        self.assertEqual(dialog.layer_labels['Secure Tunnel'].cget('text'), 'Secure Tunnel: pending')
                    dialog.window.destroy()
                    core.review_command("printf 'payload ä'")
                    proposal = core.add_proposal("printf 'next'")
                    ui.render()
                    review = core.review
                    self.assertIn(expected, ui.readiness.cget('text'))
                    self.assertEqual(ui.readiness.cget('background'), '#ffcc99')
                    self.assertTrue(ui.from_ai_button.instate(['disabled']))
                    self.assertIn(proposal, core.inbox)
                    self.assertEqual(a.ConnectionDialog.error_text('network_unavailable').startswith(
                        'Gateway/bridge' if language == 'en' else 'Gateway/Bridge'), True)
                    ui.language.set('Deutsch' if language == 'en' else 'English')
                    with mock.patch.object(ui.messagebox, 'showinfo') as notice:
                        ui.change_language()
                        notice.assert_called_once()
                    self.assertIs(core.review, review)
                    self.assertEqual(a.UI_LANGUAGE, language)  # Apply only after restart.
                    self.assertEqual(store.load_language(), 'de' if language == 'en' else 'en')
                    self.assertEqual(core.review.payload, review.payload)
                    self.assertFalse(errors)
                finally:
                    core.close()
                    for callback in root.tk.call('after', 'info'):
                        root.after_cancel(callback)
                    root.destroy()
                    gc.collect()
        a.configure_ui_language()


if __name__ == "__main__":
    unittest.main(verbosity=2)
