"""Adapter boundary tests: self-created fake analyzers, never upstream sh-guard.

Commands remain data. All files/processes are private temporary fixtures; no UI,
download, pin admission, production terminal or hosted service is involved.
"""
import copy
import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a


def analysis(command="printf x\n", score=0):
    level = "safe" if score <= 20 else "caution" if score <= 50 else "danger" if score <= 80 else "critical"
    return {"command": command, "score": score, "level": level,
            "quick_decision": "safe" if score <= 20 else "risky" if score <= 80 else "blocked",
            "reason": "Controlled fixture evidence", "risk_factors": [], "sub_commands": [],
            "pipeline_flow": None, "mitre_mappings": [], "parse_confidence": "full"}


def rich_analysis():
    value = analysis(score=100)
    value["risk_factors"] = ["pipe_to_execution"]
    value["sub_commands"] = [{
        "command": "printf x", "executable": "printf", "intent": ["info"],
        "targets": [{"path": None, "scope": "none", "sensitivity": "normal"}],
        "flags": [{"flag": "--fixture", "modifier": -128,
                   "risk_factor": "write", "description": "Fixture"}],
        "score": 0, "risk_factors": [], "reversibility": "reversible",
        "capabilities": ["command"]}]
    value["pipeline_flow"] = {
        "flow_type": "mixed", "composite_score": 100,
        "taint_flows": [{"source": {"type": "sensitive_file", "path": "/fixture"},
                         "propagators": ["passthrough", {"encoding": {"method": "base64"}},
                                         "filtering", "aggregation"],
                         "sink": {"type": "file_write", "path": "/fixture-out"},
                         "escalation": 255, "escalation_reason": "Fixture"}]}
    value["mitre_mappings"] = [{"technique_id": "T1059.004", "technique_name": "Fixture", "tactic": "Execution"}]
    return value


