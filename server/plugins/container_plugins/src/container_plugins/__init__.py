from uuid import UUID

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import PlayerQuitEvent, event_handler
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
        self.menus: dict[UUID, Menu] = {}
        self.opened_menus: set[UUID] = set()
        self.pending_withdrawals: set[tuple[UUID, int]] = set()
        self.register_events(self)
        self.logger.info("Remote Ender Chest enabled.")

    def on_disable(self) -> None:
        for menu in tuple(self.menus.values()):
            menu.close_all()

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
        player_id = player.unique_id
        current_menu = self.menus.get(player_id)
        if current_menu is not None:
            player.send_message("Your Ender Chest menu is already open or opening.")
            return

        ender_chest = player.ender_chest
        menu_type = (
            MenuType.DOUBLE_CHEST
            if ender_chest.size > MenuType.CHEST.container_size
            else MenuType.CHEST
        )
        menu = Menu(menu_type, name="Remote Ender Chest")

        for slot in range(min(ender_chest.size, menu.inventory.size)):
            menu.inventory.set_item(slot, self._copy_item(ender_chest.get_item(slot)))

        self.menus[player_id] = menu
        self.opened_menus.discard(player_id)

        def handle_withdrawal(transaction: MenuTransaction) -> MenuTransactionResult:
            slot = transaction.slot
            withdrawal_key = (transaction.player.unique_id, slot)
            if (
                0 <= slot < min(ender_chest.size, menu.inventory.size)
                and transaction.item_clicked is not None
                and transaction.item_clicked.type.id != "minecraft:air"
                and withdrawal_key not in self.pending_withdrawals
            ):
                self.pending_withdrawals.add(withdrawal_key)
                self.server.scheduler.run_task(
                    self,
                    lambda: self._withdraw_from_menu(
                        transaction.player.unique_id,
                        slot,
                        menu,
                    ),
                    delay=1,
                )
            return transaction.discard()

        menu.set_listener(handle_withdrawal)
        menu.set_open_listener(lambda _: self.opened_menus.add(player_id))
        menu.set_close_listener(lambda _: self._clear_menu_state(player_id, menu))
        menu.send_to(player)
        self.server.scheduler.run_task(
            self,
            lambda: self._expire_unopened_menu(player_id, menu),
            delay=20,
        )

    def _withdraw_from_menu(self, player_id: UUID, slot: int, menu: Menu) -> None:
        self.pending_withdrawals.discard((player_id, slot))
        player = self.server.get_player(player_id)
        if player is None:
            return

        self._withdraw_item(player, slot)
        menu.inventory.set_item(
            slot,
            self._copy_item(player.ender_chest.get_item(slot)),
        )

    def _expire_unopened_menu(self, player_id: UUID, menu: Menu) -> None:
        if self.menus.get(player_id) is not menu:
            return
        if player_id in self.opened_menus:
            return

        player = self.server.get_player(player_id)
        if player is None:
            self._clear_menu_state(player_id, menu)
            return

        self.logger.error(
            f"Inventory UI did not open for {player.name}; Ender Chest contents were not changed."
        )
        player.send_error_message(
            "The chest menu did not open. Your Ender Chest is unchanged; run /ec to retry."
        )
        self._clear_menu_state(player_id, menu)

    def _withdraw_item(self, player: Player, slot: int) -> bool:
        ender_chest = player.ender_chest
        if not 0 <= slot < ender_chest.size:
            player.send_error_message("Error: Invalid Ender Chest slot.")
            return False

        item = ender_chest.get_item(slot)
        if item is None:
            player.send_message("That Ender Chest slot is already empty.")
            return False

        offered_item = self._copy_item(item)
        if offered_item is None:
            raise RuntimeError(f"Could not copy Ender Chest item in slot {slot}.")
        leftovers = player.inventory.add_item(offered_item)
        if leftovers:
            remaining = self._copy_item(next(iter(leftovers.values())))
            if remaining is None:
                raise RuntimeError(f"Could not preserve leftover Ender Chest item in slot {slot}.")
            moved_amount = item.amount - remaining.amount
            if moved_amount <= 0:
                player.send_error_message("Your inventory is full; nothing was withdrawn.")
                return False
            ender_chest.set_item(slot, remaining)
            player.send_message(
                f"Withdrew {item.type.id} x{moved_amount}; the rest remains in that slot."
            )
            return True

        ender_chest.set_item(slot, None)
        player.send_message(f"Withdrew {item.type.id} x{item.amount} from your Ender Chest.")
        return True

    def _clear_menu_state(self, player_id: UUID, menu: Menu | None = None) -> None:
        if menu is not None and self.menus.get(player_id) is not menu:
            return
        self.menus.pop(player_id, None)
        self.opened_menus.discard(player_id)
        self.pending_withdrawals = {
            pending for pending in self.pending_withdrawals if pending[0] != player_id
        }

    @event_handler
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        player_id = event.player.unique_id
        self._clear_menu_state(player_id)

    @staticmethod
    def _copy_item(item: ItemStack | None) -> ItemStack | None:
        if item is None:
            return None
        copied = ItemStack(item.type.id, item.amount, item.data)
        meta = item.item_meta
        if meta is not None:
            if not copied.set_item_meta(meta.clone()):
                raise ValueError(f"Could not copy metadata for Ender Chest item {item.type.id}.")
        copied.nbt = item.nbt
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
