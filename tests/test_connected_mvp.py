"""Real HTTP/MCP/TLS/PTY integration tests. Test framework: Python unittest only.

cryptography is an application dependency; the bridge itself is stdlib-only.
No production files, SSH, sudo, live API credentials or hosted tunnel are used.
"""
import base64
import hashlib
import hmac
import http.client
import os
import importlib.util
import json
import os
import queue
import select
import socket
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a


def request(url, method="GET", path=None, body=None, headers=None):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    raw = None if body is None else body if isinstance(body, bytes) else a.net_json(body)
    fields = dict(headers or {})
    if raw is not None:
        fields["Content-Type"] = "application/json"
    try:
        conn.request(method, path or parsed.path or "/", raw, fields)
        response = conn.getresponse()
        content = response.read(a.FRAME_LIMIT + 1)
        return response.status, content
    finally:
        conn.close()


def mcp(process, name, args=None, modern=False):
    args = dict(args or {})
    args.setdefault("conversation", getattr(process, "chat_code", process.profile.conversation))
    value = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": args}}
    headers = {"X-AITL-AI-Key": process.ai_token}
    if modern:
        headers["MCP-Protocol-Version"] = "2026-07-28"
        value["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                     "io.modelcontextprotocol/clientCapabilities": {}}
    status, raw = request(process.mcp_url, "POST", body=value, headers=headers)
    if status != 200:
        raise a.ProbeError("test_mcp_http_failure")
    result = json.loads(raw)["result"]
    if result.get("isError"):
        raise a.ProbeError("test_mcp_tool_failure")
    data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    for item in data.get("outputs", []):
        index = item.pop("text_content_index", None)
        if index is not None:
            item["text"] = result["content"][index]["text"]
    return data


class ReviewByteDetailTests(unittest.TestCase):
    def test_normalization_counts_and_final_bytes_follow_existing_rules(self):
        core = a.AppCore()
        self.addCleanup(core.close)
        core.session, core.connection = "synthetic", "CONNECTED"
        for text, counts in [("a\r\nb\r\r\n", (2, 1, 2)), ("a\n\n", (0, 0, 2)),
                             ("a\nb", (0, 0, 0)), ("é😀", (0, 0, 0))]:
            for final_return in (False, True):
                with self.subTest(text=text, final_return=final_return):
                    review = core.review_command(text, final_return)
                    self.assertEqual(review.payload, a.normalize_command(text, final_return))
                    self.assertEqual(review.normalization, counts)
                    self.assertEqual(review.text.encode(), review.payload)
                    self.assertIn("AN" if final_return else "AUS", a.normalization_summary(review))
        previous = core.review_command("a\r\n\n", True)
        edited = core.edit_review(previous.id, "é\nb", False)
        self.assertEqual(edited.normalization, (0, 0, 0))
        self.assertGreater(edited.revision, previous.revision)
        output = core._output_review("é\n")
        self.assertIsNone(output.normalization)
        self.assertNotIn("CRLF", a.normalization_summary(output))

    def test_final_payload_offsets_and_escaped_codepoints(self):
        text = "Aé😀\n"
        review = a.LocalReview("synthetic", 3, "TO_TERMINAL", "s", text, text.encode(), True)
        details = a.review_byte_details(review)
        self.assertIn('0 | 41 | U+0041 | "A"', details)
        self.assertIn('1 | c3 a9 | U+00E9 | "\\u00e9"', details)
        self.assertIn('3 | f0 9f 98 80 | U+1F600 | "\\ud83d\\ude00"', details)
        self.assertIn('7 | 0a | U+000A | "\\n"', details)
        self.assertTrue(details.endswith("Ende: 8 Bytes"))
        self.assertEqual(review.payload, b"A\xc3\xa9\xf0\x9f\x98\x80\n")


class CompactBindingPresentationTests(unittest.TestCase):
    def setUp(self):
        self.core = a.AppCore()
        self.addCleanup(self.core.close)
        self.binding = dict(code="A1B2C3D4", status="ACTIVE", generation=1,
                            server_time=100.0, expires_at=200.0, retry_at=0.0,
                            restriction_scope="PRINCIPAL")
        self.bridge = replace(self.core.bridge_snapshot(), state="CONNECTED", mode="REMOTE",
                              chat_binding=self.binding, chat_binding_received_at=10.0)

    def test_active_display_is_compact_but_expiry_and_freshness_still_hide_code(self):
        with mock.patch.object(a.time, "monotonic", return_value=11.0):
            self.assertEqual(a.chat_binding_presentation(self.bridge), ("A1B2-C3D4", "", True))
            for bridge in (replace(self.bridge, state="DISCONNECTED"),
                           replace(self.bridge, chat_binding=None),
                           replace(self.bridge, chat_binding=dict(self.binding, expires_at=100.0)),
                           replace(self.bridge, chat_binding=dict(self.binding, status="EXPIRED"))):
                code, status, allowed = a.chat_binding_presentation(bridge)
                self.assertEqual(code, "")
                self.assertTrue(status)
                self.assertFalse(allowed)
        with mock.patch.object(a.time, "monotonic", return_value=17.0):
            code, status, allowed = a.chat_binding_presentation(self.bridge)
            self.assertEqual(code, "")
            self.assertIn("geprüft", status)
            self.assertFalse(allowed)

    def test_backoff_and_lock_preserve_specific_warning_and_block_copy(self):
        with mock.patch.object(a.time, "monotonic", return_value=11.0):
            for state in ("BACKOFF", "LOCKED"):
                with self.subTest(state=state):
                    bridge = replace(self.bridge, chat_binding=dict(self.binding, status=state, retry_at=130.0))
                    code, status, allowed = a.chat_binding_presentation(bridge)
                    self.assertEqual(code, "A1B2-C3D4")
                    self.assertTrue(status)
                    self.assertFalse(allowed)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-store-test-")
        self.now = 1800000000.0
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: self.now)
        self.controller, self.cid = self.store.issue("CONTROLLER")
        self.ai, self.aid = self.store.issue("AI")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def body(self, content="approved output", key=None, submission=None):
        return {"version": 1, "conversation": self.store.conversation,
                "idempotency_key": key or uuid.uuid4().hex, "text": content,
                "submission_id": submission, "approved_at": self.now}

    def test_role_separation_pending_confirm_revoke(self):
        with self.assertRaises(a.BridgeError):
            self.store.status(self.ai)
        token, identifier = self.store.issue("CONTROLLER", pending=True)
        with self.assertRaises(a.BridgeError):
            self.store.status(token)
        self.assertEqual(self.store.confirm(token)["state"], "PAIRED")
        self.assertEqual(self.store.confirm(token)["state"], "PAIRED")
        self.store.revoke(identifier)
        with self.assertRaises(a.BridgeError):
            self.store.status(token)

    def test_pair_code_single_use_attempt_limit_and_expiry(self):
        code = self.store.open_pair()
        for _ in range(5):
            with self.assertRaises(a.BridgeError):
                self.store.claim({"code": "ZZZZ-ZZZZ-ZZZZ" if code != "ZZZZ-ZZZZ-ZZZZ" else "0000-0000-0000",
                                  "request_id": uuid.uuid4().hex})
        with self.assertRaises(a.BridgeError):
            self.store.claim({"code": code, "request_id": uuid.uuid4().hex})
        code = self.store.open_pair()
        claim = self.store.claim({"code": code.lower(), "request_id": uuid.uuid4().hex})
        with self.assertRaises(a.BridgeError):
            self.store.claim({"code": code, "request_id": uuid.uuid4().hex})
        self.now += 121
        with self.assertRaises(a.BridgeError):
            self.store.confirm(claim["token"])
        code = self.store.open_pair()
        # Pairing-code window is 600s (Journal100); the separate PAIR_PENDING token
        # lifetime above stays 120s. Boundary: still claimable mid-window, rejected
        # past 600s.
        self.now += 599
        with self.assertRaises(a.BridgeError):
            self.store.claim({"code": "9999-9999-9999", "request_id": uuid.uuid4().hex})
        self.now += 3  # 602s elapsed total for this window
        with self.assertRaises(a.BridgeError):
            self.store.claim({"code": code, "request_id": uuid.uuid4().hex})

    def test_output_idempotency_exact_body_and_retention(self):
        value = self.body()
        first = self.store.approved_output(value)
        self.assertEqual(first, self.store.approved_output(value))
        with self.assertRaises(a.BridgeError):
            self.store.approved_output(dict(value, text="different"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM outputs").fetchone()[0], 1)
        self.now += a.BRIDGE_RETENTION + 1
        self.assertEqual(self.store.ai_output(self.store.authenticate(self.ai, "AI"), {})["outputs"], [])
        self.store.cleanup()
        with self.assertRaises(a.BridgeError):
            self.store.approved_output(value)

    def test_restart_respects_expiry_and_token_hashes(self):
        value = self.body("TEMPORARY_DISCLOSURE")
        self.store.approved_output(value)
        old_instance, conversation = self.store.instance, self.store.conversation
        token_blob = " ".join(str(tuple(row)) for row in self.store.db.execute("SELECT * FROM tokens"))
        self.assertTrue(self.ai not in token_blob and self.controller not in token_blob)
        self.store.close()
        self.store = a.BridgeStore(self.temp.name, conversation, clock=lambda: self.now)
        self.assertNotEqual(self.store.instance, old_instance)
        self.assertEqual(self.store.status(self.controller)["state"], "PAIRED")
        self.assertEqual(self.store.approved_output(value)["state"], "ACKNOWLEDGED")
        self.now += a.BRIDGE_RETENTION + 1
        self.store.cleanup()
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM outputs").fetchone()[0], 0)

    def test_proposal_limits_and_idempotency(self):
        value = {"request_id": uuid.uuid4().hex, "text": "printf 'hello\\n'"}
        first = self.store.submit(value)
        self.assertEqual(first, self.store.submit(value))
        with self.assertRaises(a.BridgeError):
            self.store.submit(dict(value, text="printf 'changed\\n'"))
        for _ in range(19):
            self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        with self.assertRaises(a.BridgeError):
            self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})

    def test_bound_cursors_and_passive_schema(self):
        self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        batch = self.store.inbox(self.controller, "")
        second, _ = self.store.issue("CONTROLLER")
        with self.assertRaises(a.BridgeError):
            self.store.inbox(second, batch["cursor"])
        with self.assertRaises(a.BridgeError):
            self.store.ai_output(self.store.authenticate(self.ai, "AI"), {"cursor": batch["cursor"]})
        for bad in ({"request_id": uuid.uuid4().hex, "text": "true", "approved": True},
                    {"request_id": uuid.uuid4().hex, "text": "true\x1b[0m"},
                    {"request_id": uuid.uuid4().hex, "text": "x" * 4097}):
            with self.assertRaises(a.BridgeError):
                self.store.submit(bad)

    def test_json_limits_duplicates_nonfinite_and_no_reflection(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":"\xff"}',
                    b'[' + b'0]' * 20, b'{"x":"' + b'x' * a.BRIDGE_BODY_LIMIT + b'"}'):
            with self.assertRaises(a.BridgeError):
                a.parse(raw)

    def test_symlink_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            victim = Path(other) / "victim"
            victim.write_text("untouched")
            Path(other, "state").mkdir(mode=0o700)
            Path(other, "state", "bridge.sqlite3").symlink_to(victim)
            with self.assertRaises(a.BridgeError):
                a.BridgeStore(Path(other, "state"), uuid.uuid4().hex)
            self.assertEqual(victim.read_text(), "untouched")

    def test_output_envelope_extreme_escaping_is_not_silently_truncated(self):
        with self.assertRaises(a.BridgeError):
            self.store.approved_output(self.body("\n" * a.OUTPUT_LIMIT))
        accepted = self.body("X" * a.OUTPUT_LIMIT)
        self.assertEqual(self.store.approved_output(accepted)["state"], "ACKNOWLEDGED")


class RuntimeModeTests(unittest.TestCase):
    def test_bridge_component_loads_without_controller_capabilities(self):
        bridge = a._load_bridge_component()
        self.assertIn("BridgeStore", bridge)
        self.assertIn("bridge_main", bridge)
        self.assertNotIn("AppCore", bridge)
        self.assertNotIn("run_terminal_helper", bridge)
        self.assertNotIn("PtySession", bridge)

    def test_no_argument_and_explicit_gui_start_gui(self):
        for argv in ([a.__file__], [a.__file__, "--gui"]):
            with self.subTest(argv=argv), mock.patch.object(a.sys, "argv", list(argv)), \
                    mock.patch.object(a, "run_gui") as run_gui:
                self.assertEqual(a.main(), 0)
                run_gui.assert_called_once_with()

    def test_bridge_flag_is_explicit_and_conflicting_role_rejected(self):
        with mock.patch.object(a.sys, "argv", [a.__file__, "--gui", "--bridge"]):
            with self.assertRaisesRegex(a.ProbeError, "choose_one_role"):
                a.main()

    def test_remote_command_is_shell_quoted_and_uses_explicit_bridge_role(self):
        command = a.remote_bridge_command("python3", "/opt/Admin in the Loop/admin_in_the_loop.py",
                                          "/home/admin/.local/state/aitl-bridge", "0.0.0.0",
                                          "8443", "bridge.example")
        argv = __import__("shlex").split(command)
        self.assertEqual(argv, ["python3", "/opt/Admin in the Loop/admin_in_the_loop.py", "--bridge",
                                "--state-dir", "/home/admin/.local/state/aitl-bridge", "--bind", "0.0.0.0",
                                "--port", "8443", "--tls-name", "bridge.example", "--pair"])
        for invalid in (
            ("python3", "relative.py", "/state", "0.0.0.0", 8443, "bridge.example"),
            ("python3", "/app.py", "/state", "not-an-ip", 8443, "bridge.example"),
            ("python3", "/app.py", "/state", "0.0.0.0", 0, "bridge.example"),
        ):
            with self.assertRaises(a.ProbeError):
                a.remote_bridge_command(*invalid)

    def test_local_bridge_self_spawns_canonical_file_and_cleans_up(self):
        process = a.LocalBridgeProcess()
        state_dir = process.directory
        try:
            self.assertNotEqual(process.process.pid, os.getpid())
            self.assertEqual(process.profile.mode, "LOCAL")
            if sys.platform.startswith("linux"):
                command = Path("/proc", str(process.process.pid), "cmdline").read_bytes().split(b"\0")
                self.assertIn(str(Path(a.__file__).resolve()).encode(), command)
                self.assertIn(b"--bridge", command)
                descriptors = [os.readlink(path) for path in Path("/proc", str(process.process.pid), "fd").iterdir()]
                self.assertFalse(any("/dev/pts" in target for target in descriptors))
                environment = Path("/proc", str(process.process.pid), "environ").read_bytes().split(b"\0")
                self.assertEqual({item.split(b"=", 1)[0] for item in environment if item},
                                 {b"PATH", b"LC_ALL", b"LANG"})
        finally:
            process.close()
        self.assertIsNotNone(process.process.poll())
        self.assertFalse(state_dir.exists())


class StreamingProjectionTests(unittest.TestCase):
    def test_fragmented_utf8_and_escapes_match_whole_stream(self):
        raw = "a€\x1b[31mred\x1b[0m\r\nplain\x1b]52;c;INVISIBLE\nPAYLOAD\x07end".encode()
        full, fragmented = a.TranscriptSanitizer(), a.TranscriptSanitizer()
        expected = full.feed(raw)
        actual = b"".join(fragmented.feed(bytes([byte])) for byte in raw)
        self.assertEqual(actual, expected)
        self.assertTrue(b"INVISIBLE" not in actual and b"PAYLOAD" not in actual)
        self.assertEqual(fragmented.pending_marker(), b"")

    def test_last_lines_never_enter_middle_of_osc_payload(self):
        ring = a.TranscriptRing()
        for raw in (b"visible\n\x1b]52;c;SECRET", b"\nHIDDEN_LINE\n", b"\x1b\\last visible\n"):
            ring.append(raw)
        projected, lost = ring.selected_text()
        self.assertFalse(lost)
        self.assertTrue(b"SECRET" not in projected and b"HIDDEN_LINE" not in projected)
        self.assertEqual(projected.splitlines()[-1], b"last visible")

    def test_unterminated_sequence_remains_bounded_and_visible(self):
        ring = a.TranscriptRing(1024)
        ring.append(b"\x1b]52;c;")
        for _ in range(100):
            ring.append(b"x" * 1000)
        self.assertLessEqual(ring.clean_size, 1024)
        self.assertLessEqual(ring.sanitizer.count, 4097)
        self.assertIn(b"unterbrochene Terminalsequenz", ring.selected_text()[0])
        ring.append(b"\x07SAFE\n")
        self.assertIn(b"SAFE", ring.selected_text()[0])

    def test_loss_and_arbitrary_partial_chunk_offset_are_explicit(self):
        ring = a.TranscriptRing(16)
        ring.append(b"old line\n")
        marker = ring.end
        ring.append(b"new line\n")
        self.assertTrue(ring.selected_text(0)[1])
        self.assertEqual(ring.selected_text(marker)[0], b"new line\n")
        self.assertTrue(ring.selected_text(marker + 1)[1])


class HTTPTests(unittest.TestCase):
    def test_other_chat_cannot_guess_or_discover_binding(self):
        headers = {"X-AITL-AI-Key": self.process.ai_token}
        for arguments in ({}, {"conversation": "0" * 64}, {"conversation": "ä" * 16}):
            value = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "get_approved_output", "arguments": arguments}}
            status, raw = request(self.process.mcp_url, "POST", body=value, headers=headers)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["result"]["isError"])
            self.assertTrue(self.process.profile.conversation.encode() not in raw)
            self.assertTrue(self.process.chat_code.encode() not in raw)
        value["params"]["name"] = "get_preferences"
        status, raw = request(self.process.mcp_url, "POST", body=value, headers=headers)
        self.assertTrue(json.loads(raw)["result"]["isError"])

    def setUp(self):
        self.process = a.LocalBridgeProcess()

    def tearDown(self):
        self.process.close()

    def test_five_tools_legacy_and_modern_discovery(self):
        value = {"jsonrpc": "2.0", "id": "list", "method": "tools/list", "params": {}}
        headers = {"X-AITL-AI-Key": self.process.ai_token}
        status, raw = request(self.process.mcp_url, "POST", body=value, headers=headers)
        self.assertEqual(status, 200)
        names = {item["name"] for item in json.loads(raw)["result"]["tools"]}
        self.assertEqual(names, {"submit_proposal", "get_submission_status", "get_approved_output",
                                 "get_preferences", "withdraw_proposal"})
        self.assertEqual(mcp(self.process, "get_preferences", modern=True)["block_size"], "SMALL")
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        value = {"jsonrpc": "2.0", "id": 2, "method": "server/discover", "params": {"_meta": meta}}
        headers["MCP-Protocol-Version"] = "2026-07-28"
        status, raw = request(self.process.mcp_url, "POST", body=value, headers=headers)
        self.assertEqual(status, 200)
        self.assertIn("2026-07-28", json.loads(raw)["result"]["supportedVersions"])

    def test_roles_auth_and_missing_terminal_endpoints(self):
        base = self.process.profile.url
        self.assertEqual(request(base, path="/v1/status")[0], 401)
        self.assertEqual(request(base, path="/v1/status", headers={"Authorization": "Bearer " + self.process.ai_token})[0], 401)
        value = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        self.assertEqual(request(self.process.mcp_url, "POST", body=value,
                                 headers={"X-AITL-AI-Key": self.process.profile.token})[0], 401)
        for path in ("/execute", "/send-keys", "/read-terminal", "/ssh", "/read-file", "/write-file"):
            self.assertEqual(request(base, "POST", path, {})[0], 404)

    def test_host_origin_limits_and_error_bodies_do_not_echo(self):
        headers = {"Authorization": "Bearer " + self.process.profile.token}
        self.assertEqual(request(self.process.profile.url, path="/v1/status", headers=dict(headers, Host="attacker.example"))[0], 403)
        self.assertEqual(request(self.process.profile.url, path="/v1/status", headers=dict(headers, Origin="https://attacker.example"))[0], 403)
        headers = {"X-AITL-AI-Key": self.process.ai_token}
        bad = b'{"CANARY_SECRET_CONTENT":"unterminated'
        status, raw = request(self.process.mcp_url, "POST", body=bad, headers=headers)
        self.assertEqual(status, 400)
        self.assertTrue(b"CANARY_SECRET_CONTENT" not in raw)
        self.assertEqual(request(self.process.mcp_url, "POST", body=b'x' * (a.FRAME_LIMIT + 1), headers=headers)[0], 413)

    def test_long_poll_empty_timeout_and_new_proposal(self):
        client = a.BridgeHTTP(self.process.profile)
        initial = client.request("GET", "/v1/inbox?wait=0")
        self.assertEqual(initial["messages"], [])
        result = []
        thread = threading.Thread(target=lambda: result.append(client.request("GET", "/v1/inbox?wait=2&cursor=" + initial["cursor"])))
        thread.start()
        time.sleep(0.1)
        item = mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex, "text": "true"})
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]["messages"][0]["id"], item["submission_id"])

    def test_remote_plaintext_rejected_and_process_no_terminal_fds(self):
        with self.assertRaises(a.ProbeError):
            a.BridgeHTTP(replace(self.process.profile, mode="REMOTE"))
        if sys.platform.startswith("linux"):
            descriptors = Path("/proc") / str(self.process.process.pid) / "fd"
            targets = [os.readlink(p) for p in descriptors.iterdir()]
            self.assertFalse(any("/dev/pts" in target for target in targets))

    def test_full_size_approved_output_is_retrievable_over_mcp(self):
        profile = self.process.profile
        value = {"version": 1, "conversation": profile.conversation, "idempotency_key": uuid.uuid4().hex,
                 "text": "X" * a.OUTPUT_LIMIT, "submission_id": None, "approved_at": time.time()}
        self.assertEqual(a.BridgeHTTP(profile).request("POST", "/v1/approved-output", value)["state"], "ACKNOWLEDGED")
        self.assertEqual(len(mcp(self.process, "get_approved_output")["outputs"][0]["text"]), a.OUTPUT_LIMIT)


class ChatBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-chat-binding-")
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000.0
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: self.now)
        self.controller, self.controller_id = self.store.issue("CONTROLLER")
        self.ai, self.ai_id = self.store.issue("AI")
        self.harness = ServiceHarness(self.store, self.controller, self.controller_id, self.ai, self.ai_id)
        self.addCleanup(self.harness.close)
        self.code = self.harness.chat_code

    def rpc(self, method, params, token=None):
        value = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": dict(params)}
        value["params"].setdefault("_meta", {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                               "io.modelcontextprotocol/clientCapabilities": {}})
        status, raw = request(self.harness.mcp_url, "POST", body=value, headers={
            "X-AITL-AI-Key": token or self.ai, "MCP-Protocol-Version": "2026-07-28"})
        self.assertEqual(status, 200)
        packet = json.loads(raw)
        return packet.get("result", packet)

    def tool(self, code, *, token=None, name="get_preferences", arguments=None):
        values = dict(arguments or {})
        values["conversation"] = code
        return self.rpc("tools/call", {"name": name, "arguments": values}, token)

    def controller_binding(self):
        return a.BridgeHTTP(self.harness.profile).request("GET", "/v1/chat-binding")

    def test_happy_path_rotation_authentication_and_idempotent_retry(self):
        self.assertEqual(len(self.code), 8)
        self.assertTrue(all(char in a.BRIDGE_CHAT_ALPHABET for char in self.code))
        self.assertNotEqual(self.code, self.store.conversation)
        entered = self.code.lower()[:4] + "-" + self.code.lower()[4:]
        self.assertEqual(self.tool(entered)["structuredContent"]["block_size"], "SMALL")
        self.assertEqual(self.controller_binding()["code"], self.code)
        self.assertEqual(request(self.harness.profile.url, path="/v1/chat-binding")[0], 401)
        self.assertEqual(request(self.harness.profile.url, path="/v1/chat-binding",
                                 headers={"Authorization": "Bearer " + self.ai})[0], 401)
        request_id = uuid.uuid4().hex
        body = {"version": 1, "request_id": request_id, "expected_generation": 1}
        rotated = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/chat-binding/rotate", body)
        replay = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/chat-binding/rotate", body)
        self.assertEqual(rotated["generation"], 2)
        self.assertEqual(rotated["code"], replay["code"])
        self.assertNotEqual(rotated["code"], self.code)
        self.assertEqual(self.harness.profile.conversation, self.store.conversation)
        self.assertEqual(self.tool(self.code)["structuredContent"]["error"], "conversation_binding_required")
        self.assertEqual(self.tool(rotated["code"])["structuredContent"]["block_size"], "SMALL")
        stale = request(self.harness.profile.url, "POST", "/v1/chat-binding/rotate",
                        {"version": 1, "request_id": uuid.uuid4().hex, "expected_generation": 1},
                        {"Authorization": "Bearer " + self.controller})
        self.assertEqual(stale[0], 409)

    def test_backoff_sequence_principal_lock_spam_and_recovery(self):
        for _ in range(3):
            self.assertEqual(self.tool("WRONG000")["structuredContent"]["error"], "conversation_binding_required")
        for failure, delay in enumerate(a._bridge_component["BRIDGE_CHAT_BACKOFF"], start=4):
            result = self.tool("WRONG000")["structuredContent"]
            self.assertEqual(result["error"], "conversation_binding_backoff")
            self.assertEqual(result["retry_after_seconds"], delay)
            if failure == 4:
                for _ in range(3):
                    spam = self.tool(self.code)["structuredContent"]
                    self.assertEqual(spam["error"], "conversation_binding_backoff")
                    self.assertEqual(spam["retry_after_seconds"], delay)
                row = self.store.execute("SELECT failures,next_allowed FROM chat_binding_attempts WHERE principal=?",
                                         (self.ai_id,)).fetchone()
                self.assertEqual(row["failures"], 4)
                deadline = row["next_allowed"]
                self.assertEqual(deadline, self.store.execute(
                    "SELECT next_allowed FROM chat_binding_attempts WHERE principal=?", (self.ai_id,)).fetchone()[0])
            self.now += delay
        locked = self.tool("WRONG000")["structuredContent"]
        self.assertEqual(locked["error"], "conversation_binding_locked")
        until = self.store.execute("SELECT locked_until FROM chat_binding_attempts WHERE principal=?",
                                   (self.ai_id,)).fetchone()[0]
        for _ in range(3):
            self.assertEqual(self.tool(self.code)["structuredContent"]["error"], "conversation_binding_locked")
        self.assertEqual(self.store.execute("SELECT locked_until FROM chat_binding_attempts WHERE principal=?",
                                            (self.ai_id,)).fetchone()[0], until)
        self.assertEqual(self.controller_binding()["status"], "LOCKED")
        self.now += a.BRIDGE_CHAT_LOCKOUT
        self.assertEqual(self.tool(self.code)["structuredContent"]["block_size"], "SMALL")

    def test_binding_wide_lock_across_principals_and_recovery(self):
        principals = [(self.ai, self.ai_id)] + [self.store.issue("AI") for _ in range(2)]
        final = None
        for principal_index, (token, _) in enumerate(principals):
            for failure in range(1, 11):
                final = self.tool("WRONG000", token=token)["structuredContent"]
                if failure < 4:
                    self.assertEqual(final["error"], "conversation_binding_required")
                elif failure < 10:
                    self.assertEqual(final["error"], "conversation_binding_backoff")
                elif principal_index < len(principals) - 1:
                    self.assertEqual(final["error"], "conversation_binding_backoff")
                else:
                    self.assertEqual(final["error"], "conversation_binding_locked")
                if failure >= 4:
                    self.now += a._bridge_component["BRIDGE_CHAT_BACKOFF"][failure - 4]
        self.assertEqual(final["error"], "conversation_binding_locked")
        row = self.store.execute("SELECT failure_times,locked_until FROM chat_binding_attempts WHERE principal='*'").fetchone()
        self.assertEqual(len(json.loads(row["failure_times"])), a.BRIDGE_CHAT_BINDING_FAILURES)
        until = row["locked_until"]
        for _ in range(4):
            self.assertEqual(self.tool(self.code)["structuredContent"]["error"], "conversation_binding_locked")
        self.assertEqual(self.store.execute("SELECT locked_until FROM chat_binding_attempts WHERE principal='*'").fetchone()[0], until)
        self.assertEqual(self.controller_binding()["status"], "LOCKED")
        self.now = until
        self.assertEqual(self.tool(self.code)["structuredContent"]["block_size"], "SMALL")

    def test_parallel_bad_guesses_are_serialized_and_bad_auth_does_not_count(self):
        tokens = [self.store.issue("AI") for _ in range(20)]
        barrier = threading.Barrier(len(tokens))
        results = []
        result_lock = threading.Lock()

        def guess(token, _identifier):
            barrier.wait(timeout=5)
            value = self.tool("WRONG000", token=token)["structuredContent"]
            with result_lock:
                results.append(value["error"])

        workers = [threading.Thread(target=guess, args=pair) for pair in tokens]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=8)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(len(results), len(tokens))
        aggregate = self.store.execute("SELECT failure_times FROM chat_binding_attempts WHERE principal='*'").fetchone()
        self.assertEqual(len(json.loads(aggregate[0])), len(tokens))
        before = len(json.loads(aggregate[0]))
        status, _ = request(self.harness.mcp_url, "POST", body={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": "get_preferences", "arguments": {"conversation": "WRONG000"}}},
            headers={"X-AITL-AI-Key": "0" * 64})
        self.assertEqual(status, 401)
        after = self.store.execute("SELECT failure_times FROM chat_binding_attempts WHERE principal='*'").fetchone()
        self.assertEqual(len(json.loads(after[0])), before)

    def test_expiry_rotation_and_expired_code_recovery(self):
        self.now += a.BRIDGE_CHAT_LIFETIME
        expired = self.controller_binding()
        self.assertEqual(expired["status"], "EXPIRED")
        self.assertIsNone(expired["code"])
        self.assertEqual(self.tool(self.code)["structuredContent"]["error"], "conversation_binding_expired")
        rotated = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/chat-binding/rotate", {
            "version": 1, "request_id": uuid.uuid4().hex, "expected_generation": 1})
        self.assertEqual(rotated["status"], "VALID")
        self.assertEqual(rotated["generation"], 2)
        self.assertEqual(self.tool(rotated["code"])["structuredContent"]["block_size"], "SMALL")

    def test_legacy_code_alias_is_one_time_and_rotation_ends_it(self):
        legacy_dir = Path(self.temp.name, "legacy")
        conversation = uuid.uuid4().hex
        legacy = a.BridgeStore(legacy_dir, conversation, clock=lambda: self.now)
        _, identifier = legacy.issue("AI")
        legacy.close()
        db = sqlite3.connect(legacy_dir / "bridge.sqlite3")
        db.execute("DELETE FROM meta WHERE key='chat_binding'")
        db.commit()
        db.close()
        migrated = a.BridgeStore(legacy_dir, conversation, clock=lambda: self.now)
        try:
            self.assertNotEqual(migrated.chat_binding["code"], conversation)
            self.assertEqual(migrated.authorize_chat_binding(identifier, conversation), 1)
            rotated = migrated.rotate_chat_binding(uuid.uuid4().hex, 1, identifier)
            with self.assertRaises(a.BridgeError) as old:
                migrated.authorize_chat_binding(identifier, conversation)
            self.assertEqual(old.exception.code, "conversation_binding_required")
            self.assertEqual(migrated.authorize_chat_binding(identifier, rotated["code"]), 2)
            self.now += a.BRIDGE_CHAT_LIFETIME
            with self.assertRaises(a.BridgeError) as expired:
                migrated.authorize_chat_binding(identifier, rotated["code"])
            self.assertEqual(expired.exception.code, "conversation_binding_expired")
        finally:
            migrated.close()

    def test_event_subscription_generation_and_callback_rotation_race(self):
        secret = "whsec_" + base64.b64encode(b"r" * 24).decode()
        params = {"name": a.BRIDGE_EVENT_NAME, "arguments": {"conversation": self.code},
                  "delivery": {"mode": "webhook", "url": "https://callback.example/generation",
                               "secret": secret}}
        subscribed = self.rpc("events/subscribe", params)
        identifier = subscribed["id"]
        self.assertEqual(self.store.find_subscription(self.ai_id, "https://callback.example/generation",
                                                      a.BRIDGE_EVENT_NAME, "{}")["binding_generation"], 1)
        rotated = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/chat-binding/rotate", {
            "version": 1, "request_id": uuid.uuid4().hex, "expected_generation": 1})
        self.assertIsNone(self.store.active_subscription(identifier, self.now))
        self.assertEqual(self.store.count_subscriptions(self.ai_id), 0)
        self.assertEqual(self.tool(self.code)["structuredContent"]["error"], "conversation_binding_required")

        def rotate_during_verification(*_):
            self.store.rotate_chat_binding(uuid.uuid4().hex, rotated["generation"], self.controller_id)
            return True

        race_params = {"name": a.BRIDGE_EVENT_NAME,
                       "arguments": {"conversation": rotated["code"]},
                       "delivery": {"mode": "webhook", "url": "https://callback.example/race",
                                    "secret": secret}}
        with mock.patch.object(self.harness.service, "verify_callback", rotate_during_verification):
            raced = self.rpc("events/subscribe", race_params)
        self.assertEqual(raced["error"]["data"]["reason"], "conversation_binding_expired")
        self.assertEqual(self.store.count_subscriptions(self.ai_id), 0)

    def test_backoff_persists_across_store_restart(self):
        for _ in range(3):
            with self.assertRaises(a.BridgeError):
                self.store.authorize_chat_binding(self.ai_id, "WRONG000")
        with self.assertRaises(a.BridgeError) as blocked:
            self.store.authorize_chat_binding(self.ai_id, "WRONG000")
        self.assertEqual(blocked.exception.code, "conversation_binding_backoff")
        conversation = self.store.conversation
        code = self.code
        self.harness.close()
        reopened = a.BridgeStore(self.temp.name, conversation, clock=lambda: self.now)
        self.harness.store = reopened
        self.store = reopened
        with self.assertRaises(a.BridgeError) as still_blocked:
            reopened.authorize_chat_binding(self.ai_id, code)
        self.assertEqual(still_blocked.exception.code, "conversation_binding_backoff")
        self.now += 1
        self.assertEqual(reopened.authorize_chat_binding(self.ai_id, code), 1)


class ConnectedRoundTripTests(unittest.TestCase):
    def test_stopped_network_worker_blocks_existing_approval(self):
        self.submit(": > stopped-worker-marker")
        review = self.take_review()
        self.core.bridge_worker.stop.set()
        self.core.pump()
        self.assertEqual(self.core.bridge_state, "BLOCKED")
        with self.assertRaises(a.ProbeError):
            self.core.approve(review.id)
        self.assertFalse(Path(self.temp.name, "stopped-worker-marker").exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-roundtrip-")
        self.fixture = a.IntegrationFixture(self.temp.name)
        self.core = self.fixture.core
        self.core.connect_local_bridge()
        self.fixture.wait(lambda: self.core.bridge_state == "CONNECTED", timeout=6)
        self.process = self.core.bridge_process

    def tearDown(self):
        self.fixture.close()
        self.temp.cleanup()

    def submit(self, content):
        item = mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex, "text": content})
        self.fixture.wait(lambda: bool(self.core.inbox), timeout=6)
        return item["submission_id"]

    def take_review(self):
        """W2: bridge-bound takeover is asynchronous (TAKE_PENDING -> bridge ACK)."""
        self.assertEqual(self.core.review_state in a.AppCore.STAGE_FREE, True)
        self.assertIsNone(self.core.review_pending_proposal())
        self.assertEqual(self.core.review_state, "TAKE_PENDING")
        self.fixture.wait(lambda: self.core.review is not None and self.core.review_state == "REVIEW",
                          timeout=6)
        return self.core.review

    def test_complete_mcp_review_pty_output_review_mcp_round_trip(self):
        identifier = self.submit("printf 'CONNECTED_ROUNDTRIP\\n'; : > human-approved-marker")
        marker = Path(self.temp.name, "human-approved-marker")
        self.assertFalse(marker.exists())
        self.assertIsNone(self.core.review)
        self.assertEqual(mcp(self.process, "get_approved_output", {"submission_id": identifier})["outputs"], [])
        review = self.take_review()
        self.assertFalse(marker.exists())
        self.core.approve(review.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(review.id, override=True)
            self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        self.fixture.wait(lambda: marker.exists() and b"CONNECTED_ROUNDTRIP\r\n" in self.core.output.data)
        self.assertEqual(mcp(self.process, "get_submission_status", {"submission_id": identifier})["state"], "TAKEN")
        output = self.core.select_current_output()
        self.assertEqual(mcp(self.process, "get_approved_output", {"submission_id": identifier})["outputs"], [])
        output = self.core.edit_review(output.id, "CONNECTED_ROUNDTRIP\nOnly this chosen text is shared.", False)
        exact = output.payload
        self.core.approve(output.id)
        self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        returned = mcp(self.process, "get_approved_output", {"submission_id": identifier})["outputs"]
        self.assertEqual(len(returned), 1)
        self.assertEqual(returned[0]["text"].encode(), exact)
        with self.assertRaises(a.ProbeError):
            self.core.approve(output.id)

    def test_approved_output_event_continuation_uses_exact_canonical_read(self):
        store = a.BridgeStore(Path(self.temp.name, "event-bridge"), uuid.uuid4().hex)
        controller, controller_id = store.issue("CONTROLLER")
        ai, ai_id = store.issue("AI")
        harness = ServiceHarness(store, controller, controller_id, ai, ai_id)
        self.addCleanup(harness.close)
        self.core.connect_profile(harness.profile)
        self.addCleanup(self.core.disconnect_bridge)
        self.fixture.wait(lambda: self.core.bridge_state == "CONNECTED", timeout=6)
        process = SimpleNamespace(profile=harness.profile, ai_token=ai, mcp_url=harness.mcp_url,
                                  chat_code=harness.chat_code)

        def event_rpc(method, params):
            value = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method,
                     "params": dict(params, _meta={
                         "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                         "io.modelcontextprotocol/clientCapabilities": {}})}
            status, raw = request(harness.mcp_url, "POST", body=value, headers={
                "X-AITL-AI-Key": ai, "MCP-Protocol-Version": "2026-07-28"})
            self.assertEqual(status, 200)
            return json.loads(raw)["result"]

        secret = "whsec_" + base64.b64encode(b"e" * 24).decode()
        subscribed = event_rpc("events/subscribe", {
            "name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": harness.chat_code},
            "delivery": {"mode": "webhook", "url": "https://callback.example/continuation",
                         "secret": secret}})
        subscription_id = subscribed["id"]

        command_runs = Path(self.temp.name, "event-command-runs")
        proposal = mcp(process, "submit_proposal", {
            "request_id": uuid.uuid4().hex,
            "text": "printf 'APPROVED_EVENT_OUTPUT\\n'; printf x >> event-command-runs"})
        submission_id = proposal["submission_id"]
        self.fixture.wait(lambda: bool(self.core.inbox), timeout=6)
        self.assertIsNone(self.core.review)
        self.assertFalse(command_runs.exists())
        self.assertEqual(mcp(process, "get_approved_output", {"submission_id": submission_id})["outputs"], [])
        self.assertEqual(harness.deliveries, {})

        command_review = self.take_review()
        self.assertEqual(command_review.proposal_id, submission_id)
        self.assertFalse(command_runs.exists())
        self.core.approve(command_review.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(command_review.id, override=True)
            self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        self.fixture.wait(lambda: command_runs.exists()
                          and b"APPROVED_EVENT_OUTPUT\r\n" in self.core.output.data)
        self.assertEqual(command_runs.read_text(), "x")
        self.assertEqual(mcp(process, "get_submission_status", {"submission_id": submission_id})[
            "approved_output_available"], False)
        self.assertEqual(harness.deliveries, {})

        output_review = self.core.select_current_output()
        self.assertIn("APPROVED_EVENT_OUTPUT", output_review.text)
        output_review = self.core.edit_review(output_review.id, "HUMAN_APPROVED_EVENT_OUTPUT\n", False)
        posted_outputs = []
        original_request = a.BridgeHTTP.request

        def capture_approved_output(client, method, path, value=None, **kwargs):
            result = original_request(client, method, path, value, **kwargs)
            if path == "/v1/approved-output":
                posted_outputs.append(value)
            return result

        with mock.patch.object(a.BridgeHTTP, "request", capture_approved_output):
            self.core.approve(output_review.id, submission_id=submission_id)
            self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        self.assertEqual(len(posted_outputs), 1)
        harness.wait(lambda: len(harness.deliveries.get(subscription_id, [])) == 1)

        event = harness.deliveries[subscription_id][0][1]
        self.assertEqual(event["name"], a.BRIDGE_EVENT_NAME)
        self.assertEqual(event["eventId"], event["data"]["output_id"])
        self.assertEqual(event["data"]["submission_id"], submission_id)
        self.assertNotIn("conversation", event["data"])
        self.assertNotIn(harness.profile.conversation, json.dumps(event))
        self.assertNotIn("HUMAN_APPROVED_EVENT_OUTPUT", json.dumps(event))
        row = store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                            (event["eventId"],)).fetchone()
        self.assertEqual(row["delivered"], 1)
        self.assertIsNotNone(row["delivered_at"])

        processed = {}

        def continue_from_notification(notification):
            event_id = notification["eventId"]
            if event_id in processed:
                return False
            data = notification["data"]
            self.assertEqual(data["output_id"], event_id)
            readback = mcp(process, "get_approved_output", {"submission_id": data["submission_id"]})
            outputs = readback["outputs"]
            self.assertEqual(len(outputs), 1)
            self.assertEqual(outputs[0]["output_id"], event_id)
            self.assertEqual(outputs[0]["submission_id"], submission_id)
            self.assertEqual(outputs[0]["text"], "HUMAN_APPROVED_EVENT_OUTPUT\n")
            processed[event_id] = outputs[0]
            return True

        self.assertTrue(continue_from_notification(event))
        self.assertEqual(mcp(process, "get_submission_status", {"submission_id": submission_id})[
            "approved_output_available"], False)
        self.assertEqual(mcp(process, "get_approved_output")["outputs"], [])
        wrong_binding = event_rpc("tools/call", {"name": "get_approved_output", "arguments": {
            "conversation": "wrong-conversation-binding", "submission_id": submission_id}})
        self.assertTrue(wrong_binding["isError"])

        replayed_upload = a.BridgeHTTP(harness.profile).request(
            "POST", "/v1/approved-output", posted_outputs[0])
        self.assertEqual(replayed_upload["output_id"], event["eventId"])
        self.assertEqual(len(harness.deliveries[subscription_id]), 1)

        subscription = store.active_subscription(subscription_id, store.clock())
        harness.service.deliver({"subscription": subscription, "event": event, "attempts": 0})
        self.assertEqual(len(harness.deliveries[subscription_id]), 2)
        replay_event = harness.deliveries[subscription_id][1][1]
        self.assertEqual(replay_event["eventId"], event["eventId"])
        self.assertFalse(continue_from_notification(replay_event))
        final_row = store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                                  (event["eventId"],)).fetchone()
        self.assertEqual(tuple(final_row), tuple(row))
        self.assertEqual(tuple(processed), (event["eventId"],))
        self.assertEqual(command_runs.read_text(), "x")
        self.assertFalse(self.core.inbox)
        self.assertEqual(store.execute("SELECT count(*) FROM proposals").fetchone()[0], 1)

    def test_output_binding_is_exact_per_submission_not_last_heuristic(self):
        first = self.submit("printf 'MULTI_FLIGHT_ONE\\n'")
        second = self.submit("printf 'MULTI_FLIGHT_TWO\\n'")
        for proposal in (first, second):
            self.fixture.wait(lambda: bool(self.core.inbox), timeout=6)
            review = self.take_review()
            self.assertEqual(review.proposal_id, proposal)
            self.core.approve(review.id)
            self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
            if self.core.review_state == "OVERRIDE_REQUIRED":
                self.core.approve(review.id, override=True)
            self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
            # R4 (rev3 send barrier): a second real terminal send requires the previous
            # return to be closed first; the explicit waiver variant keeps :891-898 intact.
            if self.core.open_return is not None:
                self.core.close_open_return()
        candidates = self.core.output_candidates()
        self.assertEqual({item["submission_id"] for item in candidates}, {first, second})
        # TRANSFERRED acknowledges the terminal write, not arrival of shell output.
        self.fixture.wait(lambda: b"MULTI_FLIGHT_TWO\r\n" in self.core.output.data)
        output = self.core.select_current_output()
        with self.assertRaises(a.ProbeError):
            self.core.approve(output.id, submission_id="f" * 32)
        self.core.approve(output.id, submission_id=second)
        self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        named = mcp(self.process, "get_approved_output", {"submission_id": second})["outputs"]
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0]["submission_id"], second)
        self.assertIn(b"MULTI_FLIGHT", named[0]["text"].encode())
        other = mcp(self.process, "get_approved_output", {"submission_id": first})["outputs"]
        self.assertEqual(other, [])
        general = mcp(self.process, "get_approved_output")["outputs"]
        self.assertEqual([item["submission_id"] for item in general], [second])

    def test_explicit_unbound_binding_ignores_last_submission(self):
        first = self.submit("printf 'EXPBIND_A\\n'")
        review = self.take_review()
        self.core.approve(review.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(review.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        self.assertEqual(self.core.last_proposal_id, first)
        output = self.core._output_review("EXPLICIT_UNBOUND_CHOICE\n")
        self.core.approve(output.id, explicit_binding=True)
        self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        with_named = mcp(self.process, "get_approved_output", {"submission_id": first})["outputs"]
        self.assertEqual(with_named, [])
        general = mcp(self.process, "get_approved_output")["outputs"]
        self.assertEqual(len(general), 1)
        self.assertIsNone(general[0]["submission_id"])
        self.assertEqual(general[0]["text"].encode(), output.payload)

    def test_pending_second_proposal_never_changes_review(self):
        first = self.submit("printf 'FIRST\\n'")
        review = self.take_review()
        mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex, "text": "printf 'SECOND\\n'"})
        self.fixture.wait(lambda: bool(self.core.inbox), timeout=6)
        self.assertEqual(self.core.review, review)
        self.assertEqual(review.proposal_id, first)
        self.assertEqual(self.core.review_state, "REVIEW")
        self.assertEqual(len(self.core.inbox), 1)

    def test_bridge_disconnect_stales_review_manual_shell_survives(self):
        self.submit(": > forbidden-after-disconnect")
        review = self.take_review()
        self.core.disconnect_bridge()
        with self.assertRaises(a.ProbeError):
            self.core.approve(review.id)
        self.assertEqual(self.core.review_state, "STALE")
        self.fixture.manual("printf 'MANUAL_STILL_AVAILABLE\\n'\n")
        self.fixture.wait(lambda: b"MANUAL_STILL_AVAILABLE\r\n" in self.core.output.data)
        self.assertFalse(Path(self.temp.name, "forbidden-after-disconnect").exists())

    def test_ack_loss_retry_identical_snapshot_no_duplicate_upload(self):
        self.submit("true")
        output = self.core._output_review("EXACT_APPROVED_SNAPSHOT\n")
        original = a.BridgeHTTP.request
        posted, lost = [], [False]
        def unreliable(client, method, path, value=None, **kwargs):
            result = original(client, method, path, value, **kwargs)
            if path == "/v1/approved-output":
                posted.append(value)
                if not lost[0]:
                    lost[0] = True
                    raise a.TransportError("network_unavailable", True)
            return result
        with mock.patch.object(a.BridgeHTTP, "request", unreliable):
            self.core.approve(output.id)
            self.fixture.wait(lambda: self.core.review_state == "DELIVERY_UNCERTAIN", timeout=6)
            self.fixture.wait(lambda: self.core.bridge_state == "CONNECTED", timeout=6)
            self.core.output.append(b"UNAPPROVED_LATER_OUTPUT\n")
            with self.assertRaises(a.ProbeError):
                self.core.select_current_output()
            self.core.retry_output(output.id)
            self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        self.assertEqual(len(posted), 2)
        self.assertEqual(posted[0], posted[1])
        response = mcp(self.process, "get_approved_output")
        self.assertEqual(len(response["outputs"]), 1)
        self.assertEqual(response["outputs"][0]["text"].encode(), output.payload)
        self.assertEqual(mcp(self.process, "get_approved_output", {"cursor": response["cursor"]})["outputs"], [])

    def test_reconnect_generation_and_expired_proposal_block_approval(self):
        self.submit(": > generation-marker")
        review = self.take_review()
        self.core.bridge_worker.emit("disconnected", ("network_unavailable", True))
        self.core.pump()
        self.assertEqual(self.core.review_state, "STALE")
        self.core.bridge_worker.emit("connected", self.process.profile.controller_id)
        self.core.pump()
        with self.assertRaises(a.ProbeError):
            self.core.approve(review.id)
        self.assertFalse(Path(self.temp.name, "generation-marker").exists())

    def test_disclosed_preference_single_and_no_approval_restore(self):
        self.core.set_preferences("SINGLE")
        last_poll = [0]
        def published():
            if time.monotonic() - last_poll[0] < 0.2:
                return False
            last_poll[0] = time.monotonic()
            return mcp(self.process, "get_preferences")["block_size"] == "SINGLE"
        self.fixture.wait(published, timeout=6)
        self.assertEqual(self.core.bridge_snapshot().mode, "LOCAL")
        self.assertFalse(hasattr(self.core.bridge_snapshot(), "token"))
        self.assertIsNone(a.AppCore().snapshot().review)

    def test_reconnect_does_not_represent_consumed_proposal(self):
        self.submit("true")
        review = self.take_review()
        self.core.reject(review.id)
        self.core.reconnect_bridge()
        self.fixture.wait(lambda: self.core.bridge_state == "CONNECTED", timeout=6)
        deadline = time.monotonic() + 1.3
        while time.monotonic() < deadline:
            self.fixture.pump()
            time.sleep(0.01)
        self.assertFalse(self.core.inbox)
        self.assertEqual(self.core.review_state, "REJECTED")

    @unittest.skip("PENDING_EXTERNAL: real ChatGPT-Work host/workspace is unavailable here")
    def test_chatgpt_work_event_continuation_without_another_user_turn(self):
        """External checkpoint in this connected run: exercise the approved-output event in
        the actual configured ChatGPT-Work workspace, continue on that same event without a
        new user turn, read the exact event submission via get_approved_output, and verify
        that neither approval nor a follow-up command is bypassed. Record external evidence
        before removing this pending marker; local fixtures cannot satisfy this checkpoint.
        """
        self.fail("External host E2E must be evidenced in the real ChatGPT-Work workspace")


