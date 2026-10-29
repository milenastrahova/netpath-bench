"""Safe offline tests for orchestrator argument validation and command construction."""
import importlib.util
import os
from pathlib import Path, PureWindowsPath, PurePosixPath
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1]/"scripts"/"bgp_routed_trial.py"
spec = importlib.util.spec_from_file_location("trial", MODULE)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)

class BgpTrialTests(unittest.TestCase):
    def test_failover_requires_explicit_consent(self):
        with self.assertRaises(SystemExit):
            trial.parse_args(["--compose","test.yaml","--mode","failover"])

    def test_baseline_never_implicitly_stops_primary(self):
        args = trial.parse_args(["--compose","test.yaml"])
        self.assertEqual(args.mode, "baseline")
        self.assertFalse(args.allow_primary_stop)

    def test_unique_run_label(self):
        a=trial.parse_args(["--compose","test.yaml","--run-id","run02"])
        self.assertEqual(a.run_id,"run02")
        with self.assertRaises(SystemExit):
            trial.parse_args(["--compose","test.yaml","--run-id","../unsafe"])

    def test_invalid_time_rejected(self):
        with self.assertRaises(SystemExit):
            trial.parse_args(["--compose","test.yaml","--seconds","7"])
        with self.assertRaises(SystemExit):
            trial.parse_args(["--compose","test.yaml","--mode","failover", "--allow-primary-stop",
                              "--seconds","10", "--fault-at","7", "--fault-seconds","3"])

    def test_routed_orchestrator_uses_current_image(self):
        compose = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text()
        self.assertEqual(trial.IMAGE, "netpath-bench-lab:1.0")
        self.assertIn("image: netpath-bench-lab:1.0", compose)

    def test_command_targets_exact_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = trial.make_probe_cmd(Path(tmp),run_name="trial", seconds=22,
                                       timeout_ms=200,interval_us=20000,tcp=False,edge_container="edge-container-id")
            self.assertIn("container:edge-container-id",cmd)
            self.assertIn("10.10.10.1",cmd)
            self.assertIn("10.40.40.1",cmd)
            self.assertIn("/reports/trial.csv",cmd)

    def test_compose_command_uses_supplied_file(self):
        # Use the OS-native path: on Windows Path('/tmp/...') is '\\tmp\\...'.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "compose.yaml"
            cmd = trial.compose_cmd(path, "stop", "transit_primary")
            self.assertEqual(cmd, ["docker", "compose", "-f", os.fspath(path),
                                   "stop", "transit_primary"])

    def test_compose_command_preserves_windows_and_posix_paths(self):
        # PurePath variants let Linux CI regression-test Windows path semantics.
        for path in (PureWindowsPath(r"C:\lab files\compose.yaml"),
                     PurePosixPath("/tmp/lab files/compose.yaml")):
            with self.subTest(path=str(path)):
                cmd = trial.compose_cmd(path, "stop", "transit_primary")
                self.assertEqual(cmd[3], str(path))
                self.assertEqual(cmd[:3], ["docker", "compose", "-f"])
                self.assertEqual(cmd[4:], ["stop", "transit_primary"])


    def test_preflight_resolves_routers_by_compose_service(self):
        import json
        from unittest.mock import patch
        cfg={"name":"generic-bgp-lab", "services": {
            svc:{"image":"quay.io/frrouting/frr:10.7.1"} for svc in trial.SERVICES}}
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/"compose.yaml"
            f.write_text("name: generic-bgp-lab\n")
            def fake_call(argv, **kwargs):
                if argv[-3:]==["config","--format","json"]: return json.dumps(cfg)
                if argv[-3:]==["--services","--status","running"]: return "\n".join(sorted(trial.SERVICES))
                if argv[-3:]==["ps","-q","edge"]: return "edge-id"
                if argv[-3:]==["ps","-q","core"]: return "core-id"
                if argv[:2]==["docker","inspect"]: return "true"
                if argv[:3]==["docker","image","inspect"]: return ""
                raise AssertionError(argv)
            with patch.object(trial,"call",side_effect=fake_call):
                self.assertEqual(trial.check_preflight(f), ("generic-bgp-lab","edge-id","core-id"))

    def test_preflight_rejects_unrelated_compose_project(self):
        import json
        from unittest.mock import patch
        cfg={"name":"unrelated", "services":{"edge":{"image":"nginx:stable"}}}
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/"compose.yaml";f.write_text("name: unrelated\n")
            with patch.object(trial,"call",return_value=json.dumps(cfg)):
                with self.assertRaisesRegex(RuntimeError,"exactly edge"):
                    trial.check_preflight(f)

    def test_preflight_missing_file_never_calls_docker(self):
        with mock.patch.object(trial,"call") as fake:
            with self.assertRaisesRegex(RuntimeError,"Missing BGP Compose"):
                trial.check_preflight(Path("/this/file/does/not/exist.yaml"))
            fake.assert_not_called()

if __name__=="__main__": unittest.main()
