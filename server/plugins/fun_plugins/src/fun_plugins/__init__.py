import json
import math
import os
import re
import secrets
from pathlib import Path
from typing import TypedDict

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import PlayerQuitEvent, event_handler
from endstone.level import Location
from endstone.plugin import Plugin


ROLL_DEFAULT_SIDES = 6
ROLL_MAX_SIDES = 1_000
AUTOSAVE_TICKS = 20 * 60 * 60
EIGHT_BALL_ANSWERS = (
    "Absolutely!",
    "The odds look good.",
    "Ask again in a little while.",
    "Probably not.",
    "The outlook is not great.",
    "Definitely not!",
)


class SavedLocation(TypedDict):
    dimension: str
    x: float
    y: float
    z: float
    pitch: float
    yaw: float


def _find_online_player(server: object, args: list[str]) -> Player | None:
    name = " ".join(args).strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in ("'", '"'):
        name = name[1:-1].strip()
    if not name:
        return None

    players = server.online_players
    exact_matches = [player for player in players if player.name.casefold() == name.casefold()]
    if len(exact_matches) == 1:
        return exact_matches[0]

    compact_name = "".join(name.split()).casefold()
    compact_matches = [
        player for player in players
        if "".join(player.name.split()).casefold() == compact_name
    ]
    return compact_matches[0] if len(compact_matches) == 1 else None