class ProposalLifecycleStoreTests(unittest.TestCase):
    """W2 bridge dimension: atomic take<->withdraw, RECORDED readback, matrix, legacy, restart."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-w2-store-")
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000.0
        self.conversation = uuid.uuid4().hex
        self.store = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now)
        self.controller, self.cid = self.store.issue("CONTROLLER")
        self.ai, self.aid = self.store.issue("AI")

    def tearDown(self):
        self.store.close()

    def reopen(self):
        self.store.close()
        self.store = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now)

    def submit(self, text="true"):
        return self.store.submit({"request_id": uuid.uuid4().hex, "text": text})["submission_id"]

    def take(self, submission, nonce=None, instance=None):
        return self.store.take(self.controller, submission, nonce or uuid.uuid4().hex,
                               self.store.instance if instance is None else instance)

    def status(self, submission):
        return self.store.submission_status(submission)

    def test_take_withdraw_race_has_exactly_one_winner_in_both_orders(self):
        for order in ("take_first", "withdraw_first", "concurrent"):
            for _ in range(3):
                submission = self.submit()
                nonce = uuid.uuid4().hex
                results = {}
                barrier = threading.Barrier(2)

                def run_take():
                    if order == "withdraw_first":
                        self.store.withdraw(submission)
                    elif order == "concurrent":
                        barrier.wait(timeout=5)
                    try:
                        results["take"] = self.take(submission, nonce)["state"]
                    except a.BridgeError as exc:
                        results["take"] = "error:" + exc.code

                def run_withdraw():
                    if order == "take_first":
                        try:
                            self.take(submission, nonce)
                        except a.BridgeError:
                            pass
                    elif order == "concurrent":
                        barrier.wait(timeout=5)
                    results["withdraw"] = self.store.withdraw(submission)["state"]

                threads = [threading.Thread(target=run_take), threading.Thread(target=run_withdraw)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=8)
                    self.assertFalse(thread.is_alive())
                state = self.status(submission)["state"]
                with self.subTest(order=order):
                    self.assertEqual(results["withdraw"], "RECORDED")  # never a success claim
                    self.assertIn(state, {"TAKEN", "WITHDRAWN"})
                    row = self.store.execute("SELECT * FROM proposals WHERE id=?", (submission,)).fetchone()
                    if state == "TAKEN":
                        self.assertIsNone(row["withdrawn_at"])
                        self.assertEqual(results["take"], "TAKEN")
                    else:
                        self.assertIsNone(row["taken_at"])
                        self.assertEqual(results["take"], "error:proposal_withdrawn")

    def test_recorded_readback_matrix_and_requested_without_withdrawn(self):
        submission = self.submit()
        self.assertEqual(self.store.withdraw(submission), {"submission_id": submission, "state": "RECORDED"})
        first = self.status(submission)
        self.assertEqual(first["state"], "WITHDRAWN")
        self.assertIsNotNone(first["withdraw_requested_at"])
        self.assertIsNotNone(first["withdrawn_at"])
        self.assertEqual(self.store.withdraw(submission)["state"], "RECORDED")  # idempotent
        self.assertEqual(self.status(submission)["withdrawn_at"], first["withdrawn_at"])
        with self.assertRaises(a.BridgeError):
            self.take(submission)
        other = self.submit()
        taken = self.take(other)
        self.assertEqual(taken["state"], "TAKEN")
        self.assertEqual(self.store.withdraw(other)["state"], "RECORDED")
        after = self.status(other)
        self.assertEqual(after["state"], "TAKEN")
        self.assertIsNotNone(after["withdraw_requested_at"])
        self.assertIsNone(after["withdrawn_at"])  # recorded, not-withdrawable

    def test_take_replay_constant_facts_conflicts_and_restart_instance(self):
        submission = self.submit()
        nonce = uuid.uuid4().hex
        first = self.take(submission, nonce)
        old_instance = self.store.instance
        replay = self.store.take(self.controller, submission, nonce, old_instance)
        self.assertEqual(replay["taken_at"], first["taken_at"])
        self.assertEqual(replay["expires_at"], first["expires_at"])
        self.assertEqual(replay["instance"], old_instance)
        with self.assertRaisesRegex(a.BridgeError, "proposal_taken"):
            self.take(submission)  # different nonce
        self.reopen()
        self.assertNotEqual(self.store.instance, old_instance)
        after = self.store.take(self.controller, submission, nonce, self.store.instance)
        self.assertEqual(after["taken_at"], first["taken_at"])  # stored facts survive restart
        self.assertEqual(after["instance"], self.store.instance)  # current instance, no contradiction
        with self.assertRaisesRegex(a.BridgeError, "instance_changed"):
            self.store.take(self.controller, submission, uuid.uuid4().hex, old_instance)
        fresh = self.submit()
        with self.assertRaisesRegex(a.BridgeError, "instance_changed"):
            self.store.take(self.controller, fresh, uuid.uuid4().hex, "f" * 32)
        self.assertEqual(self.status(fresh)["state"], "ACCEPTED")  # fail-closed, no side effect

    def test_unknown_and_expired_are_not_actionable_but_recordable(self):
        submission = self.submit()
        self.store.execute("UPDATE proposals SET state='UNKNOWN' WHERE id=?", (submission,))
        with self.assertRaisesRegex(a.BridgeError, "proposal_unknown"):
            self.take(submission)
        self.assertEqual(self.store.withdraw(submission)["state"], "RECORDED")
        row = self.status(submission)
        self.assertEqual(row["state"], "UNKNOWN")
        self.assertIsNotNone(row["withdraw_requested_at"])
        self.assertIsNone(row["withdrawn_at"])
        other = self.submit()
        self.now += a.BRIDGE_RETENTION + 1
        self.assertEqual(self.store.withdraw(other)["state"], "RECORDED")  # answer never leaks
        with self.assertRaisesRegex(a.BridgeError, "submission_unavailable"):
            self.status(other)
        with self.assertRaisesRegex(a.BridgeError, "submission_expired"):
            self.store.take(self.controller, other, uuid.uuid4().hex, self.store.instance)

    def test_bridge_restart_starts_new_cycle_without_reanimating_old_states(self):
        store = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now,
                              new_cycle=True)
        controller, cid = store.issue("CONTROLLER")
        ai, aid = store.issue("AI")
        waiting = store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        taken = store.submit({"request_id": uuid.uuid4().hex, "text": "printf x"})["submission_id"]
        store.take(controller, taken, uuid.uuid4().hex, store.instance)
        withdrawn = store.submit({"request_id": uuid.uuid4().hex, "text": "printf y"})["submission_id"]
        store.withdraw(withdrawn)
        delivered_cursor = store.inbox(controller, "")["cursor"]
        store.approved_output({"version": 1, "conversation": self.conversation,
                               "idempotency_key": uuid.uuid4().hex, "text": "KEPT OUTPUT",
                               "submission_id": taken, "approved_at": self.now})
        code_before, instance_before = store.chat_binding["code"], store.instance
        store.close()
        restarted = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now,
                                  new_cycle=True)
        self.addCleanup(restarted.close)
        self.assertNotEqual(restarted.instance, instance_before)
        # Old actionable cycle states are terminally unknown, never re-delivered or takeable.
        self.assertEqual(restarted.submission_status(waiting)["state"], "UNKNOWN")
        self.assertEqual(restarted.submission_status(taken)["state"], "UNKNOWN")
        with self.assertRaisesRegex(a.BridgeError, "proposal_unknown"):
            restarted.take(controller, waiting, uuid.uuid4().hex, restarted.instance)
        with self.assertRaisesRegex(a.BridgeError, "invalid_cursor"):
            restarted.inbox(controller, delivered_cursor)
        # Terminal facts and durable data survive the cycle boundary.
        row = restarted.execute("SELECT state, withdrawn_at FROM proposals WHERE id=?",
                                (withdrawn,)).fetchone()
        self.assertEqual(row[0], "WITHDRAWN")
        self.assertIsNotNone(row[1])
        self.assertEqual(restarted.chat_binding["code"], code_before)
        self.assertEqual(restarted.authenticate(controller, "CONTROLLER")["id"], cid)
        named = restarted.ai_output(restarted.authenticate(ai, "AI"),
                                    {"submission_id": taken})["outputs"]
        self.assertEqual(len(named), 1)
        # A fresh cycle proposal is fully actionable; utility reopen never wipes.
        fresh = restarted.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        utility = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now)
        utility.close()
        self.assertEqual(restarted.submission_status(fresh)["state"], "ACCEPTED")
        batch = restarted.inbox(controller, "")
        self.assertEqual([m["id"] for m in batch["messages"]], [fresh])
        self.assertEqual(restarted.take(controller, fresh, uuid.uuid4().hex,
                                        restarted.instance)["state"], "TAKEN")

    def test_cycle_init_is_atomic_and_crash_safe(self):
        store = a.BridgeStore(self.temp.name, self.conversation, clock=lambda: self.now,
                              new_cycle=True)
        waiting = store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        conversation = store.conversation
        store.close()
        calls = {"n": 0}
        def bad_clock():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash inside the init transaction")
            return self.now
        with self.assertRaises(RuntimeError):
            a.BridgeStore(self.temp.name, conversation, clock=bad_clock, new_cycle=True)
        probe = sqlite3.connect(Path(self.temp.name, "bridge.sqlite3"))
        state = probe.execute("SELECT state FROM proposals WHERE id=?", (waiting,)).fetchone()[0]
        probe.close()
        self.assertEqual(state, "WAITING")  # rollback, no partially applied cycle state
        reopened = a.BridgeStore(self.temp.name, conversation, clock=lambda: self.now,
                                 new_cycle=True)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.submission_status(waiting)["state"], "UNKNOWN")

    def test_legacy_database_gains_schema_and_cycle_boundary_on_serving_start(self):
        first, second = self.submit("true"), self.submit("printf x")
        delivered = self.store.inbox(self.controller, "")
        self.assertEqual(delivered["messages"][0]["id"], first)
        path = Path(self.temp.name, "bridge.sqlite3")
        conversation = self.store.conversation
        self.store.close()
        legacy = sqlite3.connect(path, isolation_level=None)
        legacy.execute("DROP INDEX IF EXISTS proposals_take_idem")
        for column in ("state", "taken_at", "take_request_id", "terminal_sent_at",
                       "output_reviewed_at", "withdraw_requested_at", "withdrawn_at",
                       "lifecycle_updated_at"):
            legacy.execute("ALTER TABLE proposals DROP COLUMN " + column)
        legacy.execute("DELETE FROM meta WHERE key='bridge_cycle'")
        legacy.close()
        reopened = a.BridgeStore(self.temp.name, conversation, clock=lambda: self.now,
                                 new_cycle=True)
        self.addCleanup(reopened.close)
        # Serving start on a pre-lifecycle database: schema healed AND no old state
        # stays actionable (the abandoned delivered-cursor backfill is not needed).
        self.assertEqual(reopened.submission_status(first)["state"], "UNKNOWN")
        self.assertEqual(reopened.submission_status(second)["state"], "UNKNOWN")
        with self.assertRaisesRegex(a.BridgeError, "proposal_unknown"):
            reopened.take(self.controller, second, uuid.uuid4().hex, reopened.instance)
        self.assertEqual(reopened.inbox(self.controller, "")["messages"], [])

    def test_observation_guard_first_write_wins_and_server_time_authority(self):
        submission = self.submit()
        body = {"version": 1, "submission_id": submission, "kind": "TERMINAL_SENT",
                "observed_at": self.now, "observation_request_id": uuid.uuid4().hex}
        with self.assertRaisesRegex(a.BridgeError, "proposal_not_taken"):
            self.store.observe(self.controller, body)  # WAITING never accepts observations
        self.take(submission)
        self.now += 5
        stored = self.store.observe(self.controller, dict(body, observed_at=self.now - 2))
        self.assertEqual(stored["state"], "TAKEN")
        row = self.status(submission)
        self.assertEqual(row["terminal_sent_at"], self.now)  # server clock, not the client hint
        for _ in range(2):
            self.store.observe(self.controller, dict(body, observation_request_id=uuid.uuid4().hex))
        self.assertEqual(self.status(submission)["terminal_sent_at"], self.now)  # first-write-wins
        for bad in (self.now - a.BRIDGE_RETENTION - 10, self.now + 400):
            with self.assertRaisesRegex(a.BridgeError, "invalid_schema"):
                self.store.observe(self.controller, dict(body, observed_at=bad))
        columns = {c[1] for c in self.store.execute("PRAGMA table_info(proposals)")}
        self.assertNotIn("observation_request_id", columns)  # N5: nonce deliberately not persisted
        reviewed = dict(body, kind="OUTPUT_REVIEWED", observed_at=self.now)
        self.store.observe(self.controller, reviewed)
        self.assertIsNotNone(self.status(submission)["output_reviewed_at"])

    def test_inbox_filter_and_waiting_only_quota(self):
        first, second = self.submit("true"), self.submit("printf x")
        self.store.withdraw(first)
        batch = self.store.inbox(self.controller, "")
        self.assertEqual([m["id"] for m in batch["messages"]], [second])  # withdrawn never delivered
        self.take(second)
        self.assertEqual(self.store.inbox(self.controller, batch["cursor"])["messages"], [])
        ids = [self.submit() for _ in range(20)]
        with self.assertRaisesRegex(a.BridgeError, "inbox_full"):
            self.submit()
        self.store.withdraw(ids[0])
        self.submit()  # withdrawn frees waiting quota

    def test_shared_ever_survives_completion_ack_and_retention_is_honest(self):
        submission = self.submit()
        self.take(submission)
        value = {"version": 1, "conversation": self.conversation, "idempotency_key": uuid.uuid4().hex,
                 "text": "HUMAN APPROVED", "submission_id": submission, "approved_at": self.now}
        self.store.approved_output(value)
        before = self.status(submission)
        self.assertTrue(before["approved_output_available"])
        self.assertTrue(before["output_shared_ever"])
        self.store.execute("UPDATE outputs SET delivered=1, delivered_at=? WHERE submission=?",
                           (self.now, submission))  # completion ACK flip
        after = self.status(submission)
        self.assertFalse(after["approved_output_available"])
        self.assertTrue(after["output_shared_ever"])  # permanent fact, read-side only
        self.store.execute("DELETE FROM outputs")     # retention expiry
        self.assertFalse(self.status(submission)["output_shared_ever"])
        unbound = {"version": 1, "conversation": self.conversation, "idempotency_key": uuid.uuid4().hex,
                   "text": "UNBOUND", "submission_id": None, "approved_at": self.now}
        self.store.approved_output(unbound)
        self.assertFalse(self.status(submission)["output_shared_ever"])  # unbound never attributed
        allowed = {"state", "approved_output_available", "output_shared_ever", "expires_at",
                   "server_time", "lifecycle_changed_at", "taken_at", "terminal_sent_at",
                   "output_reviewed_at", "withdraw_requested_at", "withdrawn_at", "generation"}
        self.assertEqual(set(self.status(submission)), allowed)
        self.assertNotIn("instance", self.status(submission))

    def test_take_rejection_uses_fixed_error_envelope(self):
        submission = self.submit()
        self.store.withdraw(submission)
        service = a.BridgeService(self.store)
        handler = type("_HTake", (a.BridgeRequestHandler,), {"service": service, "kind": "CONTROLLER"})
        server = a.BridgeHTTPServer(("127.0.0.1", 0), handler)
        service.controller_hosts.add("127.0.0.1:%d" % server.socket.getsockname()[1])
        service.start()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (service.stop(), server.shutdown(), server.server_close()))
        profile = a.ConnectionProfile("http://127.0.0.1:%d" % server.socket.getsockname()[1], None,
                                      self.conversation, self.cid, self.controller, "LOCAL")
        status, raw = request(profile.url, "POST", "/v1/proposal/take",
                              {"version": 1, "submission_id": submission,
                               "take_request_id": uuid.uuid4().hex,
                               "expected_instance": self.store.instance},
                              {"Authorization": "Bearer " + self.controller})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(raw), {"error": "proposal_withdrawn"})


class MCPWithdrawTests(unittest.TestCase):
    def setUp(self):
        self.process = a.LocalBridgeProcess()

    def tearDown(self):
        self.process.close()

    def raw_call(self, name, args, token=None):
        value = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": name, "arguments": dict(args, conversation=self.process.chat_code)}}
        status, raw = request(self.process.mcp_url, "POST", body=value,
                              headers={"X-AITL-AI-Key": token or self.process.ai_token})
        self.assertEqual(status, 200)
        return json.loads(raw)["result"]

    def test_withdraw_is_recorded_only_and_status_is_authoritative(self):
        created = mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        result = self.raw_call("withdraw_proposal", {"submission_id": submission})
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"submission_id": submission, "state": "RECORDED"})
        status = mcp(self.process, "get_submission_status", {"submission_id": submission})
        self.assertEqual(status["state"], "WITHDRAWN")
        self.assertIsNotNone(status["withdrawn_at"])
        self.assertEqual(self.raw_call("withdraw_proposal", {"submission_id": submission})[
            "structuredContent"]["state"], "RECORDED")  # replay identical, still no success claim
        unknown = self.raw_call("withdraw_proposal", {"submission_id": "u" * 32})
        self.assertEqual(unknown["structuredContent"]["state"], "RECORDED")  # no enumeration oracle
        missing = self.raw_call("get_submission_status", {"submission_id": "u" * 32})
        self.assertTrue(missing["isError"])
        self.assertEqual(missing["structuredContent"]["error"], "submission_unavailable")
        bad_binding = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "withdraw_proposal",
                                  "arguments": {"submission_id": submission, "conversation": "WRONG0000"}}}
        status_code, raw = request(self.process.mcp_url, "POST", body=bad_binding,
                                   headers={"X-AITL-AI-Key": self.process.ai_token})
        self.assertEqual(status_code, 200)
        self.assertTrue(json.loads(raw)["result"]["isError"])

    def test_status_leaks_no_payload_and_lists_no_ids(self):
        created = mcp(self.process, "submit_proposal",
                      {"request_id": uuid.uuid4().hex, "text": "printf 'SECRET_CANARY'"})
        status = mcp(self.process, "get_submission_status",
                     {"submission_id": created["submission_id"]})
        blob = json.dumps(status)
        self.assertNotIn("SECRET_CANARY", blob)
        self.assertNotIn("instance", status)
        self.assertNotIn(self.process.profile.conversation, blob)
        self.assertEqual(status["state"], "ACCEPTED")


class ControllerTakeFlowTests(unittest.TestCase):
    """Async take handshake, discard/invalidation, cache-pause mandatory case, §13 stage machine."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-w2-flow-")
        self.fixture = a.IntegrationFixture(self.temp.name)
        self.core = self.fixture.core
        self.core.connect_local_bridge()
        self.fixture.wait(lambda: self.core.bridge_state == "CONNECTED", timeout=6)
        self.process = self.core.bridge_process

    def tearDown(self):
        self.fixture.close()
        self.temp.cleanup()

    def submit(self, content):
        item = mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex, "text": content})
        self.fixture.wait(lambda: bool(self.core.inbox), timeout=6)
        return item["submission_id"]

    def inject(self, kind, value):
        self.core.bridge_worker.events.put((self.core.worker_id, kind, value))
        self.core.pump()

    def test_take_pending_then_ack_builds_review_and_resumes_poll(self):
        submission = self.submit("printf 'ASYNC_TAKE\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.assertEqual(self.core.review_state, "TAKE_PENDING")
        self.assertIsNone(self.core.review)
        self.assertEqual(self.core.pending_take["submission_id"], submission)
        with self.assertRaisesRegex(a.ProbeError, "stage_conflict"):
            self.core.review_pending_proposal()  # second take guarded before any network send
        self.fixture.wait(lambda: self.core.review is not None and self.core.review_state == "REVIEW",
                          timeout=6)
        review = self.core.review
        self.assertEqual(review.proposal_id, submission)
        self.assertIsNone(self.core.pending_take)
        self.assertFalse(self.core.inbox)
        self.fixture.wait(lambda: self.core.bridge_worker.poll_enabled, timeout=6)
        self.assertEqual(mcp(self.process, "get_submission_status", {"submission_id": submission})[
            "state"], "TAKEN")
        self.core.reject(review.id)

    def test_pending_discard_restores_prior_state_and_late_ack_is_ignored(self):
        submission = self.submit("true")
        self.core.review_proposal(submission)
        nonce = self.core.pending_take["take_request_id"]
        self.core.discard_pending_take()
        self.assertEqual(self.core.review_state, "EMPTY")
        self.assertIsNone(self.core.pending_take)
        with self.assertRaisesRegex(a.ProbeError, "review_not_active"):
            self.core.discard_pending_take()
        self.inject("take_result", {"status": "taken", "submission_id": submission,
                                    "take_request_id": nonce, "instance": self.core.bridge_instance,
                                    "taken_at": time.time(), "expires_at": time.time() + 60})
        self.assertIsNone(self.core.review)  # no phantom review from a discarded nonce
        self.assertEqual(self.core.review_state, "EMPTY")
        # The bridge fact stands (no untake): orphan documented, per-ID status honest.
        self.fixture.wait(lambda: mcp(self.process, "get_submission_status",
                                      {"submission_id": submission})["state"] == "TAKEN", timeout=6)

    def test_benign_withdrawn_rejection_is_nonfatal_and_invalidates_cache(self):
        submission = self.submit(": > w2-benign-marker")
        self.assertEqual(mcp(self.process, "withdraw_proposal", {"submission_id": submission})[
            "state"], "RECORDED")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "EMPTY"
                          and self.core.pending_take is None, timeout=6)
        self.assertEqual(self.core.bridge_state, "CONNECTED")  # never BLOCKED by a benign 409
        self.assertFalse(self.core.inbox)                      # withdrawn cache entry dropped
        self.assertIsNone(self.core.review)
        self.assertFalse(Path(self.temp.name, "w2-benign-marker").exists())
        later = self.submit("true")  # poll continued
        self.assertEqual(mcp(self.process, "get_submission_status", {"submission_id": later})[
            "state"], "ACCEPTED")
        self.core.remove_proposal(later)

    def test_cache_poll_pause_mandatory_case_keeps_review_b_untouched(self):
        first = self.submit("printf 'B_FIRST\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        review_b = self.core.review
        item = mcp(self.process, "submit_proposal", {"request_id": uuid.uuid4().hex,
                                                     "text": "printf 'A_CACHED\\n'"})
        second = item["submission_id"]
        self.fixture.wait(lambda: second in self.core.inbox, timeout=6)
        self.assertFalse(self.core.bridge_worker.poll_enabled)  # poll paused while cached
        self.assertEqual(mcp(self.process, "withdraw_proposal", {"submission_id": second})[
            "state"], "RECORDED")
        with self.assertRaisesRegex(a.ProbeError, "stage_conflict"):
            self.core.review_pending_proposal()  # initiation barred while B is in review
        self.assertEqual(self.core.review, review_b)
        self.assertEqual(self.core.review_state, "REVIEW")
        self.core.reject(review_b.id)  # human frees the stage explicitly
        self.assertEqual(self.core.review_state, "REJECTED")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REJECTED"
                          and self.core.pending_take is None, timeout=6)
        self.assertEqual(self.core.review, review_b)  # prior state and object restored exactly
        self.assertNotIn(second, self.core.inbox)     # bound rejection invalidated the cache
        self.assertEqual(self.core.bridge_state, "CONNECTED")
        self.assertEqual(mcp(self.process, "get_submission_status", {"submission_id": second})[
            "state"], "WITHDRAWN")

    def test_disconnect_during_pending_discards_without_restore(self):
        submission = self.submit("true")
        self.core.review_proposal(submission)
        self.core.bridge_worker.emit("disconnected", ("network_unavailable", True))
        self.core.pump()
        self.assertIsNone(self.core.pending_take)
        self.assertEqual(self.core.review_state, "EMPTY")
        self.assertIn(self.core.bridge_state, {"RETRYING", "CONNECTED", "BLOCKED"})

    def test_open_return_blocks_send_until_waiver_and_park_resume_keeps_identity(self):
        first = self.submit("printf 'RETURN_FIRST\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        review_a = self.core.review
        self.core.approve(review_a.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(review_a.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        self.assertIsNotNone(self.core.open_return)
        self.assertEqual(self.core.open_return["submission_id"], first)
        self.assertEqual(self.core.open_return["return_state"], "offen_sammelnd")
        second = self.submit("printf 'SEND_BLOCKED\\n'")
        self.assertIsNone(self.core.review_pending_proposal())  # takeover allowed, stage free
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        review_b = self.core.review
        with self.assertRaisesRegex(a.ProbeError, "stage_conflict"):
            self.core.approve(review_b.id)  # send barrier while the return is open
        with self.assertRaisesRegex(a.ProbeError, "invalid_conflict_decision"):
            self.core.resolve_stage_conflict("SEND_ANYWAY")
        info = self.core.stage_conflict_info()
        self.assertEqual(info["direction"], "proposal_in_stage")
        # Park B (dialog option 2): lossless holding, bridge row stays TAKEN.
        self.core.resolve_stage_conflict("DISCARD_PROPOSAL_KEEP_RETURN")
        self.assertIsNotNone(self.core.staged_handoff)
        self.assertEqual(self.core.review_state, "EMPTY")
        self.assertIsNotNone(self.core.open_return)
        taken_before = mcp(self.process, "get_submission_status", {"submission_id": second})
        resumed = self.core.resume_staged_proposal()
        self.assertEqual(resumed.id, review_b.id)  # identical review, no second take
        self.assertEqual(self.core.review_state, "REVIEW")
        taken_after = mcp(self.process, "get_submission_status", {"submission_id": second})
        self.assertEqual(taken_after["taken_at"], taken_before["taken_at"])
        # Cancel is a no-op.
        before = (self.core.review_state, self.core.open_return and self.core.open_return["return_state"])
        self.core.resolve_stage_conflict("CANCEL")
        self.assertEqual(before, (self.core.review_state,
                                  self.core.open_return and self.core.open_return["return_state"]))
        # Waiver via the conflict decision closes ONLY the return, then sends B.
        self.core.resolve_stage_conflict("CLOSE_WITHOUT_RETURN_AND_SEND")
        self.assertIsNone(self.core.open_return)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(self.core.review.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        first_status = mcp(self.process, "get_submission_status", {"submission_id": first})
        self.assertEqual(first_status["state"], "TAKEN")
        self.assertIsNotNone(first_status["terminal_sent_at"])
        self.assertFalse(first_status["output_shared_ever"])  # waived: never shared
        self.assertFalse(Path(self.temp.name, "SEND_BLOCKED").exists())

    def test_return_review_bidirectional_and_capture_identity(self):
        first = self.submit("printf 'CAPTURE_IDENTITY\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        self.core.approve(self.core.review.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(self.core.review.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED"
                          and b"CAPTURE_IDENTITY" in self.core.output.data)
        # The return review enters the free stage directly (no conflict yet).
        capture = self.core.take_return_review()
        self.assertEqual(self.core.review_state, "REVIEW")
        self.assertEqual(self.core.open_return["return_state"], "in_stage")
        self.assertIn(b"CAPTURE_IDENTITY", capture.payload)
        # Direction 2: proposal takeover from the active return review keeps it open.
        second = self.submit("printf 'STAGED_SECOND\\n'")
        with self.assertRaisesRegex(a.ProbeError, "stage_conflict"):
            self.core.review_pending_proposal()
        self.assertEqual(self.core.stage_conflict_info()["direction"], "return_in_stage")
        self.core.resolve_stage_conflict("LEAVE_RETURN_TAKE_PROPOSAL")
        self.assertEqual(self.core.review_state, "TAKE_PENDING")
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        self.assertEqual(self.core.review.proposal_id, second)
        self.assertIsNotNone(self.core.open_return)  # A stays open and attributable
        self.assertEqual(self.core.open_return["return_state"], "reviewbereit")
        # Direction 1: return review requested while the proposal occupies the stage.
        self.assertEqual(self.core.stage_conflict_info()["direction"], "proposal_in_stage")
        capture2 = self.core.resolve_stage_conflict("DISCARD_PROPOSAL_TAKE_RETURN")
        self.assertEqual(capture2.direction, "TO_OUTPUT_SINK")
        self.assertEqual(self.core.open_return["return_state"], "in_stage")
        self.assertIsNotNone(self.core.staged_handoff)
        # Decision #58: rejecting the staged return is the SAME completion as the waiver.
        self.core.reject(self.core.review.id)
        self.assertIsNone(self.core.open_return)
        self.assertEqual(self.core.review_state, "REJECTED")
        # The parked proposal is resumable without a second bridge take.
        resumed = self.core.resume_staged_proposal()
        self.assertEqual(resumed.proposal_id, second)
        self.assertEqual(self.core.review_state, "REVIEW")

    def test_uncertain_transfer_blocks_new_send_until_explicit_confirmation(self):
        first = self.submit("printf 'UNCERTAIN_A\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        review_a = self.core.review
        with mock.patch.object(self.core.channel, "send", side_effect=OSError("link down")):
            with self.assertRaises(a.ProbeError):
                self.core.approve(review_a.id)
        self.assertEqual(self.core.review_state, "TRANSFER_UNCERTAIN")
        fact = self.core.uncertain_transfer
        self.assertIsNotNone(fact)
        self.assertEqual(fact["command_review_id"], review_a.id)
        self.assertEqual(fact["submission_id"], first)
        self.assertFalse(fact["operator_acknowledged"])
        # Stage change is allowed; the fact survives it (B1: never forgotten).
        self.submit("printf 'UNCERTAIN_B\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        review_b = self.core.review
        self.assertIs(self.core.uncertain_transfer, fact)
        sends = []
        with mock.patch.object(self.core.channel, "send", side_effect=lambda value: sends.append(value)):
            with self.assertRaisesRegex(a.ProbeError, "transfer_uncertain_conflict"):
                self.core.approve(review_b.id)
            self.assertEqual(sends, [])  # nothing reached the terminal
        self.assertFalse(self.core.uncertain_transfer["operator_acknowledged"])  # neutral
        self.core.confirm_uncertain_send()
        self.assertTrue(self.core.uncertain_transfer["operator_acknowledged"])
        self.core.approve(review_b.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(review_b.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED")
        # A stays uncertain forever: never relabeled, no terminal-sent fact on the bridge.
        self.assertEqual(self.core.uncertain_transfer["command_review_id"], review_a.id)
        self.assertEqual(self.core.uncertain_transfer["uncertain_at"], fact["uncertain_at"])
        self.assertTrue(self.core.uncertain_transfer["operator_acknowledged"])
        status = mcp(self.process, "get_submission_status", {"submission_id": first})
        self.assertEqual(status["state"], "TAKEN")
        self.assertIsNone(status["terminal_sent_at"])

    def test_note_output_binding_is_deliberate_only(self):
        first = self.submit("printf 'OBSERVE_BIND\\n'")
        self.assertIsNone(self.core.review_pending_proposal())
        self.fixture.wait(lambda: self.core.review_state == "REVIEW", timeout=6)
        self.core.approve(self.core.review.id)
        self.fixture.wait(lambda: self.core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
        if self.core.review_state == "OVERRIDE_REQUIRED":
            self.core.approve(self.core.review.id, override=True)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED"
                          and b"OBSERVE_BIND" in self.core.output.data)
        output = self.core.select_current_output()
        with self.assertRaisesRegex(a.ProbeError, "unknown_output_binding"):
            self.core.note_output_binding(output.id, "e" * 32)
        self.core.note_output_binding(output.id, first)
        self.fixture.wait(lambda: mcp(self.process, "get_submission_status",
                                      {"submission_id": first})["output_reviewed_at"] is not None,
                          timeout=6)
        self.core.approve(output.id, submission_id=first, explicit_binding=True)
        self.fixture.wait(lambda: self.core.review_state == "ACKNOWLEDGED", timeout=6)
        status = mcp(self.process, "get_submission_status", {"submission_id": first})
        self.assertTrue(status["output_shared_ever"])


class RemoteFixture:
    def __init__(self, directory, port=None):
        port_args = [] if port is None else ["--port", str(port)]
        self.process = subprocess.Popen([sys.executable, "-I", str(Path(a.__file__).resolve()), "--bridge",
                                         "--state-dir", str(directory), "--tls-name", "127.0.0.1", "--pair", *port_args],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env=a.isolated_service_environment(), close_fds=True)
        try:
            def line():
                deadline = time.monotonic() + 6
                raw = bytearray()
                while not raw.endswith(b"\n"):
                    a.require(time.monotonic() < deadline and self.process.poll() is None, "remote_start_failed")
                    if select.select([self.process.stdout], [], [], 0.05)[0]:
                        chunk = os.read(self.process.stdout.fileno(), 1)
                        a.require(bool(chunk), "remote_start_failed")
                        raw.extend(chunk)
                return raw.decode()
            value = json.loads(line())
            self.url = "https://127.0.0.1:" + str(value["port"])
            self.pin = value["pin"]
            # M9: the guided console may show usable URLs and the SPKI pin before
            # the pairing code; consume a bounded number of informational lines.
            pair_line = line()
            for _ in range(32):
                if pair_line.startswith("PAIR CODE"):
                    break
                pair_line = line()
            a.require(pair_line.startswith("PAIR CODE"), "remote_start_failed")
            self.code = pair_line.split(": ", 1)[1].strip()
            # 0.9.4: the bridge prints secret-free progress lines later; drain the
            # pipe continuously so the fixture can never block on a full buffer.
            self.reader = threading.Thread(target=self._drain, daemon=True)
            self.reader.start()
        except BaseException:
            self.close()
            raise

    def _drain(self):
        try:
            while self.process.stdout.read(4096):
                pass
        except (OSError, ValueError):
            pass

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        try:
            self.process.stdout.close()
        except (OSError, ValueError):
            pass
        reader = getattr(self, "reader", None)
        if reader is not None:
            reader.join(timeout=1)


class TLSPairingTests(unittest.TestCase):
    def test_saved_connection_recovers_lost_confirm_without_new_claim(self):
        with tempfile.TemporaryDirectory(prefix="aitl-confirm-loss-") as directory:
            bridge = RemoteFixture(Path(directory, "bridge"))
            self.addCleanup(bridge.close)
            store = a.ConnectionStore(Path(directory, "controller"))
            core = a.AppCore(connection_store=store)
            self.addCleanup(core.close)
            original = a.BridgeHTTP.request
            calls = []
            lost = False
            def request(client, method, path, *args, **kwargs):
                nonlocal lost
                calls.append(path)
                result = original(client, method, path, *args, **kwargs)
                if path == "/v1/pair/confirm" and not lost:
                    lost = True
                    raise a.TransportError("network_unavailable", True)
                return result
            with mock.patch.object(a.BridgeHTTP, "request", request):
                with self.assertRaises(a.TransportError):
                    core.pair_remote(bridge.url, bridge.pin, bridge.code)
                self.assertIsNone(core.saved_connection)
                saved = store.load_connection()["profile"]
                core.connect_saved_bridge()
                deadline = time.monotonic() + 6
                while core.bridge_state != "CONNECTED" and time.monotonic() < deadline:
                    core.pump()
                    time.sleep(0.01)
                self.assertEqual(core.bridge_state, "CONNECTED")
                self.assertEqual(core.bridge_profile.token, saved["token"])
                self.assertEqual(calls.count("/v1/pair/claim"), 1)
                self.assertGreaterEqual(calls.count("/v1/pair/confirm"), 2)
                self.assertIsNone(core.bridge_process)

    def test_certificate_renewal_keeps_spki_identity(self):
        with tempfile.TemporaryDirectory(prefix="aitl-renew-cert-") as directory:
            _, pin = a.bridge_certificate(directory, ["127.0.0.1"])
            old = Path(directory, "tls-cert.pem").read_bytes()
            _, renewed_pin = a.bridge_certificate(directory, ["127.0.0.1"], renew=True)
            renewed = Path(directory, "tls-cert.pem").read_bytes()
            self.assertEqual(pin, renewed_pin)
            self.assertNotEqual(old, renewed)
            der = ssl.PEM_cert_to_DER_cert(renewed.decode())
            self.assertIsNotNone(a.check_certificate(der, "127.0.0.1", pin))

    def test_real_remote_pair_persist_confirm_revoke(self):
        with tempfile.TemporaryDirectory(prefix="aitl-remote-") as directory:
            bridge_dir = Path(directory, "bridge")
            bridge = RemoteFixture(bridge_dir)
            store = a.ConnectionStore(Path(directory, "controller"))
            core = a.AppCore(connection_store=store)
            try:
                profile = core.pair_remote(bridge.url, bridge.pin, bridge.code)
                self.assertEqual(a.validate_status(a.BridgeHTTP(profile).request("GET", "/v1/status"), profile).__len__(), 32)
                self.assertEqual(store.load_connection()["profile"]["pin"], bridge.pin)
                self.assertEqual(os.stat(store.directory / "connection.json").st_mode & 0o777, 0o600)
                self.assertTrue(profile.token not in repr(profile))
                self.assertIsNone(core.bridge_process)
                with self.assertRaises(a.ProbeError):
                    core.pair_remote(bridge.url, bridge.pin, bridge.code)
                result = subprocess.run([sys.executable, "-I", str(Path(a.__file__).resolve()), "--bridge", "--state-dir", str(bridge_dir),
                                         "--revoke", profile.controller_id], capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                with self.assertRaises(a.TransportError):
                    a.BridgeHTTP(profile).request("GET", "/v1/status")
                restored = a.AppCore(connection_store=store)
                self.assertIsNone(restored.review)
                self.assertEqual(restored.bridge_state, "DISCONNECTED")
                restored.close()
            finally:
                core.close()
                bridge.close()

    def test_pinning_and_name_checked_before_any_http_bytes(self):
        with tempfile.TemporaryDirectory(prefix="aitl-tls-trap-") as directory:
            context, pin = a.bridge_certificate(directory, ["127.0.0.1"])
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(3)
            observed = []
            def serve_once():
                try:
                    sock, _ = listener.accept()
                    with context.wrap_socket(sock, server_side=True) as channel:
                        channel.settimeout(2)
                        observed.append(channel.recv(2048))
                except (OSError, ssl.SSLError):
                    observed.append(b"")
            thread = threading.Thread(target=serve_once)
            thread.start()
            profile = a.ConnectionProfile("https://127.0.0.1:" + str(listener.getsockname()[1]), "0" * 64,
                                           "1" * 32, "2" * 32, "3" * 64)
            try:
                with self.assertRaises(a.TransportError):
                    a.BridgeHTTP(profile).request("POST", "/v1/pair/claim", {"SECRET_CODE_CANARY": "do not send"}, authenticate=False)
                thread.join(timeout=4)
                self.assertFalse(thread.is_alive())
                self.assertEqual(observed, [b""])
                der = ssl.PEM_cert_to_DER_cert(Path(directory, "tls-cert.pem").read_text())
                with self.assertRaises(a.ProbeError):
                    a.check_certificate(der, "wrong.example", pin)
                self.assertIsNotNone(a.check_certificate(der, "127.0.0.1", pin))
            finally:
                listener.close()
                thread.join(timeout=4)

    def test_unsafe_saved_config_and_plaintext_remote_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = a.ConnectionStore(Path(directory, "private"))
            store.load_connection()
            path = store.directory / "connection.json"
            path.write_text('{}')
            path.chmod(0o644)
            with self.assertRaises(a.ProbeError):
                store.load_connection()
            path.unlink()
            victim = Path(directory, "victim")
            victim.write_text("untouched")
            path.symlink_to(victim)
            with self.assertRaises(a.ProbeError):
                store.load_connection()
            self.assertEqual(victim.read_text(), "untouched")
        for url in ("http://bridge.example:8443", "https://user:pass@bridge.example:8443", "https://bridge.example:8443/path"):
            with self.assertRaises(a.ProbeError):
                a.check_profile(a.ConnectionProfile(url, "0" * 64, "1" * 32, "2" * 32, "3" * 64))


class TunnelTests(unittest.TestCase):
    def test_bad_cli_arguments_never_echo_credentials(self):
        result = subprocess.run([sys.executable, "-I", a.__file__, "--bridge", "--api-key", "CLI_SECRET_CANARY_123456"],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(b"CLI_SECRET_CANARY" not in result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get("AITL_TEST_TUNNEL_BINARY"), "official client binary not supplied")
    def test_official_tunnel_forwards_full_human_controlled_round_trip(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        jobs, responses, changed = queue.Queue(), {}, threading.Condition()
        tid = "tunnel_" + "c" * 32
        class ControlPlane(BaseHTTPRequestHandler):
            def send_json(self, value, status=200):
                raw = a.net_json(value)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                if "/poll" in self.path:
                    try:
                        self.send_json({"commands": [jobs.get(timeout=.2)]})
                    except queue.Empty:
                        self.send_response(204)
                        self.end_headers()
                else:
                    self.send_json({"id": tid, "name": "local-only-test"})
            def do_POST(self):
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= a.FRAME_LIMIT:
                    self.send_response(400)
                    self.end_headers()
                    return
                value = json.loads(self.rfile.read(count))
                with changed:
                    responses[value["request_id"]] = value
                    changed.notify_all()
                self.send_json({"ok": True})
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), ControlPlane)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix="aitl-real-tunnel-chain-") as directory:
            fixture = a.IntegrationFixture(directory)
            core = fixture.core
            tunnel = None
            try:
                core.connect_local_bridge()
                fixture.wait(lambda: core.bridge_state == "CONNECTED", timeout=6)
                config = {"binary": os.environ["AITL_TEST_TUNNEL_BINARY"], "tunnel_id": tid,
                          "api_key": "SYNTHETIC_LOCAL_TUNNEL_ONLY_KEY"}
                original = subprocess.Popen
                def local_only(argv, **kwargs):
                    return original(argv + ["--control-plane.base-url", "http://127.0.0.1:" + str(server.server_port)], **kwargs)
                with mock.patch.object(a.subprocess, "Popen", local_only):
                    tunnel = a.TunnelProcess(config, core.bridge_process.mcp_url, core.bridge_process.ai_token)
                def call(name, args=None):
                    identifier = uuid.uuid4().hex
                    args = dict(args or {}) | {"conversation": core.bridge_process.chat_code}
                    payload = {"jsonrpc": "2.0", "id": identifier, "method": "tools/call",
                               "params": {"name": name, "arguments": args, "_meta": {
                                   "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                   "io.modelcontextprotocol/clientCapabilities": {}}}}
                    jobs.put({"request_id": identifier, "shard_token": "local-shard", "command_type": "jsonrpc",
                              "channel": "main", "created_at": a.datetime.now(a.timezone.utc).isoformat(),
                              "response_timeout": "30s", "headers": {"MCP-Protocol-Version": ["2026-07-28"]}, "jsonrpc": payload})
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        fixture.pump()
                        with changed:
                            if identifier in responses:
                                response = responses.pop(identifier)
                                a.require(response["resp_code"] == 200, "tunnel_forward_http_failure")
                                result = response["resp_json"]["result"]
                                a.require(not result.get("isError"), "tunnel_forward_tool_failure")
                                return result
                            changed.wait(.02)
                    raise a.ProbeError("tunnel_forward_timeout")
                response = call("submit_proposal", {"request_id": uuid.uuid4().hex,
                                                     "text": "printf 'REAL_TUNNEL_CHAIN\\n'; : > tunnel-approved-marker"})
                submission = response["structuredContent"]["submission_id"]
                fixture.wait(lambda: bool(core.inbox), timeout=6)
                self.assertFalse(Path(directory, "tunnel-approved-marker").exists())
                self.assertIsNone(core.review)
                self.assertEqual(call("get_approved_output", {"submission_id": submission})["structuredContent"]["outputs"], [])
                self.assertIsNone(core.review_pending_proposal())
                fixture.wait(lambda: core.review is not None and core.review_state == "REVIEW", timeout=6)
                review = core.review
                core.approve(review.id)
                fixture.wait(lambda: core.review_state in {"TRANSFERRED", "OVERRIDE_REQUIRED"})
                if core.review_state == "OVERRIDE_REQUIRED":
                    core.approve(review.id, True)
                fixture.wait(lambda: Path(directory, "tunnel-approved-marker").exists())
                output = core._output_review("REAL_TUNNEL_CHAIN\nChosen human disclosure.")
                core.approve(output.id)
                fixture.wait(lambda: core.review_state == "ACKNOWLEDGED", timeout=6)
                response = call("get_approved_output", {"submission_id": submission})
                entry = response["structuredContent"]["outputs"][0]
                self.assertEqual(response["content"][entry["text_content_index"]]["text"].encode(), output.payload)
            finally:
                if tunnel:
                    tunnel.close()
                fixture.close()
                server.shutdown()
                server.server_close()

    def test_private_key_files_and_no_credential_argv_environment(self):
        process = a.LocalBridgeProcess()
        with tempfile.TemporaryDirectory(prefix="aitl-fake-tunnel-") as directory:
            executable = Path(directory, "client")
            executable.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(30)\n")
            executable.chmod(0o700)
            config = {"binary": str(executable), "tunnel_id": "tunnel_" + "a" * 32, "api_key": "SYNTHETIC_TUNNEL_KEY_CANARY"}
            with mock.patch.dict(os.environ, {"SSH_AUTH_SOCK": "must-not-inherit", "CONTROL_PLANE_API_KEY": "must-not-inherit"}):
                tunnel = a.TunnelProcess(config, process.mcp_url, process.ai_token)
            try:
                self.assertTrue(config["api_key"] not in " ".join(tunnel.argv) and process.ai_token not in " ".join(tunnel.argv))
                self.assertEqual(os.stat(tunnel.directory / "api-key").st_mode & 0o777, 0o600)
                if sys.platform.startswith("linux"):
                    environ = Path("/proc", str(tunnel.process.pid), "environ").read_bytes()
                    self.assertTrue(b"CONTROL_PLANE_API_KEY" not in environ and b"SSH_AUTH_SOCK" not in environ)
                tunnel.refresh()
                self.assertEqual(tunnel.state, "RUNNING_NOT_READY")
                saved_dir = tunnel.directory
            finally:
                tunnel.close()
                process.close()
            self.assertFalse(saved_dir.exists())

    @unittest.skipUnless(os.environ.get("AITL_TEST_TUNNEL_BINARY"), "official client binary not supplied")
    def test_official_runtime_cli_start_health_and_stop_without_cloud(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class ControlPlane(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(401)
                self.end_headers()
            def do_POST(self):
                self.do_GET()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), ControlPlane)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        bridge = a.LocalBridgeProcess()
        config = {"binary": os.environ["AITL_TEST_TUNNEL_BINARY"], "tunnel_id": "tunnel_" + "b" * 32,
                  "api_key": "SYNTHETIC_LOCAL_CONTROL_PLANE_KEY"}
        real_popen = subprocess.Popen
        def local_only(argv, **kwargs):
            return real_popen(argv + ["--control-plane.base-url", "http://127.0.0.1:" + str(server.server_port)], **kwargs)
        tunnel = None
        try:
            with mock.patch.object(a.subprocess, "Popen", local_only):
                tunnel = a.TunnelProcess(config, bridge.mcp_url, bridge.ai_token)
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline and not (tunnel.directory / "health-url").exists() and tunnel.process.poll() is None:
                time.sleep(0.05)
            self.assertIsNone(tunnel.process.poll())
            self.assertTrue((tunnel.directory / "health-url").exists())
            tunnel.refresh()
            # v0.0.15 reports /readyz even when control-plane authentication fails.
            # Readiness is client-local lifecycle evidence, not a cloud round trip.
            self.assertIn(tunnel.state, {"RUNNING_NOT_READY", "READY"})
        finally:
            if tunnel:
                tunnel.close()
            bridge.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class ServiceHarness:
    """In-process bridge servers; webhook transport is a stub, no real network."""
    def __init__(self, store, controller, controller_id, ai, ai_id):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-events-")
        self.store, self.controller, self.ai = store, controller, ai
        self.ai_id, self.controller_id = ai_id, controller_id
        self.chat_code = store.chat_binding["code"]
        self.service = a.BridgeService(store)
        self.verifications, self.deliveries, self.failures = {}, {}, {}

        def webhook_call(inner, subscription, body, webhook_id=None):
            parsed = json.loads(body)
            if parsed.get("type") == "verification":
                self.verifications.setdefault(subscription["id"], []).append((subscription, parsed))
                if self.failures.get("verify"):
                    raise a.WebhookFailure(self.failures["verify"], retryable=False)
                return 200, json.dumps({"challenge": parsed["challenge"]}).encode()
            self.deliveries.setdefault(subscription["id"], []).append((subscription, parsed))
            if self.failures.get("deliver"):
                raise a.WebhookFailure(self.failures["deliver"], retryable=True)
            return 200, b""

        self.patcher = mock.patch.object(a.BridgeService, "webhook_call", webhook_call)
        self.patcher.start()

        def handler(kind):
            return type("_Harness" + kind, (a.BridgeRequestHandler,),
                        {"service": self.service, "kind": kind})
        self.controller_server = a.BridgeHTTPServer(("127.0.0.1", 0), handler("CONTROLLER"))
        self.mcp_server = a.BridgeHTTPServer(("127.0.0.1", 0), handler("MCP"))
        self.service.controller_hosts.add("127.0.0.1:%d" % self.controller_server.socket.getsockname()[1])
        self.service.mcp_hosts.add("127.0.0.1:%d" % self.mcp_server.socket.getsockname()[1])
        self.profile = a.ConnectionProfile(
            "http://127.0.0.1:%d" % self.controller_server.socket.getsockname()[1], None,
            store.conversation, controller_id, controller, "LOCAL")
        self.mcp_url = "http://127.0.0.1:%d/mcp" % self.mcp_server.socket.getsockname()[1]
        self.subscriptions = []
        self.service.start()
        self.threads = [threading.Thread(target=server.serve_forever, daemon=True)
                        for server in (self.controller_server, self.mcp_server)]
        for thread in self.threads:
            thread.start()

    def close(self):
        self.service.stop()
        for server in (self.controller_server, self.mcp_server):
            server.shutdown()
            server.server_close()
        self.patcher.stop()
        self.store.close()
        self.temp.cleanup()

    def wait(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        raise a.ProbeError("events_test_timeout")


class BridgeTunnelTests(unittest.TestCase):
    """M9: bridge-owned tunnel config/status contract, protected 0600 persistence
    and the bounded one-start lifecycle. No real client, no cloud, no secrets."""

    class FakeProcess:
        def __init__(self, exit_code=None):
            self.pid = 999999999
            self.exit_code = exit_code

        def poll(self):
            return self.exit_code

        def terminate(self):
            self.exit_code = -15

        def kill(self):
            self.exit_code = -9

        def wait(self, timeout=None):
            return self.exit_code if self.exit_code is not None else 0

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-bridge-tunnel-")
        self.addCleanup(self.temp.cleanup)
        self.tunnel_id, self.key = "tunnel_" + "b" * 32, "R" * 32

    def recorder(self):
        calls, processes = [], []
        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            processes.append(self.FakeProcess())
            return processes[-1]
        return spawn, calls, processes

    def settle(self, tunnel, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = tunnel.status()
            if status["phase"] in {"starting", "connected", "error"}:
                return status
            time.sleep(0.03)
        self.fail("tunnel setup worker did not settle")

    def live_tunnel(self, spawn, directory=None):
        tunnel = a.BridgeTunnel(directory or self.temp.name, spawn=spawn)
        tunnel._locate = lambda: "/bin/true"
        tunnel.attach(41111, Path(self.temp.name, "ai-token"))
        return tunnel

    def test_config_persistence_restart_and_key_never_leaves(self):
        spawn, calls, processes = self.recorder()
        tunnel = a.BridgeTunnel(self.temp.name, spawn=spawn)
        self.assertEqual(tunnel.status(), {"version": 1, "phase": "missing", "detail": "", "step": ""})
        tunnel = self.live_tunnel(spawn)
        tunnel.configure(self.tunnel_id, self.key)
        self.assertEqual(self.settle(tunnel)["phase"], "starting")
        self.assertEqual(len(calls), 1)
        argv = calls[0][0]
        self.assertNotIn(self.key, " ".join(argv))
        self.assertIn("file:" + str(Path(tunnel.work, "api-key")), argv)
        key_file = Path(tunnel.work, "api-key")
        self.assertEqual(key_file.read_text(), self.key)
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        stored = Path(self.temp.name, "tunnel.json")
        self.assertEqual(json.loads(stored.read_text())["runtime_key"], self.key)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.key, json.dumps(tunnel.status()))
        self.assertNotIn(self.key, repr(tunnel.status()))
        # A bridge restart re-loads the protected config and starts exactly once more.
        reloaded = a.BridgeTunnel(self.temp.name, spawn=spawn)
        self.assertEqual(reloaded.status()["phase"], "configured")
        reloaded._locate = lambda: "/bin/true"
        reloaded.attach(41111, Path(self.temp.name, "ai-token"))
        self.assertEqual(self.settle(reloaded)["phase"], "starting")
        self.assertEqual(len(calls), 2)
        # A deliberate replace stops the old process and starts the new config once.
        replacement = self.recorder()
        reloaded.spawn = replacement[0]
        reloaded.configure("tunnel_" + "c" * 32, "S" * 32)
        self.assertEqual(self.settle(reloaded)["phase"], "starting")
        self.assertEqual(len(replacement[1]), 1)
        self.assertNotIn("R" * 32, " ".join(replacement[1][0][0]))
        reloaded.close()
        tunnel.close()

    def test_health_auth_failure_transient_state_and_process_exit(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        payload = {"schema_version": 1, "component": "control-plane", "status": "ok",
                   "details": {"http_status": 401, "last_success": None, "consecutive_failures": 3}}
        class Health(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        spawn, calls, processes = self.recorder()
        tunnel = self.live_tunnel(spawn)
        tunnel.configure(self.tunnel_id, self.key)
        self.settle(tunnel)
        health = Path(tunnel.work, "health-url")
        health.write_text("http://127.0.0.1:%d" % server.server_address[1])
        os.chmod(health, 0o600)
        tunnel.checked_at = 0.0  # the observation throttle is not under test here
        status = tunnel.status()
        self.assertEqual((status["phase"], status["detail"]), ("error", "runtime_key_rejected"))
        self.assertIsNone(tunnel.process)
        # Transient provider state stays a bounded wait, never a premature claim.
        payload["details"] = {"http_status": 429, "last_success": None, "consecutive_failures": 0}
        tunnel.configure(self.tunnel_id, self.key)
        self.settle(tunnel)
        health = Path(tunnel.work, "health-url")
        health.write_text("http://127.0.0.1:%d" % server.server_address[1])
        os.chmod(health, 0o600)
        tunnel.checked_at = 0.0
        status = tunnel.status()
        self.assertEqual((status["phase"], status["detail"]), ("starting", "runtime_rate_limited"))
        # A healthy control-plane poll is the only accepted readiness evidence.
        payload["details"] = {"http_status": 200, "last_success": "2026-10-08T10:00:00Z",
                              "consecutive_failures": 0}
        tunnel.checked_at = 0.0
        self.assertEqual(tunnel.status()["phase"], "connected")
        tunnel.close()
        # An exited client is reported honestly instead of being reanimated.
        spawn2, calls2, processes2 = self.recorder()
        tunnel2 = a.BridgeTunnel(self.temp.name, spawn=spawn2)
        tunnel2._locate = lambda: "/bin/true"
        tunnel2.attach(41111, Path(self.temp.name, "ai-token"))
        tunnel2.configure(self.tunnel_id, self.key)
        self.assertEqual(self.settle(tunnel2)["phase"], "starting")
        tunnel2.tail.extend(("Runtime API key " + self.key + " rejected\nvalue " + "x" * 40 + "\n").encode())
        tunnel2.process.exit_code = 1
        tunnel2.checked_at = 0.0
        detail = tunnel2.status()["detail"]
        self.assertTrue(detail.startswith("tunnel_process_exited"))
        self.assertNotIn(self.key, detail)
        self.assertNotIn("x" * 40, detail)
        self.assertIn("credential-bearing line omitted", detail)
        self.assertIn("[REDACTED]", detail)
        tunnel2.close()

    def test_controller_only_endpoints_and_validation(self):
        with tempfile.TemporaryDirectory(prefix="aitl-tunnel-http-") as directory:
            store = a.BridgeStore(directory, uuid.uuid4().hex, clock=lambda: time.time())
            self.addCleanup(store.close)
            controller, controller_id = store.issue("CONTROLLER")
            ai, ai_id = store.issue("AI")
            harness = ServiceHarness(store, controller, controller_id, ai, ai_id)
            self.addCleanup(harness.close)
            profile = harness.profile
            self.assertEqual(a.BridgeHTTP(profile).request("GET", "/v1/tunnel/status"),
                             {"version": 1, "phase": "missing", "detail": "", "step": ""})
            self.assertEqual(request(profile.url, path="/v1/tunnel/status")[0], 401)
            self.assertEqual(request(profile.url, "PUT", path="/v1/tunnel/config",
                                     body={"version": 1, "tunnel_id": "tunnel_" + "a" * 32,
                                           "runtime_key": "k" * 16})[0], 401)
            headers = {"Authorization": "Bearer " + controller}
            for body, code in (({"version": 1, "tunnel_id": "tunnel_short", "runtime_key": "k" * 16},
                                "tunnel_config_invalid_id"),
                               ({"version": 1, "tunnel_id": "tunnel_" + "a" * 32, "runtime_key": "x"},
                                "tunnel_config_invalid_key"),
                               ({"version": 1, "tunnel_id": "tunnel_" + "a" * 32, "runtime_key": "k" * 16,
                                 "extra": 1}, "invalid_schema"),
                               ({"version": 2, "tunnel_id": "tunnel_" + "a" * 32, "runtime_key": "k" * 16},
                                "invalid_schema")):
                status, raw = request(profile.url, "PUT", path="/v1/tunnel/config", body=body, headers=headers)
                self.assertEqual((status, json.loads(raw)), (400, {"error": code}))
            value = a.BridgeHTTP(profile).request("PUT", "/v1/tunnel/config",
                                                  {"version": 1, "tunnel_id": "tunnel_" + "a" * 32,
                                                   "runtime_key": "k" * 16})
            self.assertEqual(value["phase"], "configured")
            self.assertEqual(a.BridgeHTTP(profile).request("GET", "/v1/tunnel/status")["phase"], "configured")


    def test_console_lines_are_secret_free_progress(self):
        import contextlib
        import io
        spawn, calls, processes = self.recorder()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            tunnel = self.live_tunnel(spawn)
            tunnel.configure(self.tunnel_id, self.key)
            self.settle(tunnel)
        log = buffer.getvalue()
        self.assertIn("Tunnel-Konfiguration empfangen", log)
        self.assertIn("Tunnel-Client gefunden", log)
        self.assertIn("Tunnel-Client gestartet", log)
        self.assertIn("Tunnel-Status: starting", log)
        self.assertNotIn(self.key, log)
        self.assertNotIn(self.tunnel_id, log)
        buffer2 = io.StringIO()
        with contextlib.redirect_stdout(buffer2):
            processes[-1].exit_code = 1
            tunnel.checked_at = 0.0
            tunnel.status()
        log2 = buffer2.getvalue()
        self.assertIn("Tunnel-Status: error (tunnel_process_exited)", log2)
        self.assertNotIn(self.key, log2)
        self.assertNotIn(self.tunnel_id, log2)
        tunnel.close()

    def test_console_missing_client_unsupported_platform_names_manual_guidance(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory(prefix="aitl-tunnel-nobin-") as directory:
            buffer = io.StringIO()
            with mock.patch.dict(a.BridgeTunnel.ARCHITECTURES, {}, clear=True), contextlib.redirect_stdout(buffer):
                tunnel = a.BridgeTunnel(directory)
                tunnel.attach(41111, Path(directory, "ai-token"))
                tunnel.configure("tunnel_" + "d" * 32, "K" * 32)
                status = self.settle(tunnel)
            log = buffer.getvalue()
            self.assertEqual((status["phase"], status["detail"]), ("error", "tunnel_client_unavailable"))
            self.assertIn("manuell", log)  # klare Anleitung statt stiller Auslassung
            self.assertNotIn("K" * 32, log)

    def test_console_autoinstall_attempt_is_visible_and_download_failure_is_specific(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory(prefix="aitl-tunnel-dl-") as directory:
            tunnel = a.BridgeTunnel(directory, spawn=self.recorder()[0])
            tunnel._download = lambda url, cancel: (_ for _ in ()).throw(
                a.BridgeError("tunnel_download_failed"))
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                tunnel.attach(41111, Path(directory, "ai-token"))
                tunnel.configure("tunnel_" + "d" * 32, "K" * 32)
                status = self.settle(tunnel)
            log = buffer.getvalue()
            self.assertEqual((status["phase"], status["detail"]), ("error", "tunnel_download_failed"))
            self.assertIn("Tunnel-Vorbereitung: offizielles Release von GitHub laden", log)
            self.assertIn("Tunnel-Status: error (tunnel_download_failed)", log)
            self.assertNotIn("K" * 32, log)

    def test_finds_state_dir_client_kit(self):
        from test_local_setup import fake_client
        with tempfile.TemporaryDirectory(prefix="aitl-tunnel-locate-") as directory:
            kit = Path(directory, "tunnel-client-v0.0.15-linux-amd64")
            kit.mkdir()
            binary = fake_client(kit / "tunnel-client-runtime")
            tunnel = a.BridgeTunnel(directory)
            self.assertEqual(tunnel._locate(), str(binary))


class ConsoleVisibilityTests(unittest.TestCase):
    """0.9.4: the operator console shows secret-free controller/MCP progress; the
    RemoteFixture pipe stays drained."""

    def test_mcp_and_controller_console_lines_and_fixture_drain(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory(prefix="aitl-console-http-") as directory:
            store = a.BridgeStore(directory, uuid.uuid4().hex, clock=lambda: time.time())
            self.addCleanup(store.close)
            controller, controller_id = store.issue("CONTROLLER")
            ai, ai_id = store.issue("AI")
            harness = ServiceHarness(store, controller, controller_id, ai, ai_id)
            self.addCleanup(harness.close)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                status, _raw = request(harness.mcp_url, "POST",
                                       body={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                             "params": {"protocolVersion": "2025-11-25",
                                                        "capabilities": {}, "clientInfo": {}}},
                                       headers={"X-AITL-AI-Key": ai})
                self.assertEqual(status, 200)
                status, _raw = request(harness.mcp_url, "POST",
                                       body={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
                                       headers={"X-AITL-AI-Key": "0" * 64})
                self.assertEqual(status, 401)
                status, _raw = request(harness.mcp_url, "POST",
                                       body={"jsonrpc": "2.0", "id": 3, "method": "unbekannt/80"},
                                       headers={"X-AITL-AI-Key": ai})
                self.assertEqual(status, 200)
                status, _raw = request(harness.profile.url, "POST", path="/v1/pair/confirm",
                                       body={"version": 1}, headers={"Authorization": "Bearer " + controller})
                self.assertEqual(status, 200)
            log = buffer.getvalue()
            self.assertIn("mcp: initialize beantwortet", log)
            self.assertIn("mcp: abgewiesen (unauthorized)", log)
            self.assertIn("mcp: abgewiesen (method_not_found)", log)
            self.assertNotIn("unbekannt/80", log)  # client-controlled names never reach the console
            self.assertIn("Controller-Kontakt: Kopplung bestaetigt", log)
            self.assertNotIn(ai, log)
            self.assertNotIn(controller, log)

class TunnelAutoInstallTests(unittest.TestCase):
    """0.9.5: pinned official release, integrity-checked auto-install on Linux,
    idempotent saves and clean replacement. Download is stubbed; extraction,
    permissions and the version probe run for real."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-tunnel-install-")
        self.addCleanup(self.temp.cleanup)
        import platform
        self.architecture = a.BridgeTunnel.ARCHITECTURES.get(platform.machine().lower())
        if self.architecture is None or not sys.platform.startswith("linux"):
            self.skipTest("auto-install test requires linux amd64/arm64 host")
        self.tunnel_id = "tunnel_" + "a" * 32
        self.key = "K" * 32

    def recorder(self):
        calls, processes = [], []
        def spawn(argv, **kwargs):
            calls.append((argv, kwargs))
            process = BridgeTunnelTests.FakeProcess()
            processes.append(process)
            return process
        return spawn, calls, processes

    def archive(self, version="0.0.15", extra=False):
        import hashlib
        import io
        import zipfile
        stem = "tunnel-client-runtime-" + a.BridgeTunnel.RELEASE + "-linux-" + self.architecture
        script = ("#!/bin/sh\ncase \"$*\" in\n  --version) printf '%s\\n' " + version + ";;\n"
                  "  *) exit 2;;\nesac\n")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as target:
            for name, content in (("tunnel-client-runtime", script), ("LICENSE", "L"), ("NOTICE", "N"),
                                  (stem + "-licenses.txt", "T"), (stem + ".spdx.json", "{}")):
                info = zipfile.ZipInfo(name)
                info.external_attr = ((0o100755 if name == "tunnel-client-runtime" else 0o100644) << 16)
                target.writestr(info, content)
            if extra:
                target.writestr("EXTRA", "x")
        value = buffer.getvalue()
        return value, hashlib.sha256(value).hexdigest()

    def settle(self, tunnel, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = tunnel.status()
            if status["phase"] in {"starting", "connected", "error"}:
                return status
            time.sleep(0.03)
        self.fail("tunnel setup worker did not settle")

    def test_installs_pinned_release_into_state_dir_and_starts_once(self):
        import contextlib
        import io
        archive, digest = self.archive()
        spawn, calls, processes = self.recorder()
        tunnel = a.BridgeTunnel(self.temp.name, spawn=spawn)
        urls = []
        def fake_download(url, cancel):
            urls.append(url)
            return archive
        tunnel._download = fake_download
        buffer = io.StringIO()
        with mock.patch.dict(a.BridgeTunnel.ARCHIVE_SHA256, {self.architecture: digest}),                 contextlib.redirect_stdout(buffer):
            tunnel.attach(41111, Path(self.temp.name, "ai-token"))
            tunnel.configure(self.tunnel_id, self.key)
            status = self.settle(tunnel)
        log = buffer.getvalue()
        self.assertEqual(status["phase"], "starting")
        self.assertEqual(status["step"], "wait")
        self.assertEqual(len(calls), 1)
        self.assertEqual(urls, ["https://github.com/openai/tunnel-client/releases/download/"
                               + a.BridgeTunnel.RELEASE + "/tunnel-client-runtime-" + a.BridgeTunnel.RELEASE
                               + "-linux-" + self.architecture + ".zip"])
        destination = Path(self.temp.name, "tunnel-client-" + a.BridgeTunnel.RELEASE + "-linux-" + self.architecture)
        binary = destination / "tunnel-client-runtime"
        self.assertEqual(binary.read_text().splitlines()[0], "#!/bin/sh")
        self.assertEqual(binary.stat().st_mode & 0o777, 0o700)
        self.assertEqual((destination / "LICENSE").stat().st_mode & 0o777, 0o600)
        self.assertIn("SHA-256-Prüfung gegen das gepinnte offizielle Release bestanden", log)
        self.assertIn("installiert und geprüft", log)
        self.assertNotIn(self.key, log)
        tunnel.close()

    def test_checksum_mismatch_and_unsafe_archive_are_rejected_without_executing(self):
        archive, digest = self.archive()
        wrong = archive + b"!"  # digest mismatch for the pinned value
        spawn, calls, processes = self.recorder()
        tunnel = a.BridgeTunnel(self.temp.name, spawn=spawn)
        tunnel._download = lambda url, cancel: wrong
        with mock.patch.dict(a.BridgeTunnel.ARCHIVE_SHA256, {self.architecture: digest}):
            tunnel.attach(41111, Path(self.temp.name, "ai-token"))
            tunnel.configure(self.tunnel_id, self.key)
            status = self.settle(tunnel)
        self.assertEqual(status["detail"], "tunnel_archive_checksum_mismatch")
        self.assertFalse(any(Path(self.temp.name).glob("tunnel-client-" + a.BridgeTunnel.RELEASE + "*")))
        self.assertEqual(len(calls), 0)
        # A structurally invalid member set is refused even with the right checksum.
        extra, extra_digest = self.archive(extra=True)
        spawn2, calls2, _ = self.recorder()
        tunnel2 = a.BridgeTunnel(self.temp.name, spawn=spawn2)
        tunnel2._download = lambda url, cancel: extra
        with mock.patch.dict(a.BridgeTunnel.ARCHIVE_SHA256, {self.architecture: extra_digest}):
            tunnel2.attach(41112, Path(self.temp.name, "ai-token"))
            tunnel2.configure(self.tunnel_id, self.key)
            status = self.settle(tunnel2)
        self.assertEqual(status["detail"], "tunnel_archive_unsafe")
        self.assertEqual(len(calls2), 0)

    def test_old_client_is_replaced_and_current_client_never_downloads(self):
        import platform
        stale_dir = Path(self.temp.name, "tunnel-client-old-v1")
        stale_dir.mkdir()
        stale = stale_dir / "tunnel-client-runtime"
        stale.write_text("#!/bin/sh\ncase \"$*\" in\n  --version) printf '0.0.14\\n';;\n  *) exit 2;;\nesac\n")
        stale.chmod(0o700)
        archive, digest = self.archive()
        spawn, calls, processes = self.recorder()
        tunnel = a.BridgeTunnel(self.temp.name, spawn=spawn)
        tunnel._download = lambda url, cancel: archive
        with mock.patch.dict(a.BridgeTunnel.ARCHIVE_SHA256, {self.architecture: digest}):
            tunnel.attach(41113, Path(self.temp.name, "ai-token"))
            tunnel.configure(self.tunnel_id, self.key)
            status = self.settle(tunnel)
        self.assertEqual(status["phase"], "starting")
        self.assertIn("-linux-" + self.architecture, calls[0][0][0])
        self.assertNotIn("tunnel-client-old-v1", calls[0][0][0])
        tunnel.close()
        # A current compatible client must be started directly without any download.
        good_dir = Path(self.temp.name, "tunnel-client-current")
        good_dir.mkdir()
        good = good_dir / "tunnel-client-runtime"
        good.write_text("#!/bin/sh\ncase \"$*\" in\n  --version) printf '0.0.16\\n';;\n  *) exit 2;;\nesac\n")
        good.chmod(0o700)
        spawn2, calls2, processes2 = self.recorder()
        tunnel2 = a.BridgeTunnel(self.temp.name, spawn=spawn2)
        def must_not_download(url, cancel):
            raise AssertionError("download must not run for a compatible client")
        tunnel2._download = must_not_download
        tunnel2.attach(41114, Path(self.temp.name, "ai-token"))
        tunnel2.configure(self.tunnel_id, self.key)
        self.assertEqual(self.settle(tunnel2)["phase"], "starting")
        tunnel2.close()

    def test_duplicate_save_is_idempotent_and_replacement_cancels_cleanly(self):
        archive, digest = self.archive()
        gate = threading.Event()
        downloads = []
        def slow_download(url, cancel):
            downloads.append(url)
            while not gate.wait(0.02):
                if cancel.is_set():
                    raise a.BridgeError("tunnel_setup_cancelled")
            return archive
        spawn, calls, processes = self.recorder()
        tunnel = a.BridgeTunnel(self.temp.name, spawn=spawn)
        tunnel._download = slow_download
        with mock.patch.dict(a.BridgeTunnel.ARCHIVE_SHA256, {self.architecture: digest}):
            tunnel.attach(41115, Path(self.temp.name, "ai-token"))
            tunnel.configure(self.tunnel_id, self.key)
            time.sleep(0.1)  # the worker is verifiably inside the stubbed download
            again = tunnel.configure(self.tunnel_id, self.key)  # duplicate deliberate save
            self.assertIn(again["phase"], {"installing", "configured", "starting"})
            self.assertEqual(len(downloads), 1)  # no second download, no second start
            other = "S" * 32
            tunnel._download = lambda url, cancel: archive
            tunnel.configure(self.tunnel_id, other)  # replacement cancels the stalled attempt
            gate.set()
            status = self.settle(tunnel)
        self.assertEqual(status["phase"], "starting")
        self.assertEqual(Path(tunnel.work, "api-key").read_text(), other)
        self.assertLessEqual(len(calls), 2)  # only the replacement ever spawned
        tunnel.close()

class RemoteTunnelCoordinationTests(unittest.TestCase):
    """M9 S4: Main observes and saves through the same authenticated bridge."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-tunnel-coord-")
        self.addCleanup(self.temp.cleanup)
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: time.time())
        self.addCleanup(self.store.close)
        controller, controller_id = self.store.issue("CONTROLLER")
        ai, ai_id = self.store.issue("AI")
        self.harness = ServiceHarness(self.store, controller, controller_id, ai, ai_id)
        self.addCleanup(self.harness.close)
        self.core = a.AppCore()
        self.addCleanup(self.core.close)
        self.core.bridge_profile = self.harness.profile
        self.core.bridge_state = "CONNECTED"
        self.core.bridge_instance = self.store.instance

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.core.pump()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("tunnel_coordination_timeout")

    def test_second_save_while_save_in_flight_is_rejected(self):
        self.core.remote_tunnel_busy = True
        with self.assertRaises(a.ProbeError) as caught:
            self.core.save_remote_tunnel("tunnel_" + "a" * 32, "k" * 32)
        self.assertEqual(str(caught.exception), "tunnel_config_busy")
        self.core.remote_tunnel_busy = False

    def test_probe_save_and_disconnect_clear_state(self):
        key = "k" * 32
        self.core.begin_tunnel_probe()
        self.wait(lambda: self.core.remote_tunnel is not None)
        self.assertEqual(self.core.remote_tunnel["phase"], "missing")
        probe = self.core.remote_tunnel_probe
        self.core.begin_tunnel_probe()  # idempotent per instance: kein zweiter Beobachtungsloop
        self.assertIs(self.core.remote_tunnel_probe, probe)
        self.assertEqual(self.core.bridge_snapshot().tunnel_phase, "missing")
        with self.assertRaises(a.ProbeError):
            self.core.save_remote_tunnel("not-a-tunnel", key)
        with self.assertRaises(a.ProbeError):
            self.core.save_remote_tunnel("tunnel_" + "a" * 32, "short")
        self.core.save_remote_tunnel("tunnel_" + "a" * 32, key)
        self.wait(lambda: self.core.remote_tunnel is not None
                  and self.core.remote_tunnel["phase"] == "configured")
        self.assertFalse(self.core.remote_tunnel_busy)
        self.assertNotIn(key, json.dumps(self.core.remote_tunnel))
        self.assertNotIn(key, repr(self.core.bridge_snapshot()))
        stored = Path(self.store.directory, "tunnel.json")
        self.assertEqual(json.loads(stored.read_text())["runtime_key"], key)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        self.core.disconnect_bridge()
        self.assertIsNone(self.core.remote_tunnel)
        self.assertIsNone(self.core.remote_tunnel_probe)
        self.assertIsNone(self.core.bridge_snapshot().tunnel_phase)


class EventSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-events-suite-")
        self.addCleanup(self.temp.cleanup)
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: time.time())
        self.addCleanup(self.store.close)
        controller, controller_id = self.store.issue("CONTROLLER")
        ai, ai_id = self.store.issue("AI")
        self.ai_id = ai_id
        self.harness = ServiceHarness(self.store, controller, controller_id, ai, ai_id)
        self.addCleanup(self.harness.close)
        self.secret = "whsec_" + base64.b64encode(b"x" * 24).decode()
        self.callback_url = "https://callback.example/hook"
        self.harness.service.WEBHOOK_RETRY_DELAYS = (0.01, 0.02)

    def rpc(self, method, params=None, modern=True):
        value = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method,
                 "params": dict(params) if params is not None else {}}
        if modern:
            value["params"].setdefault("_meta", {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                                 "io.modelcontextprotocol/clientCapabilities": {}})
        header = "2026-07-28" if modern else "2025-11-25"
        status, raw = request(self.harness.mcp_url, "POST", body=value,
                              headers={"X-AITL-AI-Key": self.harness.ai, "MCP-Protocol-Version": header})
        self.assertEqual(status, 200)
        return json.loads(raw)

    def subscribe(self, name=a.BRIDGE_EVENT_NAME, arguments=None,
                  url="https://callback.example/hook", secret=None, mode="webhook", ttl=None):
        delivery = {"mode": mode, "url": url, "secret": secret or self.secret}
        params = {"name": name, "delivery": delivery,
                  "arguments": dict(arguments or {}, conversation=self.harness.chat_code)}
        if ttl is not None:
            params["ttlMs"] = ttl
        return self.rpc("events/subscribe", params)

    def canonical(self, arguments):
        return json.dumps(dict(sorted(arguments.items())), separators=(",", ":"))

    def test_bridge_component_is_stdlib_only(self):
        text = Path(a.__file__).read_text(encoding="utf-8")
        block = text.split("## BEGIN AITL EMBEDDED BRIDGE SOURCE", 1)[1].split("## END AITL", 1)[0]
        self.assertNotIn("aiohttp", block)

    def test_discovery_lists_events_only_for_modern_protocol(self):
        modern = self.rpc("server/discover", {})
        self.assertIn("events", modern["result"]["capabilities"])
        definition = self.rpc("events/list")["result"]["events"][0]
        self.assertEqual(definition["name"], a.BRIDGE_EVENT_NAME)
        self.assertEqual(definition["delivery"], ["webhook"])
        self.assertIn("output_id", definition["payloadSchema"]["required"])
        self.assertIn("conversation", definition["inputSchema"]["required"])
        self.assertNotIn("conversation", definition["payloadSchema"]["properties"])
        self.assertNotIn(self.store.conversation, json.dumps(definition))
        self.assertNotIn(self.harness.chat_code, json.dumps(definition))
        self.assertEqual(self.rpc("events/list", {"cursor": "ignored"}, modern=False)["error"]["code"], -32601)

    def test_webhook_signature_helper_matches_standard_webhooks(self):
        body = b'{"eventId":"evt_1"}'
        secret = "whsec_" + base64.b64encode(b"0123456789abcdef01234567").decode()
        headers = a.standard_webhook_headers("sub_x", "evt_1", secret, body)
        key = base64.b64decode(secret[6:])
        signed = ("evt_1." + headers["webhook-timestamp"] + ".").encode() + body
        expected = "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        self.assertEqual(headers["webhook-signature"], expected)
        self.assertEqual(headers["webhook-id"], "evt_1")
        self.assertTrue(a.webhook_address_allowed("8.8.8.8"))
        for address in ("127.0.0.1", "::1", "10.0.0.5", "169.254.169.254", "0.0.0.0"):
            self.assertFalse(a.webhook_address_allowed(address))

    def test_subscribe_refresh_unsubscribe_and_persistence(self):
        result = self.subscribe()
        self.assertTrue({"id", "refreshBefore", "cursor", "truncated"}
                        <= set(result["result"]))
        identifier = result["result"]["id"]
        self.assertTrue(identifier.startswith("sub_"))
        self.assertIsNone(result["result"]["cursor"])
        self.assertEqual(len(self.harness.verifications[identifier]), 1)
        row = self.harness.store.find_subscription(self.ai_id, "https://callback.example/hook",
                                                   a.BRIDGE_EVENT_NAME, self.canonical({}))
        self.assertEqual(row["id"], identifier)
        self.assertEqual(self.subscribe()["result"]["id"], identifier)
        self.assertEqual(len(self.harness.verifications[identifier]), 1)
        filtered = self.subscribe(arguments={"submission_id": "s" * 32},
                                  url="https://callback.example/hook-s")
        self.assertNotEqual(filtered["result"]["id"], identifier)
        first = self.rpc("events/unsubscribe", {
            "name": a.BRIDGE_EVENT_NAME, "arguments": {"submission_id": "s" * 32,
                                                       "conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": "https://callback.example/hook-s"}})
        self.assertEqual({key: value for key, value in first["result"].items()
                          if key not in {"resultType", "_meta"}}, {})
        self.assertIsNone(self.harness.store.find_subscription(
            self.ai_id, "https://callback.example/hook-s", a.BRIDGE_EVENT_NAME,
            self.canonical({"submission_id": "s" * 32})))
        again = self.rpc("events/unsubscribe", {
            "name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": "https://callback.example/hook-s"}})
        self.assertEqual({key: value for key, value in again["result"].items()
                          if key not in {"resultType", "_meta"}}, {})

    def test_subscription_limit_caps_across_urls(self):
        for index in range(a.BRIDGE_EVENT_SUBSCRIPTION_LIMIT):
            self.store.store_subscription(self.ai_id, self.callback_url + str(index),
                                          a.BRIDGE_EVENT_NAME, "{}", self.secret,
                                          self.store.clock() + 600, bound=True)
        blocked = self.subscribe(url=self.callback_url)
        self.assertEqual(blocked["error"]["code"], -32013)
        self.assertEqual(self.store.count_subscriptions(self.ai_id), a.BRIDGE_EVENT_SUBSCRIPTION_LIMIT)
        # An active refresh consumes no new allocation at the limit.
        refreshed = self.subscribe(url=self.callback_url + "0")
        self.assertIn("result", refreshed)
        self.assertEqual(self.store.count_subscriptions(self.ai_id), a.BRIDGE_EVENT_SUBSCRIPTION_LIMIT)

    def test_missing_wrong_binding_cannot_subscribe_receive_or_ack(self):
        params = {"name": a.BRIDGE_EVENT_NAME,
                  "delivery": {"mode": "webhook", "url": self.callback_url, "secret": self.secret}}
        for arguments in (None, {}, {"conversation": "wrong_binding_0001"}):
            with self.subTest(arguments=arguments):
                attempt = dict(params)
                if arguments is not None:
                    attempt["arguments"] = arguments
                blocked = self.rpc("events/subscribe", attempt)
                self.assertEqual(blocked["error"]["data"]["reason"], "conversation_binding_required")
        self.assertEqual(self.store.count_subscriptions(self.ai_id), 0)
        self.assertEqual(self.harness.verifications, {})
        submission = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        output = self.store.approved_output({"version": 1, "conversation": self.store.conversation,
            "idempotency_key": uuid.uuid4().hex, "text": "BOUND_OUTPUT",
            "submission_id": submission, "approved_at": self.store.clock()})
        self.assertEqual(self.harness.service.jobs, [])
        self.assertEqual(self.harness.deliveries, {})
        self.assertTrue(self.store.submission_status(submission)["approved_output_available"])
        self.assertEqual(self.store.execute("SELECT delivered FROM outputs WHERE id=?",
                                           (output["output_id"],)).fetchone()[0], 0)
        principal = self.store.authenticate(self.harness.ai, "AI")
        self.assertEqual(self.store.ai_output(principal, {})["outputs"][0]["output_id"], output["output_id"])
        self.assertIn("result", self.subscribe(url=self.callback_url))

    def test_refresh_secret_update_and_unsubscribe_require_binding(self):
        identifier = self.subscribe(url=self.callback_url)["result"]["id"]
        before = self.store.find_subscription(self.ai_id, self.callback_url, a.BRIDGE_EVENT_NAME, "{}")
        for arguments in ({},):
            for method in ("events/subscribe", "events/unsubscribe"):
                with self.subTest(method=method, arguments=arguments):
                    delivery = {"mode": "webhook", "url": self.callback_url}
                    if method == "events/subscribe":
                        delivery["secret"] = "whsec_" + base64.b64encode(b"z" * 24).decode()
                    blocked = self.rpc(method, {"name": a.BRIDGE_EVENT_NAME,
                                               "delivery": delivery, "arguments": arguments})
                    self.assertEqual(blocked["error"]["data"]["reason"], "conversation_binding_required")
                    self.assertEqual(self.store.find_subscription(self.ai_id, self.callback_url,
                                                                  a.BRIDGE_EVENT_NAME, "{}"), before)
        removed = self.rpc("events/unsubscribe", {"name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": self.callback_url}})
        self.assertIn("result", removed)
        self.assertIsNone(self.store.active_subscription(identifier, self.store.clock()))

    def test_subscribe_validation_failures(self):
        insecure = self.subscribe(url="http://callback.example/insecure")
        self.assertEqual(insecure["error"]["code"], -32602)
        self.assertEqual(insecure["error"]["data"]["reason"], "invalid_webhook_url")
        embedded = self.subscribe(url="https://user:secret@callback.example/hook")
        self.assertEqual(embedded["error"]["data"]["reason"], "invalid_webhook_url")
        bad_secret = self.subscribe(secret="whsec_short")
        self.assertEqual(bad_secret["error"]["data"]["reason"], "invalid_webhook_secret")
        unknown = self.subscribe(name="another.event")
        self.assertEqual(unknown["error"]["code"], -32011)
        wrong_mode = self.subscribe(mode="poll")
        self.assertEqual(wrong_mode["error"]["data"]["reason"], "delivery_mode_unsupported")
        self.harness.failures["verify"] = "timeout"
        unreachable = self.subscribe(url="https://callback.example/unreachable")
        self.assertEqual(unreachable["error"]["code"], -32015)
        self.assertEqual(unreachable["error"]["data"]["reason"], "timeout")
        self.harness.failures.clear()
        recovered = self.subscribe(url="https://callback.example/recovered")
        self.assertTrue(recovered["result"]["id"].startswith("sub_"))

    def test_verification_challenge_mismatch_fails_closed(self):
        response = {"challenge": "WRONG"}

        def webhook_call(inner, subscription, body, webhook_id=None):
            return 200, json.dumps(response).encode()

        with mock.patch.object(a.BridgeService, "webhook_call", webhook_call):
            blocked = self.subscribe(url="https://callback.example/mismatch")
        self.assertEqual(blocked["error"]["code"], -32015)
        self.assertEqual(blocked["error"]["data"]["reason"], "challenge_failed")
        self.assertIsNone(self.harness.store.find_subscription(
            self.ai_id, "https://callback.example/mismatch", a.BRIDGE_EVENT_NAME, self.canonical({})))


class EventDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: time.time())
        controller, controller_id = self.store.issue("CONTROLLER")
        ai, ai_id = self.store.issue("AI")
        self.harness = ServiceHarness(self.store, controller, controller_id, ai, ai_id)
        self.addCleanup(self.harness.close)
        self.secret = "whsec_" + base64.b64encode(b"y" * 24).decode()
        self.harness.service.WEBHOOK_RETRY_DELAYS = (0.01, 0.02)
        self.subscription_id = self.subscribe()["result"]["id"]

    def rpc(self, method, params=None, modern=True):
        value = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method,
                 "params": dict(params) if params is not None else {}}
        if modern:
            value["params"].setdefault("_meta", {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                                 "io.modelcontextprotocol/clientCapabilities": {}})
        header = "2026-07-28" if modern else "2025-11-25"
        status, raw = request(self.harness.mcp_url, "POST", body=value,
                              headers={"X-AITL-AI-Key": self.harness.ai, "MCP-Protocol-Version": header})
        self.assertEqual(status, 200)
        return json.loads(raw)

    def subscribe(self, url="https://delivery.example/hook", arguments=None):
        params = {"name": a.BRIDGE_EVENT_NAME,
                  "delivery": {"mode": "webhook", "url": url, "secret": self.secret},
                  "arguments": dict(arguments or {}, conversation=self.harness.chat_code)}
        result = self.rpc("events/subscribe", params)
        if result.get("result", {}).get("id"):
            self.harness.subscriptions.append(result["result"]["id"])
        return result

    def post_output(self, submission, key=None):
        body = {"version": 1, "conversation": self.store.conversation,
                "idempotency_key": key or uuid.uuid4().hex, "text": "APPROVED_PAYLOAD",
                "submission_id": submission, "approved_at": time.time()}
        self.last_body = body
        return a.BridgeHTTP(self.harness.profile).request("POST", "/v1/approved-output", body)

    def make_submission(self):
        return self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]

    def approved_output_tool(self, arguments):
        return self.rpc("tools/call", {"name": "get_approved_output",
                                       "arguments": dict(arguments, conversation=self.harness.chat_code)})

    def test_event_only_after_human_approved_output(self):
        created = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        self.assertEqual(self.harness.deliveries.get(self.subscription_id, []), [])
        output_id = self.post_output(submission)["output_id"]
        replay = self.last_body
        self.harness.wait(lambda: self.harness.deliveries.get(self.subscription_id))
        entry = self.harness.deliveries[self.subscription_id][-1][1]
        self.assertEqual(entry["eventId"], output_id)
        self.assertEqual(entry["name"], a.BRIDGE_EVENT_NAME)
        self.assertEqual(set(entry["data"]), {"submission_id", "output_id", "expires_at"})
        self.assertEqual(entry["data"]["output_id"], output_id)
        self.assertEqual(entry["data"]["submission_id"], submission)
        self.assertNotIn(self.store.conversation, json.dumps(entry))
        self.harness.wait(lambda: self.store.submission_status(submission)["approved_output_available"] is False)
        named = self.approved_output_tool({"submission_id": submission})
        self.assertEqual(len(named["result"]["structuredContent"]["outputs"]), 1)
        general = self.approved_output_tool({})
        self.assertEqual(general["result"]["structuredContent"]["outputs"], [])
        replayed = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/approved-output", replay)
        self.assertEqual(replayed["output_id"], output_id)

    def test_filter_limits_event_per_submission(self):
        first, second = self.make_submission(), self.make_submission()
        filtered = self.subscribe(url="https://delivery.example/filtered",
                                  arguments={"submission_id": first})
        response = self.post_output(second)
        self.harness.wait(lambda: len(self.harness.deliveries.get(self.subscription_id, [])) == 1)
        self.assertEqual(len(self.harness.deliveries.get(filtered["result"]["id"], [])), 0)
        self.assertEqual(self.harness.deliveries[self.subscription_id][-1][1]["data"]["submission_id"], second)
        self.post_output(first)
        self.harness.wait(lambda: self.harness.deliveries.get(filtered["result"]["id"]))
        self.assertEqual(self.harness.deliveries[filtered["result"]["id"]][-1][1]["data"]["submission_id"], first)

    def test_unsubscribe_stops_delivery_and_pull_remains_available(self):
        created = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        gone = self.rpc("events/unsubscribe", {
            "name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": "https://delivery.example/hook"}})
        self.assertEqual({key: value for key, value in gone["result"].items()
                          if key not in {"resultType", "_meta"}}, {})
        self.post_output(submission)
        time.sleep(0.1)
        self.assertEqual(self.harness.deliveries, {})
        pulled = self.approved_output_tool({"submission_id": submission})
        self.assertEqual(len(pulled["result"]["structuredContent"]["outputs"]), 1)

    def test_failed_delivery_keeps_output_available(self):
        created = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        self.harness.failures["deliver"] = "http_5xx"
        self.post_output(submission)
        self.harness.wait(lambda: len(self.harness.deliveries.get(self.subscription_id, [])) > 1, timeout=3)
        attempts = len(self.harness.deliveries[self.subscription_id])
        self.assertEqual(self.store.submission_status(submission)["approved_output_available"], True)
        pulled = self.approved_output_tool({"submission_id": submission})
        self.assertEqual(len(pulled["result"]["structuredContent"]["outputs"]), 1)
        self.harness.failures.clear()
        later = self.make_submission()
        self.post_output(later)
        self.harness.wait(lambda: self.store.submission_status(later)["approved_output_available"] is False)
        self.assertGreaterEqual(len(self.harness.deliveries[self.subscription_id]), attempts + 1)

    def test_delivery_state_and_subscriptions_survive_restart(self):
        created = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        self.post_output(submission)
        self.harness.wait(lambda: self.store.submission_status(submission)["approved_output_available"] is False)
        with self.store.lock:
            self.store.close()
        reopened = a.BridgeStore(self.temp.name, self.store.conversation, clock=lambda: time.time())
        try:
            canonical = json.dumps({}, separators=(",", ":"))
            row = reopened.find_subscription(self.harness.ai_id, "https://delivery.example/hook",
                                             a.BRIDGE_EVENT_NAME, canonical)
            self.assertEqual(row["id"], self.subscription_id)
            self.assertEqual(reopened.submission_status(submission)["approved_output_available"], False)
            named = reopened.ai_output(reopened.authenticate(self.harness.ai, "AI"),
                                       {"submission_id": submission})
            self.assertEqual(len(named["outputs"]), 1)
        finally:
            reopened.close()

class WebhookReceiver:
    """Real TLS webhook endpoint: verifies the Standard Webhooks signature."""
    def __init__(self, secret_bytes, directory, verify_status=200):
        self.secret = secret_bytes
        self.record = []
        self.verify_status = verify_status
        self.before_ack = None
        tls, pin = a.bridge_certificate(directory, ["127.0.0.1", "callback.example"])
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                count = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(count)
                lower = {key.lower(): value for key, value in self.headers.items()}
                signed = (lower["webhook-id"] + "." + lower["webhook-timestamp"] + ".").encode() + raw
                expected = "v1," + base64.b64encode(
                    hmac.new(receiver.secret, signed, hashlib.sha256).digest()).decode()
                ok = hmac.compare_digest(lower.get("webhook-signature", ""), expected)
                receiver.record.append({"headers": lower, "body": raw, "signature_ok": ok})
                if not ok or lower.get("host") != "callback.example:%d" % receiver.port:
                    self.send_response(421)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if lower["webhook-id"].startswith("msg_verification_"):
                    response = json.dumps(json.loads(raw)).encode()
                    if receiver.verify_status != 200:
                        self.send_response(receiver.verify_status)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                else:
                    response = b""
                    if receiver.before_ack is not None:
                        receiver.before_ack()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # Expected negative TLS fixtures contain no useful traceback.

            def get_request(self):
                accepted = self.socket.accept()
                accepted = (tls.wrap_socket(accepted[0], server_side=True), accepted[1])
                accepted[0].settimeout(8)
                return accepted

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.socket.getsockname()[1]
        self.pin = pin
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class WebhookTransportTests(EventSubscriptionTests):
    """The real webhook transport path: signature, identifiers, delivery state."""
    def receiver_url(self, path="hook"):
        return "https://callback.example:%d/%s" % (self.receiver.port, path)

    def setUp(self):
        EventSubscriptionTests.setUp(self)
        # The receiver verifies signatures with the SAME secret the bridge uses.
        self.receiver = WebhookReceiver(base64.b64decode(self.secret[6:]), str(self.temp.name))
        self.addCleanup(self.receiver.close)
        self.callback_url = self.receiver_url()
        # Only local destination admission/resolution are substituted. Trust this
        # fixture certificate explicitly; hostname and certificate checks stay on.
        def synthesizing():
            return ssl.create_default_context(cafile=str(Path(self.temp.name, "tls-cert.pem")))

        self.resolver = mock.patch.dict(a._bridge_component, {
            "webhook_addresses": lambda hostname, port: ["127.0.0.1"],
            # The SSRF guard itself is covered separately with private addresses;
            # this loopback receiver needs an explicit local-target allowance.
            "webhook_address_allowed": lambda address: address == "127.0.0.1",
            "webhook_tls_context": synthesizing})
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
        # Drop the harness transport stub; the actual BridgeService.webhook_call runs.
        self.harness.patcher.stop()
        self.addCleanup(self.harness.patcher.start)

    def test_subscribe_validation_failures(self):
        insecure = self.subscribe(url="http://callback.example/insecure")
        self.assertEqual(insecure["error"]["code"], -32602)
        self.assertEqual(insecure["error"]["data"]["reason"], "invalid_webhook_url")
        embedded = self.subscribe(url="https://user:secret@callback.example/hook")
        self.assertEqual(embedded["error"]["data"]["reason"], "invalid_webhook_url")
        bad_secret = self.subscribe(secret="whsec_short")
        self.assertEqual(bad_secret["error"]["data"]["reason"], "invalid_webhook_secret")
        unknown = self.subscribe(name="another.event")
        self.assertEqual(unknown["error"]["code"], -32011)
        wrong_mode = self.subscribe(mode="poll")
        self.assertEqual(wrong_mode["error"]["data"]["reason"], "delivery_mode_unsupported")
        # Deliberately failing callback verification: point one subscribe attempt at
        # a closed loopback port so the real transport returns connection_refused.
        dead_port = self.receiver.port + 1
        while True:
            probe = socket.socket()
            try:
                probe.bind(("127.0.0.1", dead_port))
            except OSError:
                dead_port += 1
                continue
            finally:
                probe.close()
            break
        self.receiver.verify_status = 503
        blocked = self.subscribe(url=self.receiver_url("failing"))
        self.assertEqual(blocked["error"]["code"], -32015)
        self.assertEqual(blocked["error"]["data"]["reason"], "http_5xx")

    def test_subscribe_refresh_unsubscribe_and_persistence(self):
        result = self.subscribe(url=self.receiver_url())
        self.assertTrue({"id", "refreshBefore", "cursor", "truncated"}
                        <= set(result["result"]))
        identifier = result["result"]["id"]
        identifier = result["result"]["id"]
        self.assertTrue(identifier.startswith("sub_"))
        self.assertIsNone(result["result"]["cursor"])
        verification_count = len([entry for entry in self.receiver.record
                                  if entry["headers"]["webhook-id"].startswith("msg_verification_")])
        self.assertEqual(verification_count, 1)
        row = self.harness.store.find_subscription(self.ai_id, self.receiver_url(),
                                                   a.BRIDGE_EVENT_NAME, self.canonical({}))
        self.assertEqual(row["id"], identifier)
        # Idempotent refresh delivers no second challenge after the cached verify.
        self.assertEqual(self.subscribe(url=self.receiver_url())["result"]["id"], identifier)
        verification_count = len([entry for entry in self.receiver.record
                                  if entry["headers"]["webhook-id"].startswith("msg_verification_")])
        self.assertEqual(verification_count, 1)
        filtered = self.subscribe(arguments={"submission_id": "s" * 32},
                                  url=self.receiver_url("hook-s"))
        self.assertNotEqual(filtered["result"]["id"], identifier)
        first = self.rpc("events/unsubscribe", {
            "name": a.BRIDGE_EVENT_NAME, "arguments": {"submission_id": "s" * 32,
                                                       "conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": self.receiver_url("hook-s")}})
        self.assertEqual({key: value for key, value in first["result"].items()
                          if key not in {"resultType", "_meta"}}, {})
        self.assertIsNone(self.harness.store.find_subscription(
            self.ai_id, self.receiver_url("hook-s"), a.BRIDGE_EVENT_NAME,
            self.canonical({"submission_id": "s" * 32})))
        again = self.rpc("events/unsubscribe", {
            "name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": self.receiver_url("hook-s")}})
        self.assertEqual({key: value for key, value in again["result"].items()
                          if key not in {"resultType", "_meta"}}, {})


    def test_delivery_signature_identifiers_and_delivery_state(self):
        receiver_url = self.receiver_url()
        created = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})
        submission = created["submission_id"]
        result = self.subscribe(url=receiver_url, arguments={"submission_id": submission})
        sub_id = result["result"]["id"]
        self.assertTrue(self.receiver.record and self.receiver.record[0]["signature_ok"])
        self.assertTrue(self.receiver.record[0]["headers"]["webhook-id"].startswith("msg_verification_"))
        output = a.BridgeHTTP(self.harness.profile).request(
            "POST", "/v1/approved-output",
            {"version": 1, "conversation": self.store.conversation,
             "idempotency_key": uuid.uuid4().hex, "text": "APPROVED_PAYLOAD",
             "submission_id": submission, "approved_at": time.time()})
        output_id = output["output_id"]
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and len(self.receiver.record) < 2:
            time.sleep(0.02)
        entry = self.receiver.record[1]
        self.assertTrue(entry["signature_ok"])
        self.assertEqual(entry["headers"]["webhook-id"], output_id)
        self.assertEqual(entry["headers"].get("x-mcp-subscription-id"), sub_id)
        self.assertEqual(entry["headers"]["host"], "callback.example:%d" % self.receiver.port)
        self.assertEqual(self.receiver.record[0]["headers"]["host"], entry["headers"]["host"])
        value = json.loads(entry["body"])
        self.assertEqual(value["eventId"], output_id)
        self.assertEqual(set(value["data"]), {"submission_id", "output_id", "expires_at"})
        self.assertEqual(value["data"]["submission_id"], submission)
        self.assertNotIn(b"APPROVED_PAYLOAD", entry["body"])
        self.assertNotIn(self.store.conversation.encode(), entry["body"])
        self.harness.wait(lambda: self.store.submission_status(submission)["approved_output_available"] is False)
        named = self.rpc("tools/call", {"name": "get_approved_output",
                                        "arguments": {"conversation": self.harness.chat_code,
                                                      "submission_id": submission}})
        self.assertEqual(len(named["result"]["structuredContent"]["outputs"]), 1)
        general = self.rpc("tools/call", {"name": "get_approved_output",
                                          "arguments": {"conversation": self.harness.chat_code}})
        self.assertEqual(general["result"]["structuredContent"]["outputs"], [])

    def test_mixed_private_dns_is_rejected_before_any_connection(self):
        class NoConnection:
            def __init__(self, *args, **kwargs):
                raise AssertionError("a blocked target must never be contacted")
        with mock.patch.dict(a._bridge_component, {
                "webhook_addresses": lambda hostname, port: ["10.0.0.5", "8.8.8.8"],
                "WebhookConnection": NoConnection}):
            with self.assertRaises(a.WebhookFailure) as trap:
                self.harness.service.webhook_call(
                    {"id": "sub_x", "url": "https://callback.example/hook",
                     "secret": self.secret}, b"payload")
        self.assertEqual(trap.exception.reason, "connection_refused")
        self.assertFalse(trap.exception.retryable)

    def test_subscription_limit_caps_across_urls(self):
        EventSubscriptionTests.test_subscription_limit_caps_across_urls(self)

    def test_callback_certificate_hostname_mismatch_is_rejected(self):
        blocked = self.subscribe(url="https://wrong-host.example:%d/hook" % self.receiver.port)
        self.assertEqual(blocked["error"]["code"], -32015)
        self.assertEqual(blocked["error"]["data"]["reason"], "tls_error")
        self.assertEqual(self.receiver.record, [])

    def test_late_transport_ack_after_revocation_keeps_pull_fallback(self):
        identifier = self.subscribe(url=self.callback_url)["result"]["id"]
        subscription = self.store.active_subscription(identifier, self.store.clock())
        submission = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        self.store.on_new_output = None  # Invoke this one delivery explicitly for race control.
        output = self.store.approved_output({"version": 1, "conversation": self.store.conversation,
            "idempotency_key": uuid.uuid4().hex, "text": "LATE_ACK_OUTPUT",
            "submission_id": submission, "approved_at": self.store.clock()})
        received, release = threading.Event(), threading.Event()
        failures = []

        def before_ack():
            received.set()
            if not release.wait(5):
                failures.append("ack_fixture_timeout")

        def deliver():
            try:
                self.harness.service.deliver({"subscription": subscription, "attempts": 0,
                    "event": {"eventId": output["output_id"], "name": a.BRIDGE_EVENT_NAME,
                              "data": {"submission_id": submission, "output_id": output["output_id"]}}})
            except Exception as exc:
                failures.append(type(exc).__name__)

        self.receiver.before_ack = before_ack
        thread = threading.Thread(target=deliver)
        thread.start()
        try:
            self.assertTrue(received.wait(5))
            self.store.revoke(self.ai_id)  # Request was received; HTTP 200 has not been sent.
        finally:
            release.set()
            thread.join(timeout=6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(self.receiver.record[-1]["signature_ok"])
        row = self.store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                                 (output["output_id"],)).fetchone()
        self.assertEqual(tuple(row), (0, None))
        self.assertTrue(self.store.submission_status(submission)["approved_output_available"])
        fresh_ai, _ = self.store.issue("AI")
        status, raw = request(self.harness.mcp_url, "POST", body={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": "get_approved_output",
            "arguments": {"conversation": self.harness.chat_code}}},
            headers={"X-AITL-AI-Key": fresh_ai})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["result"]["structuredContent"]["outputs"][0]["output_id"],
                         output["output_id"])

    def test_host_authority_default_explicit_port_and_ipv6(self):
        for url, expected in (("https://callback.example/hook", "callback.example"),
                              ("https://callback.example:443/hook", "callback.example:443"),
                              ("https://[2606:4700:4700::1111]/hook", "[2606:4700:4700::1111]"),
                              ("https://[2606:4700:4700::1111]:8443/hook", "[2606:4700:4700::1111]:8443")):
            with self.subTest(url=url):
                connection = mock.Mock()
                connection.sock.getpeername.return_value = ("127.0.0.1", 443)
                connection.getresponse.return_value.status = 200
                connection.getresponse.return_value.read.return_value = b""
                with mock.patch.dict(a._bridge_component, {"WebhookConnection": mock.Mock(return_value=connection)}):
                    self.harness.service.webhook_call({"id": "sub_test", "url": url,
                                                       "secret": self.secret}, b"{}", "event_test")
                self.assertEqual(connection.request.call_args.kwargs["headers"]["Host"], expected)

    def test_all_private_dns_is_rejected(self):
        class NoConnection:
            def __init__(self, *args, **kwargs):
                raise AssertionError("a blocked target must never be contacted")
        with mock.patch.dict(a._bridge_component, {
                "webhook_addresses": lambda hostname, port: ["192.168.1.2"],
                "WebhookConnection": NoConnection}):
            with self.assertRaises(a.WebhookFailure) as trap:
                self.harness.service.webhook_call(
                    {"id": "sub_x", "url": "https://callback.example/hook",
                     "secret": self.secret}, b"payload")
        self.assertEqual(trap.exception.reason, "connection_refused")


class SubscriptionContractTests(EventSubscriptionTests):
    """events/subscribe contract: null cursor tolerated, ttlMs in milliseconds."""
    def subscribe(self, name=a.BRIDGE_EVENT_NAME, arguments=None,
                  url="https://callback.example/hook", secret=None, mode="webhook", ttl=None,
                  cursor=None):
        delivery = {"mode": mode, "url": url, "secret": secret or self.secret}
        params = {"name": name, "delivery": delivery,
                  "arguments": dict(arguments or {}, conversation=self.harness.chat_code)}
        if ttl is not None:
            params["ttlMs"] = ttl
        params["cursor"] = cursor  # documented (subscribe carries cursor: null)
        return self.rpc("events/subscribe", params)

    def test_subscribe_accepts_documented_cursor_null(self):
        result = self.subscribe(cursor=None)
        self.assertTrue(result["result"]["id"].startswith("sub_"))
        refresh = self.rpc("events/subscribe", {
            "name": a.BRIDGE_EVENT_NAME, "cursor": None,
            "arguments": {"conversation": self.harness.chat_code},
            "delivery": {"mode": "webhook", "url": "https://callback.example/hook",
                         "secret": self.secret}})
        self.assertEqual(refresh["result"]["id"], result["result"]["id"])

    def test_ttl_milliseconds_are_respected_not_read_as_seconds(self):
        granted = self.subscribe(ttl=60000, url="https://callback.example/hook-ttl")
        stamp = datetime.fromisoformat(granted["result"]["refreshBefore"].replace("Z", "+00:00"))
        self.assertAlmostEqual(stamp.timestamp(), self.store.clock() + 60, delta=3)
        peak = self.subscribe(ttl=7 * 24 * 3600 * 1000, url="https://callback.example/hook-ttl2")
        stamp_peak = datetime.fromisoformat(peak["result"]["refreshBefore"].replace("Z", "+00:00"))
        self.assertAlmostEqual(stamp_peak.timestamp(), self.store.clock() + 7 * 24 * 3600, delta=3)


class StoreSerializationTests(EventSubscriptionTests):
    def test_submit_is_idempotent_under_threads(self):
        value = {"request_id": uuid.uuid4().hex, "text": "true"}
        results = []
        lock = threading.Lock()

        def worker():
            outcome = self.store.submit(value)
            with lock:
                results.append(outcome["submission_id"])

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.store.execute("SELECT count(*) FROM proposals WHERE request=?",
                                            (value["request_id"],)).fetchone()[0], 1)

    def test_delivery_rechecks_unsubscribed_expired_and_revoked_principals(self):
        result = self.subscribe(url="https://callback.example/recheck")
        sub_id = result["result"]["id"]
        snapshot = self.store.active_subscription(sub_id, self.store.clock())
        self.assertIsNotNone(snapshot)
        self.store.delete_subscription(self.ai_id, sub_id)
        self.assertIsNone(self.store.active_subscription(sub_id, self.store.clock()))
        self.harness.service.deliver({"subscription": snapshot, "event":
                                      {"eventId": "e" * 32, "name": a.BRIDGE_EVENT_NAME,
                                       "timestamp": "", "data": {}, "cursor": None}})
        self.assertIsNone(self.harness.deliveries.get(sub_id))
        # Expired subscription: the stored deadline is in the past.
        result = self.subscribe(url="https://callback.example/recheck3")
        sub_id3 = result["result"]["id"]
        snapshot3 = self.store.active_subscription(sub_id3, self.store.clock())
        self.store.execute("UPDATE subscriptions SET expires=(?)/2.0 WHERE id=?",
                           (snapshot3["expires"], sub_id3))
        self.harness.service.deliver({"subscription": snapshot3, "event":
                                      {"eventId": "0" * 32, "name": a.BRIDGE_EVENT_NAME,
                                       "timestamp": "", "data": {}, "cursor": None}})
        self.assertIsNone(self.harness.deliveries.get(sub_id3))
        # Revoked AI principal: the token row disappears with the subscription row intact.
        second_ai, second_id = self.store.issue("AI")
        url = "https://callback.example/recheck2"
        args_json = "{}"
        revoked_id = self.store.subscription_identity(second_id, url, a.BRIDGE_EVENT_NAME, args_json)
        self.store.store_subscription(second_id, url, a.BRIDGE_EVENT_NAME, args_json,
                                      self.secret, self.store.clock() + 600, bound=True)
        snapshot2 = self.store.active_subscription(revoked_id, self.store.clock())
        self.assertIsNotNone(snapshot2)
        self.store.revoke(second_id)
        self.assertIsNone(self.store.active_subscription(revoked_id, self.store.clock()))
        self.harness.service.deliver({"subscription": snapshot2, "event":
                                      {"eventId": "f" * 32, "name": a.BRIDGE_EVENT_NAME,
                                       "timestamp": "", "data": {}, "cursor": None}})
        self.assertIsNone(self.harness.deliveries.get(revoked_id))


class FramingParityTests(EventSubscriptionTests):
    mcp_port = property(lambda self: urlsplit(self.harness.mcp_url).port)

    def test_duplicate_content_length_is_rejected(self):
        payload = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        conn = http.client.HTTPConnection("127.0.0.1", self.mcp_port, timeout=5)
        try:
            conn.putrequest("POST", "/mcp", skip_host=True)
            conn.putheader("Host", "127.0.0.1:%d" % self.mcp_port)
            conn.putheader("X-AITL-AI-Key", self.harness.ai)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("MCP-Protocol-Version", "2026-07-28")
            conn.putheader("Content-Length", str(len(payload)))
            conn.putheader("Content-Length", str(len(payload)))
            conn.endheaders()
            conn.send(payload)
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn(b"duplicate_header", response.read())
        finally:
            conn.close()

    def test_transfer_encoding_is_rejected(self):
        payload = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        conn = http.client.HTTPConnection("127.0.0.1", self.mcp_port, timeout=5)
        try:
            conn.putrequest("POST", "/mcp", skip_host=True)
            conn.putheader("Host", "127.0.0.1:%d" % self.mcp_port)
            conn.putheader("X-AITL-AI-Key", self.harness.ai)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("MCP-Protocol-Version", "2026-07-28")
            conn.putheader("Content-Length", str(len(payload)))
            conn.putheader("Transfer-Encoding", "chunked")
            conn.endheaders()
            conn.send(payload)
            response = conn.getresponse()
            self.assertEqual(response.status, 411)
            self.assertIn(b"transfer_encoding_rejected", response.read())
        finally:
            conn.close()


class UnboundOutputTests(EventDeliveryTests):
    """H5/M1: an ACKed un-bound output stays readable; explicit unbound binding."""
    def test_unbound_output_remains_readable_after_confirmed_push(self):
        response = self.post_output(None)
        output_id = response["output_id"]
        self.harness.wait(lambda: self.harness.deliveries.get(self.subscription_id))
        pulled = self.approved_output_tool({})
        self.assertEqual(len(pulled["result"]["structuredContent"]["outputs"]), 1)
        self.assertEqual(pulled["result"]["structuredContent"]["outputs"][0]["output_id"], output_id)
        self.assertIsNone(pulled["result"]["structuredContent"]["outputs"][0]["submission_id"])
        with_cursor = self.approved_output_tool(
            {"cursor": pulled["result"]["structuredContent"]["cursor"]})
        self.assertEqual(with_cursor["result"]["structuredContent"]["outputs"], [])


class TlsStallTests(EventSubscriptionTests):
    """H7: a stalled TLS handshake must never block the serving path."""
    def test_stalled_handshake_does_not_block_tls_serving(self):
        directory = str(self.temp.name)
        tls, pin = a.bridge_certificate(directory, ["127.0.0.1"])

        def handler_for(kind):
            return type("_HarnessTls" + kind, (a.BridgeRequestHandler,),
                        {"service": self.harness.service, "kind": kind})
        tls_server = a.BridgeHTTPServer(("127.0.0.1", 0), handler_for("CONTROLLER"), tls)
        self.harness.service.controller_hosts.add("127.0.0.1:%d" % tls_server.socket.getsockname()[1])
        profile = a.ConnectionProfile("https://127.0.0.1:%d" % tls_server.socket.getsockname()[1],
                                      pin, self.store.conversation, self.harness.controller_id,
                                      self.harness.controller, "REMOTE")
        server_thread = threading.Thread(target=tls_server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(tls_server.shutdown)
        self.addCleanup(tls_server.server_close)
        time.sleep(0.05)
        stall = socket.create_connection(("127.0.0.1", tls_server.socket.getsockname()[1]), timeout=5)
        try:
            client = a.BridgeHTTP(profile)
            status = client.request("GET", "/v1/status")["version"]
            self.assertEqual(status, 1)
        finally:
            stall.close()


class CorrectionRegressionTests(unittest.TestCase):
    """Focused F1/F3/F4/F5 cases, without inherited duplicate test executions."""
    setUp = EventSubscriptionTests.setUp
    rpc = EventSubscriptionTests.rpc
    subscribe = EventSubscriptionTests.subscribe

    def test_legacy_unbound_subscription_needs_authorized_refresh(self):
        # Exercise an actual pre-F1 schema upgrade in an isolated store.
        with tempfile.TemporaryDirectory(prefix="aitl-legacy-sub-") as directory:
            conversation = uuid.uuid4().hex
            store = a.BridgeStore(directory, conversation)
            ai, principal_id = store.issue("AI")
            identifier = store.store_subscription(principal_id, self.callback_url, a.BRIDGE_EVENT_NAME,
                                                  "{}", self.secret, store.clock() + 600)
            store.execute("ALTER TABLE subscriptions DROP COLUMN bound")
            store.close()
            store = a.BridgeStore(directory, conversation)
            try:
                service = a.BridgeService(store)
                self.assertIsNone(store.active_subscription(identifier, store.clock()))
                service.queue_output_events("a" * 32, None, store.clock() + 600)
                self.assertEqual(service.jobs, [])
                principal = store.authenticate(ai, "AI")
                with mock.patch.object(service, "verify_callback", return_value=True):
                    refreshed = service.subscribe(principal, {"name": a.BRIDGE_EVENT_NAME,
                        "arguments": {"conversation": store.chat_binding["code"]},
                        "delivery": {"mode": "webhook", "url": self.callback_url, "secret": self.secret}})
                self.assertEqual(refreshed["id"], identifier)
                self.assertIsNotNone(store.active_subscription(identifier, store.clock()))
                self.assertEqual(store.find_subscription(principal_id, self.callback_url,
                                                        a.BRIDGE_EVENT_NAME, "{}")["args"], "{}")
            finally:
                store.close()

    def test_parallel_subscribes_recheck_quota_after_verification(self):
        limit = a.BRIDGE_EVENT_SUBSCRIPTION_LIMIT
        for index in range(limit - 1):
            self.store.store_subscription(self.ai_id, self.callback_url + str(index), a.BRIDGE_EVENT_NAME,
                                          "{}", self.secret, self.store.clock() + 600, bound=True)
        # One contender is a refresh of an expired existing row: it is a NEW allocation.
        expired_url = self.callback_url + "expired"
        self.store.store_subscription(self.ai_id, expired_url, a.BRIDGE_EVENT_NAME,
                                      "{}", self.secret, self.store.clock() - 1, bound=True)
        barrier = threading.Barrier(2)
        outcomes, failures, observed_counts = [], [], []

        def verify(*_):
            barrier.wait(timeout=5)
            return True

        def worker(url):
            try:
                outcomes.append(self.subscribe(url=url))
                observed_counts.append(self.store.count_subscriptions(self.ai_id))
            except Exception as exc:
                failures.append(repr(exc))

        with mock.patch.object(self.harness.service, "verify_callback", verify):
            threads = [threading.Thread(target=worker, args=(url,))
                       for url in (expired_url, self.callback_url + "new")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=6)
            self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertEqual(sum("result" in outcome for outcome in outcomes), 1)
        errors = [outcome["error"] for outcome in outcomes if "error" in outcome]
        self.assertEqual([error["code"] for error in errors], [-32013])
        self.assertTrue(all(count <= limit for count in observed_counts))
        self.assertEqual(self.store.count_subscriptions(self.ai_id), limit)

    def test_expired_refresh_at_full_quota_is_rejected(self):
        expired_url = self.callback_url + "expired"
        self.store.store_subscription(self.ai_id, expired_url, a.BRIDGE_EVENT_NAME,
                                      "{}", self.secret, self.store.clock() - 1, bound=True)
        for index in range(a.BRIDGE_EVENT_SUBSCRIPTION_LIMIT):
            self.store.store_subscription(self.ai_id, self.callback_url + str(index), a.BRIDGE_EVENT_NAME,
                                          "{}", self.secret, self.store.clock() + 600, bound=True)
        blocked = self.subscribe(url=expired_url)
        self.assertEqual(blocked["error"]["code"], -32013)
        self.assertLess(self.store.find_subscription(self.ai_id, expired_url,
                                                   a.BRIDGE_EVENT_NAME, "{}")["expires"], self.store.clock())

    def test_revocation_during_callback_verification_rejects_subscription(self):
        def verify(*_):
            self.store.revoke(self.ai_id)
            return True
        with mock.patch.object(self.harness.service, "verify_callback", verify):
            blocked = self.subscribe()
        self.assertEqual(blocked["error"]["data"]["reason"], "unauthorized")
        self.assertEqual(self.store.count_subscriptions(self.ai_id), 0)

    def test_incomplete_request_lines_bound_threads_and_release_connections(self):
        worker_count = lambda: sum("process_request_thread" in thread.name for thread in threading.enumerate())
        baseline = worker_count()
        sockets = []
        port = self.harness.mcp_server.server_port
        try:
            for _ in range(64):
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                sock.sendall(b"POST /mcp")
                sockets.append(sock)
            self.harness.wait(lambda: worker_count() - baseline == 64, timeout=2)
            for _ in range(8):
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                try:
                    self.assertEqual(sock.recv(1), b"")
                except ConnectionResetError:
                    pass
                finally:
                    sock.close()
            # The controller listener uses the SAME pre-dispatch budget.
            other = socket.create_connection(("127.0.0.1", self.harness.controller_server.server_port), timeout=2)
            try:
                self.assertEqual(other.recv(1), b"")
            finally:
                other.close()
            self.assertLessEqual(worker_count() - baseline, 64)
            self.assertEqual(self.harness.service.inflight, 0)
        finally:
            for sock in sockets:
                sock.close()
        self.harness.wait(lambda: worker_count() == baseline, timeout=3)
        self.assertIn("result", self.rpc("ping"))

    def test_trickle_body_exceeds_monotonic_total_deadline(self):
        port = self.harness.mcp_server.server_port
        request_id = uuid.uuid4().hex
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "submit_proposal", "arguments": {"request_id": request_id,
                "text": "true", "conversation": self.harness.chat_code}}}).encode()
        headers = ("POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-AITL-AI-Key: %s\r\n"
                   "Content-Type: application/json\r\nContent-Length: %d\r\n\r\n") % (port, self.harness.ai, len(body))
        sock = socket.create_connection(("127.0.0.1", port), timeout=8)
        stop = threading.Event()
        sent = []

        def trickle():
            for byte in body[-10:]:
                if stop.wait(0.9):
                    return
                try:
                    sock.sendall(bytes([byte]))
                    sent.append(byte)
                except OSError:
                    return

        began = time.monotonic()
        sock.sendall(headers.encode() + body[:-10])
        writer = threading.Thread(target=trickle)
        writer.start()
        try:
            response = http.client.HTTPResponse(sock)
            response.begin()
            self.assertEqual(response.status, 408)
            self.assertEqual(json.loads(response.read()), {"error": "body_timeout"})
            self.assertLess(time.monotonic() - began, 6.5)
            self.assertGreaterEqual(len(sent), 4)  # Continuous progress, no inactivity timeout.
        finally:
            stop.set()
            writer.join(timeout=2)
            sock.close()
        self.assertIsNone(self.store.execute("SELECT id FROM proposals WHERE request=?", (request_id,)).fetchone())
        self.harness.wait(lambda: self.harness.service.inflight == 0)
        self.assertIn("result", self.rpc("ping"))

    def test_trickle_headers_exceed_total_deadline_and_release_slot(self):
        sock = socket.create_connection(("127.0.0.1", self.harness.mcp_server.server_port), timeout=8)
        stop = threading.Event()
        sent = []

        def trickle():
            while not stop.wait(0.9):
                try:
                    sock.sendall(b"a")
                    sent.append(1)
                except OSError:
                    return

        began = time.monotonic()
        sock.sendall(b"POST /mcp HTTP/1.1\r\nHost: ")
        writer = threading.Thread(target=trickle)
        writer.start()
        try:
            self.assertEqual(sock.recv(1), b"")
            self.assertLess(time.monotonic() - began, 6.5)
            self.assertGreaterEqual(len(sent), 4)
        finally:
            stop.set()
            writer.join(timeout=2)
            sock.close()
        self.assertEqual(self.harness.service.inflight, 0)
        self.assertIn("result", self.rpc("ping"))

    def test_ack_update_authorization_is_atomic_with_external_sqlite_revocation(self):
        identifier = self.subscribe()["result"]["id"]
        self.store.on_new_output = None
        output = self.store.approved_output({"version": 1, "conversation": self.store.conversation,
            "idempotency_key": uuid.uuid4().hex, "text": "ACK_RACE", "submission_id": None,
            "approved_at": self.store.clock()})
        active = self.store.active_subscription
        external = sqlite3.connect(Path(self.temp.name, "bridge.sqlite3"), isolation_level=None)
        try:
            def revoke_after_check(*args):
                row = active(*args)
                self.assertIsNotNone(row)
                external.execute("DELETE FROM tokens WHERE id=?", (self.ai_id,))
                return row
            with mock.patch.object(self.store, "active_subscription", revoke_after_check):
                self.assertFalse(self.store.mark_delivered(output["output_id"], identifier,
                                                          self.store.chat_binding["generation"]))
        finally:
            external.close()
        self.assertEqual(self.store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                                           (output["output_id"],)).fetchone()[:], (0, None))

    def test_late_ack_after_unsubscribe_or_expiry_cannot_suppress_pull(self):
        self.store.on_new_output = None
        for reason in ("unsubscribe", "expiry"):
            with self.subTest(reason=reason):
                identifier = self.subscribe(url=self.callback_url + reason)["result"]["id"]
                snapshot = self.store.active_subscription(identifier, self.store.clock())
                output = self.store.approved_output({"version": 1, "conversation": self.store.conversation,
                    "idempotency_key": uuid.uuid4().hex, "text": "LATE_ACK", "submission_id": None,
                    "approved_at": self.store.clock()})

                def late_ack(*_, **__):
                    if reason == "unsubscribe":
                        self.store.delete_subscription(self.ai_id, identifier)
                    else:
                        self.store.execute("UPDATE subscriptions SET expires=? WHERE id=?",
                                           (self.store.clock() - 1, identifier))
                    return 200, b""

                with mock.patch.object(self.harness.service, "webhook_call", late_ack):
                    self.harness.service.deliver({"subscription": snapshot, "event": {"eventId": output["output_id"]}})
                self.assertEqual(self.store.execute("SELECT delivered FROM outputs WHERE id=?",
                                                   (output["output_id"],)).fetchone()[0], 0)


