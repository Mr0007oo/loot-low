from dataclasses import dataclass
from uuid import UUID

from endstone import Player
from endstone.actor import Item
from endstone.command import Command, CommandSender
from endstone.event import (
    EventPriority,
    PlayerDeathEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerRespawnEvent,
    event_handler,
)
from endstone.form import ActionForm
from endstone.inventory import ItemStack
from endstone.level import Dimension, Location
from endstone.plugin import Plugin


ARENA_X = 0.0
ARENA_Y = 150.0
ARENA_Z = 1_000.0
ARENA_FLOOR_MIN_X = -10
ARENA_FLOOR_MAX_X = 10
ARENA_FLOOR_MIN_Z = 990
ARENA_FLOOR_MAX_Z = 1_010
ARENA_SPAWN_Z_OFFSET = 7.0
ARENA_MIN_X = -11
ARENA_MAX_X = 11
ARENA_MIN_Y = 150
ARENA_MAX_Y = 155
ARENA_MIN_Z = 989
ARENA_MAX_Z = 1_011
ARENA_CLEANUP_RADIUS = 64.0
ARENA_FLOOR_BLOCK = "minecraft:smooth_stone"
ARENA_WALL_BLOCK = "minecraft:glass"
ARENA_ROOF_BLOCK = "minecraft:glass"
KIT_NAMES = ("Netherite Kit", "Crystal PvP Kit", "Archer Kit")


@dataclass(frozen=True)
class PlayerBackup:
    contents: tuple[ItemStack | None, ...]
    helmet: ItemStack | None
    chestplate: ItemStack | None
    leggings: ItemStack | None
    boots: ItemStack | None
    offhand: ItemStack | None
    held_item_slot: int


@dataclass(frozen=True)
class DuelChallenge:
    challenger_id: UUID
    target_id: UUID
    kit_name: str
    return_locations: dict[UUID, Location]


@dataclass
class DuelMatch:
    challenge: DuelChallenge
    existing_arena_item_ids: set[int]
    finishing: bool = False


