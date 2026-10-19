"""Tk/xterm smoke test under a virtual display; no external Python test library.
Run from repo root: xvfb-run -a -s '-screen 0 1920x1080x24' python3 tests/gui_smoke_test.py
This is not a macOS or manual desktop acceptance test.
"""
import os
import json
import shutil
import subprocess
import gc
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stderr
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
from test_connected_mvp import mcp, RemoteFixture
from test_local_setup import fake_brew


class GUISmokeTests(unittest.TestCase):
    def test_native_tk_terminal_review_and_connection_dialog(self):
        with tempfile.TemporaryDirectory(prefix="aitl-gui-") as directory:
            preferences = Path(directory, "config")
            core = a.AppCore(a.PreferenceStore(preferences), a.ConnectionStore(preferences))
            root = tk.Tk()
            core.start_local(directory)
            ui = a.ReviewUI(root, core)
            original = ui.messagebox.showerror
            failures = []
            ui.messagebox.showerror = lambda *args, **kwargs: failures.append("gui_error")
            try:
                root.update()
                self.assertEqual(ui.editor.text.cget("wrap"), "word")
                self.assertGreater(ui.editor.frame.winfo_width(), ui.readiness.winfo_width())
                self.assertLessEqual(abs(ui.from_terminal_button.winfo_rooty() - ui.from_ai_button.winfo_rooty()), 1)
                self.assertLessEqual(abs(ui.from_ai_button.winfo_rooty() - ui.approve_button.winfo_rooty()), 1)
                self.assertEqual(ui.preference.get(), "SMALL")
                self.assertEqual(core.output_mode, "LAST_20")
                self.assertEqual(ui.output_mode.get(), "Letzte 20")
                self.assertTrue(ui.terminal_button.winfo_ismapped())
                ui.output_mode.set("Letzte 50")
                ui.change_output_mode()
                self.assertEqual(core.output_mode, "LAST_50")
                ui.output_mode.set("Letzte 20")
                ui.change_output_mode()
                self.assertEqual(core.output_mode, "LAST_20")
                ui.open_terminal()
                def until(predicate, timeout=8):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        root.update()
                        if predicate():
                            return
                        time.sleep(0.01)
                    raise a.ProbeError("gui_smoke_timeout")
                until(lambda: core.connection == "CONNECTED")
                self.assertFalse(ui.terminal_button.winfo_ismapped())
                self.assertIn("Terminal verbunden", ui.terminal_status.get())
                ui.action(lambda: core.add_proposal("printf 'Hello Admin in the Loop\\n'"))
                ui.from_ai_button.invoke()
                root.update()
                self.assertEqual(core.review_state, "REVIEW")
                self.assertTrue(ui.return_row.winfo_ismapped())
                self.assertTrue(ui.final_return.get())
                with mock.patch.object(ui.messagebox, "askyesno", return_value=True):
                    ui.approve_button.invoke()
                    until(lambda: core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
                    if core.review_state == "OVERRIDE_REQUIRED":
                        ui.approve_button.invoke()
                        until(lambda: core.review_state == "TRANSFERRED")
                until(lambda: core.output_mode == "SINCE_LAST" and b"Hello Admin in the Loop\r\n" in core.output.data)
                ui.from_terminal_button.invoke()
                root.update()
                self.assertFalse(ui.return_row.winfo_ismapped())
                self.assertEqual(core.review.direction, "TO_OUTPUT_SINK")
                ui.reject_button.invoke()
                ui.connection_settings()
                root.update()
                self.assertTrue(any(isinstance(widget, tk.Toplevel) for widget in root.winfo_children()))
                dialog = ui.connection_dialog
                remote_command = dialog.remote_command_box.text.get("1.0", "end-1c")
                self.assertIn("admin_in_the_loop.py --bridge", remote_command)
                self.assertIn("--tls-name bridge.example", remote_command)
                self.assertIsNone(core.bridge_process)
                core.connect_local_bridge()  # Exercise the transport smoke without real Platform credentials.
                until(lambda: core.bridge_state == "CONNECTED")
                until(lambda: core.chat_binding is not None)
                self.assertIn("Lokale Bridge verbunden", dialog.summary.get())
                shown = core.chat_binding["code"][:4] + "-" + core.chat_binding["code"][4:]
                self.assertEqual(ui.chat_code.get(), shown)
                self.assertTrue(ui.chat_code_copy.instate(["!disabled"]))
                ui.chat_code_copy.invoke()
                self.assertEqual(root.clipboard_get(), shown)
                dialog.buttons["chat_show"].invoke()
                self.assertEqual(dialog.binding.get(), shown)
                dialog.buttons["chat_copy"].invoke()
                self.assertEqual(root.clipboard_get(), shown)
                mcp(core.bridge_process, "submit_proposal", {"request_id": "GUI_SMOKE_REQUEST_0001", "text": "printf 'GUI_MCP\\n'"})
                until(lambda: bool(core.inbox))
                ui.from_ai_button.invoke()
                until(lambda: core.review_state == "TAKE_PENDING")
                root.update()
                self.assertIn("Übernahme wird bestätigt", ui.review_status.get())
                self.assertTrue(ui.approve_button.instate(["disabled"]))
                until(lambda: core.review_state == "REVIEW")
                root.update()
                self.assertTrue(core.review.proposal_id)
                self.assertEqual(ui.editor.text.cget("state"), "disabled")
                # An output OSC 52 must not silently replace this isolated X clipboard.
                root.clipboard_clear()
                root.clipboard_append("GUI_CLIPBOARD_CANARY")
                root.update()
                core.reject(core.review.id)
                review = core.review_command("printf '\\033]52;c;UkVQTEFDRUQ=\\007'; printf 'OSC52_DONE\\n'", True)
                core.approve(review.id)
                until(lambda: core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
                if core.review_state == "OVERRIDE_REQUIRED":
                    core.approve(review.id, True)
                until(lambda: b"OSC52_DONE\r\n" in core.output.data)
                root.update()
                self.assertEqual(root.clipboard_get(), "GUI_CLIPBOARD_CANARY")
                self.assertEqual(failures, [])
            finally:
                ui.messagebox.showerror = original
                # Unlike normal app-close, deliberately end the isolated test terminal.
                if core.channel:
                    try:
                        review = core.review_command("exit", True)
                        core.approve(review.id)
                        until(lambda: core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"}, 2)
                        if core.review_state == "OVERRIDE_REQUIRED":
                            core.approve(review.id, True)
                    except a.ProbeError:
                        pass
                core.close()
                root.destroy()
                if ui.launcher:
                    try:
                        ui.launcher.wait(timeout=2)
                    except Exception:
                        ui.launcher.terminate()


class ConnectionDialogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aitl-setup-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.core = a.AppCore(connection_store=a.ConnectionStore(Path(self.tmp.name, "config")))
        self.root = tk.Tk()
        self.callbacks = []
        self.root.report_callback_exception = lambda *_: self.callbacks.append("tk_callback_failed")
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)
        self.root.update()

    def cleanup(self):
        self.core.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.ui = self.core = self.root = None
        gc.collect()  # Dispose Tcl-owned cycles on the creating thread, before another worker starts.

    def until(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("gui_setup_timeout")

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def test_pending_proposal_explains_terminal_gate_even_with_connected_bridge(self):
        self.core.start_local(self.tmp.name)
        proposal = self.core.add_proposal("printf 'review only'")
        bridge = a.replace(self.core.bridge_snapshot(), state="CONNECTED", mode="REMOTE",
                           target="https://127.0.0.1:8443", tunnel_phase="connected")
        with mock.patch.object(self.core, "bridge_snapshot", return_value=bridge), \
                mock.patch.object(self.core, "review_pending_proposal", wraps=self.core.review_pending_proposal) as take:
            for size in ("960x560", "1360x850"):
                self.root.geometry(size)
                for state, reason in (("WAITING_FOR_TERMINAL", "Zuerst links Terminal öffnen"),
                                      ("STARTING_SHELL", "Terminal verbindet"),
                                      ("DISCONNECTED", "Terminal getrennt")):
                    with self.subTest(size=size, state=state):
                        self.core.connection = state
                        self.ui.render()
                        self.root.update()
                        self.assertIn("Command-Vorschlag vorhanden", self.ui.readiness.cget("text"))
                        self.assertIn(reason, self.ui.readiness.cget("text"))
                        self.assertTrue(self.ui.from_ai_button.instate(["disabled"]))
                        self.ui.from_ai_button.invoke()
                        self.assertIn(proposal, self.core.inbox)
                        self.assertIsNone(self.core.review)
                        self.assertTrue(self.ui.readiness.winfo_viewable())
                        self.assertGreaterEqual(self.ui.readiness.winfo_height(), self.ui.readiness.winfo_reqheight())
                        self.assertLessEqual(self.ui.from_ai_button.winfo_rooty()+self.ui.from_ai_button.winfo_height(),
                                             self.root.winfo_rooty()+self.root.winfo_height())
            take.assert_not_called()
            self.core.connection = "STARTING_SHELL"
            self.core._event({"type": "ready", "session": "12345678-1234-1234-1234-123456789012"})
            self.ui.render()
            self.root.update()
            self.assertTrue(self.ui.from_ai_button.instate(["!disabled"]))
            self.assertEqual(self.ui.readiness.cget("text"), "Command-Vorschlag vorhanden")
            self.ui.from_ai_button.invoke()
            take.assert_called_once()
            self.assertEqual(self.core.review_state, "REVIEW")
            self.assertEqual(self.core.review.text, "printf 'review only'\n")
            self.assertNotIn(proposal, self.core.inbox)
            self.assertIsNone(self.core.channel)  # No terminal send or approval took place.

    def test_pending_proposal_explains_stage_and_transfer_gates(self):
        self.core.connection, self.core.session = "CONNECTED", "UI_TEST_SESSION"
        self.core.review_command("printf 'current review'")
        proposal = self.core.add_proposal("printf 'next review'")
        for state, reason in (("REVIEW", "Aktuellen Review freigeben oder verwerfen"),
                              ("OVERRIDE_REQUIRED", "Aktuellen Review freigeben oder verwerfen"),
                              ("CHECKING", "Terminalübertragung läuft"),
                              ("TRANSFERRING", "Terminalübertragung läuft"),
                              ("TAKE_PENDING", "Übernahme wird bestätigt"),
                              ("SENDING", "Ausgabe wird zurückgegeben"),
                              ("DELIVERY_UNCERTAIN", "Zustellung der Ausgabe klären")):
            with self.subTest(state=state):
                self.core.review_state = state
                self.ui.render()
                self.assertTrue(self.ui.from_ai_button.instate(["disabled"]))
                self.assertIn(reason, self.ui.readiness.cget("text"))
                self.assertIn(proposal, self.core.inbox)
        self.core.review_state = "REVIEW"
        self.core.review = a.replace(self.core.review, direction="TO_OUTPUT_SINK", final_return=False)
        self.ui.render()
        self.assertTrue(self.ui.from_ai_button.instate(["!disabled"]))  # Existing directional dialog stays reachable.
        self.core.review = a.replace(self.core.review, direction="TO_TERMINAL")
        self.core._park_staged_proposal()
        self.core.remove_proposal(proposal)
        self.ui.render()
        self.assertTrue(self.ui.from_ai_button.instate(["!disabled"]))
        self.assertIn("Geparkter Vorschlag vorhanden", self.ui.readiness.cget("text"))
        self.assertIsNone(self.core.channel)

    def test_panel_proportions_and_shared_footer_at_supported_sizes(self):
        for width in (960, 1360):
            self.root.geometry("%dx600" % width)
            self.root.update()
            widths = [panel.winfo_width() for panel in self.ui.panels]
            for actual, target in zip(widths, (0.25, 0.5, 0.25)):
                self.assertAlmostEqual(actual / sum(widths), target, delta=0.03)
            ys = [button.winfo_rooty() for button in
                  (self.ui.from_terminal_button, self.ui.approve_button, self.ui.from_ai_button)]
            self.assertLessEqual(max(ys) - min(ys), 1)
            headers = [next(widget for widget in label.master.winfo_children()
                            if widget.winfo_class() == "TButton") for label, _ in self.ui.status_labels]
            self.assertLessEqual(abs(headers[0].winfo_rooty() - headers[1].winfo_rooty()), 1)
            self.assertGreater(int(self.ui.readiness.cget("wraplength")), widths[2] - 60)
            for section, panel in (("terminal", self.ui.panels[0]), ("ai", self.ui.panels[2])):
                image = self.ui.section_images[section]
                self.assertEqual((image.width(), image.height()), (80, 64))
                graphic = self.ui.section_logo_labels[section]
                self.assertTrue(graphic.winfo_ismapped())
                self.assertIs(graphic.master.master.master, panel)
            self.assertGreater(self.ui.header_bar.winfo_width() - self.ui.logo_label.winfo_width(), 600)
            self.assertGreater(self.ui.layout.winfo_rooty(),
                               self.ui.header_bar.winfo_rooty() + self.ui.header_bar.winfo_height() - 1)
        base = ttk.Style(self.root).lookup("TFrame", "background") or self.root.cget("background")
        self.assertEqual(self.ui.logo_variant, a._logo_variant(self.root, base))
        left, center, right = self.ui.panels
        self.assertEqual(left.cget("highlightbackground"), right.cget("highlightbackground"))
        self.assertNotEqual(left.cget("highlightbackground"), center.cget("highlightbackground"))
        self.assertTrue(self.ui.review_picker.winfo_ismapped())
        self.assertIn("Befehlsprüfung", self.ui.review_selection.get())
        self.assertFalse(self.ui.review_options.winfo_viewable())
        self.assertEqual(self.ui.editor.text.cget("state"), "disabled")
        self.assertEqual(self.callbacks, [])

    def test_logo_variant_follows_light_and_dark_native_surfaces(self):
        class Surface:
            def __init__(self, rgb):
                self.rgb = rgb

            def winfo_rgb(self, _background):
                return self.rgb

        self.assertEqual(a._logo_variant(Surface((65535, 65535, 65535)), "light"), "light")
        self.assertEqual(a._logo_variant(Surface((5000, 5000, 5000)), "dark"), "dark")

    def test_hand_buttons_preserve_review_actions_and_confirmation(self):
        self.assertTrue(self.ui.approve_button.instate(["disabled"]))
        self.assertTrue(self.ui.reject_button.instate(["disabled"]))
        self.core.session = "HAND_BUTTON_TEST_SESSION"
        self.core.connection = "CONNECTED"
        review = self.core._output_review("selected output\n")
        self.ui.render()
        self.assertEqual(self.ui.approve_button.cget("text"), "Freigeben an AI →")
        self.ui.approve_button.invoke()
        self.assertEqual(self.core.review_state, "ACKNOWLEDGED_LOCAL")
        self.assertEqual(list(self.core.approved_outputs), [review])

        self.core._output_review("do not share\n")
        self.ui.render()
        self.ui.reject_button.invoke()
        self.assertEqual(self.core.review_state, "REJECTED")
        self.assertEqual(list(self.core.approved_outputs), [review])
        self.assertEqual(self.ui.reject_button.cget("text"), "Verwerfen")

        command = self.core.review_command("printf test", False)
        self.core.channel = mock.Mock()
        self.core.review_state = "OVERRIDE_REQUIRED"
        self.ui.render()
        with mock.patch.object(self.ui.messagebox, "askyesno", return_value=False):
            self.ui.approve_button.invoke()
        self.core.channel.send.assert_not_called()
        with mock.patch.object(self.ui.messagebox, "askyesno", return_value=True):
            self.ui.approve_button.invoke()
        self.core.channel.send.assert_called_once_with({"type": "transfer", "id": command.id,
            "session": command.session, "text": command.text, "return": False, "override": True})
        self.assertEqual(self.core.review_state, "CHECKING")
        self.core.channel = None
        self.assertEqual(self.callbacks, [])

    def test_centered_dropdowns_keep_selection_callbacks(self):
        self.assertEqual(str(self.ui.output_picker.cget("justify")), "center")
        self.ui.output_picker.set("Letzte 50")
        self.ui.output_picker.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.core.output_mode, "LAST_50")
        picker = next(widget for widget in self.descendants(self.ui.panels[2])
                      if isinstance(widget, ttk.Combobox))
        self.assertEqual(str(picker.cget("justify")), "center")
        picker.set("LARGE")
        picker.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertEqual(self.core.preferences, "LARGE")
        self.assertEqual(self.callbacks, [])

    def test_one_window_contextual_sections_drafts_and_keyboard_scroll(self):
        dialog = self.ui.connection_settings()
        self.root.update()
        self.assertIs(self.ui.connection_settings(), dialog)
        self.assertFalse(any(widget.winfo_class() == "TNotebook" for widget in self.descendants(dialog.window)))
        with mock.patch.object(self.core, "connect_local_bridge") as local, \
                mock.patch.object(self.core, "begin_pair_remote") as remote:
            dialog.location.set("REMOTE")
            self.root.update()
            self.assertTrue(dialog.remote_setup.winfo_ismapped())
            self.assertFalse(dialog.local_tunnel.winfo_ismapped())
            dialog.fields["remote_script"].set("/opt/Remote Script/admin_in_the_loop.py")
            dialog.fields["code"].set("KEEP-DRAF-T123")
            self.root.update()
            self.assertIn("'/opt/Remote Script/admin_in_the_loop.py' --bridge", dialog.remote_command)
            # Navigation haelt Eingaben und loest keine Aktionen aus.
            dialog.wizard_goto(2)
            dialog.wizard_goto(0)
            self.assertEqual(dialog.fields["code"].get(), "KEEP-DRAF-T123")
            local.assert_not_called()
            remote.assert_not_called()
        dialog.window.geometry("640x480")
        # Verwaltung ist eigener Schritt: LOCAL letzte Seite zeigt Chat + Verwalten.
        dialog.location.set("LOCAL")
        dialog.wizard_goto(1)
        self.root.update()
        self.assertTrue(dialog.chat_section.winfo_ismapped())
        self.assertFalse(dialog.controls.winfo_ismapped())
        dialog.details_button.invoke()
        self.root.update()
        self.assertTrue(dialog.controls.winfo_ismapped())
        dialog.buttons["offline"].focus_force()
        self.root.update()
        self.assertGreater(dialog.canvas.yview()[0], 0)
        top = dialog.buttons["offline"].winfo_rooty()
        self.assertGreaterEqual(top, dialog.canvas.winfo_rooty())
        self.assertLessEqual(top + dialog.buttons["offline"].winfo_height(),
                             dialog.canvas.winfo_rooty() + dialog.canvas.winfo_height())
        dialog.fields["url"].set("http://bridge.example:8443")
        self.assertTrue(dialog.buttons["remote_copy"].instate(["disabled"]))
        self.assertEqual(self.callbacks, [])
    def test_pair_validation_does_not_submit_or_discard_bad_draft(self):
        dialog = self.ui.connection_settings()
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        self.root.update()
        dialog.fields["url"].set("https://bridge.example:8443")
        dialog.fields["code"].set("ABCD-EFGH-JKLI")
        with mock.patch.object(self.core, "begin_pair_remote") as pair:
            # Ohne belegte Verbindung ist Koppeln gesperrt; der Entwurf bleibt.
            dialog.run("bridge", dialog.pair)
            pair.assert_not_called()
            self.assertIn("Verbindung prüfen", dialog.errors["bridge"].get())
            self.assertEqual(dialog.fields["code"].get(), "ABCD-EFGH-JKLI")
            # Der eine bewusste Klick belegt Erreichbarkeit und forderte den Code.
            with mock.patch.object(a, "bridge_reachability", return_value="a" * 64), \
                    mock.patch.object(self.core, "hello_bridge", return_value="pairing_required"):
                dialog.buttons["remote_check"].invoke()
            self.assertEqual(dialog.remote_observed_pin, "a" * 64)
            displayed = dialog.remote_pin_box.text.get("1.0", "end-1c").replace(" ", "").strip()
            self.assertEqual(displayed, "a" * 64)  # Anzeige, kein editierbares Feld
            self.assertIn("vergleichen", dialog.remote_status.get())
            dialog.run("bridge", dialog.pair)  # Formatfehler: keine Einreichung, Entwurf bleibt
            pair.assert_not_called()
            self.assertIn("8 Zeichen", dialog.errors["bridge"].get())
            self.assertEqual(dialog.fields["code"].get(), "ABCD-EFGH-JKLI")
            dialog.fields["code"].set("ABCD-EFGH")
            dialog.run("bridge", dialog.pair)
            pair.assert_called_once_with("https://bridge.example:8443", "a" * 64, "ABCDEFGH")  # normalisiert
            self.assertEqual(dialog.fields["code"].get(), "")  # Code nach Aufwand geleert
        dialog.fields["url"].set("https://user:secret@bridge.example:8443")
        dialog.run("bridge", dialog.verify_remote)
        self.assertNotIn("secret", dialog.errors["bridge"].get())  # keine Secrets in Meldungen
        self.assertEqual(dialog.entries["code"].cget("show"), "")  # #102: Klartext-Code
        self.assertEqual(dialog.entries["api_key"].cget("show"), "*")
        self.assertEqual(self.callbacks, [])
    def test_real_remote_pair_completion_and_saved_target_guard(self):
        bridge = RemoteFixture(Path(self.tmp.name, "bridge"))
        self.addCleanup(bridge.close)
        dialog = self.ui.connection_settings()
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        dialog.fields["url"].set(bridge.url)
        self.root.update()
        # EIN bewusster Klick: echte Erreichbarkeit + Hallo/Codeanforderung.
        dialog.buttons["remote_check"].invoke()
        self.assertEqual(dialog.remote_observed_pin, bridge.pin)
        self.assertEqual(dialog.remote_pin_box.text.get("1.0", "end-1c").replace(" ", "").strip(),
                         bridge.pin)
        dialog.fields["code"].set(bridge.code)
        with mock.patch.object(self.core, "connect_local_bridge") as local, \
                mock.patch.object(self.core, "start_tunnel") as tunnel:
            dialog.buttons["pair"].invoke()
            self.assertEqual(dialog.fields["code"].get(), "")
            self.assertTrue(dialog.buttons["disconnect"].instate(["disabled"]))
            dialog.window.destroy()
            self.until(lambda: self.core.bridge_state == "CONNECTED")
            dialog = self.ui.connection_settings()
            self.root.update()
            self.assertIn("Remote-Bridge verbunden · authentifiziert", dialog.summary.get())
            # M9: kein unbelegter Tunnelbetrieb-Satz; der echte Bridge-Status wird
            # beobachtet und die Tunnel-Seite automatisch angesteuert.
            self.assertNotIn("Tunnelbetrieb am Gateway", dialog.summary.get())
            self.until(lambda: "Tunnel fehlt" in self.ui.ai_status.get())
            self.assertIn("Tunnel fehlt · Einrichtung nötig", self.ui.ai_status.get())
            self.until(lambda: dialog.wizard_index == 2)
            self.assertTrue(dialog.remote_tunnel_page.winfo_ismapped())
            self.assertFalse(dialog.tunnel_section.winfo_ismapped())
            self.assertNotIn("noch nicht verifiziert", dialog.summary.get())
            self.assertNotIn("Tunnel-Zugriff geprüft", dialog.summary.get())
            self.assertNotIn("Tunnel gestoppt", self.ui.ai_status.get())
            self.assertIsNone(self.core.bridge_process)
            self.assertIsNone(self.core.tunnel)
            local.assert_not_called()
            tunnel.assert_not_called()
        self.assertEqual(dialog.binding.get(), "")
        self.until(lambda: self.core.chat_binding is not None)
        dialog.buttons["chat_show"].invoke()
        shown = self.core.chat_binding["code"][:4] + "-" + self.core.chat_binding["code"][4:]
        self.assertEqual(dialog.binding.get(), shown)
        self.assertTrue(self.ui.chat_code_copy.instate(["!disabled"]))
        self.ui.chat_code_copy.invoke()
        self.assertEqual(self.root.clipboard_get(), shown)
        original_binding = dict(self.core.chat_binding)
        self.core.chat_binding = dict(original_binding, status="BACKOFF",
                                      retry_at=original_binding["server_time"] + 45,
                                      restriction_scope="PRINCIPAL")
        self.ui.render()
        self.assertEqual(self.ui.chat_code.get(), shown)
        self.assertIn("Wartezeit", self.ui.chat_code_status.get())
        self.assertTrue(self.ui.chat_code_copy.instate(["disabled"]))
        self.core.chat_binding = original_binding
        self.ui.render()
        old_code = original_binding["code"]
        dialog.buttons["chat_rotate"].invoke()
        self.until(lambda: self.core.chat_binding and self.core.chat_binding["generation"] == 2)
        self.root.update()
        self.assertNotEqual(self.core.chat_binding["code"], old_code)
        self.assertEqual(self.ui.chat_code.get(), self.core.chat_binding["code"][:4] + "-" +
                         self.core.chat_binding["code"][4:])
        self.assertEqual(sum(isinstance(widget, tk.Toplevel) and widget.winfo_viewable()
                             for widget in self.root.winfo_children()), 1)
        self.core.disconnect_bridge()
        self.ui.render()
        self.assertEqual(dialog.binding.get(), "")
        dialog.fields["url"].set("https://unrelated.example:8443")
        self.root.update()
        self.assertTrue(dialog.buttons["saved_connect"].instate(["disabled"]))
        with mock.patch.object(self.core, "connect_saved_bridge") as connect:
            dialog.run("bridge", dialog.open_saved)
            connect.assert_not_called()
        self.assertIn("passt nicht", dialog.errors["bridge"].get())
        self.assertEqual(self.callbacks, [])

    def test_local_two_value_flow_deferred_save_progress_and_conditional_actions(self):
        dialog = self.ui.connection_settings()
        self.assertNotIn("binary", dialog.entries)
        self.assertNotIn("local_connect", dialog.buttons)
        self.assertNotIn("tunnel_save", dialog.buttons)
        # Wizard: Auswahlkarte zuerst, lokale Zweigseite danach aktiv.
        dialog.location.set("LOCAL")
        self.root.update()
        self.assertTrue(dialog.local.winfo_ismapped())
        self.assertFalse(dialog.cards.winfo_ismapped())
        self.assertFalse(dialog.buttons["local_stop"].winfo_ismapped())
        self.assertTrue(dialog.buttons["local_start"].instate(["!disabled"]))
        dialog.fields["tunnel_id"].set("tunnel_" + "a" * 32)
        dialog.fields["api_key"].set("SYNTHETIC_UI_RUNTIME_KEY")
        executable = Path(self.tmp.name, "client")
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o700)
        preparation = mock.Mock(events=a.queue.Queue())
        client = mock.Mock(state="READY", error=None)
        client.polling_check.return_value = (False, None)
        with mock.patch.object(a, "LocalSetupPreparation", return_value=preparation), \
                mock.patch.object(a, "TunnelProcess", return_value=client):
            dialog.buttons["local_start"].invoke()
            self.assertIn("gesucht", dialog.summary.get())
            self.assertTrue(dialog.buttons["local_start"].instate(["disabled"]))
            self.assertIsNone(self.core.connection_store.load_connection())
            preparation.events.put(("stage", "INSTALLING"))
            self.core.pump()
            self.ui.render()
            self.assertIn("installiert", dialog.summary.get())
            process = a.LocalBridgeProcess()
            config = {"binary": str(executable), "tunnel_id": dialog.fields["tunnel_id"].get(),
                      "api_key": dialog.fields["api_key"].get()}
            preparation.events.put(("prepared", (process, config)))
            self.until(lambda: self.core.tunnel is client)
            self.assertIsNone(self.core.connection_store.load_connection())
            self.assertIn("geprüft", dialog.summary.get())
            dialog.window.destroy()
            client.polling_check.return_value = (True, None)
            self.core.local_check_at = 0
            self.until(lambda: self.core.local_setup_state == "CONNECTED")
            dialog = self.ui.connection_settings()
            self.root.update()
            self.assertEqual(self.core.connection_store.load_connection()["tunnel"], config)
            self.assertIn("Verbindung bereit", dialog.summary.get())
            self.assertEqual(dialog.summary.get(), "Verbindung bereit · Tunnel-Zugriff geprüft")
            self.assertFalse(dialog.local_inputs.winfo_ismapped())
            self.assertFalse(dialog.buttons["local_start"].winfo_ismapped())
            self.assertTrue(dialog.buttons["local_stop"].winfo_ismapped())
            dialog.buttons["local_stop"].invoke()
            self.assertIsNone(self.core.tunnel)
            self.assertIsNone(self.core.bridge_process)
            self.root.update()
            self.assertFalse(dialog.buttons["local_stop"].winfo_ismapped())
            self.assertTrue(dialog.buttons["local_start"].winfo_ismapped())
            client.close.assert_called_once()
        self.assertEqual(self.callbacks, [])

    def test_local_preflight_failure_help_and_reopened_installation_are_truthful(self):
        dialog = self.ui.connection_settings()
        dialog.location.set("LOCAL")
        self.root.update()
        dialog.fields["tunnel_id"].set("bad-id")
        dialog.fields["api_key"].set("SYNTHETIC_SECRET_KEY")
        with mock.patch.object(a, "LocalSetupPreparation") as prepare:
            dialog.buttons["local_start"].invoke()
            prepare.assert_not_called()
        self.assertIn("32 kleinen Hexzeichen", dialog.errors["tunnel"].get())
        self.assertNotIn("SYNTHETIC_SECRET_KEY", dialog.errors["tunnel"].get())
        self.assertIsNone(self.core.connection_store.load_connection())
        with mock.patch("webbrowser.open", return_value=True) as browser:
            dialog.buttons["tunnel_help"].invoke()
            dialog.buttons["key_help"].invoke()
            self.assertEqual(browser.call_args_list, [mock.call(a.TUNNEL_SETTINGS_URL), mock.call(a.RUNTIME_KEYS_URL)])
        dialog.fields["tunnel_id"].set("tunnel_" + "a" * 32)
        preparation = mock.Mock(events=a.queue.Queue())
        with mock.patch.object(a, "LocalSetupPreparation", return_value=preparation):
            dialog.buttons["local_start"].invoke()
            preparation.events.put(("stage", "INSTALLING"))
            self.core.pump()
            dialog.window.destroy()
            dialog = self.ui.connection_settings()
            self.assertEqual(dialog.location.get(), "LOCAL")
            self.assertIn("installiert", dialog.summary.get())
            self.assertTrue(dialog.buttons["local_start"].instate(["disabled"]))
            self.assertFalse(dialog.buttons["local_stop"].winfo_ismapped())
            preparation.events.put(("error", "runtime_key_rejected"))
            self.core.pump()
            self.ui.render()
            self.assertIn("401", dialog.errors["tunnel"].get())
            self.assertIsNone(self.core.connection_store.load_connection())
            self.assertTrue(dialog.buttons["local_start"].instate(["!disabled"]))
        self.assertEqual(self.callbacks, [])

    def test_failed_macos_installer_has_gui_and_console_details_without_secret(self):
        secret = "SYNTHETIC_MAC_INSTALL_SECRET"
        brew = fake_brew(Path(self.tmp.name), exit_code=17,
                         output="Error: Permission denied\nTOKEN=" + secret)
        dialog = self.ui.connection_settings()
        dialog.location.set("LOCAL")
        self.root.update()
        dialog.fields["tunnel_id"].set("tunnel_" + "a" * 32)
        dialog.fields["api_key"].set(secret)
        with mock.patch.object(a.sys, "platform", "darwin"), \
                mock.patch.object(a.shutil, "which", side_effect=lambda name: str(brew) if name == "brew" else None), \
                redirect_stderr(io.StringIO()) as console:
            dialog.buttons["local_start"].invoke()
            self.until(lambda: self.core.local_setup_state == "FAILED")
        self.root.update()
        self.assertTrue(dialog.cause_label.winfo_ismapped())
        self.assertIn("beschreiben", dialog.failure_cause.get())
        self.assertTrue(dialog.technical_toggle.winfo_ismapped())
        dialog.technical_toggle.invoke()
        self.root.update()
        self.assertTrue(dialog.technical_details.frame.winfo_ismapped())
        text = dialog.technical_details.text.get("1.0", "end-1c")
        self.assertIn("Phase: INSTALLING", text)
        self.assertIn("Exit-Code: 17", text)
        self.assertIn("Permission denied", text)
        self.assertIn("Cellar/tunnel-client", text)
        self.assertIn("Phase: INSTALLING", console.getvalue())
        self.assertIn("Exit-Code: 17", console.getvalue())
        self.assertNotIn(secret, text + console.getvalue() + dialog.failure_cause.get())
        self.assertIsNone(self.core.connection_store.load_connection())
        dialog.window.destroy()
        reopened = self.ui.connection_settings()
        self.assertIn("beschreiben", reopened.failure_cause.get())
        self.assertEqual(self.callbacks, [])

    def test_remote_already_paired_takeover_restores_saved_connection(self):
        # 0.9.3: Remote-Ast wie Qrexec – ehrliche Wiederherstellung der passenden
        # gespeicherten, gepinnten Verbindung; kein Code-Schritt, kein Bypass.
        dialog = self.ui.connection_settings()
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        profile = a.ConnectionProfile("https://gateway.example:8443", "ef" * 32, "c" * 64, "d" * 32, "e" * 64)
        self.core.connection_store.save_connection(profile, None, None)
        dialog.fields["url"].set("https://gateway.example:8443")
        self.root.update()
        with mock.patch.object(a, "bridge_reachability", return_value="ef" * 32), \
                mock.patch.object(self.core, "hello_bridge", return_value="already_paired"), \
                mock.patch.object(self.core, "connect_saved_bridge") as connect:
            dialog.buttons["remote_check"].invoke()
        connect.assert_called_once()
        self.assertIn("wiederhergestellt", dialog.remote_status.get())
        self.assertEqual(self.callbacks, [])

    def test_closed_dialog_recovers_saved_confirm_without_reclaim(self):
        bridge = RemoteFixture(Path(self.tmp.name, "bridge"))
        self.addCleanup(bridge.close)
        dialog = self.ui.connection_settings()
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        dialog.fields["url"].set(bridge.url)
        dialog.buttons["remote_check"].invoke()
        self.assertEqual(dialog.remote_observed_pin, bridge.pin)
        dialog.fields["code"].set(bridge.code)
        original = a.BridgeHTTP.request
        claims = []
        lost = False
        def request(client, method, path, *args, **kwargs):
            nonlocal lost
            if path == "/v1/pair/claim":
                claims.append("claim")
            result = original(client, method, path, *args, **kwargs)
            if path == "/v1/pair/confirm" and not lost:
                lost = True
                raise a.TransportError("network_unavailable", True)
            return result
        with mock.patch.object(a.BridgeHTTP, "request", request):
            dialog.buttons["pair"].invoke()
            dialog.window.destroy()
            self.until(lambda: self.core.bridge_state == "BLOCKED" and not self.core.pair_thread.is_alive())
            self.assertIsNone(self.core.saved_connection)
            dialog = self.ui.connection_settings()
            self.assertEqual(dialog.fields["url"].get(), bridge.url)
            # Kein Pin-Feld mehr: das Speicherkommando nutzt den persistenten Pin
            # und oeffnet ausschliesslich bei gleicher Adresse.
            self.assertNotIn("pin", dialog.fields)
            dialog.wizard_goto(1)
            self.root.update()
            self.assertTrue(dialog.buttons["saved_connect"].instate(["!disabled"]))
            dialog.run("bridge", dialog.open_saved)
            self.until(lambda: self.core.bridge_state == "CONNECTED")
            self.assertEqual(len(claims), 1)
            self.assertIsNone(self.core.bridge_process)
        self.assertEqual(self.callbacks, [])


    def test_tunnel_step_auto_switch_and_chat_code_auto_reveal(self):
        """M9 S4/S5 + 0.9.3: der echte Tunnelstatus steuert die Seiten – fehlt ->
        Formular (lesbar), gueltige Konfiguration (configured/starting) -> Formular
        übersprungen mit ehrlichem Status, verbunden -> Chat mit Code einmalig
        automatisch; Fehler -> Formular als bewusster Retry."""
        dialog = self.ui.connection_settings()
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        self.root.update()
        base = self.core.bridge_snapshot()
        now = time.time()
        binding = {"code": "ABCDEFGH", "code_digest": "0" * 64, "generation": 1,
                   "issued_at": now, "expires_at": now + 3600, "server_time": now,
                   "status": "VALID", "retry_at": None, "restriction_scope": None,
                   "locked_principals": 0}
        missing = a.replace(base, state="CONNECTED", mode="REMOTE", instance="a" * 32,
                            generation=1, tunnel_phase="missing", tunnel_detail="")
        with mock.patch.object(self.core, "bridge_snapshot", return_value=missing), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            dialog.render()
            self.root.update()
        self.assertEqual(dialog.wizard_index, 2)
        self.assertTrue(dialog.remote_tunnel_page.winfo_ismapped())
        self.assertIn("Kein Tunnel konfiguriert", dialog.remote_tunnel_status.get())
        # 0.9.3: beide Eingabefelder lesbar (Operator-Wunsch), Formular sichtbar.
        self.assertEqual(dialog.entries["remote_tunnel_id"].cget("show"), "")
        self.assertEqual(dialog.entries["remote_runtime_key"].cget("show"), "")
        self.assertEqual(dialog.remote_tunnel_form.winfo_manager(), "grid")
        self.assertTrue(dialog.buttons["tunnel_cancel_remote"].instate(["disabled"]))
        # 0.9.5: die Bridge installiert automatisch; die Phase wird stufengenau gezeigt.
        preparing = a.replace(missing, tunnel_phase="installing", tunnel_step="download")
        with mock.patch.object(self.core, "bridge_snapshot", return_value=preparing), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            dialog.render()
            self.root.update()
        self.assertEqual(dialog.wizard_index, 2)
        self.assertEqual(dialog.remote_tunnel_form.winfo_manager(), "")
        self.assertIn("von GitHub geladen", dialog.remote_tunnel_status.get())
        starting = a.replace(missing, tunnel_phase="starting")
        with mock.patch.object(self.core, "bridge_snapshot", return_value=starting), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            dialog.render()
            self.root.update()
        self.assertEqual(dialog.wizard_index, 2)  # wartet sichtbar, springt nicht vor
        self.assertEqual(dialog.remote_tunnel_form.winfo_manager(), "")  # gueltige Config: Formular übersprungen
        self.assertIn("Verbindung zur Platform", dialog.remote_tunnel_status.get())
        connected = a.replace(missing, tunnel_phase="connected", chat_binding=binding,
                              chat_binding_received_at=time.monotonic())
        with mock.patch.object(self.core, "bridge_snapshot", return_value=connected), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            dialog.render()
            self.root.update()
        self.assertEqual(dialog.wizard_index, 3)
        self.assertTrue(dialog.chat_section.winfo_ismapped())
        self.assertEqual(dialog.binding.get(), "ABCD-EFGH")  # S5: einmal automatisch
        error = a.replace(missing, tunnel_phase="error", tunnel_detail="runtime_key_rejected")
        dialog.wizard_goto(1)
        with mock.patch.object(self.core, "bridge_snapshot", return_value=error), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            dialog.render()
            self.root.update()
        self.assertEqual(dialog.wizard_index, 2)
        self.assertEqual(dialog.remote_tunnel_form.winfo_manager(), "grid")  # Retry bleibt bewusst moeglich
        self.assertIn("Runtime API key", dialog.remote_tunnel_status.get())
        self.assertEqual(self.callbacks, [])


class BrandingSingleFileTests(unittest.TestCase):
    def test_downloaded_single_file_renders_both_variants_from_external_cwd(self):
        source = Path(a.__file__).resolve()
        with tempfile.TemporaryDirectory(prefix="aitl-single-file-") as directory:
            sandbox = Path(directory).resolve()
            self.assertFalse(sandbox.is_relative_to(source.parent))
            download = sandbox / "Downloads"
            working = sandbox / "external-cwd"
            download.mkdir()
            working.mkdir()
            shutil.copyfile(source, download / source.name)
            code = r'''
import gc, json, sys, tkinter as tk
from tkinter import ttk
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import admin_in_the_loop as app
assert Path(app.__file__).parent != Path.cwd()
assert sorted(p.name for p in Path(app.__file__).parent.iterdir()) == ["admin_in_the_loop.py"]
results = []
def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)

for variant, background in (("light", "#ffffff"), ("dark", "#101010")):
    root = tk.Tk()
    ttk.Style(root).configure("TFrame", background=background)
    core = app.AppCore()
    ui = app.ReviewUI(root, core)
    root.update()
    assert ui.logo_variant == variant
    for section, panel in (("terminal", ui.panels[0]), ("ai", ui.panels[2])):
        image = ui.section_images[section]
        graphic = ui.section_logo_labels[section]
        assert image is not None
        assert (image.width(), image.height()) == (80, 64)
        assert graphic.winfo_ismapped() and str(graphic.cget("image"))
        assert graphic.master.master.master is panel
        assert graphic.winfo_rooty() < ui.status_labels[0 if section == "terminal" else 1][0].winfo_rooty()
        assert image.transparency_get(0, 0) == (variant == "dark")
    assert ui.logo_label.cget("text") == "Admin in the Loop"
    for name, button in (("ok", ui.approve_button), ("stop", ui.reject_button)):
        image = ui.button_hand_images[name]
        assert image is not None and (image.width(), image.height()) == (24, 24)
        assert image.transparency_get(0, 0)
        assert tuple(map(str, root.tk.splitlist(button.cget("image")))) == (str(image),)
        assert str(button.cget("compound")) == "left" and button.winfo_ismapped()
        assert button.instate(["disabled"])
    assert ui.header_bar.winfo_width() - ui.logo_label.winfo_width() > 600
    for width in (960, 1100, 1360):
        root.geometry("%dx600" % width)
        root.update()
        for section, panel in (("terminal", ui.panels[0]), ("ai", ui.panels[2])):
            center = panel.winfo_rootx() + panel.winfo_width() / 2
            graphic = ui.section_logo_labels[section]
            assert abs(graphic.winfo_rootx() + graphic.winfo_width() / 2 - center) <= 1
            for widget in descendants(panel):
                if isinstance(widget, ttk.Label) and not str(widget.cget("image")):
                    assert str(widget.cget("anchor")) == "center"
                    assert str(widget.cget("justify")) == "center"
                    assert abs(widget.winfo_rootx() + widget.winfo_width() / 2 - center) <= 1
                if isinstance(widget, ttk.Combobox):
                    assert str(widget.cget("justify")) == "center"
                    assert widget.winfo_width() >= panel.winfo_width() - 30
        for label, _ in ui.status_labels:
            assert str(label.cget("justify")) == "center"
        assert ui.review_picker.winfo_ismapped()
        assert ui.review_picker.grid_info()["sticky"] == "ew"
        assert ui.review_selection.get().startswith("Befehlsprüfung")
        assert not ui.review_options.winfo_viewable()
        assert ui.editor.text.cget("state") == "disabled"
    assert core.bridge_process is None and core.tunnel is None
    results.append({"variant": variant, "dimensions": [80, 64], "sections": ["terminal", "ai"], "mapped": True})
    core.close()
    for callback in root.tk.call("after", "info"):
        root.after_cancel(callback)
    root.destroy()
    del ui, core, root
    gc.collect()
assert sorted(p.name for p in Path(sys.argv[1]).iterdir()) == ["admin_in_the_loop.py"]
assert not list(Path.cwd().iterdir())
print(json.dumps(results))
'''
            result = subprocess.run([sys.executable, "-I", "-c", code, str(download)], cwd=working,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [
                {"variant": "light", "dimensions": [80, 64], "sections": ["terminal", "ai"], "mapped": True},
                {"variant": "dark", "dimensions": [80, 64], "sections": ["terminal", "ai"], "mapped": True},
            ])

    def test_embedded_png_decode_failure_keeps_text_fallback(self):
        root = tk.Tk()
        core = a.AppCore()
        ui = None
        try:
            with mock.patch.dict(a._SECTION_LOGO_PNG, {"terminal": {"light": "invalid", "dark": "invalid"},
                                                      "ai": {"light": "invalid", "dark": "invalid"}}):
                ui = a.ReviewUI(root, core)
                root.update()
                self.assertEqual(ui.section_images, {"terminal": None, "ai": None})
                self.assertEqual(ui.section_logo_labels, {})
                self.assertEqual(ui.logo_label.cget("text"), "Admin in the Loop")
                self.assertTrue(ui.logo_label.winfo_ismapped())
                for label, _ in ui.status_labels:
                    titles = [child.cget("text") for child in label.master.winfo_children()
                              if child.winfo_class() == "TLabel" and not str(child.cget("textvariable"))]
                    self.assertTrue(any(title in {"Terminal", "AI / MCP"} for title in titles))
        finally:
            core.close()
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
            del ui, core, root
            gc.collect()

    def test_invalid_hand_icons_keep_text_buttons_and_actions(self):
        root = tk.Tk()
        core = a.AppCore()
        ui = None
        try:
            with mock.patch.dict(a._BUTTON_HAND_PNG, {"ok": "invalid", "stop": "invalid"}):
                ui = a.ReviewUI(root, core)
                root.update()
                self.assertEqual(ui.button_hand_images, {"ok": None, "stop": None})
                self.assertFalse(str(ui.approve_button.cget("image")))
                self.assertFalse(str(ui.reject_button.cget("image")))
                self.assertEqual(ui.reject_button.cget("text"), "Verwerfen")
                core.session = "TEXT_FALLBACK_SESSION"
                core.connection = "CONNECTED"
                core._output_review("reject this\n")
                ui.render()
                ui.reject_button.invoke()
                self.assertEqual(core.review_state, "REJECTED")
        finally:
            core.close()
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
            del ui, core, root
            gc.collect()


class WorkPackageReviewUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.core = a.AppCore()
        self.ui = a.ReviewUI(self.root, self.core)
        self.core.session = "SYNTHETIC_REVIEW_SESSION"
        self.core.connection = "CONNECTED"
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.core.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        del self.ui, self.core, self.root
        gc.collect()

    def test_byte_details_are_passive_and_new_revision_marks_them_stale(self):
        review = self.core.review_command("printf 'é😀'", True)
        self.ui.render()
        with mock.patch.object(self.core, "approve") as approve:
            self.ui.payload_details_button.invoke()
            window, captured, status = self.ui.payload_details
            self.assertEqual(captured, review)
            self.assertIn("Aktueller Snapshot", status.get())
            box = next(child for child in window.winfo_children() if child.winfo_class() == "TFrame")
            text = next(child for child in box.winfo_children() if child.winfo_class() == "Text")
            self.assertEqual(text.cget("state"), "disabled")
            self.assertIn("U+1F600", text.get("1.0", "end"))
            changed = self.core.edit_review(review.id, "printf 'new'", False)
            self.ui.render()
            self.assertNotEqual(changed.id, review.id)
            self.assertIn("Nicht mehr aktuell", status.get())
            self.assertEqual(self.core.review_state, "REVIEW")
            approve.assert_not_called()

    def test_normalization_hint_is_bound_to_the_current_revision_and_direction(self):
        review = self.core.review_command("a\r\nb\r\n\n", True)
        self.ui.render()
        self.assertIn("CRLF→LF: 2", self.ui.normalization.get())
        self.assertIn("Schluss-LF entfernt: 2", self.ui.normalization.get())
        self.assertEqual(review.payload, b"a\nb\n")
        self.core.edit_review(review.id, "new", False)
        self.ui.render()
        self.assertIn("CRLF→LF: 0", self.ui.normalization.get())
        self.assertIn("Return: AUS", self.ui.normalization.get())
        self.core._output_review("output\n")
        self.ui.render()
        self.assertNotIn("CRLF", self.ui.normalization.get())

    def test_source_selection_copy_unicode_lf_wrap_and_partial_notation_reject(self):
        source = "TOKEN_" + "a" * 180 + " é😀\nsecond ↵ line\n"
        review = self.core._output_review(source)
        self.ui.render()
        box = self.ui.editor
        text = box.text
        with mock.patch.object(self.core, "approve") as approve:
            text.tag_add("sel", "1.0", "end-1c")
            text.event_generate("<<Copy>>")
            self.assertEqual(self.root.clipboard_get(), source)
            text.tag_remove("sel", "1.0", "end")
            start = source.index("é")
            text.tag_add("sel", box.copy_positions[start], box.copy_positions[start + 2])
            box.copy_selection()
            self.assertEqual(self.root.clipboard_get(), "é😀")
            self.root.clipboard_clear()
            self.root.clipboard_append("CLIPBOARD_CANARY")
            text.tag_remove("sel", "1.0", "end")
            text.tag_add("sel", text.index(box.copy_positions[start] + "+1c"), box.copy_positions[start + 1])
            box.copy_selection()
            self.assertEqual(self.root.clipboard_get(), "CLIPBOARD_CANARY")
            self.assertIn("Zeichennotation", self.ui.copy_notice.get())
            before = text.get("1.0", "end-1c")
            text.event_generate("<<Paste>>")
            self.assertEqual(text.get("1.0", "end-1c"), before)
            self.assertEqual(text.cget("state"), "disabled")
            self.assertEqual(self.core.review, review)
            self.assertEqual(self.core.review_state, "REVIEW")
            approve.assert_not_called()

    def test_exact_snapshot_copy_rechecks_identity_even_before_render(self):
        review = self.core.review_command("echo 'é😀'\r\n", True)
        self.ui.show_payload_details()
        self.ui.payload_copy_button.invoke()
        self.assertEqual(self.root.clipboard_get().encode(), review.payload)
        self.core.edit_review(review.id, "new", False)
        self.root.clipboard_clear()
        self.root.clipboard_append("STALE_CANARY")
        self.ui.copy_payload_snapshot(review)
        self.assertEqual(self.root.clipboard_get(), "STALE_CANARY")
        self.assertTrue(self.ui.payload_copy_button.instate(["disabled"]))

    def test_native_editable_text_and_entry_paste_without_review_mutation(self):
        review = self.core.review_command("echo safe", False)
        window = tk.Toplevel(self.root)
        editor = a.ScrollableText(window)
        editor.frame.pack()
        entry = ttk.Entry(window)
        entry.pack()
        window.update()
        self.root.clipboard_clear()
        self.root.clipboard_append("SYNTHETIC_TOKEN_" + "z" * 200 + "\né")
        editor.text.event_generate("<<Paste>>")
        self.assertEqual(editor.text.get("1.0", "end-1c"), self.root.clipboard_get())
        entry.event_generate("<<Paste>>")
        self.assertIn("SYNTHETIC_TOKEN_", entry.get())
        self.assertEqual(self.core.review, review)
        self.assertEqual(self.core.review_state, "REVIEW")
        window.destroy()

    def test_mouse_context_copy_paste_for_entries_text_and_readonly_fields(self):
        window = tk.Toplevel(self.root)
        try:
            widgets = (tk.Entry(window), ttk.Entry(window, show="*"), ttk.Combobox(window),
                       tk.Spinbox(window), ttk.Spinbox(window), tk.Text(window, height=2))
            for widget in widgets:
                widget.pack()
            self.root.update()
            menu = self.ui.clipboard_menu.menu
            for widget in widgets:
                with self.subTest(widget=widget.winfo_class()):
                    self.root.clipboard_clear()
                    self.root.clipboard_append("MOUSE-é")
                    widget.event_generate("<Button-3>", x=5, y=5, rootx=100, rooty=100)
                    self.root.update()
                    self.assertIs(self.ui.clipboard_menu.target, widget)
                    self.assertEqual(str(menu.entrycget("Einfügen", "state")), "normal")
                    menu.invoke("Einfügen")
                    menu.unpost()
                    if isinstance(widget, tk.Text):
                        self.assertEqual(widget.get("1.0", "end-1c"), "MOUSE-é")
                        widget.tag_add("sel", "1.0", "end-1c")
                    else:
                        self.assertIn("MOUSE-é", widget.get())
                        widget.selection_range(0, "end")
                    widget.event_generate("<Button-3>", x=5, y=5, rootx=100, rooty=100)
                    self.root.update()
                    menu.invoke("Kopieren")
                    menu.unpost()
                    copied = widget.get("1.0", "end-1c") if isinstance(widget, tk.Text) else widget.get()
                    self.assertEqual(self.root.clipboard_get(), copied)
            entry = widgets[1]
            entry.configure(state="readonly")
            entry.selection_range(0, "end")
            entry.event_generate("<Button-3>", x=5, y=5, rootx=100, rooty=100)
            self.root.update()
            self.assertEqual(str(menu.entrycget("Einfügen", "state")), "disabled")
            self.assertEqual(str(menu.entrycget("Kopieren", "state")), "normal")
            menu.unpost()
            self.assertIsNone(self.core.review)
        finally:
            window.destroy()

    def test_code_context_paste_edits_source_selection_only_after_apply(self):
        review = self.core.review_command("echo é😀 old", False)
        self.ui.render()
        box = self.ui.editor
        box.show_review(review.text, ((0, len(review.text), 50),))
        first, last = review.text.index("old"), len(review.text)
        box.text.tag_add("sel", box.copy_positions[first], box.copy_positions[last])
        self.root.clipboard_clear()
        self.root.clipboard_append("new")
        with mock.patch.object(self.core, "approve") as approve:
            box.text.event_generate("<Button-3>", x=5, y=5, rootx=100, rooty=100)
            self.root.update()
            self.ui.context.invoke("Einfügen")
            self.ui.context.unpost()
            self.root.update()
            self.assertEqual(self.ui.edit_box.text.get("1.0", "end-1c"), "echo é😀 new")
            self.assertEqual(self.core.review, review)
            self.ui.edit_apply_button.invoke()
            self.root.update()
            self.assertEqual(self.core.review.text, "echo é😀 new")
            self.assertGreater(self.core.review.revision, review.revision)
            self.assertEqual(self.core.review_state, "REVIEW")
            approve.assert_not_called()
        self.core.review_state = "ACKNOWLEDGED_LOCAL"
        box.text.event_generate("<Button-3>", x=5, y=5, rootx=100, rooty=100)
        self.root.update()
        self.assertEqual(str(self.ui.context.entrycget("Einfügen", "state")), "disabled")
        self.ui.context.unpost()

    def test_keyboard_and_context_copy_keep_review_colors_font_and_risk_tags(self):
        review = self.core.review_command("echo é😀", False)
        self.ui.render()
        box = self.ui.editor
        box.show_review(review.text, ((0, 4, 90),))
        self.root.update()
        box.text.focus_force()
        self.root.update()
        box.text.tag_add("sel", "1.0", box.copy_positions[-1])
        box.text.event_generate("<Control-c>")
        self.assertEqual(self.root.clipboard_get(), review.text)
        self.ui.context.invoke(0)
        self.assertEqual(self.root.clipboard_get(), review.text)
        self.assertEqual(box.text.cget("background"), "#000000")
        self.assertEqual(box.text.cget("foreground"), "#00ff00")
        self.assertEqual(box.text.cget("font"), str(self.ui.review_font))
        self.assertEqual(box.text.tag_cget("control", "foreground"), "#a8c2e0")
        self.assertEqual(box.text.tag_cget("warning", "foreground"), "#edbd8d")
        self.assertTrue(box.text.tag_ranges("risk-sub-0"))
        self.assertFalse(self.core.risk_requested)

    def test_normal_code_has_no_permanent_hint_but_expiry_restores_warning(self):
        binding = dict(code="A1B2C3D4", status="ACTIVE", generation=1,
                       server_time=100.0, expires_at=200.0, retry_at=0.0,
                       restriction_scope="PRINCIPAL")
        bridge = a.replace(self.core.bridge_snapshot(), state="CONNECTED", mode="REMOTE",
                           chat_binding=binding, chat_binding_received_at=10.0)
        with mock.patch.object(a.time, "monotonic", return_value=11.0), \
                mock.patch.object(self.core, "bridge_snapshot", return_value=bridge):
            self.ui.render()
            self.root.update_idletasks()
            self.assertEqual(self.ui.chat_code.get(), "A1B2-C3D4")
            self.assertEqual(self.ui.chat_code_status.get(), "")
            self.assertFalse(self.ui.chat_code_status_label.winfo_ismapped())
            self.assertTrue(self.ui.chat_code_copy.instate(["!disabled"]))
        expired = a.replace(bridge, chat_binding=dict(binding, expires_at=100.0))
        with mock.patch.object(a.time, "monotonic", return_value=11.0), \
                mock.patch.object(self.core, "bridge_snapshot", return_value=expired):
            self.ui.render()
            self.root.update_idletasks()
            self.assertEqual(self.ui.chat_code.get(), "")
            self.assertIn("Abgelaufen", self.ui.chat_code_status.get())
            self.assertTrue(self.ui.chat_code_status_label.winfo_ismapped())
            self.assertTrue(self.ui.chat_code_copy.instate(["disabled"]))


class TerminalAttachmentUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aitl-terminal-ui-")
        self.core = a.AppCore()
        self.core.start_local(self.tmp.name)
        self.root = tk.Tk()
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)

    def until(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("terminal_attach_timeout")

    def end_shell(self):
        if self.core.channel and self.core.connection == "CONNECTED":
            review = self.core.review_command("exit", True)
            self.core.approve(review.id)
            self.until(lambda: self.core.connection == "DISCONNECTED", 3)

    def cleanup(self):
        try:
            self.end_shell()
        except Exception:
            pass
        self.core.close()
        if self.ui.launcher and self.ui.launcher.poll() is None:
            try:
                self.ui.launcher.wait(timeout=2)
            except Exception:
                self.ui.launcher.terminate()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.tmp.cleanup()

    def test_attached_hides_attach_button_and_loss_allows_fresh_attach(self):
        self.root.update()
        button = self.ui.terminal_button
        self.assertTrue(button.winfo_ismapped())
        self.ui.open_terminal()
        self.until(lambda: self.core.connection == "CONNECTED")
        self.ui.render()
        self.assertFalse(button.winfo_ismapped())
        self.assertIn("Terminal verbunden", self.ui.terminal_status.get())

        self.end_shell()
        self.ui.render()
        self.assertTrue(button.winfo_ismapped())
        self.assertEqual(button.instate(["!disabled"]), True)
        self.assertIn("Terminal getrennt", self.ui.terminal_status.get())
        old_endpoint = self.core.endpoint
        button.invoke()
        self.assertIsNot(self.core.endpoint, old_endpoint)
        self.until(lambda: self.core.connection == "CONNECTED")
        self.ui.render()
        self.assertFalse(button.winfo_ismapped())
        self.assertIn("Terminal verbunden", self.ui.terminal_status.get())


class StageConflictDialogTests(unittest.TestCase):
    """§13.4/§13.7(10): exact #36 dialog texts, buttons, neutral cancel, core parity."""

    SEND_TEXT = ("Die Ausgabe des vorherigen Kommandos wurde noch nicht an die KI zurückgegeben. "
                 "Möchtest du darauf verzichten und das neue Kommando senden?")
    TAKE_RETURN_TEXT = ("Im Review-Bereich liegt bereits ein neuer Kommandovorschlag. "
                        "Möchtest du ihn verwerfen, um die Ausgabe des vorherigen Kommandos zu prüfen?")
    TAKE_PROPOSAL_TEXT = ("Im Review-Bereich liegt die Ausgabe des vorherigen Kommandos. "
                          "Möchtest du die Rückgabeprüfung verlassen und den neuen Kommandovorschlag prüfen? "
                          "Die Ausgabe bleibt für eine spätere Rückgabe erhalten.")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aitl-stage-ui-")
        self.core = a.AppCore()
        self.core.start_local(self.tmp.name)
        self.root = tk.Tk()
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)
        self.root.update()
        self.ui.open_terminal()
        self.until(lambda: self.core.connection == "CONNECTED")
        self.core.connect_local_bridge()
        self.until(lambda: self.core.bridge_state == "CONNECTED")

    def until(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("stage_dialog_timeout")

    def cleanup(self):
        try:
            if self.core.open_return is not None:
                self.core.close_open_return()
            if self.core.connection == "CONNECTED" and self.core.channel:
                review = self.core.review_command("exit", True)
                self.core.approve(review.id)
                self.until(lambda: self.core.connection == "DISCONNECTED", 3)
        except Exception:
            pass
        self.core.close()
        if self.ui.launcher and self.ui.launcher.poll() is None:
            try:
                self.ui.launcher.wait(timeout=2)
            except Exception:
                self.ui.launcher.terminate()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.tmp.cleanup()

    def submit(self, text, request):
        mcp(self.core.bridge_process, "submit_proposal", {"request_id": request, "text": text})
        self.until(lambda: bool(self.core.inbox))

    def take(self):
        self.ui.from_ai_button.invoke()
        self.until(lambda: self.core.review_state == "TAKE_PENDING")
        self.root.update()
        self.assertIn("Übernahme wird bestätigt", self.ui.review_status.get())
        self.assertTrue(self.ui.approve_button.instate(["disabled"]))
        self.until(lambda: self.core.review_state == "REVIEW")

    def transfer(self):
        review = self.core.review
        self.core.approve(review.id)
        self.until(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(review.id, override=True)
        self.until(lambda: self.core.review_state == "TRANSFERRED")

    def assert_dialog(self, message, ordered_labels):
        self.root.update()
        dialog = self.ui.conflict_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.ui.conflict_message_label.cget("text"), message)
        self.assertEqual([button.cget("text") for button in self.ui.conflict_buttons.values()],
                         ordered_labels)

    def test_clipboard_selection_reads_on_check_and_requires_explicit_approval(self):
        self.submit("printf 'LOCAL_SOURCE\\n'", "GUI_CLIPBOARD_SOURCE_001")
        self.take()
        self.transfer()
        self.ui.output_mode.set("Zwischenablage")
        with mock.patch.object(self.root, "clipboard_get", side_effect=AssertionError("early read")):
            self.ui.change_output_mode()
            self.ui.render()
        self.root.clipboard_clear()
        self.root.clipboard_append("External clipboard snapshot\n")
        pending = dict(self.core.open_return)
        self.ui.from_terminal_button.invoke()
        self.root.update()
        review = self.core.review
        self.assertEqual(review.text, "External clipboard snapshot\n")
        self.assertEqual(review.output_source, "CLIPBOARD")
        self.assertEqual(self.ui.direction.get(), "Zwischenablage → AI")
        self.assertEqual(self.ui.review_notebook.tab(self.ui.code_tab, "text"), "Zwischenablage")
        self.assertIsNone(self.ui.binding_submission[self.ui.binding_value.get()])
        self.root.clipboard_clear()
        self.root.clipboard_append("Changed after review")
        self.assertEqual(self.core.review.text, "External clipboard snapshot\n")
        self.assertEqual(mcp(self.core.bridge_process, "get_approved_output")["outputs"], [])
        self.ui.approve_button.invoke()
        self.until(lambda: self.core.review_state == "ACKNOWLEDGED")
        output = mcp(self.core.bridge_process, "get_approved_output")["outputs"][0]
        self.assertEqual(output["text"], review.text)
        self.assertIsNone(output["submission_id"])
        self.assertEqual(self.core.open_return, pending)
        self.ui.from_terminal_button.invoke()
        self.assertEqual(self.core.review.text, "Changed after review")

    def test_clipboard_unavailable_and_active_review_leave_content_unchanged(self):
        self.core.set_output_mode("CLIPBOARD")
        with mock.patch.object(self.ui.messagebox, "showerror") as error:
            with mock.patch.object(self.root, "clipboard_get", side_effect=tk.TclError()):
                self.ui.from_terminal()
            self.assertIn("keinen verfügbaren Text", error.call_args.args[1])
            self.assertIsNone(self.core.review)
            command = self.core.review_command("true")
            with mock.patch.object(self.root, "clipboard_get", side_effect=AssertionError("early read")):
                self.ui.from_terminal()
            self.assertIn("offene Prüfung", error.call_args.args[1])
            self.assertEqual(self.core.review, command)

    def test_send_conflict_dialog_cancel_escape_and_waiver_send(self):
        self.submit("printf 'GUI_STAGE_A\\n'", "GUI_STAGE_A_REQ_0001")
        self.take()
        self.transfer()  # open return for A exists now
        self.submit(": > gui-b-marker; printf 'GUI_STAGE_B\\n'", "GUI_STAGE_B_REQ_0001")
        self.take()
        self.root.update()
        self.assertTrue(self.ui.from_ai_button.instate(["disabled"]))  # initiation barrier visible
        self.ui.approve_button.invoke()  # send click with an open return -> dialog, no transfer
        self.assert_dialog(self.SEND_TEXT,
                           ["Ohne Rückgabe fortfahren und senden", "Neuen Vorschlag verwerfen", "Abbrechen"])
        self.assertFalse(Path(self.tmp.name, "gui-b-marker").exists())
        self.ui.conflict_buttons["CANCEL"].invoke()
        self.root.update()
        self.assertEqual(self.core.review_state, "REVIEW")  # cancel is state-neutral
        self.assertIsNotNone(self.core.open_return)
        self.assertFalse(Path(self.tmp.name, "gui-b-marker").exists())
        self.ui.approve_button.invoke()
        self.assert_dialog(self.SEND_TEXT,
                           ["Ohne Rückgabe fortfahren und senden", "Neuen Vorschlag verwerfen", "Abbrechen"])
        self.ui.conflict_dialog.event_generate("<Escape>")
        self.root.update()
        self.assertEqual(self.core.review_state, "REVIEW")  # Escape == Abbrechen (default)
        self.assertIsNotNone(self.core.open_return)
        self.ui.approve_button.invoke()
        self.until(lambda: self.ui.conflict_dialog is not None and self.ui.conflict_dialog.winfo_exists())
        self.ui.conflict_buttons["CLOSE_WITHOUT_RETURN_AND_SEND"].invoke()
        self.until(lambda: self.core.review_state in {"CHECKING", "TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(self.core.review.id, override=True)
        self.until(lambda: self.core.review_state == "TRANSFERRED")
        self.assertTrue(Path(self.tmp.name, "gui-b-marker").exists())
        self.assertEqual(self.core.open_return["return_state"], "offen_sammelnd")  # B's own return now

    def test_recheck_running_command_output_before_and_after_first_return_without_reexecution(self):
        gate = Path(self.tmp.name, "continue-output")
        counter = Path(self.tmp.name, "execution-count")
        # Octal markers prevent the shell's echoed command from satisfying output checks.
        command = ("printf 'run\\n' >> execution-count; printf '\\101\\114\\120\\110\\101\\n'; "
                   "while [ ! -e continue-output ]; do sleep 0.02; done; "
                   "printf '\\102\\105\\124\\101\\n'")
        try:
            self.submit(command, "RECHECK_OUTPUT_0001")
            self.take()
            submission = self.core.review.proposal_id
            self.transfer()
            self.until(lambda: b"ALPHA\r\n" in self.core.output.data)
            with mock.patch.object(self.core.channel, "send", wraps=self.core.channel.send) as terminal_send:
                self.ui.from_terminal_button.invoke()
                first = self.core.review
                self.assertEqual(first.direction, "TO_OUTPUT_SINK")
                self.assertIn("ALPHA\n", first.text)
                self.assertNotIn("BETA\n", first.text)
                draft = self.core.edit_review(first.id, "unshared draft", False)
                self.ui.render()
                # Every click reloads a fresh capture, even while already reviewing output.
                self.ui.from_terminal_button.invoke()
                self.assertNotEqual(self.core.review.id, draft.id)
                self.assertIn("ALPHA\n", self.core.review.text)
                self.assertNotIn("unshared draft", self.core.review.text)
                self.core.edit_review(self.core.review.id, "checked ALPHA\n", False)
                self.ui.render()
                self.ui.approve_button.invoke()
                with self.assertRaisesRegex(a.ProbeError, "return_not_ready"):
                    self.core.take_return_review()
                with self.assertRaisesRegex(a.ProbeError, "transfer_in_progress"):
                    self.core.select_current_output()
                self.until(lambda: self.core.review_state == "ACKNOWLEDGED")
                first_id = self.core.review.id
                self.assertIsNone(self.core.open_return)
                self.assertFalse(gate.exists())  # The command is still waiting for its late output.
                first_return = mcp(self.core.bridge_process, "get_approved_output", {"submission_id": submission})
                self.assertEqual(first_return["outputs"][0]["text"], "checked ALPHA\n")
                self.assertEqual(first_return["outputs"][0]["submission_id"], submission)
                gate.touch()
                self.until(lambda: b"BETA\r\n" in self.core.output.data)
                self.ui.from_terminal_button.invoke()
                second = self.core.review
                self.assertNotEqual(second.id, first_id)
                self.assertEqual(second.direction, "TO_OUTPUT_SINK")
                self.assertIn("ALPHA\n", second.text)
                self.assertIn("BETA\n", second.text)
                self.assertEqual(self.ui.binding_submission[self.ui.binding_value.get()], submission)
                args = {"submission_id": submission, "cursor": first_return["cursor"]}
                self.assertEqual(mcp(self.core.bridge_process, "get_approved_output", args)["outputs"], [])
                second = self.core.edit_review(second.id, "checked ALPHA\nchecked BETA\n", False)
                self.ui.render()
                self.ui.approve_button.invoke()
                self.until(lambda: self.core.review_state == "ACKNOWLEDGED")
                late_return = mcp(self.core.bridge_process, "get_approved_output", args)["outputs"]
                self.assertEqual(len(late_return), 1)
                self.assertEqual(late_return[0]["submission_id"], submission)
                self.assertEqual(late_return[0]["text"].encode(), second.payload)
                self.assertNotEqual(late_return[0]["output_id"], first_return["outputs"][0]["output_id"])
                self.assertFalse(self.core.inbox)
                terminal_send.assert_not_called()  # Reviewing/editing/returning never sends terminal input.
            self.assertEqual(counter.read_text(), "run\n")
        finally:
            gate.touch()  # Always let the existing fixture finish its command and clean up.

    def test_bidirectional_dialogs_park_and_resume_via_ui(self):
        self.submit("printf 'GUI_STAGE_A\\n'", "GUI_BIDI_A_00001")
        self.take()
        self.transfer()
        # Return review from a free stage needs no dialog.
        self.ui.from_terminal_button.invoke()
        self.until(lambda: self.core.review_state == "REVIEW"
                   and self.core.review.direction == "TO_OUTPUT_SINK")
        self.assertEqual(self.core.open_return["return_state"], "in_stage")
        # Direction 2: proposal takeover while the return review occupies the stage.
        self.submit("printf 'GUI_STAGE_D\\n'", "GUI_BIDI_D_00001")
        self.ui.from_ai_button.invoke()
        self.assert_dialog(self.TAKE_PROPOSAL_TEXT, ["Neuen Vorschlag prüfen", "Abbrechen"])
        self.ui.conflict_buttons["CANCEL"].invoke()
        self.root.update()
        self.assertEqual(self.core.review.direction, "TO_OUTPUT_SINK")  # return review kept
        self.ui.from_ai_button.invoke()
        self.until(lambda: self.ui.conflict_dialog is not None and self.ui.conflict_dialog.winfo_exists())
        self.ui.conflict_buttons["LEAVE_RETURN_TAKE_PROPOSAL"].invoke()
        self.until(lambda: self.core.review_state == "TAKE_PENDING")
        self.until(lambda: self.core.review_state == "REVIEW")
        self.assertEqual(self.core.review.direction, "TO_TERMINAL")
        self.assertIsNotNone(self.core.open_return)  # leaving is not waiving
        self.assertEqual(self.core.open_return["return_state"], "reviewbereit")
        # Direction 1: return review requested while proposal D occupies the stage.
        self.ui.from_terminal_button.invoke()
        self.assert_dialog(self.TAKE_RETURN_TEXT, ["Vorschlag verwerfen und Ausgabe prüfen", "Abbrechen"])
        self.ui.conflict_buttons["CANCEL"].invoke()
        self.root.update()
        self.assertEqual(self.core.review.direction, "TO_TERMINAL")  # D untouched
        self.ui.from_terminal_button.invoke()
        self.until(lambda: self.ui.conflict_dialog is not None and self.ui.conflict_dialog.winfo_exists())
        self.ui.conflict_buttons["DISCARD_PROPOSAL_TAKE_RETURN"].invoke()
        self.root.update()
        self.assertEqual(self.core.review.direction, "TO_OUTPUT_SINK")  # A's capture staged
        self.assertIsNotNone(self.core.staged_handoff)  # D parked losslessly
        self.assertEqual(self.core.open_return["return_state"], "in_stage")
        # Rejecting the staged return completes it (§14.2: same closure as the waiver).
        self.core.reject(self.core.review.id)
        self.assertIsNone(self.core.open_return)
        self.ui.from_ai_button.invoke()  # staged_handoff present -> resume path
        self.root.update()
        self.assertIsNone(self.core.staged_handoff)
        self.assertEqual(self.core.review_state, "REVIEW")
        self.assertEqual(self.core.review.text, "printf 'GUI_STAGE_D\\n'\n")


    def test_uncertain_send_dialog_blocks_until_conscious_confirmation(self):
        self.submit("printf 'GUI_UNC_A\\n'", "GUI_UNCERTAIN_A_001")
        self.take()
        with mock.patch.object(self.core.channel, "send", side_effect=OSError("link down")):
            with self.assertRaises(a.ProbeError):
                self.core.approve(self.core.review.id)
        self.assertEqual(self.core.review_state, "TRANSFER_UNCERTAIN")
        self.submit(": > gui-unc-b-marker; printf 'GUI_UNC_B\\n'", "GUI_UNCERTAIN_B_001")
        self.take()  # stage change allowed while the fact stands
        self.root.update()
        self.assertIn("Übertragung des vorherigen Befehls ungewiss", self.ui.review_status.get())
        self.ui.approve_button.invoke()
        self.assert_dialog("Die Übertragung des vorherigen Befehls ist ungewiss. "
                           "Trotzdem den neuen Befehl senden und auf die vorherige Rückgabe verzichten?",
                           ["Trotzdem senden und verzichten", "Abbrechen"])
        self.ui.conflict_buttons["CANCEL"].invoke()
        self.root.update()
        self.assertFalse(self.core.uncertain_transfer["operator_acknowledged"])
        self.assertFalse(Path(self.tmp.name, "gui-unc-b-marker").exists())
        self.ui.approve_button.invoke()
        self.until(lambda: self.ui.conflict_dialog is not None and self.ui.conflict_dialog.winfo_exists())
        self.ui.conflict_buttons["PROCEED_UNCERTAIN_SEND"].invoke()
        self.until(lambda: self.core.review_state in {"CHECKING", "TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(self.core.review.id, override=True)
        self.until(lambda: self.core.review_state == "TRANSFERRED")
        self.assertTrue(Path(self.tmp.name, "gui-unc-b-marker").exists())
        self.assertTrue(self.core.uncertain_transfer["operator_acknowledged"])
        self.assertNotEqual(self.core.uncertain_transfer["command_review_id"], self.core.review.id)
        self.root.update()
        self.assertNotIn("Übertragung des vorherigen Befehls ungewiss", self.ui.review_status.get())


class SentStylingUITests(unittest.TestCase):
    """M3/#74: sent snapshots keep their marks and gain honest sent optics;
    unknown tails show a non-blocking readiness hint; copy stays exact."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aitl-sent-ui-")
        self.core = a.AppCore()
        self.core.start_local(self.tmp.name)
        self.root = tk.Tk()
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)
        self.root.update()
        self.ui.open_terminal()
        self.until(lambda: self.core.connection == "CONNECTED")

    def until(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("sent_ui_timeout")

    def cleanup(self):
        try:
            if self.core.connection == "CONNECTED" and self.core.channel:
                review = self.core.review_command("exit", True)
                self.core.approve(review.id)
                self.until(lambda: self.core.connection == "DISCONNECTED", 3)
        except Exception:
            pass
        self.core.close()
        if self.ui.launcher and self.ui.launcher.poll() is None:
            try:
                self.ui.launcher.wait(timeout=2)
            except Exception:
                self.ui.launcher.terminate()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.tmp.cleanup()

    def test_sent_optics_labels_and_exact_copy(self):
        item = self.core.review_command("printf SENT_MARK", True)
        self.until(lambda: self.core.review_state == "REVIEW" and "AI → Terminal" in self.ui.direction.get())
        self.assertNotIn("Eingabezustand unklar", self.ui.review_status.get())
        self.assertNotIn("gesendet", self.ui.direction.get())
        self.core.approve(item.id)
        self.until(lambda: self.core.review_state == "TRANSFERRED")
        self.until(lambda: "Gesendet ins Terminal · Bytes übertragen" in self.ui.review_status.get())
        self.assertIn("AI → Terminal", self.ui.direction.get())
        self.assertIn("gesendet", self.ui.direction.get())
        text = self.ui.editor.text
        self.assertTrue(text.tag_ranges("sent"))
        # Exact copy survives the sent state (presentation only, never payload).
        text.tag_add("sel", "1.0", "end-1c")
        self.ui.editor.copy_selection()
        self.assertEqual(self.root.clipboard_get(), "printf SENT_MARK\n")
        # A fresh review removes the sent optics again.
        self.core.review_command("printf NEXT_MARK", True)
        self.until(lambda: self.core.review_state == "REVIEW" and not text.tag_ranges("sent"))
        self.assertNotIn("gesendet", self.ui.direction.get())

    def test_unknown_tail_hint_is_honest_and_non_blocking(self):
        first = self.core.review_command("IFS= read -r -p 'GUI_WAIT: ' x; printf '\\nGUI_DONE\\n'", True)
        self.core.approve(first.id)
        self.until(lambda: self.core.review_state == "TRANSFERRED")
        self.until(lambda: bytes(self.core.output.data).endswith(b"GUI_WAIT: "))
        self.core.review_command("answer", True)
        self.until(lambda: "Eingabezustand unklar" in self.ui.review_status.get())
        # #74: the honest hint never blocks the explicit reviewed send.
        self.core.approve(self.core.review.id)
        self.until(lambda: self.core.review_state == "TRANSFERRED"
                   and b"\r\nGUI_DONE\r\n" in self.core.output.data)

    def test_output_share_sent_labels(self):
        review = self.core.review_command("printf SHARED_MARK", True)
        self.core.approve(review.id)
        self.until(lambda: self.core.review_state == "TRANSFERRED")
        output = self.core.select_current_output()
        self.core.approve(output.id)
        self.until(lambda: self.core.review_state == "ACKNOWLEDGED_LOCAL")
        self.until(lambda: "Output lokal freigegeben · keine AI-Übertragung" in self.ui.review_status.get())
        self.assertIn("Terminal → AI", self.ui.direction.get())
        self.assertIn("gesendet", self.ui.direction.get())
        self.assertTrue(self.ui.editor.text.tag_ranges("sent"))


class QrexecDialogTests(unittest.TestCase):
    """M9 #88-#91: ein Wizard-Schritt = eine Seite; EIN Klick prueft und fordert den
    Code; Kopplung nur per Code mit nicht-editierbarer Fingerprint-Anzeige (TOFU-Pin
    bleibt technisch erhalten); Diagnose pro Versuch; Navigation loest nichts aus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aitl-qrexec-ui-")
        self.addCleanup(self.tmp.cleanup)
        self.core = a.AppCore(connection_store=a.ConnectionStore(Path(self.tmp.name, "config")))
        self.root = tk.Tk()
        self.callbacks = []
        self.root.report_callback_exception = lambda *_: self.callbacks.append("tk_callback_failed")
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)
        self.root.update()

    def cleanup(self):
        self.core.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.ui = self.core = self.root = None
        gc.collect()

    def open_dialog(self, qubes):
        patcher = mock.patch.object(a, "qubes_detected", return_value=qubes)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(a, "source_qube_name", return_value="personal" if qubes else None):
            dialog = self.ui.connection_settings()
        self.root.update()
        return dialog

    def labels(self, frame):
        found = []
        stack = [frame]
        while stack:
            widget = stack.pop()
            for child in widget.winfo_children():
                if child.winfo_class() == "TLabel":
                    found.append(str(child.cget("text")))
                stack.append(child)
        return found

    def test_cards_first_only_one_page_and_restart(self):
        dialog = self.open_dialog(False)
        values = [str(button.cget("value")) for button in dialog.location_buttons]
        self.assertEqual(values, ["LOCAL", "REMOTE"])  # keine Qube-Karte ohne Qubes
        self.assertTrue(dialog.cards.winfo_ismapped())
        for hidden in (dialog.local, dialog.remote, dialog.qrexec_panel,
                       dialog.tunnel_section, dialog.chat_section, dialog.controls):
            self.assertFalse(hidden.winfo_ismapped())
        dialog.location.set("REMOTE")
        self.root.update()
        self.assertEqual(dialog.wizard_step.get(), "Schritt 1 von 4 · Bridge-Standort und Startbefehl")
        self.assertTrue(dialog.remote_setup.winfo_ismapped())
        self.assertFalse(dialog.remote_pair.winfo_ismapped())
        self.assertFalse(dialog.cards.winfo_ismapped())
        # Ruewaerts erhalt Eingaben; zweiter Rueckschritt erreicht die Karten erneut.
        dialog.fields["qrexec_target"].set("untrusted")
        dialog.wizard_goto(2)
        dialog.wizard_goto(0)
        self.assertEqual(dialog.fields["qrexec_target"].get(), "untrusted")
        dialog.wizard_back()
        self.root.update()
        self.assertEqual(dialog.location.get(), "CARD")
        self.assertTrue(dialog.cards.winfo_ismapped())
        # Expliziter Neustart ist nur Assistent-Zustand: kein Core-Eingriff noetig.
        dialog.location.set("QREXEC") if False else None
        self.assertEqual(self.callbacks, [])

    def test_qubes_flow_check_then_hello_then_code_page(self):
        dialog = self.open_dialog(True)
        values = [str(button.cget("value")) for button in dialog.location_buttons]
        self.assertEqual(values, ["LOCAL", "QREXEC", "REMOTE"])
        dialog.location.set("QREXEC")
        self.root.update()
        self.assertTrue(dialog.q1.winfo_ismapped())
        self.assertIn("qrexec_copy_command", dialog.buttons)  # One-click copy in the simplified setup.
        self.assertNotIn("qrexec_pin", dialog.fields)  # #90: keine Hex-Pflichteingabe
        # Feldbezogene Validierung am Schritt 1, inkl. IP/localhost-Ausschluss.
        for bad in ("bad name", "127.0.0.1", "localhost"):
            dialog.fields["qrexec_target"].set(bad)
            dialog.buttons["wizard_next"].invoke()
            self.assertIn("Qube-Name", dialog.errors["bridge"].get())
            self.assertEqual(dialog.wizard_step.get(), "Schritt 1 von 5 · Ziel-Qube")
        dialog.fields["qrexec_target"].set("untrusted")
        dialog.buttons["wizard_next"].invoke()
        self.assertIn("nicht verifiziert", dialog.qubes_note.get())
        self.root.update()
        self.assertEqual(dialog.wizard_step.get(), "Schritt 2 von 5 · Bridge starten und verbinden")
        self.assertEqual(dialog.qrexec_command_box.text.get("1.0", "end-1c").strip(),
                         "python3 ./admin_in_the_loop.py --bridge")
        self.assertTrue(any("Strg+Umschalt+C" in text for text in self.labels(dialog.q2)))
        self.assertTrue(any("39 Zeichen" in text for text in self.labels(dialog.q2)))  # #7 Laengenanker
        self.assertFalse(dialog.tunnel_section.winfo_ismapped())  # #98: nicht im Hauptfluss
        self.assertTrue(dialog.q2_tunnel_box.frame.winfo_manager() == "")  # eingeklappt
        # Primäraktion direkt unter dem Startbefehl; Fehler bleibt auf dem Schritt.
        self.assertEqual(dialog.buttons["qrexec_check"].cget("text"),
                         "Bridge gestartet – Verbindung prüfen")
        fail = {"phase": "qrexec_target_unreachable", "reachable": False, "observed_pin": None}

        def fail_check(target, port=8443):
            self.core._qrexec_note("qvm-connect-tcp", "qrexec_target_unreachable", None,
                                   "Beleg aus Mock", "Erneut prüfen")
            return fail
        with mock.patch.object(self.core, "verify_qrexec_connection", side_effect=fail_check):
            dialog.buttons["qrexec_check"].invoke()
        self.assertEqual(dialog.wizard_index, 1)  # Fehler bleibt auf dem Schritt
        self.assertIn("Erneut prüfen", dialog.qrexec_status.get())
        self.assertNotEqual(dialog.qrexec_help.winfo_manager(), "")
        self.assertIn("qubes.ConnectTCP +8443 personal untrusted allow",
                      dialog.qrexec_policy_box.text.get("1.0", "end-1c"))
        dialog.q2_diag_open.set(True)
        dialog.refresh_qubes_diagnostics()
        self.root.update()
        self.assertIn("Phase qrexec_target_unreachable", dialog.q2_diag_box.text.get("1.0", "end-1c"))
        # EIN Klick: Erreichbarkeit erfolgreich -> desselbe Klick fordert den Code an
        # und wechselt erst jetzt automatisch auf die Kopplungsseite.
        ok = {"phase": "bridge_reachable", "reachable": True, "observed_pin": "ab" * 32}
        with mock.patch.object(self.core, "verify_qrexec_connection", return_value=ok) as check, \
                mock.patch.object(self.core, "hello_bridge", return_value="pairing_required") as hello:
            dialog.buttons["qrexec_check"].invoke()
        check.assert_called_once()
        hello.assert_called_once_with("https://127.0.0.1:8443")
        self.assertEqual(dialog.wizard_index, 2)
        self.assertEqual(dialog.wizard_step.get(), "Schritt 3 von 5 · Bewusst koppeln")
        displayed = dialog.qrexec_pin_box.text.get("1.0", "end-1c").replace(" ", "")
        self.assertEqual(displayed, "ab" * 32)  # vollständiger Fingerprint, nur Anzeige
        self.assertEqual(dialog.qrexec_pin_box.text.cget("state"), "disabled")
        self.core.qrexec_forwarder = mock.Mock(running=True)
        self.root.update()
        self.assertTrue(dialog.buttons["qrexec_pair"].instate(["disabled"]))  # ohne Code gesperrt
        self.assertEqual(dialog.entries["qrexec_code"].cget("show"), "")  # #102: Klartext
        dialog.fields["qrexec_code"].set("ABCD-EFGH")
        self.root.update()
        self.assertTrue(dialog.buttons["qrexec_pair"].instate(["!disabled"]))
        with mock.patch.object(self.core, "begin_pair_remote") as pair:
            dialog.pair_qrexec()
        pair.assert_called_once_with("https://127.0.0.1:8443", "ab" * 32, "ABCDEFGH")  # normalisiert ohne Bindestrich
        self.assertEqual(dialog.fields["qrexec_code"].get(), "")
        self.assertEqual(self.callbacks, [])

    def test_hello_failure_and_already_paired_stay_on_check_page(self):
        dialog = self.open_dialog(True)
        dialog.location.set("QREXEC")
        dialog.fields["qrexec_target"].set("untrusted")
        dialog.wizard_goto(1)
        ok = {"phase": "bridge_reachable", "reachable": True, "observed_pin": "cd" * 32}
        with mock.patch.object(self.core, "verify_qrexec_connection", return_value=ok):
            # Code-Anforderung scheitert (Cooldown): Schritt bleibt, Beleg entwertet.
            with mock.patch.object(self.core, "hello_bridge", side_effect=a.ProbeError("pairing_rate_limited")):
                dialog.buttons["qrexec_check"].invoke()
            self.assertEqual(dialog.wizard_index, 1)
            self.assertIn("Code-Anforderung fehlgeschlagen", dialog.qrexec_status.get())
            self.assertIsNone(dialog.qrexec_observed_pin)
            # already_paired ohne passende gespeicherte Credentials: ehrlicher Status,
            # keine Ubernahme, kein Fortschritt (0.9.3) – kein Auth-Bypass.
            with mock.patch.object(self.core, "hello_bridge", return_value="already_paired"), \
                    mock.patch.object(self.core, "connect_saved_bridge") as connect:
                dialog.buttons["qrexec_check"].invoke()
            self.assertEqual(dialog.wizard_index, 1)
            self.assertIn("keine passende gespeicherte", dialog.qrexec_status.get())
            connect.assert_not_called()
            self.assertIsNone(self.core.remote_tunnel_probe)
        # Navigation loest niemals Bridge-/Hallo-Aktionen aus (Negativkontrolle).
        with mock.patch.object(self.core, "verify_qrexec_connection") as check, \
                mock.patch.object(self.core, "hello_bridge") as hello, \
                mock.patch.object(self.core, "start_qrexec_forwarder") as start:
            dialog.buttons["wizard_next"].invoke()  # -> Kopplungsseite (leere Felder)
            dialog.buttons["wizard_back"].invoke()
            dialog.wizard_restart()
        check.assert_not_called()
        hello.assert_not_called()
        start.assert_not_called()
        self.assertEqual(dialog.location.get(), "CARD")
        self.assertEqual(self.callbacks, [])

    def test_already_paired_takeover_restores_saved_pinned_connection_once(self):
        # 0.9.3: passende gespeicherte Controller-Verbindung wird automatisch ueber
        # den bestehenden echt authentifizierten Weg wiederhergestellt (Pin vor
        # Bytes, idempotentes Confirm) – ohne Code-Schritt, ohne Doppeluebernahme,
        # ohne Neukopplung, keine Tunnel-Beobachtung ohne echte Verbindung.
        dialog = self.open_dialog(True)
        dialog.location.set("QREXEC")
        dialog.fields["qrexec_target"].set("untrusted")
        dialog.wizard_goto(1)
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "cd" * 32, "c" * 64, "d" * 32, "e" * 64)
        self.core.connection_store.save_connection(profile, None, {"target": "untrusted", "port": 8443})
        ok = {"phase": "bridge_reachable", "reachable": True, "observed_pin": "cd" * 32}
        with mock.patch.object(self.core, "verify_qrexec_connection", return_value=ok), \
                mock.patch.object(self.core, "hello_bridge", return_value="already_paired"), \
                mock.patch.object(self.core, "connect_saved_bridge") as connect:
            dialog.buttons["qrexec_check"].invoke()
            self.assertEqual(connect.call_count, 1)
            self.assertIn("wiederhergestellt", dialog.qrexec_status.get())
            # Bewusster zweiter Klick auf derselben Seite: keine Doppelwiederherstellung.
            dialog.fields["qrexec_target"].set("untrusted")  # identical, no invalidation
            dialog.buttons["qrexec_check"].invoke()
            self.assertEqual(connect.call_count, 1)
            self.assertIn("bereits angestoßen", dialog.qrexec_status.get())
        self.assertIsNone(self.core.remote_tunnel_probe)
        self.assertEqual(self.callbacks, [])

    def test_already_paired_takeover_requires_matching_saved_target(self):
        # 0.9.3: gespeichertes Ziel muss zum eingegebenen passen – Ubernahme auf ein
        # anderes Qube ist stillschweigend ausgeschlossen (auch manuell).
        dialog = self.open_dialog(True)
        dialog.location.set("QREXEC")
        dialog.fields["qrexec_target"].set("untrusted")
        dialog.wizard_goto(1)
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "cd" * 32, "c" * 64, "d" * 32, "e" * 64)
        self.core.connection_store.save_connection(profile, None, {"target": "other-qube", "port": 8443})
        ok = {"phase": "bridge_reachable", "reachable": True, "observed_pin": "cd" * 32}
        with mock.patch.object(self.core, "verify_qrexec_connection", return_value=ok), \
                mock.patch.object(self.core, "hello_bridge", return_value="already_paired"), \
                mock.patch.object(self.core, "connect_saved_bridge") as connect:
            dialog.buttons["qrexec_check"].invoke()
        connect.assert_not_called()
        self.assertIn("keine passende gespeicherte", dialog.qrexec_status.get())
        self.root.update()
        self.assertTrue(dialog.buttons["qrexec_saved_connect"].instate(["disabled"]))
        self.assertEqual(self.callbacks, [])

    def test_remote_reachability_is_not_pairing_and_pin_is_readonly(self):
        dialog = self.open_dialog(False)
        dialog.location.set("REMOTE")
        dialog.wizard_goto(1)
        self.root.update()
        self.assertTrue(dialog.buttons["pair"].instate(["disabled"]))
        with mock.patch.object(self.core, "hello_bridge", return_value="pairing_required"):
            with mock.patch.object(a, "bridge_reachability", return_value="ef" * 32):
                dialog.buttons["remote_check"].invoke()
        self.assertTrue(dialog.buttons["pair"].instate(["disabled"]))  # Code fehlt noch
        self.assertEqual(dialog.remote_pin_box.text.get("1.0", "end-1c").replace(" ", "").strip(), "ef" * 32)
        # Bloede Erreichbarkeit ohne bestaetigte Code-Anforderung koppelt nicht.
        dialog.qrexec_reset_verification()
        with mock.patch.object(a, "bridge_reachability", return_value="ef" * 32):
            with mock.patch.object(self.core, "hello_bridge", side_effect=a.ProbeError("pairing_contract")):
                dialog.buttons["remote_check"].invoke()
        self.assertIsNone(dialog.remote_observed_pin)  # kein Beleg bei Vertragsfehler
        self.assertIn("Code-Anforderung fehlgeschlagen", dialog.remote_status.get())
        self.assertEqual(self.callbacks, [])


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(verbosity=2, resultclass=a.SafeResult))