class BindingDisplayRegressionTests(unittest.TestCase):
    """Execute the real ReviewUI logic headlessly; no GUI-smoke claim."""
    def setUp(self):
        self.first, self.second = "a" * 32, "b" * 32
        self.candidates = [{"submission_id": self.first, "text_view": "first"},
                           {"submission_id": self.second, "text_view": "second"}]
        value = [""]
        self.snapshot = SimpleNamespace(bridge=SimpleNamespace(state="CONNECTED"), review_state="REVIEW",
                                        review=SimpleNamespace(id="review-id", direction="TO_OUTPUT_SINK"))
        self.ui = SimpleNamespace(core=SimpleNamespace(output_candidates=lambda: self.candidates,
            last_proposal_id=self.second, snapshot=lambda: self.snapshot, approve=mock.Mock()),
            binding_row=mock.Mock(), binding_picker=mock.Mock(),
            binding_value=SimpleNamespace(get=lambda: value[0], set=lambda text: value.__setitem__(0, text)),
            binding_submission={}, binding_touched=False, last_binding_rows=None, last_binding_review=None,
            action=lambda run: run())

    def render(self):
        a.ReviewUI._render_binding_row(self.ui, self.snapshot, self.snapshot.review, True)

    def test_selection_only_and_unknown_label_is_rejected(self):
        self.render()
        self.assertEqual(self.ui.binding_picker.configure.call_args_list[0].kwargs["state"], "readonly")
        self.ui.binding_value.set("arbitrary input")
        with self.assertRaisesRegex(a.ProbeError, "unknown_output_binding"):
            a.ReviewUI.approve(self.ui)
        self.ui.core.approve.assert_not_called()
        self.ui.binding_value.set(next(label for label, value in self.ui.binding_submission.items() if value is None))
        a.ReviewUI.approve(self.ui)
        self.ui.core.approve.assert_called_once_with("review-id", override=False,
                                                    submission_id=None, explicit_binding=True)

    def test_approved_binding_frozen_across_candidate_expiry_removal_and_disconnect(self):
        self.render()
        label = next(label for label, value in self.ui.binding_submission.items() if value == self.first)
        self.ui.binding_value.set(label)
        self.ui.binding_touched = True
        a.ReviewUI.approve(self.ui)
        self.ui.core.approve.assert_called_once_with("review-id", override=False,
                                                    submission_id=self.first, explicit_binding=True)
        frozen = dict(self.ui.binding_submission)
        self.candidates.pop(0)  # Selected candidate expires / disappears from output_candidates.
        self.ui.binding_row.reset_mock()
        for state in ("SENDING", "DELIVERY_UNCERTAIN", "SENDING", "ACKNOWLEDGED"):
            with self.subTest(state=state):
                self.snapshot.review_state = state
                self.render()
                self.assertEqual(self.ui.binding_value.get(), label)
                self.assertEqual(self.ui.binding_submission, frozen)
                self.assertEqual(self.ui.binding_picker.configure.call_args.kwargs["state"], "disabled")
        self.candidates.clear()
        self.snapshot.bridge.state = "DISCONNECTED"
        self.render()
        self.assertEqual(self.ui.binding_value.get(), label)
        self.ui.binding_row.grid_remove.assert_not_called()
        # A different review gets a fresh mapping/default, never the consumed selection.
        self.snapshot.review = SimpleNamespace(id="next-review", direction="TO_OUTPUT_SINK")
        self.snapshot.review_state = "REVIEW"
        self.snapshot.bridge.state = "CONNECTED"
        self.candidates.append({"submission_id": self.second, "text_view": "second"})
        self.render()
        self.assertEqual(self.ui.binding_submission[self.ui.binding_value.get()], self.second)


