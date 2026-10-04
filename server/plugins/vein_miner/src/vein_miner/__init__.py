from collections import deque

from endstone import GameMode, Player
from endstone.block import Block
from endstone.command import Command, CommandSender
from endstone.event import BlockBreakEvent, EventPriority, event_handler
from endstone.inventory import ItemStack
from endstone.level import Location
from endstone.plugin import Plugin


MAX_BLOCKS_PER_BREAK = 32
NEIGHBOR_OFFSETS = (
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, -1),
    (0, 0, 1),
    (-1, 0, 0),
    (1, 0, 0),
)
ORE_DROPS = {
    "coal_ore": ("coal", 1),
    "copper_ore": ("raw_copper", 2),
    "iron_ore": ("raw_iron", 1),
    "gold_ore": ("raw_gold", 1),
    "redstone_ore": ("redstone", 4),
    "lapis_ore": ("lapis_lazuli", 4),
    "diamond_ore": ("diamond", 1),
    "emerald_ore": ("emerald", 1),
    "nether_gold_ore": ("gold_nugget", 2),
    "nether_quartz_ore": ("quartz", 1),
    "ancient_debris": ("ancient_debris", 1),
}
VEIN_SUFFIXES = ("_ore", "_log", "_wood", "_stem", "_hyphae")


class VeinMinerPlugin(Plugin):
    api_version = "0.11"
    prefix = "VeinMiner"

    commands = {
        "veinmine": {
            "description": "Toggle vein mining",
            "usages": ["/veinmine"],
            "permissions": ["veinminer.toggle"],
        }
    }

    permissions = {
        "veinminer.toggle": {
            "description": "Toggle vein mining",
            "default": True,
        }
    }

    def on_enable(self) -> None:
        self.disabled_players = set()
        self.register_events(self)
        self.logger.info("Vein Miner enabled (32-block limit).")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "veinmine":
            return False
        if args:
            sender.send_message("Error: Usage: /veinmine")
            return True
        if not isinstance(sender, Player):
            sender.send_message("Error: This command can only be used by a player.")
            return True

        if sender.unique_id in self.disabled_players:
            self.disabled_players.remove(sender.unique_id)
            sender.send_message("Vein mining enabled.")
        else:
            self.disabled_players.add(sender.unique_id)
            sender.send_message("Vein mining disabled.")
        return True

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_block_break(self, event: BlockBreakEvent) -> None:
        player = event.player
        if player.unique_id in self.disabled_players or player.game_mode != GameMode.SURVIVAL:
            return

        block_type = event.block.type
        block_name = block_type.removeprefix("minecraft:")
        if not block_name.endswith(VEIN_SUFFIXES) and block_name != "ancient_debris":
            return

        connected = self._collect_connected_blocks(event.block, block_type)
        for block in connected[1:]:
            block.set_type("minecraft:air")
            self._drop_block(block, block_type)

        if len(connected) > 1:
            player.send_message(f"Vein Miner broke {len(connected) - 1} additional blocks.")

    @staticmethod
    def _collect_connected_blocks(start: Block, block_type: str) -> list[Block]:
        connected = [start]
        pending = deque([start])
        seen = {(start.x, start.y, start.z)}

        while pending and len(connected) < MAX_BLOCKS_PER_BREAK:
            current = pending.popleft()
            for offset_x, offset_y, offset_z in NEIGHBOR_OFFSETS:
                neighbor = current.get_relative(offset_x, offset_y, offset_z)
                position = (neighbor.x, neighbor.y, neighbor.z)
                if position in seen:
                    continue
                seen.add(position)
                if neighbor.type != block_type:
                    continue
                connected.append(neighbor)
                if len(connected) >= MAX_BLOCKS_PER_BREAK:
                    break
                pending.append(neighbor)

        return connected

    @staticmethod
    def _drop_block(block: Block, block_type: str) -> None:
        block_name = block_type.removeprefix("minecraft:")
        if block_name.startswith("deepslate_"):
            block_name = block_name.removeprefix("deepslate_")
        item_name, amount = ORE_DROPS.get(block_name, (block_name, 1))
        location = Location(
            block.dimension,
            block.x + 0.5,
            block.y + 0.5,
            block.z + 0.5,
        )
        block.dimension.drop_item(
            location,
            ItemStack(f"minecraft:{item_name}", amount),
        )
