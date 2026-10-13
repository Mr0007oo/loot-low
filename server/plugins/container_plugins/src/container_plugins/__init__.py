from endstone import Player
from endstone.command import Command, CommandSender
from endstone.form import ActionForm
from endstone.inventory import Inventory
from endstone.plugin import Plugin


PLAYER_STORAGE_SLOTS = 36


class ContainerPlugins(Plugin):
    api_version = "0.11"
    prefix = "Containers"

    commands = {
        "ec": {
            "description": "View and manage your remote Ender Chest",
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
            "description": "View your Ender Chest contents",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.logger.info("Container commands enabled.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "ec":
            if not isinstance(sender, Player):
                sender.send_message("Error: This command can only be used by a player.")
                return True
            if not args:
                self._open_ender_chest(sender)
                return True
            if args[0] == "store":
                self._store_item(sender, args[1:], sender.ender_chest, "ender")
            elif args[0] == "take":
                self._take_item(sender, args[1:], sender.ender_chest, "ender")
            else:
                sender.send_message(
                    "Error: Usage: /ec [store <inventory_slot> <ender_store_slot>|take <ender_take_slot>]"
                )
            return True

        return False

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

    def _open_ender_chest(self, player: Player) -> None:
        player.send_form(
            ActionForm(
                title="Ender Chest",
                content=(
                    "Your personal Ender Chest is available from anywhere. "
                    "Choose a graphical menu to move items in or out."
                ),
            )
            .add_button(
                "Withdraw an item",
                on_click=lambda current_player: self._show_ender_items(current_player),
            )
            .add_button(
                "Deposit an item",
                on_click=lambda current_player: self._show_player_items(current_player),
            )
        )

    def _show_ender_items(self, player: Player) -> None:
        inventory = player.ender_chest
        form = ActionForm(
            title="Ender Chest - Withdraw",
            content="Choose an item to move into your inventory.",
        )
        available = False
        for slot in range(inventory.size):
            item = inventory.get_item(slot)
            if item is None:
                continue
            available = True
            form.add_button(
                f"Slot {slot + 1}: {item.type.id} x{item.amount}",
                on_click=lambda current_player, selected_slot=slot: self._withdraw_slot(
                    current_player,
                    selected_slot,
                ),
            )
        if not available:
            form.content = "Your Ender Chest is empty."
        form.add_button("Back", on_click=self._open_ender_chest)
        player.send_form(form)

    def _show_player_items(self, player: Player) -> None:
        player_inventory = player.inventory
        ender_chest = player.ender_chest
        empty_slots = [
            slot
            for slot in range(ender_chest.size)
            if ender_chest.get_item(slot) is None
        ]
        form = ActionForm(
            title="Ender Chest - Deposit",
            content="Choose an inventory stack. It will move into an empty Ender Chest slot.",
        )
        available = False
        if empty_slots:
            for slot in range(min(player_inventory.size, PLAYER_STORAGE_SLOTS)):
                item = player_inventory.get_item(slot)
                if item is None:
                    continue
                available = True
                form.add_button(
                    f"Inventory {slot + 1}: {item.type.id} x{item.amount}",
                    on_click=lambda current_player, selected_slot=slot: self._show_ender_destinations(
                        current_player,
                        selected_slot,
                    ),
                )
        if not available:
            form.content = (
                "There are no items to deposit."
                if empty_slots
                else "Your Ender Chest has no empty slots."
            )
        form.add_button("Back", on_click=self._open_ender_chest)
        player.send_form(form)

    def _show_ender_destinations(self, player: Player, source_slot: int) -> None:
        player_inventory = player.inventory
        source = player_inventory.get_item(source_slot)
        if source is None:
            player.send_message("Error: That inventory slot is now empty.")
            self._show_player_items(player)
            return

        ender_chest = player.ender_chest
        form = ActionForm(
            title="Ender Chest - Choose Slot",
            content=f"Choose an empty slot for {source.type.id} x{source.amount}.",
        )
        available = False
        for slot in range(ender_chest.size):
            if ender_chest.get_item(slot) is not None:
                continue
            available = True

            def deposit(
                current_player: Player,
                selected_source: int = source_slot,
                destination: int = slot,
                item_id: str = source.type.id,
                amount: int = source.amount,
            ) -> None:
                self._deposit_slot(
                    current_player,
                    selected_source,
                    destination,
                    item_id,
                    amount,
                )

            form.add_button(
                f"Empty slot {slot + 1}",
                on_click=deposit,
            )
        if not available:
            form.content = "Your Ender Chest has no empty slots."
        form.add_button(
            "Back",
            on_click=lambda current_player: self._show_player_items(current_player),
        )
        player.send_form(form)

    def _deposit_slot(
        self,
        player: Player,
        source_slot: int,
        destination_slot: int,
        expected_item_id: str,
        expected_amount: int,
    ) -> None:
        player_inventory = player.inventory
        ender_chest = player.ender_chest
        item = player_inventory.get_item(source_slot)
        if (
            item is None
            or item.type.id != expected_item_id
            or item.amount != expected_amount
            or item.amount > item.max_stack_size
        ):
            player.send_message("Error: That inventory stack changed; nothing was deposited.")
            self._open_ender_chest(player)
            return
        if not 0 <= destination_slot < ender_chest.size:
            player.send_message("Error: Invalid Ender Chest slot.")
            self._open_ender_chest(player)
            return
        if ender_chest.get_item(destination_slot) is not None:
            player.send_message("Error: That Ender Chest slot is no longer empty.")
            self._show_player_items(player)
            return

        ender_chest.set_item(destination_slot, item)
        player_inventory.set_item(source_slot, None)
        player.send_message(f"Deposited {item.type.id} x{item.amount} into your Ender Chest.")
        self._open_ender_chest(player)

    def _withdraw_slot(self, player: Player, slot: int) -> None:
        ender_chest = player.ender_chest
        if not 0 <= slot < ender_chest.size:
            player.send_message("Error: Invalid Ender Chest slot.")
            self._open_ender_chest(player)
            return
        item = ender_chest.get_item(slot)
        if item is None:
            player.send_message("Error: That Ender Chest slot is now empty.")
            self._show_ender_items(player)
            return

        leftovers = player.inventory.add_item(item)
        if leftovers:
            ender_chest.set_item(slot, next(iter(leftovers.values())))
            player.send_message(
                "Error: Your inventory is full; remaining items stayed in your Ender Chest."
            )
        else:
            ender_chest.set_item(slot, None)
            player.send_message(f"Moved {item.type.id} x{item.amount} to your inventory.")
        self._open_ender_chest(player)

    def _store_item(
        self,
        player: Player,
        args: list[str],
        inventory: Inventory,
        slot_name: str,
    ) -> None:
        if len(args) != 2:
            player.send_message(
                f"Error: Usage: /ec store <inventory_slot> <{slot_name}_store_slot>"
            )
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        inventory_slot, container_slot = slots
        player_inventory = player.inventory
        player_storage_size = min(player_inventory.size, PLAYER_STORAGE_SLOTS)
        if not 1 <= inventory_slot <= player_storage_size:
            player.send_message(f"Error: Inventory slots range from 1 to {player_storage_size}.")
            return
        if not 1 <= container_slot <= inventory.size:
            player.send_message(f"Error: Ender Chest slots range from 1 to {inventory.size}.")
            return

        item = player_inventory.get_item(inventory_slot - 1)
        if item is None:
            player.send_message("Error: That inventory slot is empty.")
            return
        if inventory.get_item(container_slot - 1) is not None:
            player.send_message("Error: That ender chest slot is occupied.")
            return

        inventory.set_item(container_slot - 1, item)
        player_inventory.set_item(inventory_slot - 1, None)
        player.send_message(f"Stored {item.type.id} in Ender Chest slot {container_slot}.")

    def _take_item(
        self,
        player: Player,
        args: list[str],
        inventory: Inventory,
        slot_name: str,
    ) -> None:
        if len(args) != 1:
            player.send_message(
                f"Error: Usage: /ec take <{slot_name}_take_slot>"
            )
            return
        slots = self._parse_slots(player, args)
        if slots is None:
            return
        container_slot = slots[0]
        if not 1 <= container_slot <= inventory.size:
            player.send_message(f"Error: Ender Chest slots range from 1 to {inventory.size}.")
            return

        item = inventory.get_item(container_slot - 1)
        if item is None:
            player.send_message("Error: That ender chest slot is empty.")
            return

        leftovers = player.inventory.add_item(item)
        if leftovers:
            inventory.set_item(container_slot - 1, next(iter(leftovers.values())))
            player.send_message(
                "Error: Your inventory is full; the remaining items stayed in the ender chest."
            )
            return
        inventory.set_item(container_slot - 1, None)
        player.send_message(f"Moved {item.type.id} to your inventory.")

    @staticmethod
    def _parse_slots(player: Player, args: list[str]) -> list[int] | None:
        try:
            return [int(value) for value in args]
        except ValueError:
            player.send_message("Error: Slot numbers must be whole numbers.")
            return None