class PvPDuelsPlugin(Plugin):
    api_version = "0.11"
    prefix = "PvPDuels"

    commands = {
        "pvp": {
            "description": "Challenge a player to a graphical kit duel",
            "usages": ["/pvp <player_name>"],
            "permissions": ["pvpduels.challenge"],
        },
        "pvpaccept": {
            "description": "Accept a pending PvP duel challenge",
            "usages": ["/pvpaccept"],
            "permissions": ["pvpduels.challenge"],
        },
        "pvpdeny": {
            "description": "Deny a pending PvP duel challenge",
            "usages": ["/pvpdeny"],
            "permissions": ["pvpduels.challenge"],
        },
    }

    permissions = {
        "pvpduels.challenge": {
            "description": "Challenge and accept PvP duels",
            "default": True,
        }
    }

    def on_enable(self) -> None:
        self.pending_challenges: dict[UUID, DuelChallenge] = {}
        self.player_backups: dict[UUID, PlayerBackup] = {}
        self.return_locations: dict[UUID, Location] = {}
        self.pending_restores: set[UUID] = set()
        self.active_match: DuelMatch | None = None
        self.arena_dimension = self._find_overworld()
        self._ensure_arena()
        self.register_events(self)
        self.logger.info(
            f"PvP Duels enabled (sky arena at {ARENA_X:g}, {ARENA_Y:g}, {ARENA_Z:g})."
        )

    def on_disable(self) -> None:
        for player_id in list(self.player_backups):
            player = self.server.get_player(player_id)
            if player is not None:
                self._restore_and_return(player)

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name not in ("pvp", "pvpaccept", "pvpdeny"):
            return False
        if not isinstance(sender, Player):
            sender.send_message("Error: This command can only be used by a player.")
            return True

        if command.name == "pvp":
            if len(args) != 1:
                sender.send_message("Error: Usage: /pvp <player_name>")
                return True
            self._show_kit_selection(sender, args[0])
        elif command.name == "pvpaccept":
            if args:
                sender.send_message("Error: Usage: /pvpaccept")
                return True
            self._accept_challenge(sender)
        else:
            if args:
                sender.send_message("Error: Usage: /pvpdeny")
                return True
            self._deny_challenge(sender)
        return True

    @event_handler(priority=EventPriority.HIGHEST)
    def on_player_death(self, event: PlayerDeathEvent) -> None:
        match = self.active_match
        if match is None or event.player.unique_id not in self._match_player_ids(match):
            return
        self._finish_after_death(match, event.player.unique_id)

    @event_handler(priority=EventPriority.HIGHEST)
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        player_id = event.player.unique_id
        for target_id, challenge in list(self.pending_challenges.items()):
            if player_id not in (challenge.challenger_id, challenge.target_id):
                continue
            del self.pending_challenges[target_id]
            remaining_id = (
                challenge.target_id
                if player_id == challenge.challenger_id
                else challenge.challenger_id
            )
            remaining = self.server.get_player(remaining_id)
            if remaining is not None:
                remaining.send_message(
                    "The PvP duel challenge was cancelled because a player left."
                )

        match = self.active_match
        if match is not None and player_id in self._match_player_ids(match):
            self._finish_after_quit(match, event.player)
        elif player_id in self.player_backups:
            self.pending_restores.discard(player_id)
            self._restore_and_return(event.player)

    @event_handler(priority=EventPriority.HIGHEST)
    def on_player_respawn(self, event: PlayerRespawnEvent) -> None:
        player_id = event.player.unique_id
        if player_id in self.pending_restores:
            self._schedule_restore(player_id)

    @event_handler(priority=EventPriority.HIGHEST)
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        player_id = event.player.unique_id
        if player_id in self.pending_restores:
            self._schedule_restore(player_id)

    def _show_kit_selection(self, player: Player, target_name: str) -> None:
        target = self.server.get_player(target_name)
        if target is None:
            player.send_message("Error: That player is not online.")
            return
        if target.unique_id == player.unique_id:
            player.send_message("Error: You cannot challenge yourself.")
            return
        if self._is_busy(player.unique_id) or self._is_busy(target.unique_id):
            player.send_message("Error: You or that player already has a pending or active duel.")
            return
        if self.active_match is not None:
            player.send_message("Error: The sky arena is currently in use.")
            return

        form = ActionForm(
            title="Choose a PvP Kit",
            content=f"Choose a kit for your duel challenge to {target.name}.",
        )
        target_id = target.unique_id
        for kit_name in KIT_NAMES:
            form.add_button(
                kit_name,
                on_click=lambda current_player, selected_kit=kit_name: self._send_challenge(
                    current_player,
                    target_id,
                    selected_kit,
                ),
            )
        player.send_form(form)

    def _send_challenge(self, challenger: Player, target_id: UUID, kit_name: str) -> None:
        target = self.server.get_player(target_id)
        if target is None:
            challenger.send_message("Error: That player is no longer online.")
            return
        if (
            self.active_match is not None
            or self._is_busy(challenger.unique_id)
            or self._is_busy(target_id)
        ):
            challenger.send_message(
                "Error: You or that player already has a pending or active duel."
            )
            return

        challenge = DuelChallenge(
            challenger_id=challenger.unique_id,
            target_id=target_id,
            kit_name=kit_name,
            return_locations={
                challenger.unique_id: self._copy_location(challenger.location),
                target_id: self._copy_location(target.location),
            },
        )
        self.pending_challenges[target_id] = challenge
        challenger.send_message(f"Duel challenge sent to {target.name} using {kit_name}.")
        target.send_message(
            f"{challenger.name} challenged you to a {kit_name} duel. "
            "Use /pvpaccept or /pvpdeny, or choose a button below."
        )
        target.send_form(
            ActionForm(
                title="PvP Duel Challenge",
                content=f"{challenger.name} wants to duel using {kit_name}.",
            )
            .add_button("Accept Duel", on_click=self._accept_challenge)
            .add_button("Deny Duel", on_click=self._deny_challenge)
        )

    def _accept_challenge(self, target: Player) -> None:
        challenge = self.pending_challenges.get(target.unique_id)
        if challenge is None:
            target.send_message("Error: You have no pending PvP duel challenges.")
            return
        challenger = self.server.get_player(challenge.challenger_id)
        if challenger is None:
            del self.pending_challenges[target.unique_id]
            target.send_message("Error: The challenging player is no longer online.")
            return
        if self.active_match is not None:
            target.send_message("Error: The sky arena is currently in use.")
            return
        del self.pending_challenges[target.unique_id]
        self._start_match(challenger, target, challenge)

    def _deny_challenge(self, target: Player) -> None:
        challenge = self.pending_challenges.pop(target.unique_id, None)
        if challenge is None:
            target.send_message("Error: You have no pending PvP duel challenges.")
            return
        challenger = self.server.get_player(challenge.challenger_id)
        target.send_message("PvP duel challenge denied.")
        if challenger is not None:
            challenger.send_message(f"{target.name} denied your PvP duel challenge.")

    def _start_match(
        self,
        challenger: Player,
        target: Player,
        challenge: DuelChallenge,
    ) -> None:
        if self.arena_dimension is None:
            target.send_message("Error: The overworld arena dimension is not available.")
            challenger.send_message("Error: The overworld arena dimension is not available.")
            return
        if not self._ensure_arena():
            target.send_message("Error: The sky arena is obstructed; the duel was not started.")
            challenger.send_message("Error: The sky arena is obstructed; the duel was not started.")
            return
        if self._is_busy(challenger.unique_id) or self._is_busy(target.unique_id):
            target.send_message("Error: You or the challenger already has an active duel.")
            return

        challenger_loadout = self._build_kit(challenge.kit_name)
        target_loadout = self._build_kit(challenge.kit_name)
        self.player_backups[challenger.unique_id] = self._snapshot_inventory(challenger)
        self.player_backups[target.unique_id] = self._snapshot_inventory(target)
        self.return_locations.update(challenge.return_locations)

        existing_item_ids = {
            actor.runtime_id
            for actor in self.server.level.actors
            if isinstance(actor, Item) and self._is_near_arena(actor.location)
        }
        match = DuelMatch(challenge, existing_item_ids)
        self.active_match = match

        target_spawn = Location(
            self.arena_dimension,
            ARENA_X,
            ARENA_Y,
            ARENA_Z + ARENA_SPAWN_Z_OFFSET,
        )
        challenger_spawn = Location(
            self.arena_dimension,
            ARENA_X,
            ARENA_Y,
            ARENA_Z - ARENA_SPAWN_Z_OFFSET,
        )
        self._equip_loadout(challenger, challenger_loadout)
        self._equip_loadout(target, target_loadout)
        if not challenger.teleport(challenger_spawn):
            self._rollback_start(challenger, target)
            return
        if not target.teleport(target_spawn):
            self._rollback_start(challenger, target)
            return

        message = f"{challenger.name} and {target.name} started a {challenge.kit_name} duel!"
        challenger.send_message(message)
        target.send_message(message)

    def _rollback_start(self, challenger: Player, target: Player) -> None:
        self.active_match = None
        self._restore_and_return(challenger)
        self._restore_and_return(target)
        challenger.send_message(
            "Error: Could not teleport both players to the arena; duel cancelled."
        )
        target.send_message("Error: Could not teleport both players to the arena; duel cancelled.")

    def _finish_after_death(self, match: DuelMatch, loser_id: UUID) -> None:
        if match.finishing:
            return
        match.finishing = True
        self.active_match = None
        winner_id = next(
            player_id
            for player_id in self._match_player_ids(match)
            if player_id != loser_id
        )
        winner = self.server.get_player(winner_id)
        loser = self.server.get_player(loser_id)
        if winner is not None:
            winner.send_message("You won the PvP duel!")
        if loser is not None:
            loser.send_message(
                "You lost the PvP duel. Your original inventory will be restored on respawn."
            )

        for player_id in (winner_id, loser_id):
            player = self.server.get_player(player_id)
            if player is None or player_id == loser_id:
                self.pending_restores.add(player_id)
            else:
                self._restore_and_return(player)
        self._schedule_arena_cleanup(match)

    def _finish_after_quit(self, match: DuelMatch, quitter: Player) -> None:
        if match.finishing:
            return
        quitter_id = quitter.unique_id
        match.finishing = True
        self.active_match = None
        winner_id = next(
            player_id for player_id in self._match_player_ids(match) if player_id != quitter_id
        )
        winner = self.server.get_player(winner_id)
        if winner is not None:
            winner.send_message("You won the PvP duel because your opponent left.")

        for player_id in self._match_player_ids(match):
            player = quitter if player_id == quitter_id else self.server.get_player(player_id)
            if player is None:
                self.pending_restores.add(player_id)
            else:
                self.pending_restores.discard(player_id)
                self._restore_and_return(player)
        self._schedule_arena_cleanup(match)

    def _schedule_arena_cleanup(self, match: DuelMatch) -> None:
        self.server.scheduler.run_task(
            self,
            lambda: self._cleanup_arena_items(match),
            delay=2,
        )

    def _cleanup_arena_items(self, match: DuelMatch) -> None:
        for actor in self.server.level.actors:
            if (
                isinstance(actor, Item)
                and actor.runtime_id not in match.existing_arena_item_ids
                and self._is_near_arena(actor.location)
            ):
                actor.remove()

    def _schedule_restore(self, player_id: UUID) -> None:
        self.server.scheduler.run_task(
            self,
            lambda: self._restore_online_player(player_id),
            delay=1,
        )

    def _restore_online_player(self, player_id: UUID) -> None:
        if player_id not in self.pending_restores:
            return
        player = self.server.get_player(player_id)
        if player is None:
            return
        self._restore_and_return(player)
        self.pending_restores.discard(player_id)

    def _restore_and_return(self, player: Player) -> None:
        player_id = player.unique_id
        backup = self.player_backups.get(player_id)
        location = self.return_locations.get(player_id)
        if backup is None or location is None:
            self.logger.error(f"Cannot restore PvP state for {player.name}: backup is incomplete.")
            return

        inventory = player.inventory
        inventory.clear()
        inventory.contents = [self._copy_item(item) for item in backup.contents]
        inventory.helmet = self._copy_item(backup.helmet)
        inventory.chestplate = self._copy_item(backup.chestplate)
        inventory.leggings = self._copy_item(backup.leggings)
        inventory.boots = self._copy_item(backup.boots)
        inventory.item_in_off_hand = self._copy_item(backup.offhand)
        inventory.held_item_slot = backup.held_item_slot
        self.player_backups.pop(player_id, None)
        self.return_locations.pop(player_id, None)

        if not player.teleport(location):
            self.logger.error(f"Could not return {player.name} to their saved pre-duel location.")
            player.send_message(
                "Error: Your inventory was restored, but returning to your location failed."
            )
        else:
            player.send_message("Your original inventory was safely restored.")

    def _snapshot_inventory(self, player: Player) -> PlayerBackup:
        inventory = player.inventory
        return PlayerBackup(
            contents=tuple(self._copy_item(item) for item in inventory.contents),
            helmet=self._copy_item(inventory.helmet),
            chestplate=self._copy_item(inventory.chestplate),
            leggings=self._copy_item(inventory.leggings),
            boots=self._copy_item(inventory.boots),
            offhand=self._copy_item(inventory.item_in_off_hand),
            held_item_slot=inventory.held_item_slot,
        )

    @staticmethod
    def _copy_item(item: ItemStack | None) -> ItemStack | None:
        if item is None:
            return None
        copied = ItemStack(item.type.id, item.amount, item.data)
        if not copied.set_item_meta(item.item_meta.clone()):
            raise ValueError(f"Could not clone metadata for inventory item {item.type.id}.")
        copied.nbt = item.nbt
        return copied

    @staticmethod
    def _copy_location(location: Location) -> Location:
        return Location(
            location.dimension,
            location.x,
            location.y,
            location.z,
            location.pitch,
            location.yaw,
        )

    @staticmethod
    def _build_kit(
        kit_name: str,
    ) -> tuple[tuple[ItemStack, ...], dict[int, ItemStack], ItemStack | None]:
        if kit_name == "Netherite Kit":
            armor = tuple(
                ItemStack(f"minecraft:netherite_{piece}")
                for piece in ("helmet", "chestplate", "leggings", "boots")
            )
            items = {
                0: PvPDuelsPlugin._enchanted_item(
                    "netherite_sword", (("minecraft:sharpness", 5),)
                ),
                1: ItemStack("minecraft:golden_apple", 16),
                2: ItemStack("minecraft:end_crystal", 64),
                3: ItemStack("minecraft:obsidian", 64),
            }
            return armor, items, ItemStack("minecraft:shield")

        if kit_name == "Crystal PvP Kit":
            armor = tuple(
                ItemStack(f"minecraft:diamond_{piece}")
                for piece in ("helmet", "chestplate", "leggings", "boots")
            )
            items = {
                0: ItemStack("minecraft:obsidian", 64),
                1: ItemStack("minecraft:end_crystal", 64),
                2: ItemStack("minecraft:totem_of_undying", 8),
                3: ItemStack("minecraft:golden_apple", 64),
                4: ItemStack("minecraft:golden_carrot", 64),
                5: ItemStack("minecraft:shield"),
            }
            return armor, items, ItemStack("minecraft:totem_of_undying")

        if kit_name == "Archer Kit":
            armor = tuple(
                ItemStack(f"minecraft:chainmail_{piece}")
                for piece in ("helmet", "chestplate", "leggings", "boots")
            )
            items = {
                0: PvPDuelsPlugin._enchanted_item(
                    "bow",
                    (
                        ("minecraft:power", 4),
                        ("minecraft:infinity", 1),
                        ("minecraft:unbreaking", 3),
                    ),
                ),
                1: ItemStack("minecraft:arrow", 64),
            }
            return armor, items, None

        raise ValueError(f"Unknown PvP kit: {kit_name}")

    @staticmethod
    def _enchanted_item(
        item_name: str,
        enchantments: tuple[tuple[str, int], ...],
    ) -> ItemStack:
        item = ItemStack(f"minecraft:{item_name}")
        meta = item.item_meta
        for enchantment, level in enchantments:
            if not meta.add_enchant(enchantment, level, force=True):
                raise ValueError(f"Could not add {enchantment} {level} to {item_name}.")
        if not item.set_item_meta(meta):
            raise ValueError(f"Could not apply enchantments to {item_name}.")
        return item

    @staticmethod
    def _equip_loadout(
        player: Player,
        loadout: tuple[
            tuple[ItemStack, ...],
            dict[int, ItemStack],
            ItemStack | None,
        ],
    ) -> None:
        armor, items, offhand = loadout
        inventory = player.inventory
        inventory.clear()
        inventory.contents = [None] * inventory.size
        for slot, item in items.items():
            inventory.set_item(slot, item)
        inventory.helmet, inventory.chestplate, inventory.leggings, inventory.boots = armor
        inventory.item_in_off_hand = offhand
        inventory.held_item_slot = 0

    def _find_overworld(self) -> Dimension | None:
        for dimension in self.server.level.dimensions:
            if dimension.name.removeprefix("minecraft:").lower() == "overworld":
                return dimension
        self.logger.error("PvP Duels could not find the overworld dimension.")
        return None

    def _ensure_arena(self) -> bool:
        if self.arena_dimension is None:
            return False

        blueprint = self._arena_blueprint()
        for x, y, z in blueprint:
            if not (
                ARENA_MIN_X <= x <= ARENA_MAX_X
                and ARENA_MIN_Y <= y <= ARENA_MAX_Y
                and ARENA_MIN_Z <= z <= ARENA_MAX_Z
            ):
                self.logger.error(
                    f"Refusing to build arena block outside approved bounds: {x}, {y}, {z}."
                )
                return False

        for x in range(ARENA_MIN_X, ARENA_MAX_X + 1):
            for y in range(ARENA_MIN_Y, ARENA_MAX_Y + 1):
                for z in range(ARENA_MIN_Z, ARENA_MAX_Z + 1):
                    block = self.arena_dimension.get_block_at(x, y, z)
                    existing_type = block.type
                    if ":" not in existing_type:
                        existing_type = f"minecraft:{existing_type}"
                    expected_type = blueprint.get((x, y, z))
                    if existing_type != "minecraft:air" and existing_type != expected_type:
                        self.logger.error(
                            "Refusing to build PvP arena because a non-air block exists "
                            f"inside its protected bounds at {x}, {y}, {z}."
                        )
                        return False

        for (x, y, z), block_type in blueprint.items():
            block = self.arena_dimension.get_block_at(x, y, z)
            existing_type = block.type
            if ":" not in existing_type:
                existing_type = f"minecraft:{existing_type}"
            if existing_type != block_type:
                block.set_type(block_type, apply_physics=False)
        return True

    @staticmethod
    def _arena_blueprint() -> dict[tuple[int, int, int], str]:
        blueprint = {
            (x, ARENA_MIN_Y, z): ARENA_FLOOR_BLOCK
            for x in range(ARENA_FLOOR_MIN_X, ARENA_FLOOR_MAX_X + 1)
            for z in range(ARENA_FLOOR_MIN_Z, ARENA_FLOOR_MAX_Z + 1)
        }
        for y in range(ARENA_MIN_Y + 1, ARENA_MAX_Y):
            for x in range(ARENA_FLOOR_MIN_X, ARENA_FLOOR_MAX_X + 1):
                blueprint[(x, y, ARENA_FLOOR_MIN_Z)] = ARENA_WALL_BLOCK
                blueprint[(x, y, ARENA_FLOOR_MAX_Z)] = ARENA_WALL_BLOCK
            for z in range(ARENA_FLOOR_MIN_Z + 1, ARENA_FLOOR_MAX_Z):
                blueprint[(ARENA_FLOOR_MIN_X, y, z)] = ARENA_WALL_BLOCK
                blueprint[(ARENA_FLOOR_MAX_X, y, z)] = ARENA_WALL_BLOCK
        blueprint.update(
            {
                (x, ARENA_MAX_Y, z): ARENA_ROOF_BLOCK
                for x in range(ARENA_FLOOR_MIN_X, ARENA_FLOOR_MAX_X + 1)
                for z in range(ARENA_FLOOR_MIN_Z, ARENA_FLOOR_MAX_Z + 1)
            }
        )
        return blueprint

    def _is_busy(self, player_id: UUID) -> bool:
        if player_id in self.player_backups:
            return True
        return any(
            player_id in (challenge.challenger_id, challenge.target_id)
            for challenge in self.pending_challenges.values()
        )

    @staticmethod
    def _match_player_ids(match: DuelMatch) -> tuple[UUID, UUID]:
        return match.challenge.challenger_id, match.challenge.target_id

    def _is_near_arena(self, location: Location) -> bool:
        if self.arena_dimension is None or location.dimension.name != self.arena_dimension.name:
            return False
        dx = location.x - ARENA_X
        dy = location.y - ARENA_Y
        dz = location.z - ARENA_Z
        return dx * dx + dy * dy + dz * dz <= ARENA_CLEANUP_RADIUS * ARENA_CLEANUP_RADIUS