class SchemaTests(unittest.TestCase):
    def validate(self, value, code=0):
        return a.validate_command_risk(json.dumps(value).encode(), "printf x\n", code)

    def test_risk_exit_codes_and_thresholds_are_evidence_not_failures(self):
        for score, code in ((0, 0), (20, 0), (21, 1), (50, 1), (51, 2), (80, 2), (81, 3), (100, 3)):
            with self.subTest(score=score):
                data = self.validate(analysis(score=score), code)
                self.assertEqual(data["score"], score)
                self.assertEqual(data["level"], ("safe", "caution", "danger", "critical")[code])

    def test_source_bound_serde_shapes_and_deep_immutability(self):
        value = rich_analysis()
        data = self.validate(value, 3)
        self.assertEqual(data["pipeline_flow"]["taint_flows"][0]["propagators"][1]["encoding"]["method"], "base64")
        with self.assertRaises(TypeError):
            data["sub_commands"][0]["score"] = 100
        self.assertIsInstance(data["risk_factors"], tuple)
        for source in ("environment_var", "command_output", "stdin"):
            for sink in ("network_send", "execution", "display"):
                alternate = copy.deepcopy(value)
                alternate["pipeline_flow"]["taint_flows"][0].update(
                    source={"type": source}, sink={"type": sink})
                self.validate(alternate, 3)

    def test_closed_schema_rejects_wrong_types_fields_enums_and_alignment(self):
        mutations = [
            lambda v: v.update(score=True), lambda v: v.update(score=101),
            lambda v: v.update(score=12.0), lambda v: v.update(command="different"),
            lambda v: v.update(level="safe"), lambda v: v.update(quick_decision="approve"),
            lambda v: v.update(parse_confidence="certain"), lambda v: v.update(extra="ignored?"),
            lambda v: v.pop("reason"), lambda v: v.update(reason=None),
            lambda v: v.update(risk_factors=["invented"]),
            lambda v: v.update(sub_commands={}),
            lambda v: v["sub_commands"][0].update(intent=["download"]),
            lambda v: v["sub_commands"][0].update(intents=[]),
            lambda v: v["sub_commands"][0].update(capabilities=["execute"]),
            lambda v: v["sub_commands"][0]["flags"][0].update(modifier=False),
            lambda v: v["sub_commands"][0]["targets"][0].update(scope="everywhere"),
            lambda v: v["pipeline_flow"]["taint_flows"][0].update(escalation=True),
            lambda v: v["pipeline_flow"]["taint_flows"][0].update(propagators=[{"type": "encoding", "method": "base64"}]),
            lambda v: v["pipeline_flow"]["taint_flows"][0]["source"].update(extra=1),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                value = rich_analysis()
                mutate(value)
                with self.assertRaises(a.ProbeError):
                    self.validate(value, 3)
        with self.assertRaises(a.ProbeError):
            self.validate(analysis(score=100), 0)

    def test_framing_unicode_duplicates_nonfinite_and_limits(self):
        good = json.dumps(analysis()).encode()
        invalid = [b"", b"{}", good + good, b"banner\n" + good, b"\xef\xbb\xbf" + good,
                   b"\xff", good.replace(b'"score": 0', b'"score": NaN'),
                   good.replace(b'"score": 0', b'"score": Infinity'),
                   good.replace(b'"score": 0', b'"score": 0, "score": 0'),
                   b"[" * 33 + b"0" + b"]" * 33,
                   json.dumps({**analysis(), "reason": "\ud800"}).encode(),
                   json.dumps({**analysis(), "reason": "x" * 8193}).encode(),
                   json.dumps({**analysis(), "risk_factors": ["write"] * 513}).encode(),
                   b" " * (a.RISK_STDOUT_LIMIT + 1)]
        for index, raw in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(a.ProbeError):
                a.validate_command_risk(raw, "printf x\n", 0)
        self.assertEqual(a.validate_command_risk(good + b"\n \t", "printf x\n", 0)["score"], 0)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-tests-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.work = self.directory / "work"
        self.work.mkdir(mode=0o700)
        self.record = self.directory / "record.json"
        self.core = a.AppCore()
        self.core.session = "RISK_TEST_SESSION"
        self.core.connection = "CONNECTED"
        self.core.set_command_target("TERMINAL")
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.addCleanup(self.core.close)

    def test_clipboard_command_is_analyzed_without_terminal_and_copy_preserves_evidence(self):
        channel = self.core.channel
        self.core._disconnect()
        self.core.set_command_target("CLIPBOARD")
        review = self.core.review_command("printf x")
        self.enable(self.fake())
        result = self.until(lambda item: item.state == "RESULT")
        self.assertEqual(json.loads(self.record.read_text())["argv"][-1], review.text)
        self.assertEqual(result.result.key.review_id, review.id)
        copied = []
        self.core.copy_command(review.id, copied.append)
        self.assertEqual(copied, [review.text])
        self.assertEqual(self.core.command_risk_snapshot().result, result.result)
        channel.send.assert_not_called()

    def fake(self, mode="normal", score=0, response=None):
        # A private fixture program, pinned by its actual bytes. Not an upstream pin.
        binary = self.directory / ("fake-" + mode + "-" + uuid.uuid4().hex)
        source = "#!" + str(Path(sys.executable).resolve()) + "\n" + f'''
import fcntl, json, os, signal, stat, sys, time
if sys.argv[1:] == ["--version"]:
    print("sh-guard {'9.9.9' if mode == 'wrongversion' else '0.1.10'}")
    sys.exit(0)
args = sys.argv[1:]
assert len(args) == 7 and args[:4] == ["--json", "--shell", "bash", "--rules"] and args[5] == "--"
command = args[6]
evidence = {{"argv": args, "cwd": os.getcwd(), "env": dict(os.environ), "pid": os.getpid()}}
try:
    fd = int(args[4].rsplit("/", 1)[1])
    assert os.path.exists(args[4]) and stat.S_ISREG(os.fstat(fd).st_mode)
    assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
    assert os.read(fd, 1) == b""
    evidence["rules_valid"] = True
except Exception:
    evidence["rules_valid"] = False
    sys.stderr.write("Warning: rules file unavailable " + command)
for path in (os.path.join(os.getcwd(), ".sh-guard.toml"), os.path.join(os.environ["HOME"], ".config/sh-guard/rules.toml")):
    assert not os.path.exists(path)
with open({str(self.record)!r}, "w") as target:
    json.dump(evidence, target)
mode = {mode!r}
value = {response or analysis(score=score)!r}
value["command"] = command
if mode == "hang":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
if mode == "flood":
    while True:
        os.write(1, b"x" * 65536)
if mode == "signal":
    os.kill(os.getpid(), signal.SIGKILL)
if mode == "exit":
    sys.exit(9)
if mode == "badjson":
    print("not JSON")
elif mode == "stderr":
    sys.stderr.write("Warning: fixture " + command)
    print(json.dumps(value))
else:
    print(json.dumps(value))
sys.exit(("safe", "caution", "danger", "critical").index(value["level"]))
'''
        binary.write_text(source)
        binary.chmod(0o500)
        raw = binary.read_bytes()
        return a.CommandRiskTool(str(binary), hashlib.sha256(raw).hexdigest(), len(raw), "0.1.10", 1)

    def enable(self, tool):
        return self.core.set_command_risk(tool, str(self.work))

    def until(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.core.command_risk_snapshot()
            if predicate(snapshot):
                return snapshot
            time.sleep(0.01)
        self.fail("risk_fixture_deadline")

    def finish(self):
        return self.until(lambda value: value.state in {"RESULT", "UNKNOWN", "UNAVAILABLE"})

    def test_default_off_no_launch_and_output_never_analyzed(self):
        self.core.review_command("printf x")
        with mock.patch.object(a.subprocess, "Popen") as launch:
            self.assertEqual(self.core.snapshot().command_risk.state, "DISABLED")
            launch.assert_not_called()
        self.assertIsNone(self.core._command_risk.thread)
        self.core._output_review("selected output")
        self.assertEqual(self.enable(self.fake()).state, "IDLE")
        time.sleep(0.05)
        self.assertFalse(self.record.exists())

    def test_multiline_metacharacters_one_data_argument_rules_and_env(self):
        marker = self.directory / "NEVER_EXECUTED"
        text = "--setup\nprintf '€; pipe | quoted'\n$(touch " + str(marker) + ") `touch " + str(marker) + "`"
        review = self.core.review_command(text)
        hostile_home = self.directory / "hostile"
        (hostile_home / ".config/sh-guard").mkdir(parents=True)
        (hostile_home / ".config/sh-guard/rules.toml").write_text('allow = ["*"]')
        (self.directory / ".sh-guard.toml").write_text('allow = ["*"]')
        (self.work / ".sh-guard.toml").write_text('allow = ["*"]')
        tool = self.fake()
        with mock.patch.dict(os.environ, {"HOME": str(hostile_home), "XDG_CONFIG_HOME": str(hostile_home),
                                          "AITL_SECRET": "fixture-secret", "SSH_AUTH_SOCK": "fixture-agent",
                                          "HTTP_PROXY": "http://fixture.invalid"}), \
                mock.patch.object(a.subprocess, "Popen", wraps=subprocess.Popen) as launch:
            self.enable(tool)
            result = self.finish().result
            self.assertEqual(result.data["command"], review.text)
            calls = launch.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertFalse(call.kwargs["shell"])
            self.assertTrue(call.kwargs["close_fds"])
            self.assertEqual(call.args[0][0], tool.binary)
            self.assertEqual(len(call.kwargs["pass_fds"]), 1)
        self.assertEqual(calls[1].args[0][-2:], ["--", review.text])
        evidence = json.loads(self.record.read_text())
        self.assertTrue(evidence["rules_valid"])
        self.assertEqual(evidence["env"]["HOME"], evidence["cwd"] + "/home")
        for name in ("AITL_SECRET", "SSH_AUTH_SOCK", "XDG_CONFIG_HOME", "HTTP_PROXY"):
            self.assertNotIn(name, evidence["env"])
        self.assertFalse(marker.exists())
        self.assertFalse(Path(evidence["cwd"]).exists())
        self.assertEqual(list(self.work.iterdir()), [self.work / ".sh-guard.toml"])

    def test_invalid_rule_fd_warning_poisoned_json_is_unavailable(self):
        original = a._risk_process

        def broken(argv, *args):
            argv = list(argv)
            if "--rules" in argv:
                argv[argv.index("--rules") + 1] = "/dev/fd/99999"
            return original(argv, *args)

        self.core.review_command("printf x")
        with mock.patch.object(a, "_risk_process", side_effect=broken):
            self.enable(self.fake())
            result = self.finish().result
        self.assertEqual(result.error, "risk_stderr")
        self.assertIsNone(result.data)

    def test_integrity_is_checked_before_any_execution(self):
        self.core.review_command("printf x")
        tool = self.fake()
        with mock.patch.object(a.subprocess, "Popen") as launch:
            self.enable(replace(tool, sha256="0" * 64))
            result = self.finish().result
            self.assertEqual(result.error, "risk_binary_integrity")
            launch.assert_not_called()
        self.assertFalse(self.record.exists())

    def test_nonregular_symlink_wrong_size_and_permissions_never_spawn(self):
        self.core.review_command("printf x")
        tool = self.fake()
        link = self.directory / "symlink"
        link.symlink_to(tool.binary)
        for invalid in (replace(tool, binary=str(link)), replace(tool, size=tool.size + 1)):
            with self.subTest(tool=invalid.binary), mock.patch.object(a.subprocess, "Popen") as launch:
                self.enable(invalid)
                self.assertEqual(self.finish().state, "UNAVAILABLE")
                launch.assert_not_called()
        Path(tool.binary).chmod(0o700)
        with mock.patch.object(a.subprocess, "Popen") as launch:
            self.enable(tool)
            self.assertEqual(self.finish().result.error, "risk_binary_integrity")
            launch.assert_not_called()

    def test_binary_change_after_version_probe_prevents_analysis_spawn(self):
        self.core.review_command("printf x")
        tool = self.fake()
        original = a._risk_process

        def tamper_after_probe(argv, *args):
            result = original(argv, *args)
            if "--version" in argv:
                binary = Path(tool.binary)
                binary.chmod(0o700)
                binary.write_text("different fixture bytes")
                binary.chmod(0o500)
            return result

        with mock.patch.object(a, "_risk_process", side_effect=tamper_after_probe), \
                mock.patch.object(a.subprocess, "Popen", wraps=subprocess.Popen) as launch:
            self.enable(tool)
            result = self.finish().result
            self.assertEqual(result.error, "risk_binary_integrity")
            self.assertEqual(launch.call_count, 1)
            self.assertFalse(self.record.exists())

    def test_substituted_fifo_is_rejected_without_waiting_for_a_writer(self):
        self.core.review_command("printf x")
        tool = self.fake()
        fifo = self.directory / "fake-fifo"
        os.mkfifo(fifo, 0o500)
        start = time.monotonic()
        with mock.patch.object(a.subprocess, "Popen") as launch:
            self.enable(replace(tool, binary=str(fifo)))
            self.assertEqual(self.finish().result.error, "risk_binary_integrity")
            launch.assert_not_called()
        self.assertLess(time.monotonic() - start, 1)

    def test_crash_bad_json_stderr_exit_and_wrong_version_are_not_safe(self):
        self.core.review_command("printf x")
        for mode, reason in (("signal", "risk_process_exit"), ("badjson", "risk_json"),
                             ("stderr", "risk_stderr"), ("exit", "risk_process_exit"),
                             ("wrongversion", "risk_version")):
            with self.subTest(mode=mode):
                self.enable(self.fake(mode))
                result = self.finish().result
                self.assertEqual(result.state, "UNAVAILABLE")
                self.assertEqual(result.error, reason)
                self.assertIsNone(result.data)
        self.assertFalse(list(self.work.iterdir()))

    def test_partial_and_fallback_keep_evidence_as_unknown(self):
        self.core.review_command("printf x")
        for confidence in ("partial", "fallback"):
            value = analysis()
            value["parse_confidence"] = confidence
            self.enable(self.fake(response=value))
            result = self.finish().result
            self.assertEqual(result.state, "UNKNOWN")
            self.assertEqual(result.data["parse_confidence"], confidence)

    def test_timeout_output_flood_and_cancel_reap_process_and_cleanup(self):
        self.core.review_command("printf x")
        original = subprocess.Popen
        for mode, reason in (("hang", "risk_timeout"), ("flood", "risk_output_limit")):
            with self.subTest(mode=mode), mock.patch.object(a, "RISK_TIMEOUT", 0.2), \
                    mock.patch.object(a.subprocess, "Popen", wraps=subprocess.Popen) as launch:
                processes = []
                def tracked(*args, **kwargs):
                    process = original(*args, **kwargs)
                    processes.append(process)
                    return process

                launch.side_effect = tracked
                start = time.monotonic()
                self.enable(self.fake(mode))
                result = self.finish().result
                self.assertEqual(result.error, reason)
                self.assertLess(time.monotonic() - start, 2)
                self.assertTrue(all(process.poll() is not None for process in processes))
                for process in processes:
                    with self.assertRaises(ChildProcessError):
                        os.waitpid(process.pid, os.WNOHANG)
                self.assertFalse(list(self.work.iterdir()))
        self.record.unlink()
        self.enable(self.fake("hang"))
        self.until(lambda _: self.record.exists())
        self.core.set_command_risk()
        self.assertEqual(self.core.command_risk_snapshot().state, "DISABLED")
        self.assertTrue(self.core._command_risk.close())
        evidence = json.loads(self.record.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(evidence["pid"], 0)
        self.assertFalse(list(self.work.iterdir()))

    def test_no_retry_after_failure_and_close_is_idempotent(self):
        self.core.review_command("printf x")
        with mock.patch.object(a.subprocess, "Popen", wraps=subprocess.Popen) as launch:
            self.enable(self.fake("badjson"))
            self.finish()
            count = launch.call_count
            for _ in range(20):
                self.core.pump()
            self.assertEqual(launch.call_count, count)
        self.assertTrue(self.core._command_risk.close())
        self.assertTrue(self.core._command_risk.close())

    def test_inbox_does_not_replace_review_and_output_does_not_scan(self):
        review = self.core.review_command("printf x")
        self.enable(self.fake())
        result = self.finish().result
        self.core.add_proposal("printf next")
        self.assertIs(self.core.review, review)
        self.assertEqual(self.core.command_risk_snapshot().result, result)
        self.core.review_pending_proposal()
        new_result = self.finish().result
        self.assertNotEqual(new_result.key.review_id, result.key.review_id)
        self.core._output_review("independently selected output")
        self.assertEqual(self.core.command_risk_snapshot().state, "IDLE")
        self.assertIsNone(self.core.command_risk_snapshot().result)

    def test_return_edit_expiry_and_target_session_invalidate_evidence(self):
        binding = ("bridge", 1)
        with mock.patch.object(self.core, "_bridge_binding", side_effect=lambda: binding):
            self.core.review_command("printf x")
            self.enable(self.fake())
            first = self.finish().result
            self.core.set_final_return(False)
            second = self.finish().result
            self.assertNotEqual(first.key.review_id, second.key.review_id)
            self.assertNotEqual(first.key.payload_sha256, second.key.payload_sha256)
            self.assertFalse(second.key.final_return)
            self.core.edit_review(self.core.review.id, "printf edited", False)
            edited = self.finish().result
            self.assertTrue(self.core.review.edited)
            self.assertNotEqual(edited.key.payload_sha256, second.key.payload_sha256)
            binding = ("bridge", 2)
            self.assertEqual(self.core.command_risk_snapshot().state, "STALE")
            self.core.review = replace(self.core.review, bridge_binding=binding,
                                       expires_at=time.time() - 1)
            self.assertIsNone(self.core.command_risk_snapshot().result)
            self.core.review = replace(self.core.review, expires_at=None)
            self.finish()
            self.core.session = "OTHER_SESSION"
            self.assertEqual(self.core.command_risk_snapshot().state, "STALE")

    def test_changed_text_without_matching_payload_rejects_cached_evidence(self):
        self.core.review_command("printf x")
        self.enable(self.fake())
        self.finish()
        self.core.review = replace(self.core.review, text="printf forged\n")
        with mock.patch.object(a.subprocess, "Popen") as launch:
            snapshot = self.core.command_risk_snapshot()
            self.assertEqual(snapshot.state, "UNAVAILABLE")
            self.assertEqual(snapshot.error, "risk_snapshot")
            self.assertIsNone(snapshot.result)
            launch.assert_not_called()

    def test_rapid_updates_late_success_error_identical_text_and_off_epoch(self):
        jobs = queue.Queue()
        releases = []

        def delayed(job, cancel):
            release = threading.Event()
            releases.append(release)
            jobs.put((job, release))
            release.wait(3)
            # Deliberately late completion despite cancellation: tests the owner boundary.
            return a.CommandRiskResult(job.key, "RESULT", data={"score": 100})

        with mock.patch.object(a, "run_command_risk", side_effect=delayed):
            self.core.review_command("printf same")
            self.enable(self.fake())
            first, release_a = jobs.get(timeout=2)
            self.core.review_command("printf same")
            self.core.command_risk_snapshot()
            middle = self.core._command_risk.current
            self.assertNotEqual(first.key.review_id, middle.review_id)
            self.core.review_command("printf newest")
            self.core.command_risk_snapshot()
            release_a.set()
            last, release_c = jobs.get(timeout=2)
            self.assertEqual(last.review.text, "printf newest\n")
            self.assertIsNone(self.core.command_risk_snapshot().result)
            release_c.set()
            current = self.finish().result
            self.core._command_risk.events.put(a.CommandRiskResult(middle, "UNAVAILABLE", "risk_timeout"))
            self.assertEqual(self.core.command_risk_snapshot().result, current)
            self.core.review_command("printf newer")
            self.core.command_risk_snapshot()
            old_epoch_job, release_d = jobs.get(timeout=2)
            self.core.set_command_risk()
            self.assertIsNone(self.core.command_risk_snapshot().result)
            self.enable(self.fake())
            self.assertNotEqual(self.core._command_risk.current.epoch, old_epoch_job.key.epoch)
            release_d.set()
            fresh, release_e = jobs.get(timeout=2)
            self.assertIsNone(self.core.command_risk_snapshot().result)
            release_e.set()
            final = self.finish().result
            self.assertEqual(final.key, fresh.key)
            wrong_tool = replace(fresh.key.tool, generation=fresh.key.tool.generation + 1)
            self.core._command_risk.events.put(a.CommandRiskResult(
                replace(fresh.key, tool=wrong_tool), "UNAVAILABLE", "risk_binary_integrity"))
            self.assertEqual(self.core.command_risk_snapshot().result, final)

    def test_reviewer_never_approves_or_transfers_even_critical(self):
        review = self.core.review_command("printf x")
        with mock.patch.object(self.core, "approve", wraps=self.core.approve) as approve:
            for mode, score in (("normal", 100), ("badjson", 0)):
                self.enable(self.fake(mode, score))
                self.finish()
                approve.assert_not_called()
                self.core.channel.send.assert_not_called()
            self.core.set_paused(True)
            with self.assertRaises(a.ProbeError):
                self.core.approve(review.id)
            self.core.channel.send.assert_not_called()
            self.core.set_paused(False)
            self.core.approve(review.id)  # Explicit existing local action only.
            self.core.channel.send.assert_called_once_with({"type": "transfer", "id": review.id,
                "session": review.session, "text": review.text, "return": True, "override": False})
            with self.assertRaises(a.ProbeError):
                self.core.approve(review.id)
            self.assertIsNone(self.core.command_risk_snapshot().result)
            self.assertEqual(self.core.review.payload, b"printf x\n")

    def test_worker_cannot_publish_by_calling_owner_methods(self):
        errors = []

        def wrong_thread():
            try:
                self.core.command_risk_snapshot()
            except a.ProbeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=wrong_thread)
        thread.start()
        thread.join(1)
        self.assertEqual(errors, ["risk_wrong_thread"])
        self.assertEqual(self.core.command_risk_snapshot().state, "DISABLED")


if __name__ == "__main__":
    unittest.main()
