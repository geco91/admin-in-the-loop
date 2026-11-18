"""Durable F1–F4 regressions from the preserved independent 797cd8b probes.

Local HTTP/MCP fixtures only; no hosted tunnel or production state.
"""
import base64
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
from test_connected_mvp import ServiceHarness, request


class ChatBindingReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chatbind-fix-")
        self.addCleanup(self.temp.cleanup)
        self.now = 1800000000.0
        self.store = a.BridgeStore(self.temp.name, uuid.uuid4().hex, clock=lambda: self.now)
        self.controller, self.cid = self.store.issue("CONTROLLER")
        self.ai, self.aid = self.store.issue("AI")
        self.harness = ServiceHarness(self.store, self.controller, self.cid, self.ai, self.aid)
        self.addCleanup(self.harness.close)
        self.code = self.store.chat_binding["code"]
        self.url = "https://callback.example/same-subscription"
        self.secret = "whsec_" + base64.b64encode(b"r" * 24).decode()
        self.store.on_new_output = None

    def rpc(self, method, params, ai=None, *, modern=True):
        value = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method, "params": dict(params)}
        headers = {"X-AITL-AI-Key": ai or self.ai}
        if modern:
            value["params"]["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                                       "io.modelcontextprotocol/clientCapabilities": {}}
            headers["MCP-Protocol-Version"] = "2026-07-28"
        status, raw = request(self.harness.mcp_url, "POST", body=value, headers=headers)
        self.assertEqual(status, 200)
        return json.loads(raw)

    def subscribe(self, code):
        return self.rpc("events/subscribe", {"name": a.BRIDGE_EVENT_NAME,
            "arguments": {"conversation": code},
            "delivery": {"mode": "webhook", "url": self.url, "secret": self.secret}})["result"]["id"]

    def output_tool(self, arguments=None, name="get_approved_output", ai=None, code=None, *, modern=True):
        return self.rpc("tools/call", {"name": name, "arguments": dict(arguments or {},
                        conversation=self.code if code is None else code)}, ai=ai, modern=modern)["result"]

    def shared_output(self, content="synthetic approved text", bound=False):
        submission = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"] if bound else None
        result = self.store.approved_output({"version": 1, "conversation": self.store.conversation,
            "idempotency_key": uuid.uuid4().hex, "text": content,
            "submission_id": submission, "approved_at": self.now})
        return result["output_id"], submission

    def acknowledge(self, item, **kwargs):
        return self.output_tool({"output_id": item["output_id"], "receipt": item["receipt"]},
                                name="acknowledge_output", **kwargs)

    def pending_read(self, arguments=None, *, ai=None):
        # Store selection before HTTP writes the response, for receipt validation tests.
        principal = self.store.authenticate(ai or self.ai, "AI")
        return self.store.ai_output(principal, arguments or {})

    def test_new_chat_pulls_latest_once_without_needing_ack_tool_or_cursor(self):
        older, older_submission = self.shared_output("older approved text", bound=True)
        newest, submission = self.shared_output("latest approved text", bound=True)
        response = self.output_tool(modern=False)
        page = response["structuredContent"]
        item, = page["outputs"]
        self.assertEqual(item["output_id"], newest)
        self.assertEqual(response["content"][item["text_content_index"]]["text"], "latest approved text")
        self.harness.wait(lambda: not self.store.submission_status(submission)["approved_output_available"])
        self.assertTrue(self.store.submission_status(submission)["output_shared_ever"])

        second_ai, _ = self.store.issue("AI")
        for arguments in ({}, {"submission_id": submission}, {"output_id": newest}):
            for token in (self.ai, second_ai):
                with self.subTest(arguments=arguments, same_token=token == self.ai):
                    self.assertEqual(self.output_tool(arguments, ai=token)["structuredContent"]["outputs"], [])
        self.assertEqual(self.store.execute("SELECT text FROM outputs WHERE id=?", (newest,)).fetchone()[0], "")
        self.assertTrue(self.store.submission_status(older_submission)["approved_output_available"])
        targeted = self.output_tool({"submission_id": older_submission})["structuredContent"]
        self.assertEqual(targeted["outputs"][0]["output_id"], older)
        fresh, _ = self.shared_output("freshly approved text")
        following = self.output_tool({"cursor": page["cursor"]})["structuredContent"]
        self.assertEqual(following["outputs"][0]["output_id"], fresh)

    def test_parallel_read_reserves_one_response_and_interrupted_write_leaves_text_pending(self):
        respond = a.BridgeRequestHandler._respond
        for successful_write in (True, False):
            with self.subTest(successful_write=successful_write):
                identifier, _ = self.shared_output()
                writing, release = threading.Event(), threading.Event()

                def pause_response(handler, status, value=None):
                    if (value or {}).get("result", {}).get("structuredContent", {}).get("outputs"):
                        writing.set()
                        if not release.wait(5):
                            raise TimeoutError("fixture stalled")
                        if not successful_write:
                            with mock.patch.object(handler, "end_headers", side_effect=BrokenPipeError):
                                return respond(handler, status, value)
                    return respond(handler, status, value)

                with ThreadPoolExecutor(max_workers=1) as executor, \
                        mock.patch.object(a.BridgeRequestHandler, "_respond", pause_response):
                    pending = executor.submit(self.output_tool)
                    try:
                        self.assertTrue(writing.wait(5))
                        request_by_id = self.output_tool({"output_id": identifier})["structuredContent"]
                        self.assertEqual(request_by_id["outputs"], [])
                    finally:
                        release.set()
                    if successful_write:
                        self.assertEqual(pending.result(timeout=5)["structuredContent"]["outputs"][0]["output_id"],
                                         identifier)
                    else:
                        with self.assertRaises(http.client.RemoteDisconnected):
                            pending.result(timeout=5)
                self.assertTrue(self.harness.service.wait_idle())
                retry = self.output_tool()["structuredContent"]["outputs"]
                self.assertEqual([item["output_id"] for item in retry], [] if successful_write else [identifier])

    def test_read_ack_still_idempotent_and_controller_retry_never_restores_text(self):
        identifier, submission = self.shared_output(bound=True)
        first = self.output_tool()["structuredContent"]["outputs"][0]
        for _ in range(2):  # includes a lost ACK response
            self.assertEqual(self.acknowledge(first)["structuredContent"]["state"], "ACKNOWLEDGED")
        self.assertEqual(self.output_tool()["structuredContent"]["outputs"], [])
        self.assertFalse(self.store.submission_status(submission)["approved_output_available"])
        for arguments in ({"output_id": identifier}, {"submission_id": submission}):
            self.assertEqual(self.output_tool(arguments)["structuredContent"]["outputs"], [])
        key = self.store.execute("SELECT idem FROM outputs WHERE id=?", (identifier,)).fetchone()[0]
        self.assertEqual(self.store.approved_output({"version": 1, "conversation": self.store.conversation,
            "idempotency_key": key, "text": "synthetic approved text", "submission_id": submission,
            "approved_at": self.now})["output_id"], identifier)
        self.assertEqual(self.store.execute("SELECT text FROM outputs WHERE id=?", (identifier,)).fetchone()[0], "")
        self.assertEqual(self.output_tool()["structuredContent"]["outputs"], [])
        self.now += a.BRIDGE_RETENTION + 1
        self.store.cleanup()
        self.assertIsNone(self.store.execute("SELECT id FROM outputs WHERE id=?", (identifier,)).fetchone())

    def test_expired_unknown_and_legacy_cursor_reset_to_latest_pending_output(self):
        first, _ = self.shared_output("first")
        page = self.output_tool()["structuredContent"]
        self.assertEqual(page["outputs"][0]["output_id"], first)
        second, _ = self.shared_output("second")
        later = self.pending_read({"cursor": page["cursor"]})
        self.assertEqual(later["outputs"][0]["output_id"], second)
        self.store.execute("UPDATE cursors SET expires=? WHERE id=?", (self.now, later["cursor"]))
        for cursor in (later["cursor"], uuid.uuid4().hex, self.store.cursor(self.aid, "OUTPUT", 9999)):
            reset = self.pending_read({"cursor": cursor})
            self.assertTrue(reset["cursor_reset"])
            self.assertEqual(reset["outputs"][0]["output_id"], second)

    def test_delivered_and_pending_output_survive_restart_and_cycle_cursor_reset(self):
        first, _ = self.shared_output("delivered")
        page = self.output_tool()["structuredContent"]
        self.assertTrue(self.harness.service.wait_idle())
        second, _ = self.shared_output("still pending")
        unread = self.pending_read({"cursor": page["cursor"]})
        reopened = a.BridgeStore(self.temp.name, self.store.conversation, clock=lambda: self.now, new_cycle=True)
        self.addCleanup(reopened.close)
        principal = reopened.authenticate(self.ai, "AI")
        reset = reopened.ai_output(principal, {"cursor": unread["cursor"]})
        self.assertTrue(reset["cursor_reset"])
        self.assertEqual(reset["outputs"][0]["output_id"], second)
        self.assertEqual(reopened.ai_output(principal, {"output_id": first})["outputs"], [])
        confirmed = page["outputs"][0]
        self.assertEqual(reopened.acknowledge_output(principal,
            {"output_id": confirmed["output_id"], "receipt": confirmed["receipt"]}, 1)["state"], "ACKNOWLEDGED")

    def test_clients_cannot_use_each_others_read_receipts(self):
        identifier, _ = self.shared_output()
        second_ai, _ = self.store.issue("AI")
        first = self.pending_read()["outputs"][0]
        second = self.pending_read(ai=second_ai)["outputs"][0]
        self.assertTrue(self.acknowledge(first, code="WRONG000")["isError"])
        missing_code = self.rpc("tools/call", {"name": "acknowledge_output", "arguments": {
            "output_id": identifier, "receipt": first["receipt"]}})["result"]
        self.assertTrue(missing_code["isError"])
        self.assertIsNone(self.store.execute("SELECT consumed_at FROM outputs WHERE id=?", (identifier,)).fetchone()[0])
        self.assertTrue(self.acknowledge(first, ai=second_ai)["isError"])
        self.assertTrue(self.output_tool({"cursor": first["receipt"]}, ai=second_ai)["isError"])
        self.assertFalse(self.acknowledge(second, ai=second_ai)["isError"])
        self.assertFalse(self.acknowledge(first)["isError"])
        self.assertEqual(self.output_tool()["structuredContent"]["outputs"], [])
        self.assertTrue(self.output_tool({"output_id": identifier}, code="WRONG000")["isError"])

    def test_named_cursor_cannot_skip_general_unread_and_selector_conflicts_are_rejected(self):
        first, _ = self.shared_output("first")
        second, submission = self.shared_output("second", bound=True)
        named = self.output_tool({"output_id": first})["structuredContent"]
        self.assertTrue(self.output_tool({"cursor": named["cursor"]})["isError"])
        self.assertEqual(self.output_tool()["structuredContent"]["outputs"][0]["output_id"], second)
        self.assertTrue(self.output_tool({"output_id": second, "submission_id": submission})["isError"])

    def test_forged_expired_and_old_generation_receipts_do_not_consume(self):
        identifier, _ = self.shared_output()
        item = self.pending_read()["outputs"][0]
        forged = dict(item, receipt=uuid.uuid4().hex)
        self.assertTrue(self.acknowledge(forged)["isError"])
        self.store.execute("UPDATE cursors SET expires=? WHERE id=?", (self.now, item["receipt"]))
        self.assertTrue(self.acknowledge(item)["isError"])
        item = self.pending_read()["outputs"][0]
        self.code = self.rotate()["code"]
        self.assertTrue(self.acknowledge(item)["isError"])
        current = self.pending_read()["outputs"][0]
        self.assertFalse(self.acknowledge(current)["isError"])
        self.assertEqual(self.store.execute("SELECT text FROM outputs WHERE id=?", (identifier,)).fetchone()[0], "")

    def test_notification_ack_does_not_consume_bound_or_unbound_text_and_late_event_is_skipped(self):
        subscription = self.subscribe(self.code)
        for bound in (False, True):
            identifier, submission = self.shared_output(bound=bound)
            with self.harness.service.jobs_cv:
                self.harness.service.queue_output_events(identifier, submission, self.now + a.BRIDGE_RETENTION)
                job = self.harness.service.jobs.pop()
            with mock.patch.object(self.harness.service, "webhook_call", return_value=(200, b"")):
                self.harness.service.deliver(job)
            self.assertEqual(self.store.execute("SELECT delivered,consumed_at FROM outputs WHERE id=?",
                                               (identifier,)).fetchone()[:], (1, None))
            item = self.output_tool()["structuredContent"]["outputs"][0]
            self.assertEqual(item["output_id"], identifier)
            self.assertTrue(self.harness.service.wait_idle())
            with mock.patch.object(self.harness.service, "webhook_call") as send:
                self.harness.service.deliver(job)
                send.assert_not_called()

    def test_ack_rechecks_external_revocation_and_storage_failure_keeps_output_pending(self):
        identifier, _ = self.shared_output()
        item = self.pending_read()["outputs"][0]
        value = {"output_id": identifier, "receipt": item["receipt"]}
        principal = self.store.authenticate(self.ai, "AI")
        execute = self.store.execute
        def fail(sql, params=()):
            if sql.startswith("UPDATE outputs SET consumed_at"):
                raise sqlite3.OperationalError("fixture storage failure")
            return execute(sql, params)
        with mock.patch.object(self.store, "execute", side_effect=fail):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.acknowledge_output(principal, value, 1)
        self.assertIsNone(self.store.execute("SELECT consumed_at FROM outputs WHERE id=?", (identifier,)).fetchone()[0])
        external = sqlite3.connect(Path(self.temp.name) / "bridge.sqlite3", isolation_level=None)
        self.addCleanup(external.close)
        def revoke(sql, params=()):
            if sql.startswith("UPDATE outputs SET consumed_at"):
                external.execute("DELETE FROM tokens WHERE id=?", (self.aid,))
            return execute(sql, params)
        with mock.patch.object(self.store, "execute", side_effect=revoke):
            with self.assertRaisesRegex(a.BridgeError, "unauthorized"):
                self.store.acknowledge_output(principal, value, 1)
        self.assertIsNone(self.store.execute("SELECT consumed_at FROM outputs WHERE id=?", (identifier,)).fetchone()[0])

    def test_read_ack_sql_rechecks_persisted_chat_binding_deadline(self):
        identifier, _ = self.shared_output()
        item = self.pending_read()["outputs"][0]
        principal = self.store.authenticate(self.ai, "AI")
        external = sqlite3.connect(Path(self.temp.name) / "bridge.sqlite3", isolation_level=None)
        self.addCleanup(external.close)
        execute = self.store.execute
        def expire(sql, params=()):
            if sql.startswith("UPDATE outputs SET consumed_at"):
                binding = dict(self.store.chat_binding, expires_at=self.now)
                external.execute("UPDATE meta SET value=? WHERE key='chat_binding'", (json.dumps(binding),))
            return execute(sql, params)
        with mock.patch.object(self.store, "execute", side_effect=expire):
            with self.assertRaisesRegex(a.BridgeError, "unauthorized"):
                self.store.acknowledge_output(principal,
                    {"output_id": identifier, "receipt": item["receipt"]}, 1)
        self.assertIsNone(self.store.execute("SELECT consumed_at FROM outputs WHERE id=?", (identifier,)).fetchone()[0])

    def test_upgrade_clears_confirmed_text_and_expiry_does_not_reopen_older_general_output(self):
        older, _ = self.shared_output("unconfirmed legacy share")
        latest, _ = self.shared_output("previously acknowledged legacy share")
        self.store.execute("UPDATE outputs SET consumed_at=? WHERE id=?", (self.now, latest))
        reopened = a.BridgeStore(self.temp.name, self.store.conversation, clock=lambda: self.now)
        self.addCleanup(reopened.close)
        principal = reopened.authenticate(self.ai, "AI")
        self.assertEqual(reopened.execute("SELECT text FROM outputs WHERE id=?", (latest,)).fetchone()[0], "")
        self.assertEqual(reopened.ai_output(principal, {"output_id": latest})["outputs"], [])
        self.assertEqual(reopened.ai_output(principal, {})["outputs"], [])
        reopened.execute("UPDATE outputs SET expires=? WHERE id=?", (self.now, latest))
        reopened.cleanup()
        self.assertEqual(reopened.ai_output(principal, {})["outputs"], [])
        self.assertEqual(reopened.ai_output(principal, {"output_id": older})["outputs"][0]["output_id"], older)

    def test_upgrade_does_not_guess_reads_from_old_notification_ack_or_delete_output(self):
        identifier, _ = self.shared_output("legacy retained output")
        self.store.execute("UPDATE outputs SET delivered=1,delivered_at=? WHERE id=?", (self.now, identifier))
        self.store.execute("ALTER TABLE outputs DROP COLUMN consumed_at")
        reopened = a.BridgeStore(self.temp.name, self.store.conversation, clock=lambda: self.now)
        self.addCleanup(reopened.close)
        page = reopened.ai_output(reopened.authenticate(self.ai, "AI"), {})
        self.assertEqual(page["outputs"][0]["output_id"], identifier)
        self.assertFalse(page["outputs"][0]["acknowledged"])
        self.assertEqual(reopened.execute("SELECT text,delivered FROM outputs WHERE id=?", (identifier,)).fetchone()[:],
                         ("legacy retained output", 1))

    def rotate(self):
        return a.BridgeHTTP(self.harness.profile).request("POST", "/v1/chat-binding/rotate", {
            "version": 1, "request_id": uuid.uuid4().hex,
            "expected_generation": self.store.chat_binding["generation"]})

    def output_and_job(self, identifier):
        submission = self.store.submit({"request_id": uuid.uuid4().hex, "text": "true"})["submission_id"]
        output = a.BridgeHTTP(self.harness.profile).request("POST", "/v1/approved-output", {
            "version": 1, "conversation": self.store.conversation, "idempotency_key": uuid.uuid4().hex,
            "text": "HUMAN_APPROVED_FIXTURE", "submission_id": submission, "approved_at": self.now})
        job = {"subscription": self.store.active_subscription(identifier, self.now),
               "attempts": 0, "ready": 0,
               "event": {"eventId": output["output_id"], "name": a.BRIDGE_EVENT_NAME,
                         "data": {"submission_id": submission, "output_id": output["output_id"],
                                  "expires_at": self.now + a.BRIDGE_RETENTION}}}
        return output, submission, job

    def assert_pending(self, output, submission):
        row = self.store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                                 (output["output_id"],)).fetchone()
        self.assertEqual(tuple(row), (0, None))
        self.assertTrue(self.store.submission_status(submission)["approved_output_available"])

    def test_old_ack_cannot_consume_after_same_id_resubscribe(self):
        identifier = self.subscribe(self.code)
        output, submission, job = self.output_and_job(identifier)

        def ack(*_, **__):
            rotated = self.rotate()
            self.assertEqual(self.subscribe(rotated["code"]), identifier)
            return 200, b""

        with mock.patch.object(self.harness.service, "webhook_call", side_effect=ack):
            self.harness.service.deliver(job)
        self.assert_pending(output, submission)

    def test_old_queued_job_does_not_rebind(self):
        identifier = self.subscribe(self.code)
        output, submission, job = self.output_and_job(identifier)
        self.assertEqual(self.subscribe(self.rotate()["code"]), identifier)
        with mock.patch.object(self.harness.service, "webhook_call", return_value=(200, b"")) as send:
            self.harness.service.deliver(job)
        send.assert_not_called()
        self.assert_pending(output, submission)

    def test_retry_preserves_original_generation(self):
        identifier = self.subscribe(self.code)
        output, submission, job = self.output_and_job(identifier)
        with mock.patch.object(self.harness.service, "webhook_call", side_effect=a.WebhookFailure(
                "http_5xx", retryable=True)):
            self.harness.service.deliver(job)
        with self.harness.service.jobs_cv:
            retry = self.harness.service.jobs.pop()
        self.assertEqual(retry["subscription"]["binding_generation"], 1)
        self.assertEqual(self.subscribe(self.rotate()["code"]), identifier)
        with mock.patch.object(self.harness.service, "webhook_call", return_value=(200, b"")) as send:
            self.harness.service.deliver(retry)
        send.assert_not_called()
        self.assert_pending(output, submission)

    def test_ack_sql_rechecks_persisted_binding_deadline(self):
        identifier = self.subscribe(self.code)
        output, submission, job = self.output_and_job(identifier)
        active = self.store.active_subscription
        external = sqlite3.connect(Path(self.temp.name, "bridge.sqlite3"), isolation_level=None)
        self.addCleanup(external.close)

        def expire_after_check(*args):
            row = active(*args)
            binding = dict(self.store.chat_binding, expires_at=self.now)
            external.execute("UPDATE meta SET value=? WHERE key='chat_binding'", (json.dumps(binding),))
            return row

        with mock.patch.object(self.store, "active_subscription", side_effect=expire_after_check):
            self.assertFalse(self.store.mark_delivered(output["output_id"], identifier,
                                                       job["subscription"]["binding_generation"]))
        self.assert_pending(output, submission)

    def test_healthy_ack_and_expiry_before_ack(self):
        identifier = self.subscribe(self.code)
        output, _, job = self.output_and_job(identifier)
        with mock.patch.object(self.harness.service, "webhook_call", return_value=(200, b"")):
            self.harness.service.deliver(job)
        self.assertEqual(self.store.execute("SELECT delivered FROM outputs WHERE id=?",
                                            (output["output_id"],)).fetchone()[0], 1)
        output, _, job = self.output_and_job(identifier)

        def expired_ack(*_, **__):
            self.now = self.store.chat_binding["expires_at"]
            return 200, b""

        with mock.patch.object(self.harness.service, "webhook_call", side_effect=expired_ack):
            self.harness.service.deliver(job)
        self.assertEqual(self.store.execute("SELECT delivered,delivered_at FROM outputs WHERE id=?",
                                            (output["output_id"],)).fetchone()[:], (0, None))

    def test_storage_failure_rolls_back_both_new_and_existing_counters(self):
        original = self.store._save_attempt

        def save(principal, state):
            if principal == "*":
                raise sqlite3.OperationalError("fixture storage failure")
            return original(principal, state)

        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    with self.assertRaisesRegex(a.BridgeError, "conversation_binding_required"):
                        self.store.authorize_chat_binding(self.aid, "WRONG000")
                before = [tuple(row) for row in self.store.execute(
                    "SELECT * FROM chat_binding_attempts ORDER BY principal").fetchall()]
                with mock.patch.object(self.store, "_save_attempt", side_effect=save):
                    status, _ = request(self.harness.mcp_url, "POST", body={"jsonrpc": "2.0", "id": 1,
                        "method": "tools/call", "params": {"name": "get_preferences",
                        "arguments": {"conversation": "WRONG000"}}}, headers={"X-AITL-AI-Key": self.ai})
                self.assertEqual(status, 500)
                after = [tuple(row) for row in self.store.execute(
                    "SELECT * FROM chat_binding_attempts ORDER BY principal").fetchall()]
                self.assertEqual(after, before)
                self.assertFalse(self.store.db.in_transaction)

    def test_corrupt_lockout_is_not_reset_by_success(self):
        for index in range(12):
            with self.assertRaises(a.BridgeError):
                self.store.authorize_chat_binding(self.aid, "WRONG000")
            if 3 <= index < 11:
                self.now += a._bridge_component["BRIDGE_CHAT_BACKOFF"][index - 3]
        self.store.execute("UPDATE chat_binding_attempts SET locked_until=NULL WHERE principal=?", (self.aid,))
        with self.assertRaisesRegex(a.BridgeError, "chat_binding_state_invalid"):
            self.store.authorize_chat_binding(self.aid, self.code)
        self.assertEqual(self.store.execute("SELECT failures FROM chat_binding_attempts WHERE principal=?",
                                            (self.aid,)).fetchone()[0], 12)

    def test_corrupt_backoff_and_aggregate_fail_closed(self):
        for _ in range(4):
            with self.assertRaises(a.BridgeError):
                self.store.authorize_chat_binding(self.aid, "WRONG000")
        self.store.execute("UPDATE chat_binding_attempts SET next_allowed=NULL WHERE principal=?", (self.aid,))
        with self.assertRaisesRegex(a.BridgeError, "chat_binding_state_invalid"):
            self.store.authorize_chat_binding(self.aid, self.code)
        self.rotate()
        with self.assertRaises(a.BridgeError):
            self.store.authorize_chat_binding(self.aid, "WRONG000")
        self.store.execute("UPDATE chat_binding_attempts SET failures=2 WHERE principal='*'")
        with self.assertRaisesRegex(a.BridgeError, "chat_binding_state_invalid"):
            self.store.authorize_chat_binding(self.aid, self.store.chat_binding["code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
