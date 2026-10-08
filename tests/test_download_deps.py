from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from scripts import download_deps
from scripts import persist_world


class BedrockRuntimeTests(unittest.TestCase):
    def test_server_uses_stable_bedrock_configuration_and_server_utils_plugin(self) -> None:
        root = Path(__file__).parents[1]
        properties = {}
        for line in (root / "server" / "server.properties").read_text(
            encoding="utf-8"
        ).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        self.assertEqual(
            {
                key: properties.get(key)
                for key in (
                    "server-port",
                    "server-ip",
                    "allow-outdated-client",
                    "emit-server-telemetry",
                )
            },
            {
                "server-port": "19132",
                "server-ip": "0.0.0.0",
                "allow-outdated-client": "true",
                "emit-server-telemetry": "false",
            },
        )
        self.assertFalse(any(key.lower().startswith("rcon") for key in properties))

        launcher = (root / "server" / "start.sh").read_text(encoding="utf-8")
        watchdog = (root / "server" / "watchdog.sh").read_text(encoding="utf-8")
        self.assertNotIn("configure_rcon", launcher)
        self.assertNotIn("RCON", watchdog)
        self.assertIn("pip uninstall", launcher)
        self.assertEqual(launcher.count("pip install"), 8)
        self.assertIn('pip install --disable-pip-version-check "$wheel"', launcher)
        self.assertIn('--interactive <&"$server_stdin_fd" &', launcher)
        self.assertIn('"$SERVER_DIR/plugins/server_utils"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/fun_plugins"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/vein_miner"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/container_plugins"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/pvp_duels"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/land_claims"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/world_edit"', launcher)
        self.assertIn("exec {server_stdin_fd}< <(tail -f /dev/null)", launcher)
        self.assertIn('--no-interactive <&"$server_stdin_fd" &', launcher)
        self.assertIn("printf 'stop\\n'", launcher)
        self.assertIn('pgrep -P "$server_pid" -x bedrock_server', launcher)
        self.assertIn('kill -INT "$native_pid"', launcher)
        self.assertIn("close_server_stdin", launcher)

        plugin_manifest = root / "server" / "plugins" / "server_utils" / "pyproject.toml"
        project = tomllib.loads(plugin_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["name"], "endstone-server-utils")
        self.assertEqual(project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            project["entry-points"]["endstone"]["server-utils"],
            "server_utils:ServerUtilsPlugin",
        )
        plugin_source = (
            root / "server" / "plugins" / "server_utils" / "src" / "server_utils" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('api_version = "0.11"', plugin_source)
        self.assertIn('"serverinfo"', plugin_source)
        self.assertIn("from endstone.event import PlayerJoinEvent, event_handler", plugin_source)
        self.assertIn("self.register_events(self)", plugin_source)
        self.assertIn('"gamerule showcoordinates true"', plugin_source)
        self.assertIn("def on_player_join(self, event: PlayerJoinEvent)", plugin_source)

        workflow = (root / ".github" / "workflows" / "minecraft.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("push:\n    branches: [main]", workflow)
        self.assertIn("pip wheel", workflow)
        self.assertIn("Server utilities enabled.", workflow)
        self.assertIn("fun_plugins", workflow)
        self.assertIn("Fun command utilities enabled.", workflow)
        self.assertIn("Container commands enabled.", workflow)
        self.assertIn("Land Claims enabled", workflow)
        self.assertIn("World Edit enabled (512-block fill limit).", workflow)
        self.assertIn("PvP Duels enabled", workflow)
        self.assertIn("server/plugins/pvp_duels/src", workflow)
        for plugin in ("container_plugins", "pvp_duels", "land_claims", "world_edit"):
            self.assertIn(f"server/plugins/{plugin}", workflow)

        fun_manifest = root / "server" / "plugins" / "fun_plugins" / "pyproject.toml"
        fun_project = tomllib.loads(fun_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(fun_project["name"], "endstone-fun-plugins")
        self.assertEqual(fun_project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            fun_project["entry-points"]["endstone"]["fun-plugins"],
            "fun_plugins:FunPlugins",
        )
        fun_source = (
            root / "server" / "plugins" / "fun_plugins" / "src" / "fun_plugins" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"coinflip"', fun_source)
        self.assertIn('"roll"', fun_source)
        self.assertIn('"magic8ball"', fun_source)
        self.assertIn("ROLL_MAX_SIDES = 1_000", fun_source)
        for command in ("sethome", "home", "tpa", "tpaccept", "tpdeny"):
            self.assertIn(f'        "{command}": {{', fun_source)
        self.assertIn("self.homes, self.waypoints = self._load_data()", fun_source)
        self.assertIn("self.tpa_requests = {}", fun_source)
        self.assertIn("sender.unique_id", fun_source)
        self.assertIn("sender.location", fun_source)
        self.assertIn("@event_handler", fun_source)

        launcher = (root / "server" / "start.sh").read_text(encoding="utf-8")
        self.assertIn("trap persist_world_on_exit EXIT", launcher)
        persistence = (root / "scripts" / "persist_world.py").read_text(encoding="utf-8")
        self.assertIn('"server/world"', persistence)
        self.assertIn('"server/worlds"', persistence)
        workflow = (root / ".github" / "workflows" / "minecraft.yml").read_text(
            encoding="utf-8"
        )
        workflow_paths = {line.strip() for line in workflow.splitlines()}
        self.assertIn("server/world", persistence)
        self.assertIn("server/worlds", persistence)
        self.assertIn("Persist world progress [skip ci]", persistence)
        self.assertIn('"HEAD:refs/heads/main"', persistence)
        self.assertIn(
            '["merge", "--no-edit", "--no-commit", "--no-ff", "-X", "ours", "origin/main"]',
            persistence,
        )
        self.assertNotIn("git rebase", persistence)
        watchdog = (root / "server" / "watchdog.sh").read_text(encoding="utf-8")
        self.assertIn('WORLD_SYNC_INTERVAL_SECONDS="${WORLD_SYNC_INTERVAL_SECONDS:-3600}"', watchdog)
        self.assertIn("trap cleanup EXIT", watchdog)
        self.assertIn("trap persist_world_on_exit EXIT", launcher)
        self.assertIn("python3 scripts/persist_world.py", workflow)
        self.assertIn("persist-credentials: true", workflow)
        self.assertIn("token: ${{ github.token }}", workflow)
        self.assertIn("TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}", workflow)
        self.assertIn("TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}", workflow)
        self.assertIn("python3 scripts/telegram_console.py", workflow)
        self.assertIn("Telegram admin requested graceful server shutdown.", workflow)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn("vars.WORLD_RECOVERY_COMMIT", workflow)
        self.assertIn("--restore-only", workflow)
        self.assertNotIn("server/worlds", workflow_paths)
        self.assertNotIn("server/world/", workflow_paths)

        vein_manifest = root / "server" / "plugins" / "vein_miner" / "pyproject.toml"
        vein_project = tomllib.loads(vein_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(vein_project["name"], "endstone-vein-miner")
        self.assertEqual(vein_project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            vein_project["entry-points"]["endstone"]["vein-miner"],
            "vein_miner:VeinMinerPlugin",
        )
        vein_source = (
            root / "server" / "plugins" / "vein_miner" / "src" / "vein_miner" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MAX_BLOCKS_PER_BREAK = 32", vein_source)
        self.assertIn(
            "from endstone.event import BlockBreakEvent, EventPriority, event_handler",
            vein_source,
        )
        self.assertIn("ignore_cancelled=True", vein_source)
        self.assertIn("def on_block_break(self, event: BlockBreakEvent)", vein_source)
        self.assertIn('"veinmine"', vein_source)
        self.assertIn("self.register_events(self)", vein_source)

        plugin_specs = (
            (
                "container_plugins",
                "endstone-container-plugins",
                "container-plugins",
                "container_plugins:ContainerPlugins",
            ),
            (
                "pvp_duels",
                "endstone-pvp-duels",
                "pvp-duels",
                "pvp_duels:PvPDuelsPlugin",
            ),
            (
                "land_claims",
                "endstone-land-claims",
                "land-claims",
                "land_claims:LandClaimsPlugin",
            ),
            (
                "world_edit",
                "endstone-world-edit",
                "world-edit",
                "world_edit:WorldEditPlugin",
            ),
        )
        for folder, distribution, entry_point, target in plugin_specs:
            manifest = root / "server" / "plugins" / folder / "pyproject.toml"
            project = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]
            self.assertEqual(project["name"], distribution)
            self.assertEqual(project["dependencies"], ["endstone==0.11.2"])
            self.assertEqual(project["entry-points"]["endstone"][entry_point], target)

        containers_source = (
            root
            / "server"
            / "plugins"
            / "container_plugins"
            / "src"
            / "container_plugins"
            / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"ec"', containers_source)
        self.assertIn('"backpack"', containers_source)
        self.assertIn("sender.ender_chest", containers_source)
        self.assertIn("from endstone.form import ActionForm", containers_source)
        self.assertIn("player.send_form(", containers_source)
        self.assertIn('"Withdraw an item"', containers_source)
        self.assertIn('"Deposit an item"', containers_source)
        self.assertIn("def _withdraw_slot(", containers_source)
        self.assertIn("def _deposit_slot(", containers_source)
        self.assertIn(
            'self._store_item(sender, args[1:], sender.ender_chest, "Ender Chest", "ender")',
            containers_source,
        )
        self.assertIn(
            'self._take_item(sender, args[1:], sender.ender_chest, "Ender Chest", "ender")',
            containers_source,
        )
        self.assertIn(
            "/ec store <inventory_slot: int> <ender_store_slot: int>",
            containers_source,
        )
        self.assertIn("BACKPACK_SIZE = 27", containers_source)
        self.assertIn("self.backpacks:", containers_source)
        self.assertIn("Your personal Ender Chest is available from anywhere.", containers_source)

        duels_source = (
            root / "server" / "plugins" / "pvp_duels" / "src" / "pvp_duels" / "__init__.py"
        ).read_text(encoding="utf-8")
        for command in ("pvp", "pvpaccept", "pvpdeny"):
            self.assertIn(f'        "{command}": {{', duels_source)
        self.assertIn("class PlayerBackup:", duels_source)
        self.assertIn("self.player_backups: dict[UUID, PlayerBackup] = {}", duels_source)
        self.assertIn(
            "contents=tuple(self._copy_item(item) for item in inventory.contents)",
            duels_source,
        )
        self.assertIn("inventory.item_in_off_hand = self._copy_item(backup.offhand)", duels_source)
        self.assertIn("    PlayerDeathEvent,", duels_source)
        self.assertIn("def on_player_death(self, event: PlayerDeathEvent)", duels_source)
        self.assertIn("def on_player_quit(self, event: PlayerQuitEvent)", duels_source)
        self.assertIn("def on_player_respawn(self, event: PlayerRespawnEvent)", duels_source)
        self.assertIn("ActionForm(", duels_source)
        self.assertIn('"Netherite Kit"', duels_source)
        self.assertIn('"Crystal PvP Kit"', duels_source)
        self.assertIn('"Archer Kit"', duels_source)
        self.assertIn("ARENA_Z = 1_000.0", duels_source)
        self.assertIn("ARENA_MIN_X = -11", duels_source)
        self.assertIn("ARENA_MAX_X = 11", duels_source)
        self.assertIn("ARENA_MIN_Y = 150", duels_source)
        self.assertIn("ARENA_MAX_Y = 155", duels_source)
        self.assertIn("ARENA_MIN_Z = 989", duels_source)
        self.assertIn("ARENA_MAX_Z = 1_011", duels_source)
        self.assertIn("self._ensure_arena()", duels_source)
        self.assertIn("def _arena_blueprint()", duels_source)
        self.assertIn("block.set_type(block_type, apply_physics=False)", duels_source)
        self.assertIn("ARENA_Z - ARENA_SPAWN_Z_OFFSET", duels_source)
        self.assertIn("ARENA_Z + ARENA_SPAWN_Z_OFFSET", duels_source)
        self.assertIn(
            "Refusing to build PvP arena because a non-air block exists",
            duels_source,
        )
        self.assertIn("actor.remove()", duels_source)

        duels_tree = ast.parse(duels_source)
        arena_constants = [
            node
            for node in duels_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id.startswith("ARENA_")
                for target in node.targets
            )
        ]
        blueprint_function = next(
            node
            for node in ast.walk(duels_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_arena_blueprint"
        )
        blueprint_function.decorator_list = []
        blueprint_module = ast.Module(
            body=[*arena_constants, blueprint_function],
            type_ignores=[],
        )
        namespace = {}
        exec(compile(blueprint_module, "<arena-blueprint-test>", "exec"), namespace)
        blueprint = namespace["_arena_blueprint"]()
        self.assertTrue(blueprint)
        self.assertTrue(
            all(
                -11 <= x <= 11 and 150 <= y <= 155 and 989 <= z <= 1011
                for x, y, z in blueprint
            )
        )
        self.assertEqual(
            (
                min(x for x, _, _ in blueprint),
                max(x for x, _, _ in blueprint),
                min(y for _, y, _ in blueprint),
                max(y for _, y, _ in blueprint),
                min(z for _, _, z in blueprint),
                max(z for _, _, z in blueprint),
            ),
            (-11, 11, 150, 155, 989, 1011),
        )

        claims_source = (
            root / "server" / "plugins" / "land_claims" / "src" / "land_claims" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("BlockBreakEvent", claims_source)
        self.assertIn("BlockPlaceEvent", claims_source)
        self.assertIn("event.cancelled = True", claims_source)
        self.assertIn("claims.json", claims_source)
        self.assertIn("def can_modify(", claims_source)
        self.assertIn("PlayerInteractEvent", claims_source)
        self.assertIn("def _is_claim_wand(", claims_source)
        self.assertIn('"golden_rod"', claims_source)
        self.assertIn('"claim wand"', claims_source)
        self.assertIn("player.is_sneaking", claims_source)
        self.assertIn("def _is_container(", claims_source)
        self.assertIn("block.dimension.name", claims_source)

        world_edit_source = (
            root / "server" / "plugins" / "world_edit" / "src" / "world_edit" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MAX_FILL_BLOCKS = 512", world_edit_source)
        self.assertIn("if block_count > MAX_FILL_BLOCKS", world_edit_source)
        self.assertIn('"pos1"', world_edit_source)
        self.assertIn('"pos2"', world_edit_source)
        self.assertIn('"wefill"', world_edit_source)
        self.assertIn('"/wefill <block_type: block>"', world_edit_source)
        self.assertNotIn('"/fill <block_type: block>"', world_edit_source)
        self.assertIn("claim_plugin.can_modify(", world_edit_source)
        self.assertNotIn("from endstone.block import BlockType", world_edit_source)
        self.assertIn(".set_type(block_id)", world_edit_source)

    def make_archive(self, archive_path: Path, executable: bytes = b"pinned-bds") -> str:
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("bedrock_server", executable)
            archive.writestr("server.properties", "server-port=19132\n")
        return hashlib.sha256(archive_path.read_bytes()).hexdigest()

    def test_world_sync_commits_only_persisted_paths_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "origin.git"
            worktree = root / "worktree"
            subprocess.run(
                ["git", "init", "--bare", "--initial-branch=main", str(remote)],
                check=True,
                capture_output=True,
                text=True,
            )
            worktree.mkdir()
            subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            for key, value in (
                ("user.name", "Test"),
                ("user.email", "test@example.invalid"),
            ):
                subprocess.run(
                    ["git", "config", key, value],
                    cwd=worktree,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            (worktree / "README").write_text("initial\n", encoding="utf-8")
            player_data = worktree / "server" / "player_data"
            player_data.mkdir(parents=True)
            (player_data / ".gitkeep").write_text("\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "README", "server/player_data/.gitkeep"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", str(remote)],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            (worktree / ".gitignore").write_text("server/world/\n", encoding="utf-8")
            (worktree / "server" / "world").mkdir(parents=True)
            (worktree / "server" / "world" / "level.dat").write_bytes(b"world")
            (player_data / "fun_plugins.json").write_text(
                '{"version": 1, "homes": {}, "waypoints": {}}\n',
                encoding="utf-8",
            )
            (worktree / "unrelated.txt").write_text("keep staged\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore", "unrelated.txt"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )

            previous_root = persist_world.ROOT
            persist_world.ROOT = worktree
            try:
                self.assertTrue(persist_world.commit_and_push())
            finally:
                persist_world.ROOT = previous_root

            message = subprocess.run(
                ["git", "--git-dir", str(remote), "show", "-s", "--format=%s", "main"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertTrue(message.startswith("Persist world progress [skip ci] "))
            timestamp = message.removeprefix("Persist world progress [skip ci] ")
            self.assertIsNotNone(datetime.fromisoformat(timestamp).tzinfo)
            changed_paths = subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(remote),
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    "main",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual(
                changed_paths,
                ["server/player_data/fun_plugins.json", "server/world/level.dat"],
            )
            remaining_staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual(remaining_staged, [".gitignore", "unrelated.txt"])

    def test_world_sync_merges_concurrent_main_and_keeps_local_world_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "origin.git"
            worktree = root / "worktree"
            concurrent = root / "concurrent"
            subprocess.run(
                ["git", "init", "--bare", "--initial-branch=main", str(remote)],
                check=True,
                capture_output=True,
                text=True,
            )
            worktree.mkdir()
            subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            for key, value in (
                ("user.name", "Test"),
                ("user.email", "test@example.invalid"),
            ):
                subprocess.run(
                    ["git", "config", key, value],
                    cwd=worktree,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            world_file = worktree / "server" / "world" / "level.dat"
            world_file.parent.mkdir(parents=True)
            world_file.write_text("base world\n", encoding="utf-8")
            bedrock_db_file = (
                worktree
                / "server"
                / "bedrock_server"
                / "worlds"
                / "world"
                / "db"
                / "001040.ldb"
            )
            bedrock_db_file.parent.mkdir(parents=True)
            bedrock_db_file.write_bytes(b"bedrock snapshot base\n")
            (worktree / "README").write_text("base\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "add",
                    "README",
                    "server/world/level.dat",
                    "server/bedrock_server/worlds/world/db/001040.ldb",
                ],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", str(remote)],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", "main"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "clone", str(remote), str(concurrent)],
                check=True,
                capture_output=True,
                text=True,
            )
            for key, value in (
                ("user.name", "Concurrent"),
                ("user.email", "concurrent@example.invalid"),
            ):
                subprocess.run(
                    ["git", "config", key, value],
                    cwd=concurrent,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            world_file.write_text("local player progress\n", encoding="utf-8")
            bedrock_db_file.unlink()
            (concurrent / "README").write_text("remote workflow update\n", encoding="utf-8")
            (concurrent / "server" / "world" / "level.dat").write_text(
                "remote world snapshot\n",
                encoding="utf-8",
            )
            concurrent_db_file = (
                concurrent
                / "server"
                / "bedrock_server"
                / "worlds"
                / "world"
                / "db"
                / "001040.ldb"
            )
            renamed_db_file = concurrent_db_file.with_name("001089.ldb")
            concurrent_db_file.rename(renamed_db_file)
            renamed_db_file.write_bytes(b"bedrock snapshot remote\n")
            subprocess.run(
                [
                    "git",
                    "add",
                    "-A",
                    "--",
                    "README",
                    "server/world/level.dat",
                    "server/bedrock_server/worlds/world/db",
                ],
                cwd=concurrent,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Concurrent main update"],
                cwd=concurrent,
                check=True,
                capture_output=True,
                text=True,
            )

            original_run_git = persist_world.run_git
            publish_concurrent_update = True

            def run_git_with_concurrent_push(
                arguments: list[str],
                *,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                nonlocal publish_concurrent_update
                if arguments[:1] == ["push"] and publish_concurrent_update:
                    publish_concurrent_update = False
                    subprocess.run(
                        ["git", "push", "origin", "main"],
                        cwd=concurrent,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                return original_run_git(arguments, check=check)

            previous_root = persist_world.ROOT
            persist_world.ROOT = worktree
            persist_world.run_git = run_git_with_concurrent_push
            try:
                self.assertTrue(persist_world.commit_and_push())
            finally:
                persist_world.ROOT = previous_root
                persist_world.run_git = original_run_git

            remote_readme = subprocess.run(
                ["git", "--git-dir", str(remote), "show", "main:README"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            remote_world = subprocess.run(
                ["git", "--git-dir", str(remote), "show", "main:server/world/level.dat"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(remote_readme, "remote workflow update\n")
            self.assertEqual(remote_world, "local player progress\n")
            for db_file in (
                "server/bedrock_server/worlds/world/db/001040.ldb",
                "server/bedrock_server/worlds/world/db/001089.ldb",
            ):
                result = subprocess.run(
                    ["git", "--git-dir", str(remote), "cat-file", "-e", f"main:{db_file}"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, f"{db_file} unexpectedly persisted")
            parents = subprocess.run(
                ["git", "--git-dir", str(remote), "rev-list", "--parents", "-n", "1", "main"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.split()
            self.assertEqual(len(parents), 3)

    def test_recovery_restores_only_missing_world_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "server" / "world").mkdir(parents=True)
            (root / "server" / "world" / "level.dat").write_text(
                "recovered world\n",
                encoding="utf-8",
            )
            (root / "server" / "worlds").mkdir(parents=True)
            (root / "server" / "worlds" / "level.dat").write_text(
                "recovered bedrock world\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            for key, value in (
                ("user.name", "Test"),
                ("user.email", "test@example.invalid"),
            ):
                subprocess.run(
                    ["git", "config", key, value],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            subprocess.run(
                ["git", "add", "server/world", "server/worlds"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "World recovery snapshot"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            shutil.rmtree(root / "server" / "world")
            (root / "server" / "worlds" / "level.dat").write_text(
                "newer active world\n",
                encoding="utf-8",
            )
            previous_root = persist_world.ROOT
            persist_world.ROOT = root
            try:
                self.assertEqual(persist_world.restore_world_paths(commit), ["server/world"])
            finally:
                persist_world.ROOT = previous_root
            self.assertEqual(
                (root / "server" / "world" / "level.dat").read_text(encoding="utf-8"),
                "recovered world\n",
            )
            self.assertEqual(
                (root / "server" / "worlds" / "level.dat").read_text(encoding="utf-8"),
                "newer active world\n",
            )

    def test_install_replaces_runtime_preserving_worlds_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            old_runtime = server_dir / "bedrock_server"
            old_runtime.mkdir()
            (old_runtime / "bedrock_server").write_bytes(b"stale-bds")
            (old_runtime / "obsolete-runtime-file").write_text("stale", encoding="utf-8")
            (old_runtime / "worlds").mkdir()
            (old_runtime / "worlds" / "level.dat").write_bytes(b"world")
            old_plugin = old_runtime / "plugins" / "custom" / "plugin.py"
            old_plugin.parent.mkdir(parents=True)
            old_plugin.write_text("old plugin", encoding="utf-8")
            (server_dir / "allowlist.json").write_text("[]\n", encoding="utf-8")
            (server_dir / "server.properties").write_text(
                "server-port=19132\n",
                encoding="utf-8",
            )
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)

            result = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )

            self.assertEqual(result, old_runtime)
            self.assertEqual((result / "bedrock_server").read_bytes(), b"pinned-bds")
            self.assertFalse((result / "obsolete-runtime-file").exists())
            self.assertFalse((result / "plugins").exists())
            self.assertEqual((result / "worlds" / "level.dat").read_bytes(), b"world")
            self.assertEqual((result / "server.properties").read_text(), "server-port=19132\n")
            self.assertEqual((result / "allowlist.json").read_text(), "[]\n")
            self.assertEqual((result / "version.txt").read_text(), "26.3\n")
            self.assertEqual(
                download_deps.verify_bds_install(
                    result,
                    expected_archive_sha256=archive_hash,
                )["bedrock_version"],
                "1.26.3.1",
            )

    def test_verifier_rejects_version_file_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)
            bds_dir = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )
            (bds_dir / "version.txt").write_text("26.51\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "version file must contain"):
                download_deps.verify_bds_install(
                    bds_dir,
                    expected_archive_sha256=archive_hash,
                )

    def test_checksum_mismatch_does_not_replace_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            old_executable = server_dir / "bedrock_server" / "bedrock_server"
            old_executable.parent.mkdir()
            old_executable.write_bytes(b"keep-me")
            archive_path = server_dir / "bds.zip"
            self.make_archive(archive_path)

            with self.assertRaisesRegex(RuntimeError, "failed SHA-256"):
                download_deps.install_bds_archive(
                    archive_path,
                    server_dir=server_dir,
                    expected_archive_sha256="0" * 64,
                )
            self.assertEqual(old_executable.read_bytes(), b"keep-me")

    def test_verifier_rejects_changed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)
            bds_dir = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )
            (bds_dir / "bedrock_server").write_bytes(b"replaced-binary")

            with self.assertRaisesRegex(RuntimeError, "does not match its verified manifest"):
                download_deps.verify_bds_install(
                    bds_dir,
                    expected_archive_sha256=archive_hash,
                )

    def test_archive_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server_dir = root / "server"
            server_dir.mkdir()
            archive_path = server_dir / "bds.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("bedrock_server", b"pinned-bds")
                archive.writestr("../outside", b"not allowed")
            archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()

            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                download_deps.install_bds_archive(
                    archive_path,
                    server_dir=server_dir,
                    expected_archive_sha256=archive_hash,
                )
            self.assertFalse((root / "outside").exists())

    def test_pins_match_selected_supported_pair(self) -> None:
        self.assertEqual(download_deps.ENDSTONE_VERSION, "0.11.2")
        self.assertEqual(download_deps.BDS_VERSION, "1.26.3.1")
        self.assertEqual(download_deps.ENDSTONE_BDS_VERSION, "26.3")
        self.assertIn("bedrock-server-1.26.3.1.zip", download_deps.BDS_ARCHIVE_URL)
        self.assertEqual(len(download_deps.BDS_ARCHIVE_SHA256), 64)
        launcher = (
            Path(__file__).parents[1] / "server" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('!= "0.11.2 26.3"', launcher)
        self.assertIn("--yes", launcher)
        self.assertIn("--no-interactive", launcher)
        self.assertIn("download_deps.py\" --check", launcher)
        self.assertLess(
            launcher.index('download_deps.py" --check'),
            launcher.index("-m endstone \\"),
        )
        workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "minecraft.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ENDSTONE_VERSION: 0.11.2", workflow)
        self.assertIn("BEDROCK_CLIENT_VERSION: 1.26.2", workflow)

    def test_watchdog_restarts_clean_server_exit_and_stays_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frpc = root / "frpc"
            launcher = root / "start-server"
            config = root / "frpc.toml"
            frpc_log = root / "frpc.log"
            server_log = root / "server.log"
            watchdog_log = root / "watchdog.log"
            counter = root / "launch-count"
            running = root / "server-running"
            output = root / "watchdog-stdout.log"
            persister = root / "persist-world.py"
            config.write_text("config = true\n", encoding="utf-8")
            persister.write_text("raise SystemExit(0)\n", encoding="utf-8")
            frpc.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, time\n"
                "running = True\n"
                "def stop(*_):\n"
                "    global running\n"
                "    running = False\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "while running:\n"
                "    time.sleep(0.1)\n",
                encoding="utf-8",
            )
            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, time\n"
                "from pathlib import Path\n"
                f"counter = Path({str(counter)!r})\n"
                f"running_file = Path({str(running)!r})\n"
                "count = int(counter.read_text() if counter.exists() else '0') + 1\n"
                "counter.write_text(str(count))\n"
                "if count == 1:\n"
                "    raise SystemExit(0)\n"
                "running = True\n"
                "def stop(*_):\n"
                "    global running\n"
                "    running = False\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "running_file.touch()\n"
                "while running:\n"
                "    time.sleep(0.1)\n",
                encoding="utf-8",
            )
            frpc.chmod(0o755)
            launcher.chmod(0o755)
            env = os.environ | {
                "FRP_SERVER_IP": "127.0.0.1",
                "FRP_TOKEN": "test-token",
                "FRPC_BIN": str(frpc),
                "FRPC_CONFIG": str(config),
                "FRPC_LOG": str(frpc_log),
                "SERVER_LAUNCHER": str(launcher),
                "WORLD_PERSIST_SCRIPT": str(persister),
                "SERVER_LOG": str(server_log),
                "WATCHDOG_LOG": str(watchdog_log),
                "WATCHDOG_INTERVAL_SECONDS": "1",
            }
            with output.open("w", encoding="utf-8") as stdout:
                watchdog = subprocess.Popen(
                    ["bash", str(Path(__file__).parents[1] / "server" / "watchdog.sh")],
                    env=env,
                    stdout=stdout,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if running.exists() and counter.exists() and counter.read_text() == "2":
                            break
                        if watchdog.poll() is not None:
                            self.fail(f"Watchdog exited unexpectedly with status {watchdog.returncode}")
                        time.sleep(0.1)
                    else:
                        self.fail("Watchdog did not restart after a clean server exit")

                    watchdog.terminate()
                    self.assertNotEqual(watchdog.wait(timeout=10), 0)
                finally:
                    if watchdog.poll() is None:
                        watchdog.terminate()
                        watchdog.wait(timeout=10)

            log_text = output.read_text(encoding="utf-8")
            self.assertIn(
                "Endstone supervisor exited with status 0; restarting in 5 seconds.",
                log_text,
            )


if __name__ == "__main__":
    unittest.main()
