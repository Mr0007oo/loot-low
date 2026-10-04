from endstone import Player
from endstone.command import Command, CommandSender
from endstone.inventory import Inventory, ItemStack
from endstone.plugin import Plugin


BACKPACK_SIZE = 27


class ContainerPlugins(Plugin):
    api_version = "0.11"
    prefix = "Containers"

    commands = {
        "ec": {
            "description": "View your Ender Chest contents",
            "usages": ["/ec"],
            "permissions": ["containers.enderchest"],
        },
        "backpack": {
            "description": "View and manage your portable backpack",
            "usages": [
                "/backpack",
                "/backpack store <inventory_slot> <bag_slot>",
                "/backpack take <bag_slot>",
            ],
            "permissions": ["containers.backpack"],
        },
    }

    permissions = {
        "containers.enderchest": {
            "description": "View your Ender Chest contents",
            "default": True,
        },
        "containers.backpack": {
            "description": "View and manage your portable backpack",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.backpacks: dict[str, list[ItemStack | None]] = {}
        self.logger.info("Container commands enabled.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "ec":
            if args:
                sender.send_message("Error: Usage: /ec")
                return True
            if not isinstance(sender, Player):
                sender.send_message("Error: This command can only be used by a player.")
                return True
            self._show_inventory(sender, sender.ender_chest, "Ender Chest")
            return True

        if command.name != "backpack":
            return False
        if not isinstance(sender, Player):
            sender.send_message("Error: This command can only be used by a player.")
            return True
        if not args:
            self._show_backpack(sender)
            return True
        if args[0] == "store":
            self._store_item(sender, args[1:])
            return True
        if args[0] == "take":
            self._take_item(sender, args[1:])
            return True

        sender.send_message(
            "Error: Usage: /backpack [store <inventory_slot> <bag_slot>|take <bag_slot>]"
        )
        return True

    def _show_inventory(self, player: Player, inventory: Inventory, title: str) -> None:
        entries = [
            f"{slot + 1}: {item.type.id} x{item.amount}"
            for slot in range(inventory.size)
            if (item := inventory.get_item(slot)) is not None
        ]
        if not entries:
            player.send_message(f"{title} is empty.")
            return
        player.send_message(f"{title} contents: " + "; ".join(entries))

    def _show_backpack(self, player: Player) -> None:
        backpack = self._get_backpack(player)
        entries = [
            f"{slot + 1}: {item.type.id} x{item.amount}"
            for slot, item in enumerate(backpack)
            if item is not None
        ]
        contents = "; ".join(entries) if entries else "empty"
        player.send_message(
            f"Backpack ({BACKPACK_SIZE} slots): {contents}. "
            "Use /backpack store <inventory_slot> <bag_slot> or "
            "/backpack take <bag_slot>."
        )

    def _store_item(self, player: Player, args: list[str]) -> None:
        if len(args) != 2:
            player.send_message("Error: Usage: /backpack store <inventory_slot> <bag_slot>")
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        inventory_slot, backpack_slot = slots
        inventory = player.inventory
        if not 1 <= inventory_slot <= inventory.size:
            player.send_message(f"Error: Inventory slots range from 1 to {inventory.size}.")
            return
        if not 1 <= backpack_slot <= BACKPACK_SIZE:
            player.send_message(f"Error: Backpack slots range from 1 to {BACKPACK_SIZE}.")
            return

        item = inventory.get_item(inventory_slot - 1)
        if item is None:
            player.send_message("Error: That inventory slot is empty.")
            return
        backpack = self._get_backpack(player)
        if backpack[backpack_slot - 1] is not None:
            player.send_message("Error: That backpack slot is occupied.")
            return

        backpack[backpack_slot - 1] = item
        inventory.set_item(inventory_slot - 1, None)
        player.send_message(f"Stored {item.type.id} in backpack slot {backpack_slot}.")

    def _take_item(self, player: Player, args: list[str]) -> None:
        if len(args) != 1:
            player.send_message("Error: Usage: /backpack take <bag_slot>")
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        backpack_slot = slots[0]
        if not 1 <= backpack_slot <= BACKPACK_SIZE:
            player.send_message(f"Error: Backpack slots range from 1 to {BACKPACK_SIZE}.")
            return

        backpack = self._get_backpack(player)
        item = backpack[backpack_slot - 1]
        if item is None:
            player.send_message("Error: That backpack slot is empty.")
            return

        leftovers = player.inventory.add_item(item)
        if leftovers:
            backpack[backpack_slot - 1] = next(iter(leftovers.values()))
            player.send_message("Error: Your inventory is full; the remaining items stayed in the backpack.")
            return
        backpack[backpack_slot - 1] = None
        player.send_message(f"Moved {item.type.id} to your inventory.")

    def _get_backpack(self, player: Player) -> list[ItemStack | None]:
        return self.backpacks.setdefault(str(player.unique_id), [None] * BACKPACK_SIZE)

    @staticmethod
    def _parse_slots(player: Player, args: list[str]) -> list[int] | None:
        try:
            return [int(value) for value in args]
        except ValueError:
            player.send_message("Error: Slot numbers must be whole numbers.")
            return None
