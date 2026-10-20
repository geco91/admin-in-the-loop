"""Causal SG-01..05 regressions: local sockets, self-created binaries, no real pin.

PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_risk_review_fixes.py
Tk tests additionally run under the already available xvfb-run.
"""
import gzip
import gc
import http.client
import io
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
import test_risk_install_ui as fixtures


class TransportBoundaryTests(unittest.TestCase):
    def setUp(self):
        proxy = mock.patch("urllib.request.getproxies", return_value={})
        proxy.start()
        self.addCleanup(proxy.stop)
        self.binary = fixtures.fake_binary()
        self.archive = fixtures.archive_for(self.binary)
        self.release = fixtures.release_for(self.binary, self.archive)
        self.cancel = threading.Event()
        self.original_timeout = socket.getdefaulttimeout()

    def tearDown(self):
        self.assertEqual(socket.getdefaulttimeout(), self.original_timeout)
        self.assertFalse(any(thread.name == "aitl-risk-download-budget" and thread.is_alive()
                             for thread in threading.enumerate()))

    def transport(self, mode, timeout=0.16):
        left, right = socket.socketpair()
        left.settimeout(1 if mode == "eof" else 0.1)
        stopped = threading.Event()
        errors, budget_holder = [], []

        def sender():
            try:
                headers = b"HTTP/1.1 200 OK\r\nContent-Length: 65536\r\n\r\n"
                if mode == "headers":
                    for char in headers:
                        if stopped.wait(0.02):
                            break
                        right.sendall(bytes([char]))
                else:
                    right.sendall(headers if mode != "eof" else b"HTTP/1.1 200 OK\r\n\r\n")
                    if mode == "eof":
                        right.sendall(self.archive)
                        stopped.wait(1)  # Body complete, but EOF is deliberately late.
                    else:
                        for _ in range(200):
                            if stopped.wait(0.02):
                                break
                            right.sendall(b"x")
                            if mode == "cancel":
                                self.cancel.set()
            except OSError:
                pass
            finally:
                right.close()

        thread = threading.Thread(target=sender, name="fixture-http-sender")
        thread.start()

        def handler(budget):
            budget.register(left)
            budget_holder.append(budget)
            return object()

        def opener(*_handlers):
            class Opener:
                def open(_self, *_args, **_kwargs):
                    response = http.client.HTTPResponse(left)
                    try:
                        response.begin()  # REAL stdlib header reader, possibly trickled.
                    except Exception:
                        response.close()
                        raise
                    return response
            return Opener()

        start = time.monotonic()
        try:
            with mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", timeout), \
                    mock.patch.object(a, "_risk_download_handler", side_effect=handler), \
                    mock.patch("urllib.request.build_opener", side_effect=opener):
                try:
                    a.download_command_risk(self.release, self.cancel)
                except a.ProbeError as exc:
                    errors.append(str(exc))
        finally:
            stopped.set()
            left.close()
            right.close()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(not value.thread.is_alive() for value in budget_holder))
        self.assertLess(time.monotonic() - start, 1.5)
        return errors

    def test_real_stdlib_trickle_body_and_headers_obey_total_deadline(self):
        for mode in ("body", "headers"):
            with self.subTest(mode=mode):
                self.assertEqual(self.transport(mode), ["risk_download_timeout"])

    def test_real_stdlib_cancel_interrupts_receive_and_eof_is_not_late_success(self):
        self.assertEqual(self.transport("cancel", timeout=5), ["risk_cancelled"])
        self.cancel.clear()
        self.assertEqual(self.transport("eof"), ["risk_download_timeout"])

    def test_late_dns_result_never_connects_and_fixture_helper_is_joined(self):
        entered, release = threading.Event(), threading.Event()
        resolvers = []
        original = a._RiskDownloadBudget

        def dns(*_args):
            entered.set()
            release.wait(2)
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 9))]

        def budget(cancel):
            value = original(cancel)
            resolvers.append(value)
            return value

        try:
            with mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 0.16), \
                    mock.patch.object(a, "_RiskDownloadBudget", side_effect=budget), \
                    mock.patch.object(a.socket, "getaddrinfo", side_effect=dns), \
                    mock.patch.object(a.socket, "socket") as connect:
                with self.assertRaisesRegex(a.ProbeError, "risk_download_timeout"):
                    a.download_command_risk(self.release, self.cancel)
                self.assertTrue(entered.is_set())
                release.set()
                for value in resolvers:
                    for thread in value.resolvers:
                        thread.join(2)
                        self.assertFalse(thread.is_alive())
                connect.assert_not_called()
        finally:
            release.set()

    def test_actual_local_connect_and_stalled_tls_obey_total_budget_and_cancel(self):
        for cancelled in (False, True):
            self.cancel.clear()
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(1)
            stopped, accepted = threading.Event(), threading.Event()
            peers = []

            def stalled_tls():
                try:
                    peer, _ = server.accept()
                    peers.append(peer)
                    accepted.set()
                    if cancelled:
                        self.cancel.set()
                    stopped.wait(1)  # No TLS ServerHello: client handshake blocks.
                except OSError:
                    pass

            thread = threading.Thread(target=stalled_tls, name="fixture-stalled-tls")
            thread.start()
            address = server.getsockname()
            try:
                with self.subTest(cancelled=cancelled), \
                        mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 0.2), \
                        mock.patch.object(a.socket, "getaddrinfo", return_value=[
                            (socket.AF_INET, socket.SOCK_STREAM, 0, "", address)]):
                    with self.assertRaisesRegex(a.ProbeError, "risk_cancelled" if cancelled else "risk_download_timeout"):
                        a.download_command_risk(self.release, self.cancel)
                    self.assertTrue(accepted.is_set())
            finally:
                stopped.set()
                for peer in peers:
                    peer.close()
                server.close()
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_redirect_budget_includes_redirect_time_and_never_reads_redirect_body(self):
        from urllib.request import Request

        def opener(*handlers):
            redirect = handlers[1]
            redirect.parent = mock.Mock(open=mock.Mock(return_value=io.BytesIO(self.archive)))
            request = Request(self.release.url)
            response = mock.Mock()
            time.sleep(0.05)
            redirect.http_error_302(request, response, 302, "", {"Location": "https://github.com/fixture"})
            response.read.assert_not_called()
            response.close.assert_called_once()
            time.sleep(0.1)
            redirect.redirect_request(request, response, 302, "", {}, "https://github.com/fixture")
            self.fail("late redirect must be rejected")

        with mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 0.12), \
                mock.patch("urllib.request.build_opener", side_effect=opener):
            with self.assertRaisesRegex(a.ProbeError, "risk_download_timeout"):
                a.download_command_risk(self.release, self.cancel)


