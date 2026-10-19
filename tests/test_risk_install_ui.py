"""Pinned SELF-CREATED archive/transport/Tk fixtures. No upstream binary/network."""
import hashlib
import gc
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a
import test_command_risk as fixtures


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fake_binary(subcommands=None, bad_probe=False):
    return ("#!" + str(Path(sys.executable).resolve()) + "\n" + f'''
import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("sh-guard 0.1.10")
    sys.exit(0)
assert sys.argv[1:5] == ["--json", "--shell", "bash", "--rules"]
with open(sys.argv[5], "rb") as rules:
    assert rules.read() == b""
assert sys.argv[6] == "--" and len(sys.argv) == 8
command = sys.argv[7]
parts = [":"] if command == ":\\n" else {subcommands!r} or [command.rstrip("\\n")]
value = {fixtures.rich_analysis()!r}
value.update(command=command)
template = value["sub_commands"][0]
value["sub_commands"] = [dict(template, command=part) for part in parts]
if {bad_probe!r}:
    print("broken fixture response")
else:
    print(json.dumps(value))
sys.exit(3)
''').encode()


def archive_for(binary, members=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload, kind in members or [("sh-guard", binary, tarfile.REGTYPE),
                                               ("sh-guard-mcp", b"fixture-unused", tarfile.REGTYPE)]:
            member = tarfile.TarInfo(name)
            member.type, member.mode = kind, 0o777  # Untrusted archive permissions ignored.
            member.size = len(payload) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE:
                member.linkname = "/outside"
            archive.addfile(member, io.BytesIO(payload) if member.size else None)
    return stream.getvalue()


def release_for(binary, archive):
    return a.CommandRiskRelease("0.1.10", "x86_64-unknown-linux-gnu", digest(archive), len(archive),
                                digest(binary), len(binary), approved=True)


class MappingTests(unittest.TestCase):
    def spans(self, source, commands, scores=None, confidence="full"):
        data = fixtures.analysis(command=source)
        data["parse_confidence"] = confidence
        data["sub_commands"] = [{"command": command, "score": score}
                                for command, score in zip(commands, scores or [0] * len(commands))]
        return a.command_risk_spans(source, data)

    def test_independent_exact_interval_vectors_quotes_comments_duplicates_unicode(self):
        vectors = [
            ("echo x; echo x\n", ["echo x", "echo x"], [(0, 6), (8, 14)]),
            ("echo 'a; b' && printf x\n", ["echo 'a; b'", "printf x"], [(0, 11), (15, 23)]),
            ("echo 'echo x'; echo x", ["echo 'echo x'", "echo x"], [(0, 13), (15, 21)]),
            (" echo  '🙂\n€' \n", ["echo  '🙂\n€'"], [(1, 12)]),
            ("echo x # echo x\necho x\n", ["echo x", "echo x"], [(0, 6), (16, 22)]),
            ("echo a\\;b | printf x", ["echo a\\;b", "printf x"], [(0, 9), (12, 20)]),
        ]
        for source, commands, expected in vectors:
            with self.subTest(source=source):
                spans = self.spans(source, commands)
                self.assertEqual([(left, right) for left, right, _ in spans], expected)
                self.assertEqual([source[left:right] for left, right, _ in spans], commands)

    def test_uncertainty_is_all_or_none_never_first_substring_or_safe(self):
        for source in ("echo x > file", "cat <<EOF\necho x\nEOF", "echo $(id)", "echo $USER",
                       "echo `id`", "echo $'x'", "echo <(id)", "(echo x)", "{ echo x; }",
                       "if true; then echo x; fi", "echo x &", "echo 'unterminated", "echo x |",
                       "echo x;; echo x", "echo a\\\nb", "echo \"$X\"", "echo x && # comment\n"):
            with self.subTest(source=source):
                self.assertEqual(self.spans(source, [source]), ())
        for commands in (["echo x"], ["echo x", "echo x", "echo x"], ["echo  x", "echo x"], ["", "echo x"]):
            self.assertEqual(self.spans("echo x; echo x", commands), ())
        self.assertEqual(self.spans("echo x", ["echo x"], confidence="partial"), ())
        self.assertEqual(self.spans("echo x", ["echo x"], confidence="fallback"), ())


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve() / "config"
        self.binary = fake_binary()
        self.archive = archive_for(self.binary)
        self.release = release_for(self.binary, self.archive)
        self.installation = a.CommandRiskInstallation(self.base, self.release)
        self.cancel = threading.Event()
        self.transport = mock.Mock(return_value=self.archive)

    def install(self, installation=None):
        return (installation or self.installation).install(self.cancel, lambda _: None, self.transport)

    def test_unadmitted_releases_gate_before_transport_path_or_execution(self):
        for admitted in a.RISK_RELEASES.values():
            self.assertTrue(admitted.approved)
            release = replace(admitted, approved=False)
            install = a.CommandRiskInstallation(self.base, release)
            with mock.patch.object(a.subprocess, "Popen") as spawn:
                for fn in (lambda: install.check(self.cancel), lambda: self.install(install), install.remove):
                    with self.assertRaisesRegex(a.ProbeError, "risk_pin_not_approved"):
                        fn()
                spawn.assert_not_called()
        self.transport.assert_not_called()
        self.assertFalse(self.base.exists())

    def test_exact_platform_selection_and_unsupported_do_not_adopt_path(self):
        for system, machine, target in (("linux", "amd64", "x86_64-unknown-linux-gnu"),
                                        ("linux", "arm64", "aarch64-unknown-linux-gnu"),
                                        ("darwin", "x86_64", "x86_64-apple-darwin"),
                                        ("darwin", "arm64", "aarch64-apple-darwin")):
            with mock.patch.object(a.sys, "platform", system), mock.patch.object(a.platform, "machine", return_value=machine):
                self.assertEqual(a.command_risk_release().target, target)
                self.assertTrue(a.command_risk_release().approved)
        with mock.patch.object(a.platform, "machine", return_value="unsupported"):
            with self.assertRaisesRegex(a.ProbeError, "risk_platform"):
                a.command_risk_release()

    def test_staged_probe_atomic_publish_private_binary_only_receipt_and_remove(self):
        tool, work = self.install()
        self.assertEqual(Path(tool.binary).read_bytes(), self.binary)
        self.assertEqual(stat.S_IMODE(Path(tool.binary).stat().st_mode), 0o500)
        self.assertEqual(set(p.name for p in Path(tool.binary).parent.iterdir()), {"sh-guard", "receipt.json"})
        receipt = Path(tool.binary).with_name("receipt.json")
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(json.loads(receipt.read_text())["binary_sha256"], digest(self.binary))
        self.assertEqual(list(Path(work).iterdir()), [])
        self.assertEqual(self.installation.check(self.cancel), tool)
        self.installation.remove()
        self.assertFalse(Path(tool.binary).parent.exists())

    def test_hash_size_and_bad_probe_never_publish_or_execute_unverified(self):
        variations = [replace(self.release, archive_sha256="0" * 64),
                      replace(self.release, archive_size=self.release.archive_size + 1),
                      replace(self.release, binary_sha256="0" * 64),
                      replace(self.release, binary_size=self.release.binary_size + 1)]
        for release in variations:
            with self.subTest(release=release), mock.patch.object(a.subprocess, "Popen") as spawn:
                with self.assertRaises(a.ProbeError):
                    self.install(a.CommandRiskInstallation(self.base, release))
                spawn.assert_not_called()
                self.assertFalse(self.installation.destination.exists())
        bad = fake_binary(bad_probe=True)
        raw = archive_for(bad)
        self.transport.return_value = raw
        with self.assertRaises(a.ProbeError):
            self.install(a.CommandRiskInstallation(self.base, release_for(bad, raw)))
        self.assertFalse(self.installation.destination.exists())

    def test_archive_traversal_links_duplicates_extra_and_missing_are_rejected(self):
        variants = [
            [("../escape", self.binary, tarfile.REGTYPE)],
            [("/escape", self.binary, tarfile.REGTYPE)],
            [("sh-guard", b"", tarfile.SYMTYPE)],
            [("sh-guard", self.binary, tarfile.REGTYPE)] * 2,
            [("sh-guard", self.binary, tarfile.REGTYPE)],
            [("sh-guard", self.binary, tarfile.REGTYPE), ("extra", b"x", tarfile.REGTYPE)],
            [("sh-guard", b"", tarfile.FIFOTYPE)],
        ]
        for members in variants:
            raw = archive_for(self.binary, members)
            self.transport.return_value = raw
            with self.subTest(names=[v[0] for v in members]), mock.patch.object(a.subprocess, "Popen") as spawn:
                with self.assertRaises(a.ProbeError):
                    self.install(a.CommandRiskInstallation(self.base, release_for(self.binary, raw)))
                spawn.assert_not_called()
                self.assertFalse(self.installation.destination.exists())

    def test_cancel_and_failed_upgrade_preserve_existing_verified_install(self):
        tool, work = self.install()
        previous = Path(tool.binary).read_bytes()
        next_release = replace(self.release, version="0.1.11", archive_sha256="0" * 64)
        with self.assertRaises(a.ProbeError):
            self.install(a.CommandRiskInstallation(self.base, next_release))
        self.assertEqual(Path(tool.binary).read_bytes(), previous)
        self.cancel.set()
        with self.assertRaisesRegex(a.ProbeError, "risk_cancelled"):
            self.install(a.CommandRiskInstallation(self.base, replace(self.release, version="0.1.12")))
        self.assertEqual(Path(tool.binary).read_bytes(), previous)
        self.assertFalse(list(Path(work).iterdir()))

    def test_new_manifest_version_publishes_separately_without_changing_old_version(self):
        tool, _ = self.install()
        next_binary = self.binary.replace(b"sh-guard 0.1.10", b"sh-guard 0.1.11")
        raw = archive_for(next_binary)
        release = replace(release_for(next_binary, raw), version="0.1.11")
        self.transport.return_value = raw
        next_tool, _ = self.install(a.CommandRiskInstallation(self.base, release))
        self.assertNotEqual(tool.binary, next_tool.binary)
        self.assertEqual(Path(tool.binary).read_bytes(), self.binary)
        self.assertEqual(Path(next_tool.binary).read_bytes(), next_binary)

    def test_symlink_base_no_write_and_binary_fifo_no_hang(self):
        outside = Path(self.temp.name, "outside")
        outside.mkdir(mode=0o700)
        self.base.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(a.ProbeError):
            self.install()
        self.assertFalse(list(outside.iterdir()))
        self.base.unlink()
        tool, _ = self.install()
        Path(tool.binary).unlink()
        os.mkfifo(tool.binary, 0o500)
        start = time.monotonic()
        with self.assertRaises(a.ProbeError):
            self.installation.check(self.cancel)
        self.assertLess(time.monotonic() - start, 1)

    def test_quarantine_only_added_and_verified_never_removed(self):
        with mock.patch.object(a.sys, "platform", "darwin"), \
                mock.patch.object(a.os, "setxattr") as set_attr, \
                mock.patch.object(a.os, "getxattr") as get_attr:
            get_attr.side_effect = lambda *_args, **_kw: set_attr.call_args.args[2]
            a._risk_quarantine("/fixture")
            self.assertEqual(set_attr.call_args.args[1], "com.apple.quarantine")
            self.assertTrue(set_attr.call_args.args[2].startswith(b"0083;"))
            get_attr.assert_called_once()

    def test_cleanup_rejects_extra_symlink_and_concurrent_lock_without_deleting(self):
        tool, _ = self.install()
        extra = Path(tool.binary).with_name("foreign")
        extra.symlink_to(Path(self.temp.name, "outside"))
        with self.assertRaisesRegex(a.ProbeError, "risk_cleanup_incomplete"):
            self.installation.remove()
        self.assertTrue(Path(tool.binary).exists())
        extra.unlink()
        with open(self.base / "tools/sh-guard/.lock", "rb") as lock:
            a.fcntl.flock(lock, a.fcntl.LOCK_EX | a.fcntl.LOCK_NB)
            with self.assertRaisesRegex(a.ProbeError, "risk_lease_busy"):
                self.installation.remove()
            self.assertTrue(Path(tool.binary).exists())

    def test_download_redirect_contract_using_only_fake_http_responses(self):
        from urllib.request import Request
        entered = []

        def opener(*handlers):
            redirects = handlers[1]
            req = Request(self.release.url)
            for url in ("http://github.com/unsafe", "https://evil.invalid/file", "https://user:pw@github.com/file"):
                with self.assertRaises(a.ProbeError):
                    redirects.redirect_request(req, None, 302, "", {}, url)
            self.assertIsNotNone(redirects.redirect_request(req, None, 302, "", {},
                                                         "https://release-assets.githubusercontent.com/fixture"))
            entered.append(req.full_url)
            return mock.Mock(open=mock.Mock(return_value=io.BytesIO(self.archive)))

        with mock.patch("urllib.request.build_opener", side_effect=opener):
            self.assertEqual(a.download_command_risk(self.release, self.cancel), self.archive)
        self.assertEqual(entered, [self.release.url])


class ActivationTests(unittest.TestCase):
    def setUp(self):
        InstallationTests.setUp(self)
        self.core = a.AppCore(preference_store=a.PreferenceStore(self.base))
        self.core.session, self.core.connection = "TEST_SESSION", "CONNECTED"
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.addCleanup(self.core.close)

    def until(self, state, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snap = self.core.command_risk_snapshot()
            if snap.state == state:
                return snap
            time.sleep(0.01)
        self.fail("setup_fixture_deadline: " + self.core.risk_setup_state)

    def test_missing_approved_fixture_requires_confirmation_then_current_review_scans(self):
        self.core.review_command("printf before")
        with mock.patch.object(a, "command_risk_release", return_value=self.release), \
                mock.patch.object(a, "download_command_risk", self.transport):
            # The default callable was bound at definition; inject only at setup boundary.
            original = a.CommandRiskSetup
            with mock.patch.object(a, "CommandRiskSetup", side_effect=lambda installation, install=False:
                                   original(installation, install, self.transport)):
                self.core.request_command_risk(True)
                self.until("INSTALL_CONFIRM")
                self.transport.assert_not_called()
                self.core.confirm_command_risk_install(True)
                self.core.review_command("printf after")
                result = self.until("RESULT").result
                self.assertEqual(result.data["command"], "printf after\n")
                self.core.channel.send.assert_not_called()

    def test_approved_installed_fixture_on_scans_existing_without_install_confirmation(self):
        self.installation.install(self.cancel, lambda _: None, self.transport)
        self.transport.reset_mock()
        review = self.core.review_command("printf visible")
        with mock.patch.object(a, "command_risk_release", return_value=self.release):
            self.core.request_command_risk(True)
            result = self.until("RESULT").result
            self.assertEqual(result.key.review_id, review.id)
            self.assertEqual(result.data["command"], review.text)
            self.transport.assert_not_called()
            self.core.request_command_risk(False)
            self.assertIsNone(self.core.command_risk_snapshot().result)
            self.assertEqual(self.core.command_risk_snapshot().state, "DISABLED")

    def test_reject_install_and_candidate_activation_never_offer_transport(self):
        with mock.patch.object(a, "command_risk_release", return_value=self.release):
            self.core.request_command_risk(True)
            self.until("INSTALL_CONFIRM")
            self.core.confirm_command_risk_install(False)
            self.assertEqual(self.core.command_risk_snapshot().state, "DISABLED")
        with mock.patch.object(a, "command_risk_release", return_value=replace(self.release, approved=False)):
            self.core.request_command_risk(True)
            result = self.core.command_risk_snapshot()
            self.assertEqual(result.state, "UNAVAILABLE")
            self.assertEqual(result.error, "risk_pin_not_approved")
        self.transport.assert_not_called()

    def test_off_during_transport_cancels_no_publish_no_late_handoff(self):
        entered, release = threading.Event(), threading.Event()

        def delayed(_manifest, cancel):
            entered.set()
            release.wait(3)
            return self.archive

        original = a.CommandRiskSetup
        with mock.patch.object(a, "command_risk_release", return_value=self.release), \
                mock.patch.object(a, "CommandRiskSetup", side_effect=lambda installation, install=False:
                                  original(installation, install, delayed)):
            self.core.request_command_risk(True)
            self.until("INSTALL_CONFIRM")
            self.core.confirm_command_risk_install(True)
            setup = self.core.risk_setup
            self.assertTrue(entered.wait(2))
            self.core.request_command_risk(False)
            release.set()
            setup.thread.join(2)
            self.assertFalse(setup.thread.is_alive())
            self.assertEqual(self.core.command_risk_snapshot().state, "DISABLED")
            self.assertFalse(self.installation.destination.exists())


@unittest.skipUnless(os.environ.get("DISPLAY"), "controlled Tk display not supplied")
class RiskGUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.temp = tempfile.TemporaryDirectory(prefix="aitl-risk-gui-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve() / "config"
        self.core = a.AppCore(preference_store=a.PreferenceStore(self.base))
        self.core.session, self.core.connection = "GUI_TEST_SESSION", "CONNECTED"
        self.core.channel = mock.Mock()
        self.core.channel.receive.return_value = []
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *_: self.errors.append("tk_callback")
        self.ui = a.ReviewUI(self.root, self.core)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.core.close()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()
        self.ui = self.root = self.core = None
        gc.collect()  # Dispose Tcl-owned cycles on the creating thread, before another worker starts.

    def until(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.root.update()
            self.ui.render()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("gui_fixture_deadline")

    def test_unadmitted_release_unavailable_no_dialog_no_autonomous_transfer(self):
        self.core.review_command("printf x")
        self.ui.render()
        self.assertFalse(self.ui.risk_enabled.get())
        with mock.patch.object(a, "command_risk_release", return_value=replace(a.command_risk_release(), approved=False)), \
                mock.patch.object(self.ui.messagebox, "askyesno") as confirm, \
                mock.patch.object(a.subprocess, "Popen") as spawn:
            self.ui.risk_checkbox.invoke()
            self.root.update()
            self.assertIn("nicht für die Installation zugelassen", self.ui.risk_hint.get())
            confirm.assert_not_called()
            spawn.assert_not_called()
        self.assertTrue(self.ui.approve_button.instate(["!disabled"]))
        self.core.channel.send.assert_not_called()
        self.ui.command_risk_details()
        self.root.update()
        self.assertIn("GPL-3.0-only", self.ui.risk_details_box.text.get("1.0", "end"))
        self.ui.risk_checkbox.invoke()
        self.assertEqual(self.ui.risk_status.get(), "Analyse ausgeschaltet")
        self.assertFalse(self.errors)

    def test_fixture_install_confirmation_projection_details_stale_and_unknown(self):
        binary = fake_binary()
        raw = archive_for(binary)
        release = release_for(binary, raw)
        source = "echo '🙂\n€'\n"
        review = self.core.review_command(source)
        self.ui.render()
        original = a.CommandRiskSetup
        with mock.patch.object(a, "command_risk_release", return_value=release), \
                mock.patch.object(a, "CommandRiskSetup", side_effect=lambda installation, install=False:
                                  original(installation, install, lambda *_: raw)):
            self.ui.risk_checkbox.invoke()
            self.until(lambda: self.core.risk_setup_state == "INSTALL_CONFIRM")
            self.assertEqual(self.ui.risk_views.select(), str(self.ui.risk_settings_page))
            self.assertEqual(self.ui.review_notebook.select(), str(self.ui.risk_summary_tab))
            self.assertEqual(self.core.review_state, "REVIEW")
            self.ui.risk_install_button.invoke()
            self.until(lambda: self.ui.risk_status.get().startswith("Kritisch · 100/100"))
        self.assertEqual(self.core.risk_installation.release.version, "0.1.10")
        self.assertTrue(self.core.risk_installation.destination.is_relative_to(self.base))
        display = self.ui.editor.text.get("1.0", "end-1c")
        self.assertEqual(display, "".join(value for value, _ in a.review_fragments(review.text)))
        ranges = self.ui.editor.text.tag_ranges("risk-sub-0")
        self.assertEqual(len(ranges), 2)
        marked = self.ui.editor.text.get(*ranges)
        self.assertEqual(marked, "".join(value for value, _ in a.review_fragments(source.rstrip("\n"))))
        self.assertEqual(self.core.review.payload, source.encode())
        self.ui.command_risk_details()
        self.root.update()
        details = self.ui.risk_details_box.text.get("1.0", "end")
        for label in ("parse_confidence", "risk_factors", "executable", "intent", "targets", "flags",
                      "reversibility", "capabilities", "pipeline_flow", "propagators", "mitre_mappings"):
            self.assertIn(label, details)
        self.core.channel.send.assert_not_called()
        self.core.edit_review(review.id, "echo $(id)", True)
        self.ui.render()
        self.assertFalse(self.ui.editor.text.tag_ranges("risk-sub-0"))
        self.until(lambda: "Einzelmarkierungen nicht verfügbar" in self.ui.risk_hint.get())
        self.assertTrue(self.ui.risk_status.get().startswith("Kritisch · 100/100"))
        self.assertFalse(self.ui.editor.text.tag_ranges("risk-sub-0"))
        self.assertNotIn(review.id, self.ui.risk_details_box.text.get("1.0", "end"))
        self.core._output_review("separate output")
        self.ui.render()
        self.assertTrue(self.ui.risk_checkbox.instate(["!disabled"]))
        self.assertFalse(self.ui.editor.text.tag_ranges("risk-sub-0"))
        self.assertFalse(self.errors)


if __name__ == "__main__":
    unittest.main()
