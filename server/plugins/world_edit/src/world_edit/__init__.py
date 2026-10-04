import math
import re

from endstone import Player
from endstone.block import BlockType
from endstone.command import Command, CommandSender
from endstone.plugin import Plugin


MAX_FILL_BLOCKS = 512
BLOCK_ID_PATTERN = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")


class WorldEditPlugin(Plugin):
    api_version = "0.11"
    prefix = "WorldEdit"
    depend = ["land_claims"]

    commands = {
        "pos1": {
            "description": "Set the first region corner at your current position",
            "usages": ["/pos1"],
            "permissions": ["worldedit.selection"],
        },
        "pos2": {
            "description": "Set the second region corner at your current position",
            "usages": ["/pos2"],
            "permissions": ["worldedit.selection"],
        },
        "fill": {
            "description": "Fill your selected region with a block (maximum 512)",
            "usages": ["/fill <block_type>"],
            "permissions": ["worldedit.fill"],
        },
    }

    permissions = {
        "worldedit.selection": {
            "description": "Set region selection corners",
            "default": True,
        },
        "worldedit.fill": {
            "description": "Fill a selected region up to 512 blocks",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.selections: dict[str, dict[int, tuple[str, int, int, int]]] = {}
        self.logger.info(f"World Edit enabled ({MAX_FILL_BLOCKS}-block fill limit).")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name not in ("pos1", "pos2", "fill"):
            return False
        if not isinstance(sender, Player):
            sender.send_message("Error: This command can only be used by a player.")
            return True

        if command.name in ("pos1", "pos2"):
            if args:
                sender.send_message(f"Error: Usage: /{command.name}")
                return True
            self._set_position(sender, 1 if command.name == "pos1" else 2)
            return True

        self._fill(sender, args)
        return True

    def _set_position(self, player: Player, position: int) -> None:
        location = player.location
        coordinates = (
            location.dimension.name,
            math.floor(location.x),
            math.floor(location.y),
            math.floor(location.z),
        )
        self.selections.setdefault(str(player.unique_id), {})[position] = coordinates
        player.send_message(
            f"Position {position} set to {coordinates[1]}, {coordinates[2]}, {coordinates[3]} "
            f"in {coordinates[0]}."
        )

    def _fill(self, player: Player, args: list[str]) -> None:
        if len(args) != 1:
            player.send_message("Error: Usage: /fill <block_type>")
            return
        selection = self.selections.get(str(player.unique_id), {})
        if 1 not in selection or 2 not in selection:
            player.send_message("Error: Set both corners first with /pos1 and /pos2.")
            return

        first, second = selection[1], selection[2]
        dimension = player.location.dimension
        if first[0] != second[0] or first[0] != dimension.name:
            player.send_message("Error: Both corners and your current position must be in one dimension.")
            return

        min_x, max_x = sorted((first[1], second[1]))
        min_y, max_y = sorted((first[2], second[2]))
        min_z, max_z = sorted((first[3], second[3]))
        block_count = (max_x - min_x + 1) * (max_y - min_y + 1) * (max_z - min_z + 1)
        if block_count > MAX_FILL_BLOCKS:
            player.send_message(
                f"Error: Selection contains {block_count} blocks; the limit is {MAX_FILL_BLOCKS}."
            )
            return

        block_id = args[0].lower()
        if ":" not in block_id:
            block_id = f"minecraft:{block_id}"
        if not BLOCK_ID_PATTERN.fullmatch(block_id):
            player.send_message("Error: Enter a valid block identifier, such as stone or minecraft:stone.")
            return
        try:
            block_type = BlockType.get(block_id)
        except (KeyError, ValueError):
            player.send_message(f"Error: Unknown block type '{block_id}'.")
            return
        if block_type is None:
            player.send_message(f"Error: Unknown block type '{block_id}'.")
            return

        claim_plugin = self.server.plugin_manager.get_plugin("land_claims")
        if claim_plugin is None:
            self.logger.error("Land Claims is not available; refusing to run /fill.")
            player.send_message("Error: Land protection is unavailable; fill was not run.")
            return
        for x in range(min_x, max_x + 1):
            for z in range(min_z, max_z + 1):
                if not claim_plugin.can_modify(
                    str(player.unique_id),
                    dimension.name,
                    x,
                    z,
                ):
                    player.send_message(
                        "Error: The selection includes a chunk claimed by another player."
                    )
                    return

        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                for z in range(min_z, max_z + 1):
                    dimension.get_block_at(x, y, z).set_type(block_type.id)

        player.send_message(f"Filled {block_count} blocks with {block_type.id}.")
