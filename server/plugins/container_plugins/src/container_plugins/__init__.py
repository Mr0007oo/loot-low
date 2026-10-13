from endstone import Player
from endstone.command import Command, CommandSender
from endstone.form import ActionForm
from endstone.inventory import Inventory, ItemStack
from endstone.plugin import Plugin


PLAYER_STORAGE_SLOTS = 36


class RemoteEnderChestPlugin(Plugin):
    api_version = "0.11"
    prefix = "RemoteEnderChest"

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
            if sender.unique_id in self.form_fallback_players:
                self._show_ender_chest_withdrawals(sender)
            else:
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
        player.send_form(
            ActionForm(
                title="Ender Chest",
                content=(
                    "Your personal Ender Chest is available from anywhere. "
                    "Choose whether to withdraw or deposit an item."
                ),
            )
            .add_button(
                "Withdraw an item",
                on_click=self._show_ender_items,
            )
            .add_button(
                "Deposit an item",
                on_click=self._show_player_items,
            )
        )

    def _show_ender_items(self, player: Player) -> None:
        ender_chest = player.ender_chest
        entries = [
            (slot, item)
            for slot in range(ender_chest.size)
            if (item := ender_chest.get_item(slot)) is not None
        ]
        form = ActionForm(
            title="Ender Chest - Withdraw",
            content=(
                "Choose an item to move into your inventory."
                if entries
                else "Your Ender Chest is empty."
            ),
        )
        for slot, item in entries:
            form.add_button(
                f"Slot {slot + 1}: {item.type.id} x{item.amount}",
                on_click=lambda current_player, selected_slot=slot, item_id=item.type.id, amount=item.amount: self._withdraw_from_form(
                    current_player,
                    selected_slot,
                    item_id,
                    amount,
                ),
            )
        form.add_button("Back", on_click=self._open_ender_chest)
        player.send_form(form)

    def _withdraw_from_form(
        self,
        player: Player,
        slot: int,
        expected_item_id: str,
        expected_amount: int,
    ) -> None:
        item = player.ender_chest.get_item(slot)
        if (
            item is None
            or item.type.id != expected_item_id
            or item.amount != expected_amount
        ):
            player.send_error_message("Error: That Ender Chest stack changed; nothing was withdrawn.")
            self._open_ender_chest(player)
            return
        self._withdraw_item(player, slot)
        self._open_ender_chest(player)

    def _show_player_items(self, player: Player) -> None:
        inventory = player.inventory
        empty_slots = [
            slot
            for slot in range(player.ender_chest.size)
            if player.ender_chest.get_item(slot) is None
        ]
        entries = [
            (slot, item)
            for slot in range(min(inventory.size, PLAYER_STORAGE_SLOTS))
            if (item := inventory.get_item(slot)) is not None
        ]
        if not empty_slots:
            content = "Your Ender Chest has no empty slots."
        elif not entries:
            content = "There are no items to deposit."
        else:
            content = "Choose an inventory stack to deposit into an empty Ender Chest slot."

        form = ActionForm(title="Ender Chest - Deposit", content=content)
        for slot, item in entries:
            form.add_button(
                f"Inventory {slot + 1}: {item.type.id} x{item.amount}",
                on_click=lambda current_player, selected_slot=slot: self._show_ender_destinations(
                    current_player,
                    selected_slot,
                ),
            )
        form.add_button("Back", on_click=self._open_ender_chest)
        player.send_form(form)

    def _show_ender_destinations(self, player: Player, source_slot: int) -> None:
        item = player.inventory.get_item(source_slot)
        if item is None:
            player.send_error_message("Error: That inventory slot is now empty.")
            self._show_player_items(player)
            return

        ender_chest = player.ender_chest
        empty_slots = [
            slot
            for slot in range(ender_chest.size)
            if ender_chest.get_item(slot) is None
        ]
        form = ActionForm(
            title="Ender Chest - Choose Slot",
            content=(
                f"Choose an empty slot for {item.type.id} x{item.amount}."
                if empty_slots
                else "Your Ender Chest has no empty slots."
            ),
        )
        for destination_slot in empty_slots:
            form.add_button(
                f"Empty slot {destination_slot + 1}",
                on_click=lambda current_player, selected_source=source_slot, selected_destination=destination_slot, item_id=item.type.id, amount=item.amount: self._deposit_from_form(
                    current_player,
                    selected_source,
                    selected_destination,
                    item_id,
                    amount,
                ),
            )
        form.add_button(
            "Back",
            on_click=self._show_player_items,
        )
        player.send_form(form)

    def _deposit_from_form(
        self,
        player: Player,
        source_slot: int,
        destination_slot: int,
        expected_item_id: str,
        expected_amount: int,
    ) -> None:
        inventory = player.inventory
        ender_chest = player.ender_chest
        item = inventory.get_item(source_slot)
        if (
            item is None
            or item.type.id != expected_item_id
            or item.amount != expected_amount
        ):
            player.send_error_message("Error: That inventory stack changed; nothing was deposited.")
            self._open_ender_chest(player)
            return
        if not 0 <= destination_slot < ender_chest.size:
            player.send_error_message("Error: Invalid Ender Chest slot.")
            self._open_ender_chest(player)
            return
        if ender_chest.get_item(destination_slot) is not None:
            player.send_error_message("Error: That Ender Chest slot is no longer empty.")
            self._show_player_items(player)
            return

        ender_chest.set_item(destination_slot, item)
        inventory.set_item(source_slot, None)
        player.send_message(
            f"Deposited {item.type.id} x{item.amount} into Ender Chest slot {destination_slot + 1}."
        )
        self._open_ender_chest(player)

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
