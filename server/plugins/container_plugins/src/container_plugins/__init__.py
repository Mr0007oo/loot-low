from uuid import UUID

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.inventory import Inventory, ItemStack
from endstone.plugin import Plugin
from endstone_inventoryui import Menu, MenuTransaction, MenuTransactionResult, MenuType


PLAYER_STORAGE_SLOTS = 36


class RemoteEnderChestPlugin(Plugin):
    api_version = "0.11"
    prefix = "RemoteEnderChest"
    depend = ["inventoryui"]

    commands = {
        "ec": {
            "description": "Open and manage your remote Ender Chest",
            "usages": [
                "/ec",
                "/ec store <inventory_slot: int> <ender_store_slot: int>",
                "/ec take <ender_take_slot: int>",
            ],
            "permissions": ["containers.enderchest"],
        },
    }

    permissions = {
        "containers.enderchest": {
            "description": "Open and manage your Ender Chest",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.logger.info("Remote Ender Chest enabled.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "ec":
            return False
        if not isinstance(sender, Player):
            sender.send_error_message("Error: This command can only be used by a player.")
            return True
        if not args:
            self._open_ender_chest(sender)
            return True
        if args[0] == "store":
            self._store_item(sender, args[1:], sender.ender_chest)
        elif args[0] == "take":
            self._take_item(sender, args[1:], sender.ender_chest)
        else:
            sender.send_error_message(
                "Error: Usage: /ec [store <inventory_slot> <ender_store_slot>|take <ender_take_slot>]"
            )
        return True

    def _open_ender_chest(self, player: Player) -> None:
        ender_chest = player.ender_chest
        menu = Menu(MenuType.CHEST, name="Ender Chest")

        for slot in range(min(ender_chest.size, menu.inventory.size)):
            menu.inventory.set_item(slot, self._copy_item(ender_chest.get_item(slot)))

        player_id = player.unique_id

        def sync_after_transaction(transaction: MenuTransaction) -> MenuTransactionResult:
            self.server.scheduler.run_task(
                self,
                lambda: self._sync_ender_chest(player_id, menu),
                delay=1,
            )
            return transaction.proceed()

        menu.set_listener(sync_after_transaction)
        menu.send_to(player)

    def _sync_ender_chest(self, player_id: UUID, menu: Menu) -> None:
        player = self.server.get_player(player_id)
        if player is None:
            return

        ender_chest = player.ender_chest
        for slot in range(min(ender_chest.size, menu.inventory.size)):
            ender_chest.set_item(
                slot,
                self._copy_item(menu.inventory.get_item(slot)),
            )

    @staticmethod
    def _copy_item(item: ItemStack | None) -> ItemStack | None:
        if item is None:
            return None
        copied = ItemStack(item.type.id, item.amount, item.data)
        meta = item.item_meta
        if meta is not None:
            copied.set_item_meta(meta.clone())
        return copied

    def _store_item(
        self,
        player: Player,
        args: list[str],
        ender_chest: Inventory,
    ) -> None:
        if len(args) != 2:
            player.send_error_message(
                "Error: Usage: /ec store <inventory_slot> <ender_store_slot>"
            )
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        inventory_slot, ender_slot = slots
        player_inventory = player.inventory
        storage_size = min(player_inventory.size, PLAYER_STORAGE_SLOTS)
        if not 1 <= inventory_slot <= storage_size:
            player.send_error_message(
                f"Error: Inventory slots range from 1 to {storage_size}."
            )
            return
        if not 1 <= ender_slot <= ender_chest.size:
            player.send_error_message(
                f"Error: Ender Chest slots range from 1 to {ender_chest.size}."
            )
            return

        item = player_inventory.get_item(inventory_slot - 1)
        if item is None:
            player.send_error_message("Error: That inventory slot is empty.")
            return
        if ender_chest.get_item(ender_slot - 1) is not None:
            player.send_error_message("Error: That Ender Chest slot is occupied.")
            return

        ender_chest.set_item(ender_slot - 1, item)
        player_inventory.set_item(inventory_slot - 1, None)
        player.send_message(
            f"Stored {item.type.id} in Ender Chest slot {ender_slot}."
        )

    def _take_item(
        self,
        player: Player,
        args: list[str],
        ender_chest: Inventory,
    ) -> None:
        if len(args) != 1:
            player.send_error_message("Error: Usage: /ec take <ender_take_slot>")
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        ender_slot = slots[0]
        if not 1 <= ender_slot <= ender_chest.size:
            player.send_error_message(
                f"Error: Ender Chest slots range from 1 to {ender_chest.size}."
            )
            return

        item = ender_chest.get_item(ender_slot - 1)
        if item is None:
            player.send_error_message("Error: That Ender Chest slot is empty.")
            return

        leftovers = player.inventory.add_item(item)
        if leftovers:
            ender_chest.set_item(ender_slot - 1, next(iter(leftovers.values())))
            player.send_error_message(
                "Error: Your inventory is full; the remaining items stayed in the Ender Chest."
            )
            return
        ender_chest.set_item(ender_slot - 1, None)
        player.send_message(f"Moved {item.type.id} to your inventory.")

    @staticmethod
    def _parse_slots(player: Player, args: list[str]) -> list[int] | None:
        try:
            return [int(value) for value in args]
        except ValueError:
            player.send_error_message("Error: Slot numbers must be whole numbers.")
            return None
