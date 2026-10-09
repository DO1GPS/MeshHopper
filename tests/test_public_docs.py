"""Public documentation examples: local files and pure parser, never radio."""
import ast
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bot"))
from bot_commands import parse_command  # noqa: E402


class PublicDocumentationTests(unittest.TestCase):
    def test_documented_command_forms_match_the_actual_parser(self):
        for text, expected in (("ping", "ping"), ("reping", "ping"), ("PING", "ping"),
                               ("test", "test"), ("retest", "test"), ("Test", "test"),
                               ("ping test", "test"), ("test ping", "test"),
                               ("room", "room"), ("ping 123", "ping"),
                               ("#ping", "ping"), ("#test", "test"), ("#room", "room"),
                               ("#reping", "ping"), ("#retest", "test"), ("#ping test", "test"),
                               ("Danke", "thanks"), ("thanks", "thanks"), ("danke 73", "thanks"),
                               ("@MeshHopper danke", "thanks"),
                               ("bitte ping mich", None), ("pong", None),
                               ("room test", None), ("ping ping", None),
                               ("ping he", None), ("Ping von 55566", None),
                               ("🤖 Gern geschehen ✌🏻, 73", None)):
            with self.subTest(text=text):
                self.assertEqual(parse_command(text), expected)

    def test_offline_example_runs_without_optional_packages(self):
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "examples/inspect_meshhopper_commands.py")]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 6)
        self.assertIn("'ReTest' -> TEST", result.stdout)
        self.assertIn("'ping test' -> TEST", result.stdout)
        self.assertIn("'bitte ping mich' -> keine Antwort", result.stdout)

    def test_offline_example_accepts_the_documented_arguments(self):
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "examples/inspect_meshhopper_commands.py"),
                   "ReTest", "ping test", "bitte ping mich"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["'ReTest' -> TEST", "'ping test' -> TEST",
                                                     "'bitte ping mich' -> keine Antwort"])

    def test_offline_example_recognizes_the_thanks_family_without_sending(self):
        command = [sys.executable, "-I", "-S", "-B", str(ROOT / "examples/inspect_meshhopper_commands.py"), "Danke"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["'Danke' -> THANKS"])

    def test_public_readme_local_links_resolve_inside_workspace(self):
        document = ROOT / "README.md"
        content = document.read_text(encoding="utf-8")
        targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
        self.assertTrue(targets)
        for relative in targets:
            with self.subTest(relative=relative):
                path = (document.parent / relative).resolve()
                self.assertTrue(path.is_relative_to(ROOT.resolve()))
                self.assertTrue(path.is_file())

    def test_readme_names_the_current_device_and_firmware(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        scope = content.split("## Was in dieser Fassung steckt\n", 1)[1].split("## ", 1)[0]
        profile = ast.parse((ROOT / "services/bot/report_profile.py").read_text(encoding="utf-8"))
        values = {node.value for node in ast.walk(profile)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for value in ("Seeed Wio Tracker L1", "1.17.1-d929643"):
            self.assertIn(value, values)
        self.assertIn("Seeed Wio Tracker L1", scope)
        self.assertIn("`1.17.1-d929643`", scope)
        self.assertNotIn("ein bestimmtes Gerät", scope)

    def test_public_docs_describe_local_settings_without_personal_values(self):
        documents = [ROOT / "README.md", ROOT / "docs/public/DEVELOPMENT.de.md"]
        staging = ROOT / "docs/public/release_staging/DEVELOPMENT.de.md"
        if staging.is_file():
            documents.append(staging)
        for document in documents:
            with self.subTest(document=document.relative_to(ROOT)):
                content = document.read_text(encoding="utf-8")
                self.assertTrue("`MESHCORE_COMPANION_NAME`" in content,
                                "Local companion setting must be documented")
                self.assertTrue("lokal" in content, "The setting must be local")
                self.assertTrue("Geräteprüfung" in content, "Keep the device check explicit")

    def test_readme_uses_a_factual_response_section_heading(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("\n## Antworttext und Erläuterung\n", content)
        self.assertNotIn("## So liest du die Antwort", content)

    def test_readme_response_example_has_the_current_five_line_layout(self):
        content = (ROOT / "README.md").read_text(encoding="utf-8")
        section = content.split("## Antworttext und Erläuterung\n", 1)[1].split("## ", 1)[0]
        block = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
        self.assertIsNotNone(block, "A concrete response example must be documented")
        lines = block[1].splitlines()
        self.assertEqual(len(lines), 5)
        self.assertRegex(lines[0], r"^PONG @.+$")
        self.assertRegex(lines[1], r"^TX: .+$")
        self.assertRegex(lines[2], r"^RX: [0-9]+ 🐇 \| SNR [+-][0-9]+(?:\.[0-9]+)? dB$")
        self.assertTrue(lines[3].startswith("Weg: "))
        self.assertIn("→", lines[3])
        self.assertTrue(lines[4].startswith("QTH: "))
        self.assertNotIn("Rückweg offen", block[1])
        self.assertNotIn("RSSI", block[1])

    def test_public_docs_explain_local_qth_and_thanks(self):
        documents = [ROOT / "README.md", ROOT / "docs/public/DEVELOPMENT.de.md"]
        staged = ROOT / "docs/public/release_staging/DEVELOPMENT.de.md"
        if staged.is_file():
            documents.append(staged)
        for document in documents:
            with self.subTest(document=document.relative_to(ROOT)):
                content = document.read_text(encoding="utf-8")
                self.assertIn("MESHCORE_MONITOR_QTH", content)
                self.assertIn("danke", content.lower())


if __name__ == "__main__":
    unittest.main()
