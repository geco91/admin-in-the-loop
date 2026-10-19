"""SG-06/07: retained exceptions and stalled resolver resource boundaries.

Only own archives, localhost HTTPS/certificates and controlled DNS are used.
No actual sh-guard pin, outbound release download, global trust or timeout mutation.
"""
import http.server
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
import test_risk_install_ui as fixtures


class ResolverAdmissionTests(unittest.TestCase):
    def test_serial_controller_attempts_cannot_accumulate_stalled_resolvers(self):
        archive = fixtures.archive_for(fixtures.fake_binary())
        release = fixtures.release_for(fixtures.fake_binary(), archive)
        entered, unblock = threading.Event(), threading.Event()
        calls, budgets, peaks = [], [], []
        original = a._RiskDownloadBudget

        def dns(*args):
            calls.append(args)
            entered.set()
            unblock.wait(3)
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 9))]

        def budget(cancel):
            result = original(cancel)
            budgets.append(result)
            return result

        try:
            with mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 0.12), \
                    mock.patch.object(a, "_RiskDownloadBudget", side_effect=budget), \
                    mock.patch.object(a.socket, "getaddrinfo", side_effect=dns), \
                    mock.patch.object(a.socket, "socket") as connect:
                for index in range(6):
                    with self.subTest(attempt=index), self.assertRaisesRegex(
                            a.ProbeError, "risk_download_timeout" if index == 0 else "risk_download_dns_busy"):
                        a.download_command_risk(release, threading.Event())
                    peaks.append(sum(thread.name == "aitl-risk-download-dns" and thread.is_alive()
                                     for thread in threading.enumerate()))
                self.assertTrue(entered.is_set())
                self.assertEqual(len(calls), 1)
                self.assertEqual(max(peaks), 1)
                self.assertEqual(len(budgets), 6)  # Distinct request/controller budgets share admission.
                self.assertTrue(budgets[0].resolvers[0].is_alive())
                admitted = a._RISK_RESOLVER_ADMISSION.acquire(blocking=False)
                if admitted:
                    a._RISK_RESOLVER_ADMISSION.release()
                self.assertFalse(admitted)
                cancelled = threading.Event()
                cancelled.set()
                with self.assertRaisesRegex(a.ProbeError, "risk_cancelled"):
                    a.download_command_risk(release, cancelled)
                connect.assert_not_called()
                unblock.set()
                for value in budgets:
                    for thread in value.resolvers:
                        thread.join(2)
                        self.assertFalse(thread.is_alive())
                connect.assert_not_called()  # Old DNS result must not start a late socket.
                fresh = original(threading.Event())
                try:
                    self.assertEqual(fresh.resolve("fixture", 443)[0][-1], ("127.0.0.1", 9))
                finally:
                    fresh.close()
                self.assertEqual(len(calls), 2)
        finally:
            unblock.set()
            for value in budgets:
                value.close()
                for thread in value.resolvers:
                    thread.join(2)
        self.assertFalse(any(t.name.startswith("aitl-risk-download-") and t.is_alive()
                             for t in threading.enumerate()))

    def test_failed_thread_construction_or_start_releases_admission_for_next_request(self):
        budget = a._RiskDownloadBudget(threading.Event())
        try:
            for target in ("threading.Thread", "threading.Thread.start"):
                with self.subTest(target=target), mock.patch(target, side_effect=RuntimeError("fixture start failure")):
                    with self.assertRaises(RuntimeError):
                        budget.resolve("fixture", 443)
                with mock.patch.object(a.socket, "getaddrinfo", return_value=[]):
                    self.assertEqual(budget.resolve("fixture", 443), [])
        finally:
            budget.close()


class HTTPSResponseResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-https-resource-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.server_context, _ = a.bridge_certificate(self.directory / "cert",
            ("github.com", "release-assets.githubusercontent.com"))
        original_context = ssl.create_default_context
        self.client_context = original_context(cafile=str(self.directory / "cert/tls-cert.pem"))
        self.assertTrue(self.client_context.check_hostname)
        self.assertEqual(self.client_context.verify_mode, ssl.CERT_REQUIRED)
        self.binary = fixtures.fake_binary()
        self.archive = fixtures.archive_for(self.binary)
        self.release = fixtures.release_for(self.binary, self.archive)
        self.original_timeout = socket.getdefaulttimeout()
        self.retained = []
        # These socket fixtures model direct HTTPS. Proxy behavior is tested
        # separately with a real local CONNECT proxy.
        proxy = mock.patch("urllib.request.getproxies", return_value={})
        proxy.start()
        self.addCleanup(proxy.stop)

    def tearDown(self):
        for error in self.retained:
            if isinstance(error, HTTPError):
                error.close()
        self.assertEqual(socket.getdefaulttimeout(), self.original_timeout)
        self.assertFalse(any(t.name.startswith("aitl-risk-download-") and t.is_alive()
                             for t in threading.enumerate()))

    def fd_count(self):
        # Linux test environment provides a deterministic process FD view.
        return len(tuple(Path("/proc/self/fd").iterdir()))

    @contextmanager
    def https(self, mode):
        payload = self.archive
        paths, server_threads = [], []

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                paths.append((self.headers.get("Host"), self.path))
                if mode == "allowed" and self.path == "/allowed" or mode == "success":
                    code, body, location = 200, payload, None
                elif mode == "error":
                    code, body, location = 500, b"held error fixture", None
                else:
                    code, body = 302, b"must not consume redirect body"
                    location = {"denied": "https://evil.invalid/denied", "missing": None,
                                "oversized": "https://github.com/" + "x" * 8200,
                                "allowed": "https://release-assets.githubusercontent.com/allowed"}[mode]
                self.send_response(code)
                if location is not None:
                    self.send_header("Location", location)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
                self.close_connection = True

            def log_message(self, *_args):
                pass

        class Server(http.server.ThreadingHTTPServer):
            def process_request_thread(self, *args):
                server_threads.append(threading.current_thread())
                return super().process_request_thread(*args)

        server = Server(("127.0.0.1", 0), Handler)
        server.socket = self.server_context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), name="fixture-resource-https")
        thread.start()
        address = server.server_address
        try:
            with mock.patch.object(a.socket, "getaddrinfo", return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 0, "", address)]), \
                    mock.patch.object(a.ssl, "create_default_context", return_value=self.client_context):
                yield paths
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(all(not worker.is_alive() for worker in server_threads))

    def test_retained_denied_and_invalid_redirect_tracebacks_do_not_hold_fds(self):
        baseline = self.fd_count()
        for mode in ("denied", "denied", "denied", "missing", "oversized", "denied"):
            with self.subTest(mode=mode):
                with self.https(mode):
                    try:
                        a.download_command_risk(self.release, threading.Event())
                    except a.ProbeError as error:
                        self.assertEqual(str(error), "risk_download_redirect")
                        self.retained.append(error)
                    else:
                        self.fail("invalid redirect accepted")
                self.assertEqual(self.fd_count(), baseline)  # Errors/tracebacks still retained.
        self.assertEqual(len(self.retained), 6)

    def test_retained_http_errors_are_closed_before_propagation(self):
        baseline = self.fd_count()
        for _ in range(4):
            with self.https("error"):
                try:
                    a.download_command_risk(self.release, threading.Event())
                except HTTPError as error:
                    self.assertEqual(error.code, 500)
                    self.assertTrue(error.closed)
                    self.retained.append(error)
                else:
                    self.fail("HTTP500 accepted")
            self.assertEqual(self.fd_count(), baseline)
        self.assertEqual(len(self.retained), 4)

    def test_valid_https_and_allowed_redirect_keep_certificate_hostname_checks(self):
        baseline = self.fd_count()
        for mode in ("success", "allowed"):
            with self.https(mode) as paths:
                result = a.download_command_risk(self.release, threading.Event())
            self.assertEqual(result, self.archive)
            self.assertEqual(self.fd_count(), baseline)
            if mode == "allowed":
                self.assertEqual(paths[-1], ("release-assets.githubusercontent.com", "/allowed"))
        self.assertTrue(self.client_context.check_hostname)
        self.assertEqual(self.client_context.verify_mode, ssl.CERT_REQUIRED)

    def test_post_response_cancel_closes_response_before_context_manager_is_entered(self):
        baseline = self.fd_count()
        cancel, responses = threading.Event(), []
        original_handler = a._risk_download_handler

        def handler(budget):
            value = original_handler(budget)
            do_open = value.do_open

            def completed(*args, **kwargs):
                response = do_open(*args, **kwargs)
                responses.append(response)
                cancel.set()
                return response

            value.do_open = completed
            return value

        with self.https("success"), mock.patch.object(a, "_risk_download_handler", side_effect=handler):
            try:
                a.download_command_risk(self.release, cancel)
            except a.ProbeError as error:
                self.assertEqual(str(error), "risk_cancelled")
                self.retained.append(error)
            else:
                self.fail("cancelled response accepted")
        self.assertTrue(responses)
        self.assertTrue(all(response.isclosed() for response in responses))
        self.assertEqual(self.fd_count(), baseline)

    def test_redirect_cancel_and_budget_exceptions_close_response_in_finally(self):
        from urllib.request import Request
        baseline = self.fd_count()
        for cancelled in (True, False):
            cancel = threading.Event()

            def redirected(_handler, _req, _fp, _code, _msg, _headers, newurl):
                if cancelled:
                    cancel.set()
                else:
                    time.sleep(0.15)  # Deadline expires after response creation, during redirect handling.
                return Request(newurl)

            with self.subTest(cancelled=cancelled), self.https("allowed"), \
                    mock.patch.object(a, "RISK_DOWNLOAD_TIMEOUT", 1 if cancelled else 0.1), \
                    mock.patch("urllib.request.HTTPRedirectHandler.redirect_request", new=redirected):
                try:
                    a.download_command_risk(self.release, cancel)
                except a.ProbeError as error:
                    self.assertEqual(str(error), "risk_cancelled" if cancelled else "risk_download_timeout")
                    self.retained.append(error)
                else:
                    self.fail("cancelled/late redirect accepted")
            self.assertEqual(self.fd_count(), baseline)


if __name__ == "__main__":
    unittest.main()
