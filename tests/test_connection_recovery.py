"""Startup recovery: real pinned TLS plus controlled Qrexec lifecycle fixtures."""
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
from test_connected_mvp import RemoteFixture


def until(core, predicate, timeout=7):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        core.pump()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("recovery timeout: " + core.bridge_state)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        language = mock.patch.object(a, "UI_LANGUAGE", "de")
        language.start()
        self.addCleanup(language.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = a.ConnectionStore(Path(self.temp.name) / "config")
        self.core = a.AppCore(connection_store=self.store)
        self.addCleanup(self.core.close)

    def restored_chat(self, expired=True):
        """Real binding lifecycle, controlled transport/tunnel; no external access."""
        now = time.time()
        store = a.BridgeStore(Path(self.temp.name) / "binding", "c" * 32, clock=lambda: now)
        self.addCleanup(store.close)
        token, controller = store.issue("CONTROLLER")
        if expired:
            now += a.BRIDGE_CHAT_LIFETIME + 1
        core = self.core
        core.bridge_profile = a.ConnectionProfile("https://127.0.0.1:8443", "a" * 64,
                                                  store.conversation, controller, token)
        core.bridge_instance = store.instance
        core.bridge_state = "CONNECTED"
        core.bridge_worker = mock.Mock(events=queue.Queue(), stop=threading.Event())
        core.recovery_state = "CONNECTING"
        with mock.patch.object(core, "begin_tunnel_probe"):
            core._pump_connection_recovery()
        core.remote_tunnel_instance = store.instance
        core.remote_tunnel = {"phase": "connected", "received_at": time.monotonic()}
        core.chat_binding = store.chat_binding_status(controller)
        core.chat_binding_received_at = time.monotonic()
        return store, controller

    def test_pairing_preserves_local_tunnel_settings_if_its_binary_is_offline(self):
        binary = Path(self.temp.name) / "tunnel-client"
        binary.write_bytes(b"fixture")
        binary.chmod(0o700)
        config = {"binary": str(binary), "tunnel_id": "tunnel_" + "a"*32, "api_key": "test_key_"*4}
        self.store.save_connection(tunnel=config)
        binary.unlink()
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.store.update_connection(profile=profile, qrexec={"target": "review-qube", "port": 8443})
        self.assertEqual(self.store.load_connection()["tunnel"], config)
        self.assertEqual(self.store.load_connection()["profile"]["controller_id"], profile.controller_id)

    def recovery_dialog(self):
        """Exercise existing callbacks and presentation with controlled widget boundaries."""
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.saved_connection = {"profile": vars(profile), "tunnel": None, "qrexec": None}
        dialog = a.ConnectionDialog.__new__(a.ConnectionDialog)
        dialog.core, dialog.busy = self.core, False
        dialog.window, dialog.ui, dialog.ttk = mock.Mock(), mock.Mock(), mock.Mock()
        dialog.pairing = lambda: False
        dialog.errors = {"bridge": mock.Mock()}
        dialog.location = mock.Mock(get=mock.Mock(return_value="REMOTE"))
        dialog.connection_path, dialog.recovery_notice = mock.Mock(), mock.Mock()
        dialog.recovery_panel, dialog.recovery_overview = mock.Mock(), True
        dialog.management = True
        dialog.ui.core = self.core
        dialog.summary = mock.Mock()
        dialog.layer_labels = {name: mock.Mock() for name in ("Bridge", "Secure Tunnel", "Chat")}
        dialog.saved_qrexec_matches = lambda: False
        dialog.saved_matches = lambda: True
        dialog.refresh_saved = mock.Mock()
        dialog.buttons = {key: mock.Mock() for key in ("qrexec_stop", "qrexec_saved_connect",
                          "saved_connect", "tunnel_cancel_remote", "tunnel_cancel_qrexec")}
        dialog.render = lambda: dialog.render_connection_layers(self.core.bridge_snapshot())
        return dialog

    def test_retry_button_repaints_and_distinguishes_identical_immediate_failures(self):
        dialog = self.recovery_dialog()
        self.core.recovery_state, self.core.recovery_error = "NEEDS_ATTENTION", "network_unavailable"
        dialog.button(dialog.recovery_panel, 1, "recovery_retry", "Retry", "bridge", dialog.retry_recovery)
        callback = dialog.ttk.Button.call_args.kwargs["command"]
        def fail(_profile):
            self.assertIn("wird erneut gestartet", dialog.recovery_notice.set.call_args.args[0])
            dialog.window.update_idletasks.assert_called()
            self.assertIsNone(self.core.bridge_error)
            raise a.ProbeError("network_unavailable")
        with mock.patch.object(self.core, "connect_profile", side_effect=fail) as connect:
            notices = []
            for attempt in (1, 2):
                callback()
                notice = dialog.recovery_notice.set.call_args.args[0]
                self.assertIn("Versuch %d: fehlgeschlagen" % attempt, notice)
                self.assertIn("Gateway/Bridge nicht erreichbar", notice)
                self.assertEqual(self.core.recovery_attempt, attempt)
                notices.append(notice)
            self.assertEqual(connect.call_count, 2)
            self.assertNotEqual(*notices)
        dialog.recovery_panel.grid.assert_called()

    def test_failure_reason_is_primary_and_precedes_saved_setup_guidance_in_both_languages(self):
        dialog = self.recovery_dialog()
        self.core.recovery_attempt, self.core.recovery_state = 1, "NEEDS_ATTENTION"
        self.core.recovery_error = "qrexec_port_conflict"
        for language, guidance in (("de", "Gespeicherte Einrichtung gefunden"), ("en", "Saved setup found")):
            with mock.patch.object(a, "UI_LANGUAGE", language):
                dialog.render()
                notice = dialog.recovery_notice.set.call_args.args[0]
                self.assertIn("[qrexec_port_conflict]", notice.splitlines()[0])
                self.assertLess(notice.index(a.ConnectionDialog.error_text("qrexec_port_conflict")),
                                notice.index(guidance))
                self.assertNotIn("If it is running", notice)
        self.core.recovery_error = None
        dialog.render()
        notice = dialog.recovery_notice.set.call_args.args[0]
        self.assertIn("[recovery_reason_unavailable]", notice.splitlines()[0])
        self.assertIn("Konkreter Fehlergrund nicht verfügbar", notice)
        self.core.recovery_error = "unexpected secret text\nTOKEN=not-a-reason-code"
        dialog.render()
        notice = dialog.recovery_notice.set.call_args.args[0]
        self.assertNotIn("TOKEN", notice)
        self.assertIn("[recovery_reason_unavailable]", notice)

    def test_retry_requires_saved_configuration_and_does_not_interrupt_connecting(self):
        with self.assertRaisesRegex(a.ProbeError, "no_saved_remote_connection"):
            self.core.retry_connection_recovery()
        self.recovery_dialog()
        self.core.bridge_state = "CONNECTING"
        with mock.patch.object(self.core, "disconnect_bridge") as disconnect:
            with self.assertRaisesRegex(a.ProbeError, "setup_busy"):
                self.core.retry_connection_recovery()
            disconnect.assert_not_called()
        self.assertEqual(self.core.recovery_attempt, 0)

    def test_port_fallback_is_single_and_ownership_failure_does_not_trigger_it(self):
        for reason, calls in (("qrexec_port_conflict", 2), ("qrexec_ownership_unverified", 1)):
            with mock.patch.object(a.QrexecForwarder, "start", side_effect=a.ProbeError(reason)) as start:
                preparation = a.SavedForwarderPreparation("ai-bridge", 8443)
                self.addCleanup(preparation.close)
                preparation.thread.join(2)
                self.assertFalse(preparation.thread.is_alive())
                self.assertEqual(preparation.take(), ("error", reason))
                self.assertEqual(start.call_count, calls)
                if calls == 2:
                    self.assertEqual(start.call_args.kwargs["remote_port"], 8443)

    def test_alternate_route_is_only_allowed_for_pinned_remote_loopback(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        for port in (0, 65536, True, "8444"):
            with self.assertRaisesRegex(a.ProbeError, "invalid_forward_port"):
                a.check_profile(replace(profile, forward_port=port))
        with self.assertRaisesRegex(a.ProbeError, "invalid_forward_port"):
            a.check_profile(replace(profile, url="https://example.com:8443", forward_port=8444))
        with self.assertRaisesRegex(a.ProbeError, "invalid_forward_port"):
            a.check_profile(replace(profile, mode="LOCAL", url="http://127.0.0.1:8443", pin=None, forward_port=8444))

    def test_killed_forwarder_recovery_is_bounded_and_can_succeed(self):
        self.recovery_dialog()
        self.core.saved_connection["qrexec"] = {"target": "ai-bridge", "port": 8443}
        created = []
        def forwarder():
            item = mock.Mock(running=True, target="ai-bridge", port=8443, remote_port=8443)
            item.stop.return_value = True
            if not created:
                item.start.side_effect = a.ProbeError("qrexec_forwarder_killed")
            created.append(item)
            return item
        def connect(profile):
            self.core.bridge_profile = profile
            self.core.bridge_state = "CONNECTED"
        with mock.patch.object(a, "QrexecForwarder", side_effect=forwarder), \
                mock.patch.object(self.core, "connect_profile", side_effect=connect), \
                mock.patch.object(self.core, "begin_tunnel_probe"):
            self.core.begin_connection_recovery()
            until(self.core, lambda: self.core.recovery_state == "WAITING")
            self.assertIn("Erneuter Versuch", a.recovery_attempt_status(self.core))
            self.core.recovery_retry_at = 0
            until(self.core, lambda: self.core.recovery_state == "RESTORED")
            self.assertEqual(self.core.recovery_attempt, 2)
            self.assertEqual(self.core.recovery_retries_left, 1)
            self.assertEqual(self.core.bridge_profile.pin, "a" * 64)
            self.assertEqual(len(created), 2)
            self.core._recovery_failure("network_timeout")
            self.core.recovery_retry_at = 0
            until(self.core, lambda: self.core.recovery_state == "RESTORED")
            self.assertEqual(self.core.recovery_retries_left, 0)
            self.core._recovery_failure("network_timeout")
            self.assertEqual(self.core.recovery_state, "NEEDS_ATTENTION")
            self.assertEqual(len(created), 3)

    def test_repeated_killed_forwarders_stop_after_three_attempts(self):
        self.recovery_dialog()
        self.core.saved_connection["qrexec"] = {"target": "ai-bridge", "port": 8443}
        with mock.patch.object(a.QrexecForwarder, "start", side_effect=a.ProbeError("qrexec_forwarder_killed")) as start:
            self.core.begin_connection_recovery()
            for attempt in (1, 2, 3):
                until(self.core, lambda: self.core.recovery_state in {"WAITING", "NEEDS_ATTENTION"})
                self.assertEqual(self.core.recovery_attempt, attempt)
                if attempt < 3:
                    self.core.recovery_retry_at = 0
                    self.core._pump_connection_recovery()
            self.assertEqual(self.core.recovery_state, "NEEDS_ATTENTION")
            self.assertIn("Automatische Wiederaufnahme beendet", a.recovery_attempt_status(self.core))
            for _ in range(5):
                self.core.pump()
            self.assertEqual(start.call_count, 3)

    def test_auto_recovery_stops_on_foreign_port_identity_auth_or_target_change(self):
        self.recovery_dialog()
        self.core.saved_connection["qrexec"] = {"target": "ai-bridge", "port": 8443}
        self.core.recovery_target = self.core._saved_recovery_target()
        for reason in ("qrexec_port_conflict", "qrexec_ownership_unverified", "pin_mismatch", "network_http_401"):
            self.core._recovery_failure(reason)
            self.assertEqual(self.core.recovery_state, "NEEDS_ATTENTION")
            self.assertIsNone(self.core.recovery_retry_at)
        self.core._recovery_failure("network_timeout")
        self.core.saved_connection["qrexec"]["target"] = "different-qube"
        self.core.recovery_retry_at = 0
        with mock.patch.object(self.core, "begin_connection_recovery") as begin:
            self.core._pump_connection_recovery()
            begin.assert_not_called()
        self.assertEqual(self.core.recovery_error, "saved_connection_mismatch")

    def test_stalled_preparation_waits_for_cleanup_and_dead_preparation_is_detected(self):
        preparation = a.SavedForwarderPreparation.__new__(a.SavedForwarderPreparation)
        preparation.cancel, preparation.lock = threading.Event(), threading.Lock()
        preparation.result = None
        preparation.thread = mock.Mock(is_alive=mock.Mock(return_value=False))
        self.assertEqual(preparation.take(), ("error", "qrexec_preparation_interrupted"))
        preparation.thread.is_alive.return_value = True
        self.core.recovery_preparation = preparation
        self.core.recovery_state, self.core.recovery_deadline = "PREPARING", 0
        self.core._pump_connection_recovery()
        self.assertEqual(self.core.recovery_error, "qrexec_preparation_timeout")
        self.assertTrue(preparation.cancel.is_set())
        with self.assertRaisesRegex(a.ProbeError, "setup_busy"):
            self.core.retry_connection_recovery()
        preparation.thread.is_alive.return_value = False
        self.core._pump_connection_recovery()
        self.assertIsNone(self.core.recovery_preparation)

    def test_lost_own_forwarder_is_recovered_and_user_disconnect_cancels_pending_retry(self):
        self.recovery_dialog()
        self.core.saved_connection["qrexec"] = {"target": "ai-bridge", "port": 8443}
        self.core.recovery_target = self.core._saved_recovery_target()
        self.core.recovery_state, self.core.bridge_state = "RESTORED", "CONNECTED"
        self.core.qrexec_forwarder = mock.Mock(running=False)
        self.core._pump_connection_recovery()
        self.assertEqual(self.core.recovery_state, "WAITING")
        self.core.disconnect_bridge()
        self.assertEqual(self.core.recovery_state, "STOPPED")
        self.assertIsNone(self.core.recovery_retry_at)
        with mock.patch.object(self.core, "begin_connection_recovery") as begin:
            self.core._pump_connection_recovery()
            begin.assert_not_called()

    def test_cancelled_preparation_blocks_new_starts_until_its_thread_finishes(self):
        self.recovery_dialog()
        preparation = mock.Mock(thread=mock.Mock(is_alive=mock.Mock(return_value=True)))
        self.core.recovery_preparation = preparation
        self.core.disconnect_bridge()
        preparation.close.assert_called_once()
        with self.assertRaisesRegex(a.ProbeError, "setup_busy"):
            self.core.retry_connection_recovery()
        with self.assertRaisesRegex(a.ProbeError, "setup_busy"):
            self.core.connect_saved_bridge()
        preparation.thread.is_alive.return_value = False
        self.core._pump_connection_recovery()
        self.assertIsNone(self.core.recovery_cleanup)

    def test_stuck_bridge_connection_has_deadline_and_manual_stop_cancels_recovery(self):
        self.recovery_dialog()
        self.core.saved_connection["qrexec"] = {"target": "ai-bridge", "port": 8443}
        self.core.qrexec_forwarder = mock.Mock(running=True, target="ai-bridge", port=8443, remote_port=8443)
        self.core.qrexec_forwarder.stop.return_value = True
        def connecting(profile):
            self.core.bridge_profile, self.core.bridge_state = profile, "CONNECTING"
        with mock.patch.object(self.core, "connect_profile", side_effect=connecting):
            self.core.begin_connection_recovery()
        self.assertIsNotNone(self.core.recovery_deadline)
        self.core.bridge_state, self.core.recovery_deadline = "RETRYING", 0
        self.core._pump_connection_recovery()
        self.assertEqual(self.core.recovery_state, "WAITING")
        self.core.stop_qrexec_forwarder()
        self.assertEqual(self.core.recovery_state, "STOPPED")
        self.assertIsNone(self.core.recovery_retry_at)

    def test_already_paired_retries_blocked_and_later_disconnected_attempts(self):
        dialog = self.recovery_dialog()
        def start():
            self.core.bridge_state = "CONNECTING"
        with mock.patch.object(self.core, "retry_connection_recovery", side_effect=start) as retry:
            for state in ("BLOCKED", "BLOCKED", "DISCONNECTED"):
                self.core.bridge_state = state
                self.assertIn("wiederhergestellt", dialog.auto_takeover_paired())
                self.assertEqual(self.core.bridge_state, "CONNECTING")
                self.assertIn("bereits aufgebaut", dialog.auto_takeover_paired())
            self.assertEqual(retry.call_count, 3)
            self.core.bridge_state = "BLOCKED"
            dialog.saved_matches = lambda: False
            self.assertIn("keine passende", dialog.auto_takeover_paired())
            self.assertEqual(retry.call_count, 3)

    def test_already_paired_preserves_active_attempts_and_allows_retry_after_direct_failure(self):
        dialog = self.recovery_dialog()
        with mock.patch.object(self.core, "retry_connection_recovery",
                               side_effect=a.ProbeError("network_unavailable")) as retry:
            for state in ("CONNECTED", "CONNECTING", "PAIRING", "RETRYING"):
                self.core.bridge_state = state
                dialog.auto_takeover_paired()
            self.core.bridge_state = "DISCONNECTED"
            self.core.recovery_preparation = mock.Mock()
            dialog.auto_takeover_paired()
            self.core.recovery_preparation = None
            retry.assert_not_called()
            for _ in range(2):
                self.assertIn("Wiederherstellung fehlgeschlagen", dialog.auto_takeover_paired())
            self.assertEqual(retry.call_count, 2)

    def test_already_paired_reports_internally_caught_failures_as_new_attempts(self):
        dialog = self.recovery_dialog()
        self.core.bridge_state = "BLOCKED"
        with mock.patch.object(self.core, "connect_profile", side_effect=a.ProbeError("network_unavailable")):
            for attempt in (1, 2):
                self.assertIn("Wiederherstellung fehlgeschlagen", dialog.auto_takeover_paired())
                self.assertEqual(self.core.recovery_attempt, attempt)
                self.assertEqual(self.core.recovery_state, "NEEDS_ATTENTION")

    def test_expired_startup_code_rotates_once_and_is_visible_without_dialog(self):
        store, controller = self.restored_chat()
        core = self.core
        core._pump_recovered_chat_binding()
        core._pump_recovered_chat_binding()
        worker = core.bridge_worker
        worker.post.assert_called_once()
        name, (request, generation) = worker.post.call_args.args
        self.assertEqual(name, "rotate_chat_binding")
        self.assertFalse(a.chat_binding_presentation(core.bridge_snapshot())[2])
        result = store.rotate_chat_binding(request, generation, controller)
        worker.events.put((core.worker_id, "chat_binding", result))
        core._pump_bridge()
        code, _, can_copy = a.chat_binding_presentation(core.bridge_snapshot())
        self.assertEqual(code.replace("-", ""), result["code"])
        self.assertTrue(can_copy)
        self.assertEqual(result["generation"], generation + 1)
        # The worker's retry uses the same request, and the server does not rotate twice.
        self.assertEqual(store.rotate_chat_binding(request, generation, controller), result)
        with mock.patch.object(a, "BridgeWorker", return_value=worker):
            core.reconnect_bridge()
        core.bridge_state, core.bridge_instance = "CONNECTED", store.instance
        core.chat_binding = result
        core.chat_binding_received_at = time.monotonic()
        core._pump_recovered_chat_binding()
        worker.post.assert_called_once()

    def test_valid_and_restricted_codes_are_preserved_even_if_they_expire_later(self):
        self.restored_chat(expired=False)
        for status in ("VALID", "LOCKED", "BACKOFF"):
            with self.subTest(status=status):
                self.core.recovery_chat_checked = False
                self.core.chat_binding["status"] = status
                self.core._pump_recovered_chat_binding()
                self.core.chat_binding["status"] = "EXPIRED"
                self.core._pump_recovered_chat_binding()
                self.core.bridge_worker.post.assert_not_called()

    def test_startup_rotation_waits_for_fresh_matching_ready_state(self):
        self.restored_chat()
        core = self.core
        cases = [("bridge_state", "CONNECTING"), ("chat_binding", None),
                 ("chat_binding_received_at", time.monotonic() - 7),
                 ("chat_binding_busy", True), ("recovery_chat_recipient", None),
                 ("recovery_chat_recipient", ("other",)),
                 ("remote_tunnel_instance", "other"), ("remote_tunnel", None)]
        cases += [("remote_tunnel", {"phase": phase, "received_at": time.monotonic()})
                  for phase in ("missing", "configured", "installing", "starting", "error")]
        cases += [("remote_tunnel", {"phase": "connected", "received_at": time.monotonic() - 7})]
        for attr, value in cases:
            with self.subTest(attr=attr, value=value), mock.patch.object(core, attr, value):
                core._pump_recovered_chat_binding()
                core.bridge_worker.post.assert_not_called()
        core._pump_recovered_chat_binding()
        core.bridge_worker.post.assert_called_once()

    def test_failed_or_uncertain_rotation_is_not_repeated_by_refresh_or_reconnect(self):
        self.restored_chat()
        core = self.core
        expired = core.chat_binding
        core._pump_recovered_chat_binding()
        worker = core.bridge_worker
        worker.events.put((core.worker_id, "chat_binding_error", "network_timeout"))
        worker.events.put((core.worker_id, "chat_binding", expired))
        core._pump_bridge()
        core._pump_recovered_chat_binding()
        self.assertIn("nicht bestätigt", a.chat_binding_presentation(core.bridge_snapshot())[1])
        with mock.patch.object(a, "BridgeWorker", return_value=worker):
            core.reconnect_bridge()
        core.bridge_state = "CONNECTED"
        core.chat_binding, core.chat_binding_received_at = expired, time.monotonic()
        core._pump_recovered_chat_binding()
        worker.post.assert_called_once()

    def test_manual_rotation_consumes_startup_attempt_and_disconnect_cancels_it(self):
        self.restored_chat()
        self.core.rotate_chat_binding()
        self.core.chat_binding_busy = False
        self.core._pump_recovered_chat_binding()
        self.core.bridge_worker.post.assert_called_once()
        self.core.disconnect_bridge()
        self.assertIsNone(self.core.recovery_chat_recipient)

    def test_sidebar_renewal_reuses_rotation_and_blocks_repeat_click(self):
        store, controller = self.restored_chat()
        ui = a.ReviewUI.__new__(a.ReviewUI)
        ui.core, ui.root = self.core, mock.Mock()
        ui.messagebox, ui.render = mock.Mock(), mock.Mock()
        self.assertTrue(a.chat_binding_can_renew(self.core.bridge_snapshot()))
        ui.chat_binding_action()
        self.assertFalse(a.chat_binding_can_renew(self.core.bridge_snapshot()))
        ui.chat_binding_action()
        self.core.bridge_worker.post.assert_called_once()
        ui.messagebox.showerror.assert_called_once()
        name, (request, generation) = self.core.bridge_worker.post.call_args.args
        self.assertEqual(name, "rotate_chat_binding")
        result = store.rotate_chat_binding(request, generation, controller)
        self.core.bridge_worker.events.put((self.core.worker_id, "chat_binding", result))
        self.core._pump_bridge()
        ui.chat_binding_action()
        ui.root.clipboard_append.assert_called_once_with(a.chat_binding_presentation(self.core.bridge_snapshot())[0])
        self.core.bridge_worker.post.assert_called_once()

    def test_sidebar_renewal_requires_connected_fresh_unrestricted_binding(self):
        self.restored_chat()
        core = self.core
        for attr, value in (("bridge_state", "DISCONNECTED"), ("bridge_state", "CONNECTING"),
                            ("bridge_state", "RETRYING"), ("chat_binding", None),
                            ("chat_binding_received_at", time.monotonic() - 7),
                            ("chat_binding_busy", True)):
            with self.subTest(attr=attr, value=value), mock.patch.object(core, attr, value):
                self.assertFalse(a.chat_binding_can_renew(core.bridge_snapshot()))
        for status in ("LOCKED", "BACKOFF"):
            with mock.patch.dict(core.chat_binding, status=status):
                self.assertFalse(a.chat_binding_can_renew(core.bridge_snapshot()))
        with mock.patch.dict(core.chat_binding, status="VALID", code="ABCDEFGH",
                             expires_at=core.chat_binding["server_time"] + 1):
            self.assertFalse(a.chat_binding_can_renew(core.bridge_snapshot()))
            core.chat_binding_received_at = time.monotonic() - 2
            self.assertTrue(a.chat_binding_can_renew(core.bridge_snapshot()))

    def test_no_saved_configuration_and_manual_connection_are_left_alone(self):
        with mock.patch.object(self.core, "connect_profile") as connect:
            self.core.begin_connection_recovery()
            self.core.begin_connection_recovery()
            connect.assert_not_called()
        self.assertEqual(self.core.recovery_state, "IDLE")
        self.core.bridge_state = "CONNECTING"
        self.core.recovery_started = False
        self.core.begin_connection_recovery()
        self.assertFalse(self.core.recovery_started)

    def test_running_remote_bridge_restores_without_dialog_pairing_or_chat_rotation(self):
        fixture = RemoteFixture(Path(self.temp.name) / "bridge", port=0)
        self.addCleanup(fixture.close)
        self.core.pair_remote(fixture.url, fixture.pin, fixture.code)
        self.core.close()
        recovered = a.AppCore(connection_store=self.store)
        self.addCleanup(recovered.close)
        with mock.patch.object(recovered, "pair_remote") as pair, \
                mock.patch.object(recovered, "rotate_chat_binding") as rotate, \
                mock.patch.object(recovered, "hello_bridge") as hello:
            recovered.begin_connection_recovery()
            until(recovered, lambda: recovered.recovery_state == "RESTORED" and recovered.chat_binding is not None
                  and recovered.remote_tunnel is not None)
            generation = recovered.worker_id
            recovered.begin_connection_recovery()
            self.assertEqual(recovered.worker_id, generation)
            self.assertEqual(recovered.bridge_profile.pin, fixture.pin)
            self.assertEqual(recovered.remote_tunnel["phase"], "missing")
            self.assertEqual(recovered.review_state, "EMPTY")
            pair.assert_not_called()
            rotate.assert_not_called()
            hello.assert_not_called()
            recovered.disconnect_bridge()
            recovered.pump()
            self.assertEqual(recovered.bridge_state, "DISCONNECTED")
            self.assertIsNone(recovered.bridge_worker)

    def test_changed_certificate_blocks_recovery_without_silent_repair(self):
        fixture = RemoteFixture(Path(self.temp.name) / "bridge", port=0)
        self.addCleanup(fixture.close)
        self.core.pair_remote(fixture.url, fixture.pin, fixture.code)
        profile = replace(a.ConnectionProfile(**self.store.load_connection()["profile"]), pin="0"*64)
        self.core.close()
        self.store.save_connection(profile)
        recovered = a.AppCore(connection_store=self.store)
        self.addCleanup(recovered.close)
        with mock.patch.object(recovered, "pair_remote") as pair:
            recovered.begin_connection_recovery()
            until(recovered, lambda: recovered.bridge_state == "BLOCKED")
            self.assertEqual(recovered.recovery_state, "NEEDS_ATTENTION")
            self.assertEqual(recovered.bridge_profile.pin, "0"*64)
            dialog = a.ConnectionDialog.__new__(a.ConnectionDialog)
            dialog.core = recovered
            dialog.location = mock.Mock(get=mock.Mock(return_value="REMOTE"))
            dialog.fields = {"url": mock.Mock(get=mock.Mock(return_value=fixture.url))}
            for _ in range(2):
                worker_id = recovered.worker_id
                self.assertIn("wiederhergestellt", dialog.auto_takeover_paired())
                self.assertGreater(recovered.worker_id, worker_id)
                until(recovered, lambda: recovered.bridge_state == "BLOCKED")
                self.assertEqual(recovered.bridge_profile.pin, "0"*64)
            pair.assert_not_called()

    def test_saved_local_setup_reuses_values_without_requiring_form_entry(self):
        config = {"binary": "/fixture/client", "tunnel_id": "tunnel_"+"a"*32, "api_key": "fixture-key"*4}
        self.core.saved_connection = {"profile": None, "tunnel": config, "qrexec": None}
        with mock.patch.object(self.core, "begin_local_setup") as setup:
            self.core.begin_connection_recovery()
            self.core.begin_connection_recovery()
            setup.assert_called_once_with(config["tunnel_id"], config["api_key"])
            self.assertEqual(self.core.recovery_state, "CONNECTING")

    def test_local_recovery_waits_for_tunnel_and_reports_setup_failure(self):
        self.core.recovery_state = "CONNECTING"
        self.core.bridge_state = "CONNECTED"
        self.core.bridge_profile = a.ConnectionProfile("http://127.0.0.1:1234", None, "b"*32, "c"*32, "d"*64, "LOCAL")
        self.core.local_setup_state = "VALIDATING"
        self.core._pump_connection_recovery()
        self.assertEqual(self.core.recovery_state, "CONNECTING")
        with mock.patch("sys.stderr"):
            self.core._fail_local_setup("local_setup_timeout")
        self.assertEqual(self.core.recovery_state, "NEEDS_ATTENTION")
        self.assertEqual(self.core.recovery_error, "local_setup_timeout")
        self.assertEqual(self.core.bridge_state, "DISCONNECTED")

    def test_forwarder_error_is_reported_without_connecting_and_cancel_cleans_owned_process(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.saved_connection = {"profile": vars(profile), "tunnel": None,
                                      "qrexec": {"target": "ai-bridge", "port": 8443}}
        with mock.patch.object(a.QrexecForwarder, "start", side_effect=a.ProbeError("qrexec_port_conflict")), \
                mock.patch.object(self.core, "connect_profile") as connect:
            self.core.begin_connection_recovery()
            until(self.core, lambda: self.core.recovery_state == "NEEDS_ATTENTION")
            self.assertEqual(self.core.recovery_error, "qrexec_port_conflict")
            connect.assert_not_called()
        entered, finish, stopped = threading.Event(), threading.Event(), threading.Event()
        class Forwarder:
            def start(self, *_):
                entered.set()
                finish.wait(3)
            def stop(self):
                stopped.set()
        with mock.patch.object(a, "QrexecForwarder", Forwarder):
            preparation = a.SavedForwarderPreparation("ai-bridge", 8443)
            try:
                self.assertTrue(entered.wait(2))
                preparation.close()
            finally:
                finish.set()
                preparation.thread.join(3)
            self.assertTrue(stopped.is_set())
            self.assertIsNone(preparation.take())

    def test_retry_reuses_existing_owned_forwarder_without_creating_port_conflict(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.saved_connection = {"profile": vars(profile), "tunnel": None,
                                      "qrexec": {"target": "ai-bridge", "port": 8443}}
        forwarder = self.core.qrexec_forwarder = mock.Mock(running=True, target="ai-bridge", port=8443, remote_port=8443)
        with mock.patch.object(a, "SavedForwarderPreparation") as preparation, \
                mock.patch.object(self.core, "connect_profile") as connect:
            self.core.begin_connection_recovery()
            self.core.retry_connection_recovery()
            self.assertEqual(connect.call_count, 2)
            connect.assert_called_with(profile)
            preparation.assert_not_called()
            forwarder.start.assert_not_called()
            forwarder.stop.assert_not_called()

    def test_prepared_forwarder_is_transferred_only_on_owner_pump(self):
        profile = a.ConnectionProfile("https://127.0.0.1:8443", "a"*64, "b"*32, "c"*32, "d"*64)
        self.core.saved_connection = {"profile": vars(profile), "tunnel": None,
                                      "qrexec": {"target": "ai-bridge", "port": 8443}}
        forwarder = mock.Mock(target="ai-bridge", port=8443, remote_port=8443)
        with mock.patch.object(a, "QrexecForwarder", return_value=forwarder), \
                mock.patch.object(self.core, "connect_profile") as connect:
            self.core.begin_connection_recovery()
            self.core.recovery_preparation.thread.join(2)
            connect.assert_not_called()
            # A settings reload during preparation must not retarget the pending attempt.
            self.core.saved_connection = dict(self.core.saved_connection,
                profile=vars(replace(profile, url="https://different.example:8443")))
            self.core._pump_connection_recovery()
            connect.assert_called_once_with(profile)
            self.assertIs(self.core.qrexec_forwarder, forwarder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
