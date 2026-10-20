"""Tk UX regressions: readable evidence, explicit actions, focus and small windows.

Uses validated synthetic analyzer output; native CLI/UI tests live separately in
test_shguard_integration.py. Run under xvfb-run or a controlled DISPLAY.
"""
import gc
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
import test_command_risk as fixtures


@unittest.skipUnless(os.environ.get("DISPLAY"), "controlled Tk display not supplied")
class CommandRiskUXTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory()
        self.core = a.AppCore(a.PreferenceStore(Path(self.temp.name) / "config"))
        self.core.session, self.core.connection = "UX_TEST", "CONNECTED"
        self.core.set_command_target("TERMINAL")
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *_: self.errors.append("tk_callback")
        self.ui = a.ReviewUI(self.root, self.core)
        self.root.geometry("960x560+0+0")
        self.root.update()
        self.review = self.core.review_command("rm -rf /")
        self.ui.render()

    def tearDown(self):
        self.core.close()
        self.ui.risk_progress.stop()  # Native ttk timer scripts are not Python callbacks.
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.ui = self.root = self.core = None
        gc.collect()
        self.temp.cleanup()
        self.assertFalse(self.errors)

    def result(self, *, unmapped=False, score=100):
        data = fixtures.rich_analysis()
        data["score"] = score
        level = sum(score > boundary for boundary in (20, 50, 80))
        data["level"] = a.RISK_LEVELS[level]
        data["command"] = self.review.text
        data["sub_commands"][0]["command"] = "another command" if unmapped else self.review.text.rstrip("\n")
        data["reason"] = "Readable reason with umlauts: gefährlich\u202eHIDDEN"
        data = a.validate_command_risk(json.dumps(data).encode(), self.review.text, level)
        tool = a.CommandRiskTool("/fixture/sh-guard", "a" * 64, 1, "0.1.10", 0)
        key = a.CommandRiskKey(0, tool, self.review.id, self.review.revision, self.review.direction,
                               self.review.session, None, None, None, self.review.final_return,
                               hashlib.sha256(self.review.payload).hexdigest())
        return a.CommandRiskSnapshot("RESULT", a.CommandRiskResult(key, "RESULT", data=data))

    def enable_guard_view(self):
        self.core.risk_requested = True
        self.core.risk_setup_state = "UNAVAILABLE"
        self.core.risk_setup_error = "risk_process_failure"
        self.ui.render()

    def press(self, widget, key):
        widget.focus_force()
        self.root.update()
        widget.event_generate("<KeyPress-" + key + ">")
        self.root.update()

    def test_readable_summary_precedes_technical_json_and_preserves_payload(self):
        self.core.risk_requested = True
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result()):
            self.ui.render()
            self.ui.command_risk_details()
            self.assertEqual(self.ui.review_notebook.index("current"), 1)
            summary = self.ui.risk_summary_box.text.get("1.0", "end-1c")
            technical = self.ui.risk_details_box.text.get("1.0", "end-1c")
            self.assertIn("Kritisch · 100/100", summary)
            self.assertIn("Pipeline übergibt Daten zur Ausführung", summary)
            self.assertIn("Einzelbefehle", summary)
            self.assertIn("gefährlich", summary)
            self.assertIn("\\u202eHIDDEN", summary)
            self.assertNotIn("\u202e", summary)
            self.assertNotIn("U+00", summary)
            self.assertNotIn("binary_sha256", summary)
            self.assertIn('"risk_factors"', technical)
            self.assertIn("Binary-SHA-256", technical)
            self.assertEqual(self.core.review.payload, self.review.payload)
            self.core.channel.send.assert_not_called()
            self.assertTrue(self.ui.risk_remove_button.instate(["disabled"]))
            self.core.review_state = "TRANSFERRED"
            self.ui.render()
            self.assertTrue(self.ui.risk_review_action.instate(["disabled"]))
            self.assertIn("Bereits gesendet", self.ui.risk_summary_box.text.get("1.0", "end"))

    def test_keyboard_tabs_and_escape_return_to_code_without_activation_or_transfer(self):
        self.enable_guard_view()
        self.ui.editor.text.focus_force()
        self.root.update()
        self.ui.editor.text.event_generate("<Control-Tab>")
        self.root.update()
        self.assertEqual(self.ui.review_notebook.index("current"), 1)
        self.assertEqual(self.ui.risk_review_action.cget("text"), "Erneut prüfen")
        self.assertEqual(self.root.grab_current(), None)
        self.assertTrue(self.core.risk_requested)
        self.press(self.ui.risk_summary_box.text, "Escape")
        self.assertEqual(self.ui.review_notebook.index("current"), 0)
        self.assertEqual(self.root.focus_get(), self.ui.editor.text)
        self.assertEqual(self.core.review_state, "REVIEW")
        self.core.channel.send.assert_not_called()

    def test_selecting_marked_code_does_not_switch_tabs_but_context_action_does(self):
        self.enable_guard_view()
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result()):
            self.ui.render()
            self.root.update()
            self.assertTrue(self.ui.editor.text.tag_ranges("risk-sub-0"))
            x, y, _, _ = self.ui.editor.text.bbox("1.0")
            self.ui.editor.text.event_generate("<Button-1>", x=x+1, y=y+1)
            self.root.update()
            self.assertEqual(self.ui.review_notebook.index("current"), 0)
            self.ui.editor.text.tag_add("sel", "1.0", "1.2")
            self.ui.editor.copy_selection()
            self.assertEqual(self.root.clipboard_get(), "rm")
            self.ui.editor.copy_menu.invoke("Analysebefund anzeigen")
            self.assertEqual(self.ui.review_notebook.index("current"), 1)
            self.assertEqual(self.core.review.payload, self.review.payload)
            self.core.channel.send.assert_not_called()

    def test_analysis_update_preserves_code_scroll_and_selection(self):
        self.enable_guard_view()
        self.review = self.core.review_command("\n".join("printf 'line %d'" % i for i in range(35)))
        self.ui.render()
        self.root.update()
        self.ui.editor.text.yview_moveto(.6)
        self.ui.editor.text.tag_add("sel", "28.0", "28.6")
        before_view = self.ui.editor.text.yview()[0]
        before_selection = tuple(str(i) for i in self.ui.editor.text.tag_ranges("sel"))
        self.assertGreater(before_view, 0)
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result()):
            self.ui.render()
            self.root.update()
            self.assertEqual(self.ui.review_notebook.index("current"), 0)
            self.assertEqual(tuple(str(i) for i in self.ui.editor.text.tag_ranges("sel")), before_selection)
            self.assertAlmostEqual(self.ui.editor.text.yview()[0], before_view, delta=.05)
            self.core.channel.send.assert_not_called()

    def test_new_review_starts_in_code_and_passive_updates_preserve_selected_tab(self):
        visible = [self.ui.review_notebook.tab(tab, "text") for tab in self.ui.review_notebook.tabs()
                   if self.ui.review_notebook.tab(tab, "state") != "hidden"]
        self.assertEqual(visible, ["Code"])
        self.enable_guard_view()
        self.assertEqual(self.ui.review_notebook.index("current"), 0)
        self.ui.command_risk_details()
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result()):
            self.ui.render()
            self.assertEqual(self.ui.review_notebook.index("current"), 1)
        self.core.edit_review(self.review.id, "printf edited", True)
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.index("current"), 0)
        self.ui.command_risk_details()
        self.core.review_command("printf new")
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.index("current"), 0)
        self.ui.show_risk_technical()
        self.core._output_review("separate output")
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.index("current"), 0)
        self.assertEqual(self.ui.review_notebook.tab(self.ui.code_tab, "text"), "Ausgabe")
        self.assertIsNone(self.root.grab_current())
        self.core.channel.send.assert_not_called()

    def test_multiselect_keeps_popup_open_and_updates_only_selected_tool_tabs(self):
        self.ui.toggle_review_selector()
        self.root.update()
        self.assertTrue(self.ui.review_options.winfo_viewable())

        def requested(enabled):
            self.core.preference_store.save_command_risk(enabled)
            self.core.risk_requested = enabled
            self.core.risk_setup_state = "UNAVAILABLE" if enabled else "DISABLED"

        with mock.patch.object(self.core, "request_command_risk", side_effect=requested):
            self.ui.risk_checkbox.invoke()
            self.ui.text_review_checkbox.invoke()
            self.root.update()
            self.assertTrue(self.ui.review_options.winfo_viewable())
            self.assertTrue(self.core.preference_store.load_command_risk())
            self.assertTrue(self.core.preference_store.load_text_review())
            self.assertEqual(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "state"), "normal")
            self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "normal")
            self.assertEqual(self.ui.review_selection.get(), "Befehlsprüfung (2)")
            self.ui.close_review_selector(True)
            self.ui.command_risk_details()
            self.assertEqual(self.ui.review_notebook.select(), str(self.ui.risk_summary_tab))
            self.ui.toggle_review_selector()
            self.ui.risk_checkbox.invoke()
            self.root.update()
            self.assertEqual(self.ui.review_notebook.select(), str(self.ui.code_tab))
            self.assertEqual(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "state"), "hidden")
            self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "normal")
            self.assertFalse(self.core.preference_store.load_command_risk())
        self.press(self.ui.text_review_checkbox, "Escape")
        self.assertFalse(self.ui.review_options.winfo_viewable())
        self.assertEqual(self.root.focus_get(), self.ui.review_picker)
        self.core.channel.send.assert_not_called()

    def test_side_selectors_keep_directional_options_and_tabs_independent(self):
        self.enable_guard_view()
        self.assertTrue(str(self.ui.return_review_picker).startswith(str(self.ui.panels[0])+"."))
        self.assertTrue(str(self.ui.review_picker).startswith(str(self.ui.panels[2])+"."))
        self.ui.toggle_review_selector("command")
        self.root.update()
        self.ui.text_review_checkbox.invoke()
        self.assertTrue(self.core.preference_store.load_text_review("command"))
        self.assertFalse(self.core.preference_store.load_text_review("output"))
        self.ui.toggle_review_selector("output")
        self.root.update()
        self.assertFalse(self.ui.risk_checkbox.winfo_ismapped())
        self.assertTrue(self.ui.output_scan_notice.winfo_ismapped())
        self.assertFalse(self.ui.text_review_options["output"].get())
        self.ui.text_review_checkbox.invoke()
        self.assertTrue(self.core.preference_store.load_text_review("output"))
        self.press(self.ui.text_review_checkbox, "Escape")
        self.assertEqual(self.root.focus_get(), self.ui.return_review_picker)
        self.core._output_review("later output\n")
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "state"), "hidden")
        self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "normal")
        self.assertIn("Rückgabe", self.ui.text_views.tab(self.ui.text_settings_page, "text"))
        self.ui.toggle_review_selector("output")
        self.ui.text_review_checkbox.invoke()
        self.ui.close_review_selector()
        self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "hidden")
        self.assertTrue(self.ui.text_review_choices["command"])
        self.assertTrue(self.core.risk_requested)
        self.core.review_command("printf next")
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "normal")
        self.assertEqual(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "state"), "normal")
        self.assertEqual(self.ui.review_notebook.select(), str(self.ui.code_tab))
        self.core.channel.send.assert_not_called()

    def test_output_settings_target_left_option_while_command_is_in_review(self):
        self.ui.toggle_review_selector("output")
        self.ui.text_settings_button.invoke()
        self.root.update()
        self.assertEqual(self.ui.text_settings_direction, "output")
        self.assertIn("Rückgabe", self.ui.text_views.tab(self.ui.text_settings_page, "text"))
        self.assertFalse(self.ui.text_review_choices["output"])
        self.ui.text_settings_checkbox.invoke()
        self.assertTrue(self.ui.text_review_choices["output"])
        self.assertFalse(self.ui.text_review_choices["command"])
        self.assertTrue(self.core.preference_store.load_text_review("output"))
        self.assertFalse(self.core.preference_store.load_text_review("command"))
        self.core.channel.send.assert_not_called()

    def test_side_popups_fit_inside_small_and_large_windows(self):
        for size in ("960x560", "1360x850"):
            self.root.geometry(size+"+24+20")
            self.root.update()
            for direction in ("command", "output"):
                with self.subTest(size=size, direction=direction):
                    self.ui.toggle_review_selector(direction)
                    self.root.update()
                    popup = self.ui.review_options
                    self.assertGreaterEqual(popup.winfo_rootx(), self.root.winfo_rootx())
                    self.assertGreaterEqual(popup.winfo_rooty(), self.root.winfo_rooty())
                    self.assertLessEqual(popup.winfo_rootx()+popup.winfo_width(),
                                         self.root.winfo_rootx()+self.root.winfo_width())
                    self.assertLessEqual(popup.winfo_rooty()+popup.winfo_height(),
                                         self.root.winfo_rooty()+self.root.winfo_height())
                    settings = self.ui.text_settings_button
                    self.assertLessEqual(settings.winfo_rootx()+settings.winfo_width(),
                                         popup.winfo_rootx()+popup.winfo_width())
                    self.ui.close_review_selector()

    def test_tool_badges_report_critical_score_and_independent_unicode_hints(self):
        self.core.risk_requested = True
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result()) as state:
            self.ui.render()
            self.assertIn("ROT 100", self.ui.review_notebook.tab(self.ui.risk_summary_tab, "text"))
            self.assertTrue(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "image"))
            self.ui.text_review_checkbox.invoke()
            self.assertIn("GRÜN 0", self.ui.review_notebook.tab(self.ui.text_review_tab, "text"))
            state.return_value = a.CommandRiskSnapshot("UNKNOWN")
            self.ui.render()
            self.assertIn("GELB ?", self.ui.review_notebook.tab(self.ui.risk_summary_tab, "text"))
        self.core.review_command("printf 'grün'")
        self.ui.render()
        self.assertIn("GELB 1", self.ui.review_notebook.tab(self.ui.text_review_tab, "text"))
        self.assertIn("U+00FC", self.ui.text_review_box.text.get("1.0", "end"))
        self.assertIn("keine Risikopunkte", self.ui.text_review_box.text.get("1.0", "end"))
        self.core.channel.send.assert_not_called()

    def test_inline_install_requires_explicit_choice_and_keeps_actions_visible(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                self.core.risk_requested = True
                self.core.risk_setup_state = "INSTALL_CONFIRM"
                installation = a.CommandRiskInstallation(self.core.preference_store.directory, a.command_risk_release())
                self.core.risk_installation = installation
                choices = []

                def commit(confirmed):
                    choices.append(confirmed)
                    self.core.request_command_risk(False)

                with mock.patch.object(self.core, "confirm_command_risk_install", side_effect=commit), \
                        mock.patch.object(a, "CommandRiskSetup") as setup:
                    self.ui.show_review_settings("sh-guard")
                    self.root.update()
                    self.ui.render()
                    self.assertEqual(choices, [])
                    source = self.ui.risk_setup_box.text.get("1.0", "end")
                    self.assertIn(installation.release.url, source)
                    self.assertIn(str(installation.destination), source)
                    self.assertIn(installation.release.archive_sha256, source)
                    self.assertIn("Einrichtung nötig", source)
                    self.assertIn("Einrichtung nötig", self.ui.review_notebook.tab(self.ui.risk_summary_tab, "text"))
                    for button in (self.ui.risk_install_button, self.ui.risk_install_cancel):
                        self.assertTrue(button.winfo_ismapped())
                        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                             self.root.winfo_rooty() + self.root.winfo_height())
                    self.assertFalse(any(w.winfo_viewable() for w in self.root.winfo_children()
                                         if isinstance(w, self.ui.tk.Toplevel)))
                    self.press(self.ui.risk_install_button if accepted else self.ui.risk_install_cancel, "Return")
                    self.assertEqual(choices, [accepted])
                    setup.assert_not_called()
                self.core.channel.send.assert_not_called()

    def test_changed_activation_invalidates_queued_install_choice(self):
        self.core.risk_requested = True
        self.core.risk_setup_state = "INSTALL_CONFIRM"
        self.core.risk_installation = a.CommandRiskInstallation(self.core.preference_store.directory, a.command_risk_release())
        self.ui.show_review_settings("sh-guard")
        old_command = self.ui.risk_install_button.cget("command")
        self.core.risk_setup_epoch += 1
        with mock.patch.object(self.core, "confirm_command_risk_install") as confirm:
            self.root.tk.call(old_command)
            confirm.assert_not_called()
        self.assertTrue(self.core.risk_requested)
        self.ui.show_review_code()
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.select(), str(self.ui.code_tab))

    def test_settings_gears_inspect_inactive_services_without_enabling_them(self):
        for button in (self.ui.risk_settings_button, self.ui.text_settings_button):
            self.assertTrue(str(button.cget("image")))
            self.assertEqual(str(button.cget("compound")), "left")
        with mock.patch.object(self.core, "request_command_risk") as activate:
            self.ui.toggle_review_selector()
            self.ui.risk_settings_button.invoke()
            self.root.update()
            self.assertFalse(self.ui.review_options.winfo_viewable())
            self.assertEqual(self.ui.risk_views.select(), str(self.ui.risk_settings_page))
            self.assertIn("Ausgeschaltet", self.ui.risk_setup_box.text.get("1.0", "end"))
            self.assertFalse(self.core.risk_requested)
            activate.assert_not_called()
            self.ui.close_review_settings("sh-guard")
            self.assertEqual(self.ui.review_notebook.tab(self.ui.risk_summary_tab, "state"), "hidden")
            self.ui.toggle_review_selector()
            self.press(self.ui.text_settings_button, "Return")
            self.assertEqual(self.ui.text_views.select(), str(self.ui.text_settings_page))
            self.assertFalse(self.ui.text_review_requested)
            self.assertIn("Keine Einrichtung", self.ui.text_settings_box.text.get("1.0", "end"))
            self.ui.close_review_settings("text")
            self.assertEqual(self.ui.review_notebook.tab(self.ui.text_review_tab, "state"), "hidden")
            self.assertFalse(self.core.preference_store.load_text_review())
            self.assertFalse(self.core.preference_store.load_command_risk())
            self.core.channel.send.assert_not_called()

    def test_failed_initialization_can_be_retried_in_settings_without_passive_navigation(self):
        self.enable_guard_view()
        self.ui.show_review_settings("sh-guard")
        self.root.update()
        self.assertIn("Initialisierung fehlgeschlagen", self.ui.risk_setup_box.text.get("1.0", "end"))
        self.assertIn("risk_process_failure", self.ui.risk_setup_box.text.get("1.0", "end"))
        self.assertFalse(self.ui.risk_install_button.winfo_ismapped())
        with mock.patch.object(self.core, "request_command_risk") as activate:
            self.press(self.ui.risk_setup_retry, "Return")
            activate.assert_called_once_with(True)
        self.ui.show_review_code()
        self.core.risk_setup_state = "CHECKING_TOOL"
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.select(), str(self.ui.code_tab))
        self.assertTrue(self.ui.risk_setup_retry.instate(["disabled"]))
        self.core.risk_setup_state = "INSTALL_CONFIRM"
        self.ui.render()
        self.assertEqual(self.ui.review_notebook.select(), str(self.ui.code_tab))
        self.assertIn("Einrichtung nötig", self.ui.review_notebook.tab(self.ui.risk_summary_tab, "text"))
        self.core.channel.send.assert_not_called()

    def test_error_retry_and_busy_cancel_have_explicit_keyboard_actions(self):
        self.core.risk_requested = True
        state = a.CommandRiskSnapshot("UNAVAILABLE", error="risk_download_timeout")
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=state) as snapshot, \
                mock.patch.object(self.core, "request_command_risk") as requested:
            self.ui.render()
            self.ui.command_risk_details()
            self.root.update()
            self.assertTrue(self.ui.risk_action_button.winfo_ismapped())
            self.assertIn("erneut versuchen", self.ui.risk_hint.get())
            self.assertEqual(self.ui.risk_action_button.cget("text"), "Erneut prüfen")
            self.press(self.ui.risk_action_button, "Return")
            requested.assert_called_once_with(True)
            requested.reset_mock()
            snapshot.return_value = a.CommandRiskSnapshot("DOWNLOADING")
            self.ui.render()
            self.root.update()
            self.assertTrue(self.ui.risk_progress.winfo_ismapped())
            self.assertTrue(self.ui.risk_progress_running)
            self.assertEqual(self.ui.risk_action_button.cget("text"), "Abbrechen")
            # A result arriving just before the click must not reinterpret the
            # visible Cancel button as an activation/retry request.
            snapshot.return_value = self.result()
            self.press(self.ui.risk_action_button, "Return")
            requested.assert_called_once_with(False)
            self.assertFalse(self.ui.risk_progress_running)
            self.core.channel.send.assert_not_called()

    def test_unknown_and_missing_spans_do_not_look_like_successful_highlighting(self):
        self.core.risk_requested = True
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result(unmapped=True)) as snapshot:
            self.ui.render()
            self.assertIn("Kritisch", self.ui.risk_status.get())
            self.assertIn("Einzelmarkierungen nicht verfügbar", self.ui.risk_hint.get())
            self.assertFalse(self.ui.editor.text.tag_ranges("risk-sub-0"))
            snapshot.return_value = a.CommandRiskSnapshot("UNKNOWN", error="risk_schema")
            self.ui.render()
            self.root.update()
            self.assertEqual(self.ui.risk_status.get(), "Analyse unvollständig")
            self.ui.command_risk_details()
            self.root.update()
            self.assertTrue(self.ui.risk_action_button.winfo_ismapped())
            self.assertFalse(self.ui.editor.text.tag_ranges("risk-sub-0"))
            self.assertNotIn("risk_schema", self.ui.risk_hint.get())

    def test_risk_levels_use_readable_text_and_contrast_on_light_and_dark_surfaces(self):
        from tkinter import font, ttk
        style = ttk.Style(self.root)
        previous = style.lookup("Review.TLabel", "background")

        def luminance(color):
            rgb = [value / 65535 for value in self.root.winfo_rgb(color)]
            rgb = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
            return sum(component * weight for component, weight in zip(rgb, (.2126, .7152, .0722)))

        try:
            for background in ("#d9d9d9", "#1e1e1e"):
                style.configure("Review.TLabel", background=background)
                for score, label in ((0, "Unauffällig"), (30, "Vorsicht"), (70, "Hohes Risiko"), (100, "Kritisch")):
                    with self.subTest(background=background, score=score), \
                            mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result(score=score)):
                        self.ui.render()
                        self.assertIn(label, self.ui.risk_status.get())
                        foreground = self.ui.risk_status_label.cget("foreground")
                        light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
                        self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)
            self.assertEqual(self.ui.risk_heading_font.actual("weight"), "bold")
            self.assertEqual(self.ui.risk_heading_font.actual("size"),
                             font.nametofont("TkDefaultFont", root=self.root).actual("size"))
        finally:
            style.configure("Review.TLabel", background=previous)

    def test_small_and_large_windows_keep_review_and_actions_visible(self):
        self.core.risk_requested = True
        with mock.patch.object(self.core, "command_risk_snapshot", return_value=self.result(unmapped=True)) as snapshot:
            for size in ("960x560", "1360x850"):
                for state in (self.result(unmapped=True),
                              a.CommandRiskSnapshot("UNAVAILABLE", error="risk_download_timeout")):
                    with self.subTest(size=size, state=state.state):
                        snapshot.return_value = state
                        self.root.geometry(size)
                        self.ui.render()
                        self.root.update()
                        self.ui.fit_panels()
                        self.root.update()
                        for widget in (self.ui.review_picker, self.ui.return_review_picker, self.ui.review_notebook, self.ui.approve_button,
                                       self.ui.return_checkbox, self.ui.reject_button):
                            self.assertGreater(widget.winfo_width(), 1)
                            self.assertGreaterEqual(widget.winfo_rootx(), self.root.winfo_rootx())
                            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                                 self.root.winfo_rootx() + self.root.winfo_width())
                            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                                 self.root.winfo_rooty() + self.root.winfo_height())
                        self.assertGreaterEqual(self.ui.editor.text.winfo_height(), 300)
                        self.assertFalse(self.ui.risk_row.winfo_ismapped())
            self.root.geometry("960x560")
            for page, button in ((self.ui.risk_summary_tab, self.ui.risk_review_action),
                                 (self.ui.risk_technical_tab, self.ui.risk_remove_button)):
                if page is self.ui.risk_technical_tab:
                    self.ui.show_risk_technical()
                else:
                    self.ui.command_risk_details()
                self.root.update()
                self.assertGreater(button.winfo_width(), 1)
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     self.ui.review_notebook.winfo_rootx() + self.ui.review_notebook.winfo_width())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     self.ui.review_notebook.winfo_rooty() + self.ui.review_notebook.winfo_height())


if __name__ == "__main__":
    unittest.main(verbosity=2)