class FunPlugins(Plugin):
    api_version = "0.11"
    prefix = "Fun"

    commands = {
        "coinflip": {
            "description": "Flip a coin",
            "usages": ["/coinflip"],
            "permissions": ["funplugins.coinflip"],
        },
        "roll": {
            "description": "Roll a die (optionally choose 2-1000 sides)",
            "usages": ["/roll [sides: int]"],
            "permissions": ["funplugins.roll"],
        },
        "magic8ball": {
            "description": "Ask the magic 8-ball a question",
            "usages": ["/magic8ball <question: message>"],
            "permissions": ["funplugins.magic8ball"],
        },
        "sethome": {
            "description": "Set your home at your current location",
            "usages": ["/sethome"],
            "permissions": ["funplugins.sethome"],
        },
        "home": {
            "description": "Teleport to your saved home",
            "usages": ["/home"],
            "permissions": ["funplugins.home"],
        },
        "setwaypoint": {
            "description": "Save your current location as a named waypoint",
            "usages": ["/setwaypoint <name: string>"],
            "permissions": ["funplugins.sethome"],
        },
        "waypointlist": {
            "description": "List your saved waypoints",
            "usages": ["/waypointlist"],
            "permissions": ["funplugins.home"],
        },
        "waypoint": {
            "description": "Teleport to one of your saved waypoints",
            "usages": ["/waypoint <name: string>"],
            "permissions": ["funplugins.home"],
        },
        "tpa": {
            "description": "Request to teleport to another player",
            "usages": ["/tpa <player: message>"],
            "permissions": ["funplugins.tpa"],
        },
        "tpaccept": {
            "description": "Accept a pending teleport request",
            "usages": ["/tpaccept"],
            "permissions": ["funplugins.tpaccept"],
        },
        "tpdeny": {
            "description": "Deny a pending teleport request",
            "usages": ["/tpdeny"],
            "permissions": ["funplugins.tpdeny"],
        },
    }

    permissions = {
        "funplugins.coinflip": {
            "description": "Flip a coin",
            "default": True,
        },
        "funplugins.roll": {
            "description": "Roll a die",
            "default": True,
        },
        "funplugins.magic8ball": {
            "description": "Ask the magic 8-ball a question",
            "default": True,
        },
        "funplugins.sethome": {
            "description": "Set your home",
            "default": True,
        },
        "funplugins.home": {
            "description": "Teleport to your home",
            "default": True,
        },
        "funplugins.tpa": {
            "description": "Request to teleport to another player",
            "default": True,
        },
        "funplugins.tpaccept": {
            "description": "Accept teleport requests",
            "default": True,
        },
        "funplugins.tpdeny": {
            "description": "Deny teleport requests",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        configured_data_dir = os.environ.get("LOOT_LOW_PLAYER_DATA_DIR")
        data_dir = Path(configured_data_dir) if configured_data_dir else Path(self.data_folder)
        self.data_path = data_dir / "fun_plugins.json"
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.homes, self.waypoints = self._load_data()
        self.tpa_requests = {}
        self.register_events(self)
        self.server.scheduler.run_task(
            self,
            self._save_data,
            delay=AUTOSAVE_TICKS,
            period=AUTOSAVE_TICKS,
        )
        self.logger.info("Fun command utilities enabled.")

    def on_disable(self) -> None:
        self._save_data()

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        self._save_data()

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "coinflip":
            sender.send_message(f"Coin flip: {secrets.choice(('Heads', 'Tails'))}!")
            return True

        if command.name == "roll":
            if len(args) > 1:
                sender.send_message("Error: Usage: /roll [sides]")
                return True
            if args:
                try:
                    sides = int(args[0])
                except ValueError:
                    sender.send_message("Error: Sides must be a whole number from 2 to 1000.")
                    return True
            else:
                sides = ROLL_DEFAULT_SIDES
            if not 2 <= sides <= ROLL_MAX_SIDES:
                sender.send_message("Error: Sides must be from 2 to 1000.")
                return True
            sender.send_message(f"You rolled {secrets.randbelow(sides) + 1} (d{sides}).")
            return True

        if command.name == "magic8ball":
            if not args:
                sender.send_message("Error: Usage: /magic8ball <question>")
                return True
            sender.send_message(f"Magic 8-ball: {secrets.choice(EIGHT_BALL_ANSWERS)}")
            return True

        if command.name in (
            "sethome",
            "home",
            "setwaypoint",
            "waypointlist",
            "waypoint",
            "tpa",
            "tpaccept",
            "tpdeny",
        ):
            if not isinstance(sender, Player):
                sender.send_message("Error: This command can only be used by a player.")
                return True

        if command.name == "sethome":
            if args:
                sender.send_message("Error: Usage: /sethome")
                return True
            homes = dict(self.homes)
            homes[str(sender.unique_id)] = self._serialize_location(sender.location)
            if not self._save_data(homes=homes):
                sender.send_message("Error: Your home was not changed because saving failed.")
                return True
            self.homes = homes
            sender.send_message("Home set at your current location.")
            return True

        if command.name == "home":
            if args:
                sender.send_message("Error: Usage: /home")
                return True
            saved_location = self.homes.get(str(sender.unique_id))
            if saved_location is None:
                sender.send_message("Error: You have not set a home yet.")
                return True
            location = self._deserialize_location(saved_location)
            if location is None:
                sender.send_message("Error: The dimension containing your home is unavailable.")
                return True
            if sender.teleport(location):
                sender.send_message("Teleported to your home.")
            else:
                sender.send_message("Error: Could not teleport you to your home.")
            return True

        if command.name == "setwaypoint":
            if len(args) != 1 or not self._valid_waypoint_name(args[0]):
                sender.send_message("Error: Usage: /setwaypoint <name> (letters, numbers, _ or -).")
                return True
            name = args[0].casefold()
            waypoints = {key: dict(value) for key, value in self.waypoints.items()}
            player_waypoints = waypoints.setdefault(str(sender.unique_id), {})
            player_waypoints[name] = self._serialize_location(sender.location)
            if not self._save_data(waypoints=waypoints):
                sender.send_message(
                    "Error: The waypoint was not changed because saving failed."
                )
                return True
            self.waypoints = waypoints
            sender.send_message(f"Waypoint '{name}' saved at your current location.")
            return True

        if command.name == "waypointlist":
            if args:
                sender.send_message("Error: Usage: /waypointlist")
                return True
            player_waypoints = self.waypoints.get(str(sender.unique_id), {})
            if not player_waypoints:
                sender.send_message("You have no saved waypoints. Use /setwaypoint <name>.")
                return True
            sender.send_message("Your waypoints: " + ", ".join(sorted(player_waypoints)))
            return True

        if command.name == "waypoint":
            if len(args) != 1:
                sender.send_message("Error: Usage: /waypoint <name>")
                return True
            name = args[0].casefold()
            saved_location = self.waypoints.get(str(sender.unique_id), {}).get(name)
            if saved_location is None:
                sender.send_message(
                    f"Error: Waypoint '{name}' was not found. Use /waypointlist to see yours."
                )
                return True
            location = self._deserialize_location(saved_location)
            if location is None:
                sender.send_message(
                    "Error: The dimension containing this waypoint is unavailable."
                )
                return True
            if sender.teleport(location):
                sender.send_message(f"Teleported to waypoint '{name}'.")
            else:
                sender.send_message(f"Error: Could not teleport you to waypoint '{name}'.")
            return True

        if command.name == "tpa":
            if not args:
                sender.send_message("Error: Usage: /tpa <player>")
                return True
            target = _find_online_player(self.server, args)
            if target is None:
                sender.send_message(
                    "Error: That player is not online or the name is ambiguous."
                )
                return True
            if target.unique_id == sender.unique_id:
                sender.send_message("Error: You cannot request to teleport to yourself.")
                return True
            self.tpa_requests[target.unique_id] = sender.unique_id
            target.send_message(
                f"{sender.name} requested to teleport to you. Use /tpaccept or /tpdeny."
            )
            sender.send_message(f"Teleport request sent to {target.name}.")
            return True

        if command.name == "tpaccept":
            if args:
                sender.send_message("Error: Usage: /tpaccept")
                return True
            requester_id = self.tpa_requests.pop(sender.unique_id, None)
            if requester_id is None:
                sender.send_message("Error: You have no pending teleport requests.")
                return True
            requester = self.server.get_player(requester_id)
            if requester is None:
                sender.send_message("Error: The requesting player is no longer online.")
                return True
            if requester.teleport(sender.location):
                requester.send_message(f"{sender.name} accepted your teleport request.")
                sender.send_message(f"Teleported {requester.name} to you.")
            else:
                requester.send_message("Error: Your teleport request could not be completed.")
                sender.send_message("Error: Could not teleport the requesting player.")
            return True

        if command.name == "tpdeny":
            if args:
                sender.send_message("Error: Usage: /tpdeny")
                return True
            requester_id = self.tpa_requests.pop(sender.unique_id, None)
            if requester_id is None:
                sender.send_message("Error: You have no pending teleport requests.")
                return True
            requester = self.server.get_player(requester_id)
            sender.send_message("Teleport request denied.")
            if requester is not None:
                requester.send_message(f"{sender.name} denied your teleport request.")
            return True

        return False

    def _load_data(self) -> tuple[dict[str, SavedLocation], dict[str, dict[str, SavedLocation]]]:
        if not self.data_path.exists():
            return {}, {}
        try:
            data = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read home and waypoint data: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise RuntimeError("Home and waypoint data has an unsupported format.")

        homes_raw = data.get("homes")
        waypoints_raw = data.get("waypoints")
        if not isinstance(homes_raw, dict) or not isinstance(waypoints_raw, dict):
            raise RuntimeError("Home and waypoint data is missing required records.")
        homes = {
            player_id: self._validate_saved_location(record)
            for player_id, record in homes_raw.items()
            if isinstance(player_id, str)
        }
        waypoints: dict[str, dict[str, SavedLocation]] = {}
        for player_id, records in waypoints_raw.items():
            if not isinstance(player_id, str) or not isinstance(records, dict):
                raise RuntimeError("Waypoint data contains an invalid player record.")
            waypoints[player_id] = {
                name: self._validate_saved_location(record)
                for name, record in records.items()
                if isinstance(name, str) and self._valid_waypoint_name(name)
            }
        if len(homes) != len(homes_raw):
            raise RuntimeError("Home data contains an invalid player ID.")
        return homes, waypoints

    @staticmethod
    def _validate_saved_location(record: object) -> SavedLocation:
        if not isinstance(record, dict) or not isinstance(record.get("dimension"), str):
            raise RuntimeError("Saved location data contains an invalid dimension.")
        values: dict[str, float] = {}
        for key in ("x", "y", "z", "pitch", "yaw"):
            value = record.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RuntimeError(f"Saved location data contains an invalid {key} value.")
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise RuntimeError(f"Saved location data contains a non-finite {key} value.")
            values[key] = numeric_value
        return {
            "dimension": record["dimension"],
            "x": values["x"],
            "y": values["y"],
            "z": values["z"],
            "pitch": values["pitch"],
            "yaw": values["yaw"],
        }

    @staticmethod
    def _serialize_location(location: Location) -> SavedLocation:
        return {
            "dimension": location.dimension.name,
            "x": location.x,
            "y": location.y,
            "z": location.z,
            "pitch": location.pitch,
            "yaw": location.yaw,
        }

    def _deserialize_location(self, saved: SavedLocation) -> Location | None:
        dimension = self.server.level.get_dimension(saved["dimension"])
        if dimension is None:
            self.logger.error(
                f"Saved location refers to unavailable dimension {saved['dimension']!r}."
            )
            return None
        return Location(
            dimension,
            saved["x"],
            saved["y"],
            saved["z"],
            saved["pitch"],
            saved["yaw"],
        )

    @staticmethod
    def _valid_waypoint_name(name: str) -> bool:
        return re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) is not None

    def _save_data(
        self,
        *,
        homes: dict[str, SavedLocation] | None = None,
        waypoints: dict[str, dict[str, SavedLocation]] | None = None,
    ) -> bool:
        payload = {
            "version": 1,
            "homes": homes if homes is not None else self.homes,
            "waypoints": waypoints if waypoints is not None else self.waypoints,
        }
        temporary_path = self.data_path.with_name(f"{self.data_path.name}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.data_path)
        except OSError as exc:
            self.logger.error(f"Could not save home and waypoint data: {exc}")
            return False
        return True
