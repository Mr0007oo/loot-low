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
    def test_frp_only_forwards_bedrock_udp(self) -> None:
        config = tomllib.loads((ROOT / "frpc.toml").read_text(encoding="utf-8"))
        self.assertEqual(len(config["proxies"]), 1)
        self.assertEqual(
            {
                "name": config["proxies"][0]["name"],
                "type": config["proxies"][0]["type"],
                "localIP": config["proxies"][0]["localIP"],
                "localPort": config["proxies"][0]["localPort"],
                "remotePort": config["proxies"][0]["remotePort"],
            },
            {
                "name": "minecraft-bedrock",
                "type": "udp",
                "localIP": "127.0.0.1",
                "localPort": 19132,
                "remotePort": 19132,
            },
        )

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

    def test_mob_spawning_and_arena_golem_command_are_configured(self) -> None:
        properties = {}
        for line in (ROOT / "server" / "server.properties").read_text(
            encoding="utf-8"
        ).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        self.assertEqual(properties.get("difficulty"), "normal")
        self.assertEqual(properties.get("emit-server-telemetry"), "false")

        server_utils = (
            PLUGIN_ROOT / "server_utils" / "src" / "server_utils" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"gamerule doMobSpawning true"', server_utils)
        server_utils_module = ast.parse(server_utils)
        server_utils_class = next(
            node
            for node in server_utils_module.body
            if isinstance(node, ast.ClassDef) and node.name == "ServerUtilsPlugin"
        )
        join_handler = next(
            node
            for node in server_utils_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "on_player_join"
        )
        self.assertIn(
            "self._enable_mob_spawning()",
            ast.unparse(join_handler),
        )

        pvp_duels = (
            PLUGIN_ROOT / "pvp_duels" / "src" / "pvp_duels" / "__init__.py"
        ).read_text(encoding="utf-8")
        module = ast.parse(pvp_duels)
        plugin_class = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "PvPDuelsPlugin"
        )
        assignments = _class_assignments(plugin_class)
        commands = ast.literal_eval(assignments["commands"])
        permissions = ast.literal_eval(assignments["permissions"])
        self.assertEqual(commands["spawngolem"]["usages"], ["/spawngolem"])
        self.assertEqual(
            commands["spawngolem"]["permissions"],
            ["pvpduels.spawngolem"],
        )
        self.assertEqual(permissions["pvpduels.spawngolem"]["default"], "op")
        self.assertIn('spawn_actor(location, "minecraft:iron_golem")', pvp_duels)
        self.assertIn("if not golem.is_valid:", pvp_duels)
        self.assertEqual(
            [
                ast.unparse(node.args[2])
                for node in ast.walk(plugin_class)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Location"
                and len(node.args) > 2
                and ast.unparse(node.args[2]) == "ARENA_SPAWN_Y"
            ],
            ["ARENA_SPAWN_Y"] * 3,
        )
        self.assertIn("ARENA_SPAWN_Y = ARENA_MIN_Y + 1", pvp_duels)


if __name__ == "__main__":
    unittest.main()
