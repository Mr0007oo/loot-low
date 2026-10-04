from __future__ import annotations

import json
import math
import os
import re
import tempfile
from itertools import product
from pathlib import Path
from typing import Any

from endstone import Player
from endstone.block import Block
from endstone.command import Command, CommandSender
from endstone.event import (
    ActorExplodeEvent,
    BlockBreakEvent,
    BlockExplodeEvent,
    BlockPlaceEvent,
    PlayerInteractEvent,
    event_handler,
)
from endstone.form import ActionForm
from endstone.inventory import ItemStack
from endstone.level import Location
from endstone.plugin import Plugin
from endstone.scoreboard import Criteria, DisplaySlot, RenderType
from typing_extensions import override


MAX_EDIT_BLOCKS = 32_768
BACKPACK_SLOTS = 27
CLAIM_RADIUS = 8
NAME_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,32}\Z")
BLOCK_PATTERN = re.compile(r"(?:[a-z0-9_]+:)?[a-z0-9_]+\Z")


def _empty_data() -> dict[str, Any]:
    return {"homes": {}, "warps": {}, "claims": [], "backpacks": {}}


def _location_data(player: Player) -> dict[str, Any]:
    location = player.location
    return {
        "dimension": location.dimension.name,
        "x": location.x,
        "y": location.y,
        "z": location.z,
        "pitch": location.pitch,
        "yaw": location.yaw,
    }


def _item_data(item: ItemStack) -> dict[str, Any]:
    return {"type": item.type.id, "amount": item.amount, "data": item.data}