class PermissiveSendTests(unittest.TestCase):
    """M2/#74: generous honest readiness labels; one explicit reviewed send suffices."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-permissive-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = a.IntegrationFixture(self.temp.name)
        self.addCleanup(self.fixture.close)
        self.core = self.fixture.core

    def test_shell_prompt_tail_classifies_as_prompt(self):
        self.assertEqual(a.classify_input_tail(bytes(self.core.output.data[-64:])), "PROMPT")

    def test_single_send_at_unknown_tail_without_override(self):
        self.fixture.manual("IFS= read -r -p 'PERMISSIVE_WAIT: ' answer; printf '\\nPERM_DONE\\n'\n")
        self.fixture.wait(lambda: self.core.output.data.endswith(b"PERMISSIVE_WAIT: "))
        self.assertNotEqual(a.classify_input_tail(bytes(self.core.output.data[-64:])), "PROMPT")
        item = self.core.review_command("answer", True)
        # #74: readiness UNKNOWN never forces a second confirmation click.
        self.core.approve(item.id)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED"
                          and b"\r\nPERM_DONE\r\n" in self.core.output.data)
        with self.assertRaises(a.ProbeError):
            self.core.approve(item.id)

    def test_password_tail_single_send_and_silent_relay(self):
        self.fixture.manual("IFS= read -r -s -p 'Password: ' pw; printf '\\nPERM_PW_DONE\\n'; unset pw\n")
        self.fixture.wait(lambda: self.core.output.data.endswith(b"Password: "))
        self.assertEqual(a.classify_input_tail(bytes(self.core.output.data[-32:])), "PASSWORD")
        secret = ("synthetic_" + uuid.uuid4().hex).encode()
        item = self.core.review_command("program-input", True)
        self.core.approve(item.id)
        self.fixture.wait(lambda: self.core.review_state == "TRANSFERRED"
                          and b"\r\nPERM_PW_DONE\r\n" in self.core.output.data)
        self.fixture.manual(b"IFS= read -r -s -p 'PERM_S: ' q; printf '\\nPERM_S_DONE\\n'\n")
        self.fixture.wait(lambda: self.core.output.data.endswith(b"PERM_S: "))
        self.fixture.manual(secret + b"\n")
        self.fixture.wait(lambda: b"\r\nPERM_S_DONE\r\n" in self.core.output.data)
        self.assertNotIn(secret, self.core.output.data)
        self.assertNotIn(secret, self.fixture.transcript)


class RiskSentPreservationTests(unittest.TestCase):
    """M3/AC3: the bound risk result of THIS exact snapshot stays published across
    CHECKING→TRANSFERRED/TRANSFER_UNCERTAIN – no reanalysis, no pin release;
    revision/binding/payload mutations invalidate instead."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-sent-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.work = self.directory / "work"
        self.work.mkdir(mode=0o700)
        self.core = a.AppCore()
        self.core.session = "RISK_SENT_SESSION"
        self.core.connection = "CONNECTED"
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.addCleanup(self.core.close)

    def fake_tool(self, bad=False):
        # Private fixture analyzer pinned by its actual bytes; never upstream sh-guard.
        binary = self.directory / ("fake-" + uuid.uuid4().hex)
        source = "#!" + str(Path(sys.executable).resolve()) + "\n" + (
            "import json, signal, sys, time\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('sh-guard 0.1.10')\n"
            "    sys.exit(0)\n"
            "command = sys.argv[7]\n"
            "if command == 'hang-command\\n':\n"
            "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "    while True:\n"
            "        time.sleep(1)\n"
            + ("print('not JSON')\nsys.exit(0)\n" if bad else
               "value = {'command': command, 'score': 0, 'level': 'safe',\n"
               "         'quick_decision': 'safe', 'reason': 'Fixture', 'risk_factors': [],\n"
               "         'sub_commands': [], 'pipeline_flow': None, 'mitre_mappings': [],\n"
               "         'parse_confidence': 'full'}\n"
               "print(json.dumps(value))\n"
               "sys.exit(0)\n"))
        binary.write_text(source)
        binary.chmod(0o500)
        raw = binary.read_bytes()
        return a.CommandRiskTool(str(binary), hashlib.sha256(raw).hexdigest(), len(raw), "0.1.10", 1)

    def until(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.core.command_risk_snapshot()
            if predicate(snapshot):
                return snapshot
            time.sleep(0.01)
        self.fail("risk_sent_deadline")

    def test_result_preserved_across_sent_states_without_reanalysis(self):
        self.core.review_command("printf x")
        self.core.set_command_risk(self.fake_tool(), str(self.work))
        first = self.until(lambda value: value.state == "RESULT").result
        reviewer = self.core._command_risk
        for state in ("CHECKING", "TRANSFERRED", "TRANSFER_UNCERTAIN", "TRANSFERRED"):
            with self.subTest(state=state):
                self.core.review_state = state
                snapshot = self.core.command_risk_snapshot()
                self.assertIs(snapshot.result, first)
                self.assertEqual(snapshot.state, "RESULT")
                self.assertIsNone(reviewer.pending)
        # A new revision invalidates the published evidence and rescans exactly once.
        self.core.review = replace(self.core.review, revision=self.core.review.revision + 1)
        self.core.review_state = "REVIEW"
        self.assertIsNone(self.core.command_risk_snapshot().result)
        second = self.until(lambda value: value.state == "RESULT" and value.result is not first).result
        self.assertNotEqual(second.key.revision, first.key.revision)
        self.assertEqual(second.key.review_id, first.key.review_id)
        # A payload mutation during a sent state never keeps stale evidence.
        self.core.review_state = "TRANSFERRED"
        self.core.review = replace(self.core.review, text="printf forged\n")
        snapshot = self.core.command_risk_snapshot()
        self.assertIsNone(snapshot.result)
        # Rejection/clearing returns to IDLE without a published result.
        self.core.review, self.core.review_state = None, "EMPTY"
        snapshot = self.core.command_risk_snapshot()
        self.assertEqual(snapshot.state, "IDLE")
        self.assertIsNone(snapshot.result)

    def test_inflight_scan_without_result_is_cancelled_at_send(self):
        self.core.review_command("hang-command")
        self.core.set_command_risk(self.fake_tool(), str(self.work))
        self.until(lambda value: value.state == "SCANNING")
        self.core.review_state = "CHECKING"
        snapshot = self.core.command_risk_snapshot()
        self.assertIsNone(snapshot.result)
        self.assertEqual(snapshot.state, "STALE")
        self.assertIsNone(self.core._command_risk.pending)
        time.sleep(0.2)
        # A late completion for the dropped job never publishes into the sent state.
        snapshot = self.core.command_risk_snapshot()
        self.assertIsNone(snapshot.result)

    def test_unavailable_evidence_is_not_preserved_at_sent(self):
        # Narrowed M3 semantics: only REAL results (colors/checked state) are
        # preserved at sent states; UNAVAILABLE keeps the pre-M3 discard
        # (frozen evidence semantics, test_command_risk.py parity).
        self.core.review_command("printf x")
        self.core.set_command_risk(self.fake_tool(bad=True), str(self.work))
        snapshot = self.until(lambda value: value.state == "UNAVAILABLE")
        self.assertEqual(snapshot.result.state, "UNAVAILABLE")
        self.core.review_state = "CHECKING"
        snapshot = self.core.command_risk_snapshot()
        self.assertIsNone(snapshot.result)
        self.assertEqual(snapshot.state, "STALE")

    def test_direction_and_session_changes_invalidate_at_sent(self):
        self.core.review_command("printf x")
        self.core.set_command_risk(self.fake_tool(), str(self.work))
        first = self.until(lambda value: value.state == "RESULT").result
        self.core.review_state = "TRANSFERRED"
        self.assertIs(self.core.command_risk_snapshot().result, first)
        self.core.session = "OTHER_SESSION"
        snapshot = self.core.command_risk_snapshot()
        self.assertIsNone(snapshot.result)
        self.assertEqual(snapshot.state, "STALE")


class QrexecForwarderTests(unittest.TestCase):
    """M9 Folgefix: qvm-connect-tcp ist ein Launcher (Skript exitet, socat/Helfer der
    eigene Gruppe behält den Port). Tests nutzen vertragsgetreue Launcher-Fakes
    (Helfer-Dateiname enthält das Identitätsmarker 'qvm-connect-tcp') statt der
    früheren Foreground-Annahme; fremde Listener werden nie übernommen/getötet."""

    LAUNCHER = (
        "#!/bin/bash --\n"
        "set -e\n"
        "LOCALPORT=\"$(echo \"$1\" | cut -d ':' -f1)\"\n"
        "TARGET=\"$(echo \"$1\" | cut -d ':' -f2)\"\n"
        "PORT=\"$(echo \"$1\" | cut -d ':' -f3)\"\n"
        "DIR=\"$(dirname \"$0\")\"\n"
        "if [ \"$TARGET\" = failqube ]; then echo \"qvm-connect-tcp: denied by policy\" >&2; exit 3; fi\n"
        "echo \"Binding TCP '$TARGET:$PORT' to 'localhost:$LOCALPORT'...\"\n"
        "if [ \"$TARGET\" = silentqube ]; then echo \"bind failed: Address already in use by test\" >&2; exit 0; fi\n"
        "\"$DIR/qvm-connect-tcp-listener\" \"$LOCALPORT\" \"$TARGET\" \"$PORT\" >/dev/null 2>&1 &\n")
    HELPER = (
        "#!" + str(Path(sys.executable).resolve()) + "\n"
        "import os, socket, sys, time\n"
        "local, target, remote = sys.argv[1:4]\n"
        "if target == 'slowqube':\n"
        "    time.sleep(30)\n"
        "os._exit(0)\n")
    LISTENER = (
        "#!" + str(Path(sys.executable).resolve()) + "\n"
        "import os, socket, sys\n"
        "spec = __import__('json').loads(os.environ.get('AITL_TEST_SPEC') or '{}')\n"
        "local, target, remote = sys.argv[1:4]\n"
        "mode = spec.get(target, 'listen')\n"
        "srv = socket.socket()\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', int(local)))\n"
        "srv.listen(5)\n"
        "import threading\n"
        "def serve_forever():\n"
        "    while True:\n"
        "        conn, _ = srv.accept()\n"
        "        if mode == 'deny':\n"
        "            conn.close(); continue\n"
        "        if mode == 'plain':\n"
        "            conn.sendall(b'NOPE NOT TLS\\r\\n'); conn.close(); continue\n"
        "        up = socket.socket(); up.settimeout(3)\n"
        "        try:\n"
        "            up.connect(('127.0.0.1', int(spec.get('remote', remote))))\n"
        "        except OSError:\n"
        "            conn.close(); continue\n"
        "        def pump(a, b):\n"
        "            try:\n"
        "                while True:\n"
        "                    data = a.recv(8192)\n"
        "                    if not data: break\n"
        "                    b.sendall(data)\n"
        "            except OSError:\n"
        "                pass\n"
        "            for side in (a, b):\n"
        "                try: side.close()\n"
        "                except OSError: pass\n"
        "        threading.Thread(target=pump, args=(conn, up), daemon=True).start()\n"
        "        threading.Thread(target=pump, args=(up, conn), daemon=True).start()\n"
        "serve_forever()\n")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-qrexec-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        launcher = self.directory / "qvm-connect-tcp"
        helper = self.directory / "qvm-connect-tcp-listener"
        launcher.write_text(self.LAUNCHER)
        helper.write_text(self.LISTENER)
        launcher.chmod(0o755); helper.chmod(0o755)
        patcher = mock.patch.object(a.shutil, "which", return_value=str(launcher))
        patcher.start(); self.addCleanup(patcher.stop)
        self.launcher = launcher

    def free_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def listener(self, port):
        with socket.socket() as probe:
            probe.settimeout(1)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def test_launcher_success_running_status_stop(self):
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        port = self.free_port()
        self.assertFalse(forwarder.running)
        forwarder.start("target-vm", port)
        # Launcher ist evtl. schon exitet – Besitz folgt aus unserer eigenen Gruppe.
        self.assertTrue(forwarder.running)
        status = forwarder.status()
        self.assertTrue(status["forwarder_running"] and status["local_listener"] and status["owned"])
        self.assertEqual((status["target"], status["port"]), ("target-vm", port))
        pgid = forwarder.pgid
        forwarder.stop()
        self.assertFalse(forwarder.running)
        self.assertFalse(self.listener(port))

    def test_single_instance_and_target_switch(self):
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        port = self.free_port()
        forwarder.start("target-vm", port)
        first_pgid = forwarder.pgid
        forwarder.start("target-vm", port)
        self.assertEqual(forwarder.pgid, first_pgid)  # identical request: same group, no duplicate
        second = self.free_port()
        forwarder.start("other-vm", second)
        self.assertNotEqual(forwarder.pgid, first_pgid)
        self.assertEqual(forwarder.status()["target"], "other-vm")

    def test_evidenced_script_failure_carries_exit_and_stderr(self):
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        with self.assertRaisesRegex(a.ProbeError, "qrexec_forwarder_failed"):
            forwarder.start("failqube", self.free_port())
        self.assertFalse(forwarder.running)
        result = forwarder.last_result
        self.assertEqual(result["exit"], 3)
        self.assertIn("denied by policy", result["detail"])  # bounded sanitized tail

    def test_exit_zero_without_listener_is_evidenced_not_success(self):
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        with self.assertRaisesRegex(a.ProbeError, "qrexec_launch_no_listener"):
            forwarder.start("silentqube", self.free_port())
        self.assertFalse(forwarder.running)
        self.assertIn("Address already in use by test", forwarder.last_result["detail"])

    def test_foreign_listener_is_never_adopted_or_killed(self):
        foreign = socket.socket()
        foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        foreign.bind(("127.0.0.1", 0))
        foreign.listen(1)
        self.addCleanup(foreign.close)
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        port = foreign.getsockname()[1]
        with self.assertRaisesRegex(a.ProbeError, "qrexec_port_conflict"):
            forwarder.start("target-vm", port)
        self.assertFalse(forwarder.running)
        self.assertEqual(self.listener(port), True)  # foreign untouched

    def test_identity_guard_never_signals_foreign_group(self):
        # Simulate PID/PGID reuse: recorded group belongs to an unrelated process.
        dummy = subprocess.Popen(["sleep", "30"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: dummy.poll() is None and dummy.kill())
        forwarder = a.QrexecForwarder()
        forwarder.pgid = os.getpgid(dummy.pid)
        forwarder.port = self.free_port()
        self.assertFalse(forwarder.owned())
        forwarder.stop()
        self.assertIsNone(dummy.poll())  # foreign process still alive, never signalled

    def test_missing_tool_and_invalid_names(self):
        forwarder = a.QrexecForwarder()
        self.addCleanup(forwarder.stop)
        with mock.patch.object(a.shutil, "which", return_value=None):
            with self.assertRaisesRegex(a.ProbeError, "qrexec_tool_missing"):
                forwarder.start("target-vm", self.free_port())
        with self.assertRaisesRegex(a.ProbeError, "invalid_qube_name"):
            forwarder.start("bad name", self.free_port())
        self.assertFalse(forwarder.running)


class QrexecConfigPersistenceTests(unittest.TestCase):
    """M9: qrexec config is private persistent state; restart recovery restores
    Main's own forwarder; legacy three-field connection files stay readable."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-qrexec-store-")
        self.addCleanup(self.temp.cleanup)
        self.store = a.ConnectionStore(Path(self.temp.name, "config"))

    def test_legacy_file_and_schema_guards(self):
        legacy = self.store.directory / "connection.json"
        self.store.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.store.directory, 0o700)
        legacy.write_bytes(a.net_json({"version": 1, "profile": None, "tunnel": None}))
        os.chmod(legacy, 0o600)
        self.assertIsNone(self.store.load_connection()["qrexec"])
        self.store.save_connection()
        self.assertIsNone(self.store.load_connection()["qrexec"])
        for body in ({"version": 1, "profile": None, "tunnel": None, "qrexec": None, "extra": 1},
                     {"version": 1, "profile": None, "tunnel": None, "qrexec": {"target": "ok", "port": "8443"}},
                     {"version": 1, "profile": None, "tunnel": None, "qrexec": {"target": "bad name", "port": 1}}):
            legacy.write_bytes(a.net_json(body))
            with self.assertRaises(a.ProbeError):
                self.store.load_connection()

    def test_core_persists_and_recovers_own_forwarder_config(self):
        binary = Path(self.temp.name, "qvm-connect-tcp")
        binary.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + (
            "import socket, sys, time\n"
            "local, target, remote = sys.argv[1].split(':')\n"
            "srv = socket.socket()\n"
            "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
            "srv.bind(('127.0.0.1', int(local)))\n"
            "srv.listen(5)\n"
            "while True:\n"
            "    time.sleep(0.5)\n"))
        binary.chmod(0o700)
        with mock.patch.object(a.shutil, "which", return_value=str(binary)):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            core = a.AppCore(connection_store=self.store)
            try:
                core.start_qrexec_forwarder("target-vm", port)
                self.assertEqual(core.qrexec, {"target": "target-vm", "port": port})
                self.assertEqual(self.store.load_connection()["qrexec"], {"target": "target-vm", "port": port})
            finally:
                core.close()
            self.assertFalse(core.qrexec_forwarder.running)  # clean shutdown of the own process
            restored = a.AppCore(connection_store=self.store)
            try:
                self.assertEqual(restored.qrexec, {"target": "target-vm", "port": port})
                profile = a.ConnectionProfile("https://127.0.0.1:%d" % port, "0" * 64,
                                              "0" * 32, "0" * 32, "0" * 64)
                self.store.save_connection(profile, None, restored.qrexec)
                forwarder = mock.Mock(running=False)
                restored.qrexec_forwarder = forwarder
                restored.saved_connection = None
                with mock.patch.object(restored, "connect_profile") as connect:
                    restored.connect_saved_bridge()
                forwarder.start.assert_called_once_with("target-vm", port)  # restart recovery
                connect.assert_called_once()
                self.assertEqual(connect.call_args.args[0].url, "https://127.0.0.1:%d" % port)
            finally:
                restored.close()

    def test_controller_paired_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix="aitl-paired-") as directory:
            store = a.BridgeStore(Path(directory), uuid.uuid4().hex)
            self.addCleanup(store.close)
            self.assertFalse(store.controller_paired())
            code = store.open_pair()
            claim = store.claim({"code": code, "request_id": uuid.uuid4().hex})
            self.assertFalse(store.controller_paired())  # PAIR_PENDING is not paired yet
            store.confirm(claim["token"])
            self.assertTrue(store.controller_paired())


class BridgeStandaloneSetupTests(unittest.TestCase):
    """M9: standalone --bridge without flags beyond state/port – automatic TLS
    SANs, usable-URL display, guided first-launch pairing; a paired bridge never
    re-opens pairing on later starts and keeps its persisted certificate."""

    def setUp(self):
        self.buffers = {}

    def spawn(self, state_dir, extra=()):
        process = subprocess.Popen([sys.executable, "-I", str(Path(a.__file__).resolve()),
                                    "--bridge", "--state-dir", str(state_dir), "--port", "0", *extra],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=a.isolated_service_environment(), close_fds=True)
        self.addCleanup(lambda: self.reap(process))
        return process

    @staticmethod
    def reap(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        process.stdout.close()

    def read_line(self, process, timeout=8):
        # One full line per call; leftover bytes stay buffered for the next read.
        buffer = self.buffers.setdefault(process, bytearray())
        deadline = time.monotonic() + timeout
        while True:
            index = buffer.find(b"\n")
            if index >= 0:
                line = bytes(buffer[:index + 1])
                del buffer[:index + 1]
                return line.decode()
            if time.monotonic() >= deadline:
                return None
            readable = select.select([process.stdout], [], [], 0.05)[0]
            if not readable:
                if process.poll() is not None:
                    return None
                continue
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                return None
            buffer.extend(chunk)

    def test_first_launch_guided_pairing_and_paired_restart(self):
        with tempfile.TemporaryDirectory(prefix="aitl-standalone-") as directory:
            state = Path(directory, "state")
            process = self.spawn(state)
            info = json.loads(self.read_line(process))
            self.assertIsNotNone(info["pin"])  # automatic TLS without --tls-name
            lines, code_line = [], None
            for _ in range(32):
                line = self.read_line(process, 4)
                if line is None:
                    break
                lines.append(line)
                if line.startswith("PAIR CODE"):
                    code_line = line
                    break
            # M9 Ergänzung (comment_e6630467): a fresh unpaired standalone start has
            # NO code and NO 2-minute window – only the readiness announcement.
            self.assertIsNone(code_line)
            self.assertTrue(any(line.startswith("Bridge läuft; zurück zur Haupt-App") for line in lines))
            self.assertTrue(any(line.startswith("Nutzbare URLs") for line in lines))
            self.assertTrue(any(line.startswith("SPKI SHA-256: ") for line in lines))
            for line in lines:
                if line.strip().startswith("https://"):
                    self.assertNotIn("0.0.0.0", line)  # wildcard bind is never a URL
            # Explicit --pair stays compatible for operator/service starts.
            self.reap(process)
            paired_process = self.spawn(state, extra=["--pair"])
            info2 = json.loads(self.read_line(paired_process))
            code_line = None
            for _ in range(32):
                line = self.read_line(paired_process, 4)
                if line is None:
                    break
                if line.startswith("PAIR CODE"):
                    code_line = line
                    break
            self.assertIsNotNone(code_line)
            self.assertIn("(10 minutes)", code_line)  # window per Journal100; attempt limits unchanged
            hint = self.read_line(paired_process, 4)
            self.assertIn("--pair", hint or "")  # explicit regeneration guidance only
            url = "https://127.0.0.1:%d" % info2["port"]
            store = a.ConnectionStore(Path(directory, "config"))
            core = a.AppCore(connection_store=store)
            try:
                profile = core.pair_remote(url, info2["pin"], code_line.split(": ", 1)[1].strip())
                self.assertEqual(profile.mode, "REMOTE")
            finally:
                core.close()
            self.reap(paired_process)
            # Later start: persisted identity/auth – no new pairing window.
            second = self.spawn(state)
            info2 = json.loads(self.read_line(second))
            self.assertEqual(info2["pin"], info["pin"])  # certificate/trust persisted
            extra = []
            for _ in range(32):
                line = self.read_line(second, 1.0)
                if line is None:
                    break
                extra.append(line)
                if line.startswith("PAIR CODE"):
                    break
            self.assertFalse(any(line.startswith("PAIR CODE") for line in extra))
            self.assertTrue(any(line.startswith("Bridge läuft; zurück zur Haupt-App") for line in extra))
            self.reap(second)


class PairingHelloContractTests(unittest.TestCase):
    """M9 Ergänzung (comment_e6630467): pairing codes exist only after an explicit
    code-free controller hello (or --pair). Dedup without rotation, already-paired
    never re-pairs, expiry allows conscious regeneration, strict machine-readable
    contract without any secret in the unauthenticated response."""

    def test_store_dedup_no_rotation_and_regeneration_after_expiry(self):
        with tempfile.TemporaryDirectory(prefix="aitl-hello-") as directory:
            store = a.BridgeStore(Path(directory), uuid.uuid4().hex)
            self.addCleanup(store.close)
            state, code = store.hello_pair()
            self.assertEqual((state, code is not None), ("pairing_required", True))
            deadline = store.pair["deadline"]
            state2, code2 = store.hello_pair()
            self.assertEqual((state2, code2), ("pairing_required", None))
            self.assertEqual(store.pair["deadline"], deadline)  # neither rotated nor extended
            # Journal100 window: still valid between 2 and 10 minutes...
            store.clock = lambda: time.time() + 300
            state3, code3 = store.hello_pair()
            self.assertEqual((state3, code3), ("pairing_required", None))  # dedup, no rotation
            self.assertEqual(store.pair["deadline"], deadline)  # code valid until 600s elapsed
            # Mid-window a fresh claim would still succeed; it is not consumed here,
            # because claiming would end the window (single use) and test nothing new.
            # ...expired exactly past the 10-minute boundary, with conscious regeneration.
            store.clock = lambda: time.time() + 601
            with self.assertRaises(a.BridgeError):
                store.claim({"code": code, "request_id": uuid.uuid4().hex})
            state4, code4 = store.hello_pair()
            self.assertEqual(state4, "pairing_required")
            self.assertIsNotNone(code4)
            self.assertNotEqual(code4, code)
            self.assertGreater(store.pair["deadline"], deadline)

    def test_hello_contract_strict_and_secret_free(self):
        class Session:
            def __init__(self, payload):
                self.payload, self.sent = payload, bytearray()
            def settimeout(self, _timeout):
                pass
            def sendall(self, data):
                self.sent.extend(data)
            def recv(self, _size):
                data, self.payload = self.payload[:1024], b""
                return data
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
        class Context:
            check_hostname = None
            verify_mode = None
            def __init__(self, session):
                self.session = session
            def wrap_socket(self, raw, server_hostname=None):
                return self.session
        def call(payload):
            session = Session(payload)
            with mock.patch.object(a.ssl, "SSLContext", return_value=Context(session)), \
                 mock.patch.object(a.socket, "create_connection", return_value=session):
                return a.bridge_hello("https://127.0.0.1:8443")
        ok = b'HTTP/1.1 200 OK\r\n\r\n{"version": 1, "state": "pairing_required"}'
        self.assertEqual(call(ok), "pairing_required")
        for bad, code in ((b"HTTP/1.1 401 Unauthorized\r\n\r\n{\"error\": \"unauthorized\"}", "pairing_contract"),
                          (b"HTTP/1.1 429 Too Many Requests\r\n\r\n{\"error\": \"rate_limit\"}", "pairing_rate_limited"),
                          (b'HTTP/1.1 200 OK\r\n\r\n{"version": 1, "state": "pairing_required", "code": "ABCD-EFGH-JKMN"}', "pairing_contract"),
                          (b'HTTP/1.1 200 OK\r\n\r\n{"version": 1, "state": "success"}', "pairing_contract"),
                          (b"HTTP/1.1 200 OK\r\n\r\nnot json", "pairing_contract")):
            with self.assertRaises(a.ProbeError) as failure:
                call(bad)
            self.assertEqual(str(failure.exception), code)

    def test_real_bridge_hello_triggers_local_code_then_full_pairing(self):
        with tempfile.TemporaryDirectory(prefix="aitl-hello-e2e-") as directory:
            state_dir = Path(directory, "state")
            state_dir.mkdir()
            os.chmod(state_dir, 0o700)
            process = subprocess.Popen([sys.executable, "-I", str(Path(a.__file__).resolve()),
                                        "--bridge", "--state-dir", str(state_dir), "--port", "0"],
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env=a.isolated_service_environment(), close_fds=True)
            self.addCleanup(lambda: self.reap(process))
            buffer = bytearray()
            def read_line(timeout=8):
                deadline = time.monotonic() + timeout
                while True:
                    index = buffer.find(b"\n")
                    if index >= 0:
                        line = bytes(buffer[:index + 1])
                        del buffer[:index + 1]
                        return line.decode()
                    if time.monotonic() >= deadline:
                        return None
                    if select.select([process.stdout], [], [], 0.05)[0]:
                        chunk = os.read(process.stdout.fileno(), 4096)
                        if not chunk:
                            return None
                        buffer.extend(chunk)
            info = json.loads(read_line())
            url = "https://127.0.0.1:%d" % info["port"]
            seen = []
            while (line := read_line(1.0)) is not None:
                seen.append(line)
            self.assertFalse(any(line.startswith("PAIR CODE") for line in seen))
            self.assertEqual(a.bridge_hello(url), "pairing_required")  # hello itself authorises nothing
            code_line = None
            for _ in range(8):
                line = read_line(4)
                if line is None:
                    break
                code_line = line if line.startswith("PAIR CODE") else code_line
                if code_line:
                    break
            self.assertIsNotNone(code_line)  # the code appears only on the LOCAL console
            code = code_line.split(": ", 1)[1].strip()
            hint = read_line(4)  # regeneration guidance belongs to the code output
            self.assertTrue(hint and ("Hallo" in hint or "--pair" in hint))
            self.assertEqual(a.bridge_hello(url), "pairing_required")  # dedup: no reprint, no rotation
            self.assertIsNone(read_line(0.6))
            core = a.AppCore(connection_store=a.ConnectionStore(Path(directory, "cfg")))
            try:
                core.pair_remote(url, info["pin"], code)
                self.assertEqual(a.bridge_hello(url), "already_paired")  # never re-pair via hello
                with self.assertRaises(a.ProbeError):
                    core.pair_remote(url, info["pin"], code)  # replay after single consumption
            finally:
                core.close()

    @staticmethod
    def reap(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        process.stdout.close()


class QrexecBridgeFirstTests(unittest.TestCase):
    """M9 Folgeanpassung (bridge-first): ONE primary check action idempotently starts
    the own forwarder and proves real unauthenticated reachability; evidenced
    failures stay separate from possible causes; pairing stays the last step and
    the 2-minute code limit only allows explicit local regeneration."""

    LAUNCHER = (
        "#!/bin/bash --\n"
        "set -e\n"
        "LOCALPORT=\"$(echo \"$1\" | cut -d ':' -f1)\"\n"
        "TARGET=\"$(echo \"$1\" | cut -d ':' -f2)\"\n"
        "PORT=\"$(echo \"$1\" | cut -d ':' -f3)\"\n"
        "echo \"Binding TCP '$TARGET:$PORT' to 'localhost:$LOCALPORT'...\"\n"
        "\"$(dirname \"$0\")/qvm-connect-tcp-forwarder\" \"$LOCALPORT\" \"$TARGET\" \"$PORT\" "
        ">/dev/null 2>&1 &\n")
    PROXY = (
        "#!" + str(Path(sys.executable).resolve()) + "\n"
        "import os, socket, sys, threading\n"
        "local, target, remote = sys.argv[1:4]\n"
        "up_port = int(os.environ.get('AITL_TEST_REMOTE_PORT') or remote)\n"
        "srv = socket.socket()\n"
        "srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "srv.bind(('127.0.0.1', int(local)))\n"
        "srv.listen(5)\n"
        "def pump(a, b):\n"
        "    try:\n"
        "        while True:\n"
        "            data = a.recv(8192)\n"
        "            if not data:\n"
        "                break\n"
        "            b.sendall(data)\n"
        "    except OSError:\n"
        "        pass\n"
        "    for side in (a, b):\n"
        "        try:\n"
        "            side.shutdown(socket.SHUT_RDWR)\n"
        "        except OSError:\n"
        "            pass\n"
        "        side.close()\n"
        "while True:\n"
        "    conn, _ = srv.accept()\n"
        "    if target == 'denyqube':\n"
        "        conn.close()\n"
        "        continue\n"
        "    if target == 'plainqube':\n"
        "        conn.sendall(b'NOPE NOT TLS\\r\\n')\n"
        "        conn.close()\n"
        "        continue\n"
        "    upstream = socket.socket()\n"
        "    upstream.settimeout(3)\n"
        "    try:\n"
        "        upstream.connect(('127.0.0.1', up_port))\n"
        "    except OSError:\n"
        "        conn.close()\n"
        "        continue\n"
        "    threading.Thread(target=pump, args=(conn, upstream), daemon=True).start()\n"
        "    threading.Thread(target=pump, args=(upstream, conn), daemon=True).start()\n")
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-bridgefirst-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        binary = self.base / "qvm-connect-tcp"
        proxy = self.base / "qvm-connect-tcp-forwarder"
        binary.write_text(self.LAUNCHER)
        proxy.write_text(self.PROXY)
        binary.chmod(0o755); proxy.chmod(0o755)
        patcher = mock.patch.object(a.shutil, "which", return_value=str(binary))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bridge = RemoteFixture(self.base / "bridge")  # real standalone TLS bridge
        self.addCleanup(self.bridge.close)
        self.bridge_port = int(self.bridge.url.rsplit(":", 1)[1])
        self.bridge_pin = self.bridge.pin

    def make_core(self):
        core = a.AppCore(connection_store=a.ConnectionStore(self.base / ("cfg-" + uuid.uuid4().hex)))
        self.addCleanup(core.close)
        return core

    def free_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def verify_with_env(self, target, port, remote_port):
        core = self.make_core()
        with mock.patch.dict(os.environ, {"AITL_TEST_REMOTE_PORT": str(remote_port)}):
            return core.verify_qrexec_connection(target, port)

    def test_reachable_existing_grant_passes_and_persists(self):
        core = self.make_core()
        port = self.free_port()
        with mock.patch.dict(os.environ, {"AITL_TEST_REMOTE_PORT": str(self.bridge_port)}):
            result = core.verify_qrexec_connection("fwdqube", port)
        self.assertEqual(result["phase"], "bridge_reachable")
        self.assertTrue(result["reachable"])
        self.assertEqual(result["observed_pin"], self.bridge.pin)  # independent comparison source
        self.assertEqual(core.qrexec, {"target": "fwdqube", "port": port})
        self.assertEqual(core.connection_store.load_connection()["qrexec"], {"target": "fwdqube", "port": port})
        first_pgid = core.qrexec_forwarder.pgid
        self.assertTrue(core.qrexec_forwarder.running)  # launcher exitete, unsere Gruppe besitzt
        with mock.patch.dict(os.environ, {"AITL_TEST_REMOTE_PORT": str(self.bridge_port)}):
            again = core.verify_qrexec_connection("fwdqube", port)  # "Erneut prüfen": idempotent
        self.assertTrue(again["reachable"])
        self.assertEqual(core.qrexec_forwarder.pgid, first_pgid)  # no double forwarder group

    def test_deny_down_plain_are_evidenced_separately_not_blanket_policy(self):
        text = a.ConnectionDialog.error_text
        dead = str(self.free_port())  # nothing listening: "target down"
        live = str(self.bridge_port)
        denied = self.verify_with_env("denyqube", self.free_port(), live)
        down = self.verify_with_env("downqube", self.free_port(), dead)
        plain = self.verify_with_env("plainqube", self.free_port(), live)
        self.assertEqual(denied["phase"], "qrexec_target_unreachable")
        self.assertEqual(down["phase"], "qrexec_target_unreachable")
        self.assertEqual(plain["phase"], "tls_handshake_failed")
        message = text("qrexec_target_unreachable")
        self.assertIn("Bridge", message)
        self.assertIn("Qrexec-Freigabe", message)
        self.assertIn("welche Ursache vorliegt, ist noch offen", message)
        self.assertNotEqual(message.strip(), "Policy fehlt.")
        self.assertNotIn("Policy", text("tls_handshake_failed"))  # TLS is a separate evidenced phase

    def test_port_conflict_foreign_listener_untouched(self):
        core = self.make_core()
        foreign = socket.socket()
        foreign.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        foreign.bind(("127.0.0.1", 0))
        foreign.listen(1)
        self.addCleanup(foreign.close)
        with mock.patch.dict(os.environ, {"AITL_TEST_REMOTE_PORT": str(self.bridge_port)}):
            result = core.verify_qrexec_connection("fwdqube", foreign.getsockname()[1])
        self.assertEqual(result["phase"], "qrexec_port_conflict")
        self.assertFalse(core.qrexec_forwarder.running)
        with socket.socket() as probe:
            probe.settimeout(1)
            self.assertEqual(probe.connect_ex(("127.0.0.1", foreign.getsockname()[1])), 0)

    def test_pinned_certificate_change_is_evidenced_not_silent(self):
        port = self.free_port()
        store = a.ConnectionStore(self.base / ("cfg-pin-" + uuid.uuid4().hex))
        profile = a.ConnectionProfile("https://127.0.0.1:%d" % port, "1" * 64,
                                      "0" * 32, "0" * 32, "0" * 64)
        store.save_connection(profile, None, {"target": "fwdqube", "port": port})
        core = a.AppCore(connection_store=store)
        self.addCleanup(core.close)
        with mock.patch.dict(os.environ, {"AITL_TEST_REMOTE_PORT": str(self.bridge_port)}):
            result = core.verify_qrexec_connection("fwdqube", port)
        self.assertEqual(result["phase"], "pin_mismatch")
        self.assertFalse(result["reachable"])

    def test_pairing_code_expiry_and_explicit_local_regeneration(self):
        with tempfile.TemporaryDirectory(prefix="aitl-codeexpiry-") as directory:
            store = a.BridgeStore(Path(directory), uuid.uuid4().hex)
            self.addCleanup(store.close)
            code = store.open_pair()
            store.clock = lambda: time.time() + 601  # 10-minute window elapsed
            with self.assertRaises(a.BridgeError):
                store.claim({"code": code, "request_id": uuid.uuid4().hex})
            # Explicit local regeneration is allowed; limits stay 10 minutes/5 failures.
            fresh = store.open_pair()
            store.clock = time.time
            claim = store.claim({"code": fresh, "request_id": uuid.uuid4().hex})
            self.assertEqual(claim["state"], "PAIR_PENDING")


if __name__ == "__main__":
    unittest.main(testRunner=unittest.TextTestRunner(verbosity=2, resultclass=a.SafeResult))
