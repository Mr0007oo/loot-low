from __future__ import annotations

import ast
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = ROOT / "server" / "plugins"


def _class_assignments(plugin_class: ast.ClassDef) -> dict[str, ast.expr]:
    assignments: dict[str, ast.expr] = {}
    for statement in plugin_class.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            assignments[statement.target.id] = statement.value
    return assignments


class PluginApiTests(unittest.TestCase):
    def test_every_plugin_manifest_and_command_matches_its_source(self) -> None:
        manifests = sorted(PLUGIN_ROOT.glob("*/pyproject.toml"))
        self.assertEqual(len(manifests), 7)

        for manifest_path in manifests:
            with self.subTest(plugin=manifest_path.parent.name):
                project = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["project"]
                self.assertEqual(project["dependencies"], ["endstone==0.11.2"])
                entry_points = project["entry-points"]["endstone"]
                self.assertEqual(len(entry_points), 1)
                entry_point, target = next(iter(entry_points.items()))
                package_name, class_name = target.split(":")
                source_path = (
                    manifest_path.parent / "src" / package_name / "__init__.py"
                )
                self.assertTrue(source_path.is_file(), f"Missing entry-point source: {source_path}")

                module = ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path),
                )
                plugin_classes = [
                    node
                    for node in module.body
                    if isinstance(node, ast.ClassDef) and node.name == class_name
                ]
                self.assertEqual(len(plugin_classes), 1)
                plugin_class = plugin_classes[0]
                assignments = _class_assignments(plugin_class)
                self.assertEqual(ast.literal_eval(assignments["api_version"]), "0.11")
                commands = ast.literal_eval(assignments["commands"])
                permissions = ast.literal_eval(assignments["permissions"])
                self.assertTrue(commands, "Plugin has no declared commands")
                self.assertTrue(entry_point)

                for command_name, command_config in commands.items():
                    self.assertIn("description", command_config, command_name)
                    self.assertTrue(command_config.get("usages"), command_name)
                    parameter_names = [
                        parameter
                        for usage in command_config["usages"]
                        for parameter in re.findall(r"<([^>]+)>", usage)
                    ]
                    self.assertEqual(
                        len(parameter_names),
                        len(set(parameter_names)),
                        f"{command_name} repeats argument enum names across usages",
                    )
                    for permission in command_config.get("permissions", []):
                        self.assertIn(
                            permission,
                            permissions,
                            f"{command_name} references undeclared permission {permission}",
                        )
                if manifest_path.parent.name == "world_edit":
                    self.assertNotIn("fill", commands)
                    self.assertIn("wefill", commands)

                handlers = [
                    node
                    for node in plugin_class.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "on_command"
                ]
                self.assertEqual(len(handlers), 1)
                handler = handlers[0]
                self.assertIsInstance(handler, ast.FunctionDef)
                assert isinstance(handler, ast.FunctionDef)
                self.assertEqual(
                    [argument.arg for argument in handler.args.args],
                    ["self", "sender", "command", "args"],
                )
                self.assertEqual(
                    [ast.unparse(argument.annotation) for argument in handler.args.args[1:]],
                    ["CommandSender", "Command", "list[str]"],
                )
                self.assertEqual(ast.unparse(handler.returns), "bool")


if __name__ == "__main__":
    unittest.main()
