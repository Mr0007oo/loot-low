import json
import math
from pathlib import Path
from typing import TypedDict

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import (
    BlockBreakEvent,
    BlockPlaceEvent,
    EventPriority,
    PlayerInteractEvent,
    event_handler,
)
from endstone.plugin import Plugin


class Claim(TypedDict):
    owner: str
    trusted: list[str]


CONTAINER_BLOCKS = {
    "barrel",
    "beehive",
    "bee_nest",
    "blast_furnace",
    "brewing_stand",
    "chest",
    "crafter",
    "dispenser",
    "dropper",
    "furnace",
    "hopper",
    "shulker_box",
    "smoker",
    "trapped_chest",
}


class LandClaimsPlugin(Plugin):
    api_version = "0.11"
    prefix = "Claims"

    commands = {
        "claim": {
            "description": "Claim the chunk you are standing in",
            "usages": ["/claim"],
            "permissions": ["landclaims.claim"],
        },
        "unclaim": {
            "description": "Remove your claim from this chunk",
            "usages": ["/unclaim"],
            "permissions": ["landclaims.claim"],
        },
        "trust": {
            "description": "Allow an online player to build in your current claim",
            "usages": ["/trust <player: message>"],
            "permissions": ["landclaims.trust"],
        },
        "untrust": {
            "description": "Remove a player's access to your current claim",
            "usages": ["/untrust <player: message>"],
            "permissions": ["landclaims.trust"],
        },
    }

    permissions = {
        "landclaims.claim": {
            "description": "Create and remove chunk claims",
            "default": True,
        },
        "landclaims.trust": {
            "description": "Manage trusted players in chunk claims",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.claims_path = Path(self.data_folder) / "claims.json"
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        self.claims = self._load_claims()
        self.register_events(self)
        self.logger.info(
            f"Land Claims enabled ({len(self.claims)} chunk claims loaded; "
            "use a Golden Stick or Claim Wand to claim)."
        )

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name not in ("claim", "unclaim", "trust", "untrust"):
            return False
        if not isinstance(sender, Player):
            sender.send_message("Error: This command can only be used by a player.")
            return True

        key = self._claim_key(sender.location.dimension.name, sender.location.x, sender.location.z)
        if command.name == "claim":
            self._claim(sender, key, args)
        elif command.name == "unclaim":
            self._unclaim(sender, key, args)
        else:
            self._change_trust(sender, key, command.name == "trust", args)
        return True

    def _claim(self, player: Player, key: str, args: list[str]) -> None:
        if args:
            player.send_message("Error: Usage: /claim")
            return
        existing = self.claims.get(key)
        owner_id = str(player.unique_id)
        if existing is not None:
            if existing["owner"] == owner_id:
                player.send_message("You already own this chunk.")
            else:
                player.send_message("Error: This chunk is already claimed by another player.")
            return

        candidate = dict(self.claims)
        candidate[key] = {"owner": owner_id, "trusted": []}
        if self._save_claims(player, candidate):
            player.send_message("Chunk claimed successfully.")

    def _unclaim(self, player: Player, key: str, args: list[str]) -> None:
        if args:
            player.send_message("Error: Usage: /unclaim")
            return
        claim = self.claims.get(key)
        if claim is None or claim["owner"] != str(player.unique_id):
            player.send_message("Error: You do not own a claim in this chunk.")
            return

        candidate = dict(self.claims)
        del candidate[key]
        if self._save_claims(player, candidate):
            player.send_message("Chunk unclaimed successfully.")

    def _change_trust(
        self,
        player: Player,
        key: str,
        trust: bool,
        args: list[str],
    ) -> None:
        command = "trust" if trust else "untrust"
        target_name = " ".join(args).strip()
        if not target_name:
            player.send_message(f"Error: Usage: /{command} <player>")
            return
        claim = self.claims.get(key)
        if claim is None or claim["owner"] != str(player.unique_id):
            player.send_message("Error: You must own this chunk to manage its trusted players.")
            return
        target = self.server.get_player(target_name)
        if target is None:
            player.send_message("Error: That player must be online.")
            return
        target_id = str(target.unique_id)
        if target_id == claim["owner"]:
            player.send_message("Error: You already own this claim.")
            return

        trusted = set(claim["trusted"])
        if trust and target_id in trusted:
            player.send_message(f"{target.name} is already trusted in this chunk.")
            return
        if not trust and target_id not in trusted:
            player.send_message(f"{target.name} is not trusted in this chunk.")
            return
        if trust:
            trusted.add(target_id)
        else:
            trusted.remove(target_id)

        candidate = dict(self.claims)
        candidate[key] = {"owner": claim["owner"], "trusted": sorted(trusted)}
        if self._save_claims(player, candidate):
            action = "trusted" if trust else "untrusted"
            player.send_message(f"{target.name} is now {action} in this chunk.")

    def can_modify(
        self,
        player_id: str,
        dimension_name: str,
        block_x: int,
        block_z: int,
    ) -> bool:
        claim = self.claims.get(self._claim_key(dimension_name, block_x, block_z))
        return (
            claim is None
            or claim["owner"] == player_id
            or player_id in claim["trusted"]
        )

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_block_break(self, event: BlockBreakEvent) -> None:
        self._protect_block(event, event.player)

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_block_place(self, event: BlockPlaceEvent) -> None:
        self._protect_block(event, event.player)

    @event_handler(priority=EventPriority.HIGHEST, ignore_cancelled=True)
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        if event.action not in (
            PlayerInteractEvent.RIGHT_CLICK_BLOCK,
            PlayerInteractEvent.RIGHT_CLICK_AIR,
        ):
            return

        player = event.player
        if self._is_claim_wand(event):
            location = player.location
            key = self._claim_key(location.dimension.name, location.x, location.z)
            if player.is_sneaking:
                self._unclaim(player, key, [])
            else:
                self._claim(player, key, [])
            event.cancelled = True
            return

        if not event.has_block:
            return
        block = event.block
        if not self._is_container(block.type):
            return
        if self.can_modify(
            str(player.unique_id),
            block.dimension.name,
            block.x,
            block.z,
        ):
            return

        event.cancelled = True
        player.send_message("Error: This container is in another player's claimed chunk.")

    def _protect_block(self, event: BlockBreakEvent | BlockPlaceEvent, player: Player) -> None:
        block = event.block
        if self.can_modify(
            str(player.unique_id),
            block.dimension.name,
            block.x,
            block.z,
        ):
            return
        event.cancelled = True
        player.send_message("Error: This chunk is claimed by another player.")

    @staticmethod
    def _is_claim_wand(event: PlayerInteractEvent) -> bool:
        if not event.has_item or event.item is None:
            return False
        item = event.item
        item_id = item.type.id.removeprefix("minecraft:")
        if item_id == "golden_rod":
            return True
        if item_id != "stick":
            return False
        meta = item.item_meta
        return meta.has_display_name and meta.display_name.strip().casefold() == "claim wand"

    @staticmethod
    def _is_container(block_type: str) -> bool:
        block_id = block_type.removeprefix("minecraft:")
        return (
            block_id in CONTAINER_BLOCKS
            or block_id.endswith("_shulker_box")
        )

    def _load_claims(self) -> dict[str, Claim]:
        if not self.claims_path.exists():
            return {}
        try:
            data = json.loads(self.claims_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read land claims from {self.claims_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Land claims file must contain a JSON object.")

        claims: dict[str, Claim] = {}
        for key, value in data.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, dict)
                or not isinstance(value.get("owner"), str)
                or not isinstance(value.get("trusted"), list)
                or not all(isinstance(player_id, str) for player_id in value["trusted"])
            ):
                raise RuntimeError("Land claims file contains an invalid claim record.")
            claims[key] = {
                "owner": value["owner"],
                "trusted": value["trusted"],
            }
        return claims

    def _save_claims(self, player: Player, claims: dict[str, Claim]) -> bool:
        temp_path = self.claims_path.with_name("claims.json.tmp")
        try:
            temp_path.write_text(
                json.dumps(claims, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self.claims_path)
        except OSError as exc:
            self.logger.error(f"Could not save land claims to {self.claims_path}: {exc}")
            player.send_message("Error: The claim was not changed because claim storage failed.")
            return False
        self.claims = claims
        return True

    @staticmethod
    def _claim_key(dimension_name: str, x: float, z: float) -> str:
        chunk_x = math.floor(x / 16)
        chunk_z = math.floor(z / 16)
        return f"{dimension_name}|{chunk_x}|{chunk_z}"
