"""Synthetic chart tests: scope, conservative false-positive boundaries and safe CLI."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("helm_audit", ROOT / "scripts" / "audit.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ChartTests(unittest.TestCase):
    def temp_chart(self, values="image:\n  tag: v1\n", template="{{ .Values.image.tag }}", other=None):
        ctx = tempfile.TemporaryDirectory()
        chart = Path(ctx.name)
        (chart / "templates").mkdir()
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: demo\nversion: 0.1.0\n")
        (chart / "values.yaml").write_text(values)
        (chart / "templates" / "config.yaml").write_text(template)
        if other:
            (chart / "templates" / "_helpers.tpl").write_text(other)
        return ctx, chart

    def findings(self, values="image:\n  tag: v1\n", template="{{ .Values.image.tag }}", other=None):
        ctx, chart = self.temp_chart(values, template, other)
        with ctx:
            return mod.audit(chart)

    def test_defined_value(self):
        self.assertEqual(self.findings(), [])

    def test_missing_top_key(self):
        r = self.findings(template="{{ .Values.missing }}")
        self.assertEqual((r[0].code, r[0].key), ("UNDECLARED_VALUE", "missing"))

    def test_missing_nested_key(self):
        self.assertEqual(self.findings(template="{{ .Values.image.digest }}")[0].key, "image.digest")

    def test_root_dollar_scope(self):
        self.assertEqual(self.findings(template="{{ $.Values.api.port }}")[0].key, "api.port")

    def test_optional_default_pipeline(self):
        self.assertEqual(self.findings(template='{{ .Values.api.port | default 80 }}')[0].code, "OPTIONAL_UNDECLARED")

    def test_required_pipeline(self):
        self.assertEqual(self.findings(template='{{ .Values.api.port | required "set port" }}')[0].severity, "INFO")

    def test_index_nested(self):
        self.assertEqual(self.findings(template='{{ index .Values "api" "port" }}')[0].key, "api.port")

    def test_index_defined(self):
        self.assertEqual(self.findings(template='{{ index .Values "image" "tag" }}'), [])

    def test_comment_ignored(self):
        self.assertEqual(self.findings(template='{{/* .Values.secret.password */}}'), [])

    def test_multiline_comment_ignored(self):
        self.assertEqual(self.findings(template='{{/* foo\n.Values.secret.password \n */}}'), [])

    def test_line_number(self):
        self.assertEqual(self.findings(template='hello\nworld\n{{ .Values.nope }}')[0].line, 3)

    def test_multiple_refs(self):
        self.assertEqual(len(self.findings(template='{{ .Values.a }}-{{ .Values.b }}')), 2)

    def test_same_ref_in_action_once(self):
        self.assertEqual(len(self.findings(template='{{ .Values.a }} {{ .Values.a }}')), 2)

    def test_key_zero(self):
        self.assertEqual(self.findings(values='replicas: 0\n', template='{{ .Values.replicas }}'), [])

    def test_key_false(self):
        self.assertEqual(self.findings(values='enabled: false\n', template='{{ .Values.enabled }}'), [])

    def test_key_null(self):
        self.assertEqual(self.findings(values='service: null\n', template='{{ .Values.service }}'), [])

    def test_dynamic_get(self):
        x = self.findings(template='{{ get .Values "dynamic" }}')
        self.assertEqual(x[0].code, "DYNAMIC_VALUES")

    def test_dynamic_range(self):
        x = self.findings(template='{{ range .Values.items }}')
        self.assertTrue(any(a.code == "DYNAMIC_VALUES" for a in x))

    def test_other_file_scanned(self):
        x = self.findings(other='{{ .Values.extra.thing }}')
        self.assertTrue(any(a.file.endswith("_helpers.tpl") for a in x))

    def test_empty_values(self):
        self.assertEqual(self.findings(values='{}\n', template='{{ .Values.foo }}')[0].severity, "REVIEW")

    def test_malformed_values(self):
        ctx, chart = self.temp_chart(values='[\n')
        with ctx, self.assertRaises(mod.InvalidChart):
            mod.audit(chart)

    def test_duplicate_values_keys(self):
        ctx, chart = self.temp_chart(values='a: 1\na: 2\n')
        with ctx, self.assertRaises(mod.InvalidChart):
            mod.audit(chart)

    def test_nonmapping_values(self):
        ctx, chart = self.temp_chart(values='[1, 2]\n')
        with ctx, self.assertRaises(mod.InvalidChart):
            mod.audit(chart)

    def test_invalid_chart_metadata(self):
        ctx, chart = self.temp_chart()
        with ctx:
            (chart / 'Chart.yaml').write_text('version: 0.1.0\n')
            with self.assertRaises(mod.InvalidChart):
                mod.audit(chart)

    def test_oversized_values(self):
        ctx, chart = self.temp_chart()
        with ctx:
            (chart / 'values.yaml').write_bytes(b'0' * (mod.MAX_FILE_BYTES + 1))
            with self.assertRaises(mod.InvalidChart):
                mod.audit(chart)

    def test_safe_fixture_cli(self):
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/audit.py'),
            str(ROOT / 'examples/chart')], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_review_cli(self):
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/audit.py'),
            str(ROOT / 'examples/chart'), '--format', 'json'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['counts']['REVIEW'], 0)

    def test_review_fixture_cli(self):
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/audit.py'),
            str(ROOT / 'examples/chart-review'), '--format', 'json'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(json.loads(p.stdout)['findings'][0]['key'], 'image.tag')

    def test_fail_on_never(self):
        ctx, chart = self.temp_chart(template='{{ .Values.missing }}')
        with ctx:
            p = mod.run([str(chart), '--fail-on', 'never'])
            self.assertEqual(p, 0)

    def test_fail_on_review(self):
        ctx, chart = self.temp_chart(template='{{ .Values.missing }}')
        with ctx:
            p = mod.run([str(chart)])
            self.assertEqual(p, 1)


if __name__ == '__main__':
    unittest.main()
