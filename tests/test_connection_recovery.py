"""Startup recovery: real pinned TLS plus controlled Qrexec lifecycle fixtures."""
import os
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
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = a.ConnectionStore(Path(self.temp.name) / "config")
        self.core = a.AppCore(connection_store=self.store)
        self.addCleanup(self.core.close)

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
        forwarder = self.core.qrexec_forwarder = mock.Mock(running=True, target="ai-bridge", port=8443)
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
        forwarder = mock.Mock()
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
