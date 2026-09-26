import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UpdateShutdownTests(unittest.TestCase):
    def test_inno_closes_running_app_without_restarting_it(self):
        installer = (ROOT / "build_exe" / "installer" / "installer.iss").read_text(encoding="utf-8")
        setup_section = installer.split("[Setup]", 1)[1].split("[Languages]", 1)[0]
        settings = {
            line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
            for line in setup_section.splitlines()
            if "=" in line and not line.lstrip().startswith(";")
        }

        self.assertEqual(settings.get("CloseApplications"), "yes")
        self.assertEqual(settings.get("RestartApplications"), "no")

    def test_in_app_update_explicitly_closes_apps_and_disables_restart(self):
        source = (ROOT / "kohya_gui.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        flags_node = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "UPDATE_INSTALLER_FLAGS"
                    for target in node.targets)
        )
        flags = ast.literal_eval(flags_node)

        self.assertIn("/CLOSEAPPLICATIONS", flags)
        self.assertIn("/NORESTARTAPPLICATIONS", flags)
        self.assertIn("/NORESTART", flags)
        self.assertIn("subprocess.Popen(_update_installer_command(dest))", source)
        self.assertNotIn("装完自动重启", source)


if __name__ == "__main__":
    unittest.main()