class LootLowPlugin(Plugin):
    prefix = "LootLowBedrock"
    api_version = "0.11"

    commands = {
        "home": {
            "description": "Teleport to a saved home",
            "usages": ["/home [name]"],
            "permissions": ["lootlow.home"],
        },
        "sethome": {
            "description": "Save a home at your current location",
            "usages": ["/sethome [name]"],
            "permissions": ["lootlow.sethome"],
        },
        "setwarp": {
            "description": "Create or update a server warp",
            "usages": ["/setwarp <name>"],
            "permissions": ["lootlow.setwarp"],
        },
        "warp": {
            "description": "List or visit server warps",
            "usages": ["/warp [name]"],
            "permissions": ["lootlow.warp"],
        },
        "claim": {
            "description": "Protect a 17 by 17 area around you",
            "usages": ["/claim"],
            "permissions": ["lootlow.claim"],
        },
        "unclaim": {
            "description": "Remove your land claim",
            "usages": ["/unclaim"],
            "permissions": ["lootlow.unclaim"],
        },
        "backpack": {
            "description": "Open your persistent backpack",
            "usages": ["/backpack"],
            "permissions": ["lootlow.backpack"],
        },
        "enderchest": {
            "description": "Open your native Ender Chest inventory",
            "usages": ["/enderchest"],
            "permissions": ["lootlow.enderchest"],
        },
        "bedrockedit": {
            "description": "Select and edit a bounded region",
            "usages": ["/bedrockedit <pos1|pos2|set> [block]"],
            "aliases": ["worldedit", "we"],
            "permissions": ["lootlow.bedrockedit"],
        },
    }

    permissions = {
        "lootlow.home": {"description": "Use saved homes", "default": True},
        "lootlow.sethome": {"description": "Save a home", "default": True},
        "lootlow.setwarp": {"description": "Create or update server warps", "default": "op"},
        "lootlow.warp": {"description": "Use server warps", "default": True},
        "lootlow.claim": {"description": "Create a land claim", "default": True},
        "lootlow.unclaim": {"description": "Remove your land claim", "default": True},
        "lootlow.backpack": {"description": "Use your persistent backpack", "default": True},
        "lootlow.enderchest": {"description": "Access your Ender Chest inventory", "default": True},
        "lootlow.bedrockedit": {"description": "Edit bounded regions", "default": "op"},
    }

    @override
    def on_enable(self) -> None:
        data_dir = Path(os.environ.get("LOOT_LOW_DATA_DIR", "plugins/lootlow_bedrock/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self._data_path = data_dir / "data.json"
        self._data = self._load_data()
        self._selections: dict[str, dict[str, Any]] = {}
        scoreboard = self.server.scoreboard
        for objective in scoreboard.objectives:
            if objective.name == "lootlow_health":
                objective.unregister()
                break
        self._health_objective = scoreboard.add_objective(
            "lootlow_health",
            Criteria.DUMMY,
            "Health",
            RenderType.HEARTS,
        )
        self._health_objective.set_display(DisplaySlot.BELOW_NAME)
        self.server.scheduler.run_task(self, self._update_health_scores, delay=1, period=20)
        self.register_events(self)
        self.logger.info("Native Bedrock utility and protection features enabled.")

    def _update_health_scores(self) -> None:
        for player in self.server.online_players:
            self._health_objective.get_score(player).value = player.health

    def _load_data(self) -> dict[str, Any]:
        if not self._data_path.exists():
            return _empty_data()
        with self._data_path.open(encoding="utf-8") as stream:
            data = json.load(stream)
        for key, default in _empty_data().items():
            if key not in data or not isinstance(data[key], type(default)):
                raise ValueError(f"Invalid plugin data: {key} must be {type(default).__name__}")
        return data

    def _save_data(self) -> None:
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._data_path.parent,
            prefix=".data.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(self._data, stream, indent=2)
            stream.write("\n")
        temp_path.replace(self._data_path)

    @staticmethod
    def _player_key(player: Player) -> str:
        return str(player.unique_id)

    @staticmethod
    def _named_record(records: dict[str, Any], name: str) -> dict[str, Any] | None:
        return next((value for key, value in records.items() if key.casefold() == name.casefold()), None)

    def _teleport(self, player: Player, destination: dict[str, Any]) -> bool:
        dimension = player.level.get_dimension(destination["dimension"])
        location = Location(
            dimension,
            float(destination["x"]),
            float(destination["y"]),
            float(destination["z"]),
            float(destination.get("pitch", 0.0)),
            float(destination.get("yaw", 0.0)),
        )
        return player.teleport(location)

    def _send_form(self, player: Player, title: str, content: str, buttons: list[tuple[str, Any]]) -> None:
        form = ActionForm(title=title, content=content)
        for label, callback in buttons:
            form.add_button(label, on_click=callback)
        player.send_form(form)

    def _open_end_chest(self, player: Player) -> None:
        inventory = player.ender_chest
        buttons: list[tuple[str, Any]] = []
        for slot in range(inventory.size):
            item = inventory.get_item(slot)
            if item is not None:
                buttons.append(
                    (
                        f"Take slot {slot + 1}: {item.type.id} x{item.amount}",
                        lambda target, index=slot: self._take_end_chest(target, index),
                    )
                )
        buttons.append(("Deposit the item in your hand", self._deposit_end_chest))
        self._send_form(player, "Ender Chest", "Choose an item to take, or deposit your held item.", buttons)

    def _take_end_chest(self, player: Player, slot: int) -> None:
        inventory = player.ender_chest
        item = inventory.get_item(slot)
        if item is None:
            player.send_error_message("That Ender Chest slot is empty.")
            return
        original_amount = item.amount
        leftovers = player.inventory.add_item(item)
        remaining = sum(stack.amount for stack in leftovers.values())
        if remaining >= original_amount:
            player.send_error_message("Your inventory is full.")
            return
        if remaining:
            item.amount = remaining
            inventory.set_item(slot, item)
        else:
            inventory.set_item(slot, None)
        player.send_message(f"Moved {original_amount - remaining} {item.type.id} to your inventory.")

    def _deposit_end_chest(self, player: Player) -> None:
        hand = player.inventory.item_in_main_hand
        if hand is None:
            player.send_error_message("Hold an item before depositing it.")
            return
        original_amount = hand.amount
        leftovers = player.ender_chest.add_item(hand)
        remaining = sum(stack.amount for stack in leftovers.values())
        if remaining >= original_amount:
            player.send_error_message("Your Ender Chest does not have enough free space.")
            return
        if remaining:
            hand.amount = remaining
            player.inventory.item_in_main_hand = hand
        else:
            player.inventory.item_in_main_hand = None
        player.send_message(f"Deposited {original_amount - remaining} {hand.type.id}.")

    def _backpack_items(self, player: Player) -> list[dict[str, Any] | None]:
        key = self._player_key(player)
        items = self._data["backpacks"].setdefault(key, [None] * BACKPACK_SLOTS)
        if len(items) != BACKPACK_SLOTS:
            raise ValueError(f"Invalid backpack slot count for player {player.name}")
        return items

    def _open_backpack(self, player: Player) -> None:
        items = self._backpack_items(player)
        buttons = [
            (
                f"Take slot {slot + 1}: {item['type']} x{item['amount']}",
                lambda target, index=slot: self._take_backpack(target, index),
            )
            for slot, item in enumerate(items)
            if item is not None
        ]
        buttons.append(("Deposit the item in your hand", self._deposit_backpack))
        self._send_form(player, "Backpack", "Choose a stored stack to take, or deposit your held item.", buttons)

    def _take_backpack(self, player: Player, slot: int) -> None:
        items = self._backpack_items(player)
        item_data = items[slot]
        if item_data is None:
            player.send_error_message("That backpack slot is empty.")
            return
        item = ItemStack(item_data["type"], int(item_data["amount"]), int(item_data.get("data", 0)))
        original_amount = item.amount
        leftovers = player.inventory.add_item(item)
        remaining = sum(stack.amount for stack in leftovers.values())
        if remaining >= original_amount:
            player.send_error_message("Your inventory is full.")
            return
        if remaining:
            item_data["amount"] = remaining
        else:
            items[slot] = None
        self._save_data()
        player.send_message(f"Moved {original_amount - remaining} {item.type.id} from your backpack.")

    def _deposit_backpack(self, player: Player) -> None:
        hand = player.inventory.item_in_main_hand
        if hand is None:
            player.send_error_message("Hold an item before depositing it.")
            return
        items = self._backpack_items(player)
        try:
            slot = items.index(None)
        except ValueError:
            player.send_error_message("Your backpack is full.")
            return
        items[slot] = _item_data(hand)
        player.inventory.item_in_main_hand = None
        self._save_data()
        player.send_message(f"Deposited {hand.type.id} x{hand.amount} in backpack slot {slot + 1}.")

    def _claim_at(self, dimension: str, x: int, z: int) -> dict[str, Any] | None:
        return next(
            (
                claim
                for claim in self._data["claims"]
                if claim["dimension"] == dimension
                and claim["min_x"] <= x <= claim["max_x"]
                and claim["min_z"] <= z <= claim["max_z"]
            ),
            None,
        )

    @event_handler
    def on_block_break(self, event: BlockBreakEvent) -> None:
        self._protect_claim(event, event.block)

    @event_handler
    def on_block_place(self, event: BlockPlaceEvent) -> None:
        self._protect_claim(event, event.block)

    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        if event.has_block:
            self._protect_claim(event, event.block)

    @event_handler
    def on_actor_explode(self, event: ActorExplodeEvent) -> None:
        event.block_list = [block for block in event.block_list if not self._is_claimed(block)]

    @event_handler
    def on_block_explode(self, event: BlockExplodeEvent) -> None:
        event.block_list = [block for block in event.block_list if not self._is_claimed(block)]

    def _protect_claim(
        self,
        event: BlockBreakEvent | BlockPlaceEvent | PlayerInteractEvent,
        block: Block,
    ) -> None:
        location = block.location
        claim = self._claim_at(block.dimension.name, math.floor(location.x), math.floor(location.z))
        if claim and str(event.player.unique_id) != claim["owner"]:
            event.cancelled = True
            event.player.send_error_message(f"This land is claimed by {claim['owner_name']}.")

    def _is_claimed(self, block: Block) -> bool:
        location = block.location
        return self._claim_at(
            block.dimension.name,
            math.floor(location.x),
            math.floor(location.z),
        ) is not None

    def _create_claim(self, player: Player) -> None:
        location = player.location
        dimension = location.dimension.name
        x, z = math.floor(location.x), math.floor(location.z)
        min_x, max_x = x - CLAIM_RADIUS, x + CLAIM_RADIUS
        min_z, max_z = z - CLAIM_RADIUS, z + CLAIM_RADIUS
        owner = self._player_key(player)
        if any(claim["owner"] == owner for claim in self._data["claims"]):
            player.send_error_message("You already have a claim. Use /unclaim before creating another.")
            return
        for claim in self._data["claims"]:
            if (
                claim["dimension"] == dimension
                and min_x <= claim["max_x"]
                and max_x >= claim["min_x"]
                and min_z <= claim["max_z"]
                and max_z >= claim["min_z"]
            ):
                player.send_error_message(f"Your claim overlaps land claimed by {claim['owner_name']}.")
                return
        self._data["claims"].append(
            {
                "owner": owner,
                "owner_name": player.name,
                "dimension": dimension,
                "min_x": min_x,
                "max_x": max_x,
                "min_z": min_z,
                "max_z": max_z,
            }
        )
        self._save_data()
        player.send_message(f"Claim created from ({min_x}, {min_z}) to ({max_x}, {max_z}).")

    def _edit_region(self, player: Player, args: list[str]) -> None:
        if not args:
            player.send_error_message("Usage: /bedrockedit <pos1|pos2|set> [block]")
            return
        action = args[0].casefold()
        key = self._player_key(player)
        if action in {"pos1", "pos2"} and len(args) == 1:
            location = player.location
            selection = self._selections.setdefault(key, {})
            selection["dimension"] = location.dimension.name
            selection[action] = (math.floor(location.x), math.floor(location.y), math.floor(location.z))
            player.send_message(f"{action} set to {selection[action]}.")
            return
        if action != "set" or len(args) != 2 or not BLOCK_PATTERN.fullmatch(args[1]):
            player.send_error_message("Usage: /bedrockedit <pos1|pos2|set> [block]")
            return
        selection = self._selections.get(key, {})
        if "pos1" not in selection or "pos2" not in selection:
            player.send_error_message("Set both corners first with /bedrockedit pos1 and /bedrockedit pos2.")
            return
        if selection.get("dimension") != player.dimension.name:
            player.send_error_message("Both selection corners must be in your current dimension.")
            return
        first, second = selection["pos1"], selection["pos2"]
        low = tuple(min(a, b) for a, b in zip(first, second))
        high = tuple(max(a, b) for a, b in zip(first, second))
        volume = (high[0] - low[0] + 1) * (high[1] - low[1] + 1) * (high[2] - low[2] + 1)
        if volume > MAX_EDIT_BLOCKS:
            player.send_error_message(f"Selection exceeds the {MAX_EDIT_BLOCKS:,}-block limit.")
            return
        for claim in self._data["claims"]:
            intersects = (
                claim["dimension"] == selection["dimension"]
                and low[0] <= claim["max_x"]
                and high[0] >= claim["min_x"]
                and low[2] <= claim["max_z"]
                and high[2] >= claim["min_z"]
            )
            if intersects and claim["owner"] != key:
                player.send_error_message(f"Region overlaps land claimed by {claim['owner_name']}.")
                return
        dimension = player.level.get_dimension(selection["dimension"])
        blocks = iter(
            product(
                range(low[0], high[0] + 1),
                range(low[1], high[1] + 1),
                range(low[2], high[2] + 1),
            )
        )
        completed = 0
        task = None

        def apply_batch() -> None:
            nonlocal completed
            try:
                for _ in range(256):
                    x, y, z = next(blocks)
                    player.level.get_block_at(Location(dimension, x, y, z)).set_type(
                        args[1],
                        apply_physics=False,
                    )
                    completed += 1
            except StopIteration:
                task.cancel()
                player.send_message(f"Set {completed:,} blocks to {args[1]}.")
            except (ValueError, RuntimeError) as exc:
                task.cancel()
                player.send_error_message(f"Region edit stopped after {completed:,} blocks: {exc}")

        task = self.server.scheduler.run_task(self, apply_batch, delay=1, period=1)
        player.send_message(f"Editing {volume:,} blocks to {args[1]} in small batches.")

    @override
    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if not isinstance(sender, Player):
            sender.send_error_message("This command is available to players in-game.")
            return False

        match command.name:
            case "sethome":
                if len(args) > 1:
                    sender.send_error_message("Usage: /sethome [name]")
                    return False
                name = args[0] if args else "home"
                if not NAME_PATTERN.fullmatch(name):
                    sender.send_error_message("Home names may contain letters, numbers, '_' and '-' only.")
                    return False
                homes = self._data["homes"].setdefault(self._player_key(sender), {})
                homes[name] = _location_data(sender)
                self._save_data()
                sender.send_message(f"Saved home '{name}'.")
            case "home":
                if len(args) > 1:
                    sender.send_error_message("Usage: /home [name]")
                    return False
                name = args[0] if args else "home"
                homes = self._data["homes"].get(self._player_key(sender), {})
                destination = self._named_record(homes, name)
                if destination is None:
                    sender.send_error_message(f"No home named '{name}' was found.")
                    return False
                if not self._teleport(sender, destination):
                    sender.send_error_message("Teleport failed.")
                    return False
            case "setwarp":
                if len(args) != 1 or not NAME_PATTERN.fullmatch(args[0]):
                    sender.send_error_message("Usage: /setwarp <name>")
                    return False
                self._data["warps"][args[0]] = _location_data(sender)
                self._save_data()
                sender.send_message(f"Saved warp '{args[0]}'.")
            case "warp":
                if len(args) > 1:
                    sender.send_error_message("Usage: /warp [name]")
                    return False
                if not args:
                    names = sorted(self._data["warps"], key=str.casefold)
                    sender.send_message("Warps: " + (", ".join(names) if names else "none"))
                    return True
                destination = self._named_record(self._data["warps"], args[0])
                if destination is None:
                    sender.send_error_message(f"No warp named '{args[0]}' was found.")
                    return False
                if not self._teleport(sender, destination):
                    sender.send_error_message("Teleport failed.")
                    return False
            case "claim":
                if args:
                    sender.send_error_message("Usage: /claim")
                    return False
                self._create_claim(sender)
            case "unclaim":
                if args:
                    sender.send_error_message("Usage: /unclaim")
                    return False
                owner = self._player_key(sender)
                previous_count = len(self._data["claims"])
                self._data["claims"] = [claim for claim in self._data["claims"] if claim["owner"] != owner]
                if len(self._data["claims"]) == previous_count:
                    sender.send_error_message("You do not have a claim.")
                    return False
                self._save_data()
                sender.send_message("Your claim has been removed.")
            case "backpack":
                if args:
                    sender.send_error_message("Usage: /backpack")
                    return False
                self._open_backpack(sender)
            case "enderchest":
                if args:
                    sender.send_error_message("Usage: /enderchest")
                    return False
                self._open_end_chest(sender)
            case "bedrockedit" | "worldedit" | "we":
                self._edit_region(sender, args)
        return True