class ArchiveBoundaryTests(unittest.TestCase):
    def test_full_physical_expansion_is_bounded_before_any_header_parser(self):
        binary = fixtures.fake_binary()
        valid = fixtures.archive_for(binary)
        metadata = b"sh-guard\0" + b"z" * (a.RISK_ARCHIVE_EXPANDED_LIMIT + 4096)
        info = tarfile.TarInfo("././@LongLink")
        info.type, info.size = tarfile.GNUTYPE_LONGNAME, len(metadata)
        physical = (info.tobuf(format=tarfile.GNU_FORMAT) + metadata
                    + b"\0" * (-len(metadata) % 512) + gzip.decompress(valid))
        raw = gzip.compress(physical)
        self.assertLess(len(raw), 100000)
        release = fixtures.release_for(binary, raw)
        with tempfile.TemporaryDirectory(prefix="aitl-risk-archive-fix-") as directory, \
                mock.patch.object(a.tarfile.TarInfo, "frombuf") as parser, \
                mock.patch.object(a.subprocess, "Popen") as spawn:
            installation = a.CommandRiskInstallation(Path(directory).resolve() / "config", release)
            with self.assertRaisesRegex(a.ProbeError, "risk_archive_size"):
                installation.install(threading.Event(), lambda _: None, lambda *_: raw)
            parser.assert_not_called()
            spawn.assert_not_called()
            self.assertFalse(installation.destination.exists())

    def test_physical_extensions_are_rejected_before_interpretation_valid_tar_works(self):
        binary = fixtures.fake_binary()
        valid = fixtures.archive_for(binary)
        release = fixtures.release_for(binary, valid)
        self.assertEqual(a._risk_archive_binary(valid, release, threading.Event()), binary)
        for kind in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK, tarfile.XHDTYPE,
                     tarfile.XGLTYPE, tarfile.GNUTYPE_SPARSE):
            header = tarfile.TarInfo("sh-guard")
            header.type, header.size = kind, 12
            raw = gzip.compress(header.tobuf(format=tarfile.GNU_FORMAT) + b"sh-guard\0".ljust(512, b"\0")
                                + gzip.decompress(valid))
            with self.subTest(kind=kind), mock.patch.object(a.tarfile.TarInfo, "frombuf") as parser:
                with self.assertRaisesRegex(a.ProbeError, "risk_archive_members"):
                    a._risk_archive_binary(raw, fixtures.release_for(binary, raw), threading.Event())
                parser.assert_not_called()


class LifecycleBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-lease-fix-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve() / "config"
        self.marker = Path(self.temp.name).resolve() / "active-pid"
        source = fixtures.fake_binary()
        blocking = ("command = sys.argv[7]\n"
                    "if command != ':\\n':\n"
                    "    import signal, time\n"
                    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "    with open(%r, 'w') as marker: marker.write(str(os.getpid()))\n"
                    "    while True: time.sleep(1)\n" % str(self.marker)).encode()
        self.binary = source.replace(b"command = sys.argv[7]\n", blocking)
        raw = fixtures.archive_for(self.binary)
        self.release = fixtures.release_for(self.binary, raw)
        self.installation = a.CommandRiskInstallation(self.base, self.release)
        self.tool, self.work = self.installation.install(threading.Event(), lambda _: None, lambda *_: raw)
        self.core = a.AppCore(preference_store=a.PreferenceStore(self.base))
        self.core.session, self.core.connection = "FIXTURE_SESSION", "CONNECTED"
        self.core.set_command_target("TERMINAL")
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.addCleanup(self.core.close)

    def wait(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("fixture boundary deadline")

    def test_check_holds_lease_across_hash_and_probe_against_other_instance_remove(self):
        entered, release = threading.Event(), threading.Event()
        original, errors = a._risk_probe, []

        def paused(*args):
            entered.set()
            release.wait(2)
            return original(*args)

        def check():
            try:
                self.installation.check(threading.Event())
            except Exception as exc:
                errors.append(type(exc).__name__)

        with mock.patch.object(a, "_risk_probe", side_effect=paused):
            thread = threading.Thread(target=check, name="fixture-check-lease")
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                other = a.CommandRiskInstallation(self.base, self.release)
                with self.assertRaisesRegex(a.ProbeError, "risk_lease_busy"):
                    other.remove()
                code = (
                    "import sys, threading; sys.path.insert(0, sys.argv[1]); import admin_in_the_loop as a\n"
                    "try:\n"
                    "    fd = a._risk_acquire_lease(sys.argv[2], threading.Event(), exclusive=True, timeout=0)\n"
                    "except a.ProbeError as exc:\n"
                    "    print(str(exc))\n"
                )
                child = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                                        str(Path(a.__file__).parent), self.tool.lease_path],
                                       shell=False, capture_output=True, timeout=3)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(child.stdout, b"risk_lease_busy\n")
                self.assertEqual(child.stderr, b"")
                self.assertTrue(Path(self.tool.binary).exists())
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_active_analysis_blocks_cross_instance_remove_until_cancel_reap(self):
        self.core.review_command("printf held")
        self.core.set_command_risk(self.tool, self.work)
        self.wait(self.marker.exists)
        pid = int(self.marker.read_text())
        with self.assertRaisesRegex(a.ProbeError, "risk_lease_busy"):
            a.CommandRiskInstallation(self.base, self.release).remove()
        os.kill(pid, 0)
        self.core.request_command_risk(False)
        with self.assertRaisesRegex(a.ProbeError, "risk_cleanup_busy"):
            self.core.risk_installation = self.installation
            self.core.remove_command_risk()
        self.wait(self.core._command_risk.quiescent)
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        self.core.remove_command_risk()
        self.assertFalse(Path(self.tool.binary).exists())

    def test_lease_wait_is_bounded_and_cancelable(self):
        path = self.tool.lease_path
        lock = a._risk_acquire_lease(path, threading.Event(), exclusive=True)
        cancel, errors = threading.Event(), []

        def blocked():
            try:
                fd = a._risk_acquire_lease(path, cancel)
                os.close(fd)
            except a.ProbeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=blocked)
        thread.start()
        cancel.set()
        thread.join(1)
        try:
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["risk_cancelled"])
            with self.assertRaisesRegex(a.ProbeError, "risk_lease_busy"):
                a._risk_acquire_lease(path, threading.Event(), timeout=0.05)
        finally:
            os.close(lock)

    def test_recheck_waits_for_term_ignoring_process_reap_without_blocking_owner(self):
        original = subprocess.Popen
        processes, peaks = [], []

        def tracked(*args, **kwargs):
            # Prior leaders MUST already be reaped before any new spawn.
            alive = sum(process.poll() is None for process in processes)
            peaks.append(alive + 1)
            process = original(*args, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(a.subprocess, "Popen", side_effect=tracked), \
                mock.patch.object(a, "command_risk_release", return_value=self.release):
            review = self.core.review_command("printf held")
            self.core.set_command_risk(self.tool, self.work)
            self.wait(self.marker.exists)
            old_pid = int(self.marker.read_text())
            self.core.edit_review(review.id, ":", True)
            self.core.request_command_risk(True)
            self.assertEqual(self.core.risk_setup_state, "WAITING_FOR_REAP")
            self.assertIsNone(self.core.risk_setup)
            # Owner continues to observe/edit/pump while TERM is ignored.
            self.core.snapshot()
            self.wait(lambda: self.core.command_risk_snapshot().state == "RESULT")
            self.assertEqual(self.core.review.text, ":\n")
            with self.assertRaises(ChildProcessError):
                os.waitpid(old_pid, os.WNOHANG)
            self.assertEqual(max(peaks), 1)
            self.core.close()
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.core.channel = None

    def test_off_on_close_during_reap_never_launches_pending_setup(self):
        self.core.review_command("printf held")
        self.core.set_command_risk(self.tool, self.work)
        self.wait(self.marker.exists)
        pid = int(self.marker.read_text())
        with mock.patch.object(a, "command_risk_release", return_value=self.release), \
                mock.patch.object(a, "CommandRiskSetup") as setup:
            self.core.request_command_risk(True)
            self.core.request_command_risk(False)
            self.core.request_command_risk(True)
            self.assertEqual(self.core.risk_setup_state, "WAITING_FOR_REAP")
            self.core.close()
            setup.assert_not_called()
            self.assertIsNone(self.core.risk_setup_pending)
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        self.core.channel = None


@unittest.skipUnless(os.environ.get("DISPLAY"), "controlled Tk display not supplied")
class RenderBoundaryTests(unittest.TestCase):
    def test_maximal_disabled_output_uses_bulk_path_without_source_index_work(self):
        import tkinter as tk
        root = tk.Tk()
        core = a.AppCore()
        core.session, core.connection = "FIXTURE_SESSION", "CONNECTED"
        core.set_command_target("TERMINAL")
        core.channel = mock.Mock(receive=mock.Mock(return_value=[]))
        ui = a.ReviewUI(root, core)
        try:
            review = core._output_review("a" * 65536)
            with mock.patch.object(ui.editor, "show", wraps=ui.editor.show) as bulk, \
                    mock.patch.object(ui.editor.text, "index", wraps=ui.editor.text.index) as indices:
                ui.render()
                bulk.assert_called_once()
                indices.assert_not_called()
            self.assertEqual(ui.editor.text.get("1.0", "end-1c"), review.text)
            self.assertEqual(core.review.payload, b"a" * 65536)
            core.review_command("echo '🙂\n€'")
            ui.render()
            self.assertEqual(ui.editor.text.get("1.0", "end-1c"),
                             "".join(display for display, _ in a.review_fragments(core.review.text)))
        finally:
            core.close()
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
            ui = core = root = bulk = indices = None
            gc.collect()


if __name__ == "__main__":
    unittest.main()
