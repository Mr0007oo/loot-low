import secrets

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.plugin import Plugin


ROLL_DEFAULT_SIDES = 6
ROLL_MAX_SIDES = 1_000
EIGHT_BALL_ANSWERS = (
    "Absolutely!",
    "The odds look good.",
    "Ask again in a little while.",
    "Probably not.",
    "The outlook is not great.",
    "Definitely not!",
)


class FunPlugins(Plugin):
    api_version = "0.11"
    prefix = "Fun"

    commands = {
        "coinflip": {
            "description": "Flip a coin",
            "usages": ["/coinflip"],
            "permissions": ["funplugins.coinflip"],
        },
        "roll": {
            "description": "Roll a die (optionally choose 2-1000 sides)",
            "usages": ["/roll [sides]"],
            "permissions": ["funplugins.roll"],
        },
        "magic8ball": {
            "description": "Ask the magic 8-ball a question",
            "usages": ["/magic8ball <question>"],
            "permissions": ["funplugins.magic8ball"],
        },
        "sethome": {
            "description": "Set your home at your current location",
            "usages": ["/sethome"],
            "permissions": ["funplugins.sethome"],
        },
        "home": {
            "description": "Teleport to your saved home",
            "usages": ["/home"],
            "permissions": ["funplugins.home"],
        },
        "tpa": {
            "description": "Request to teleport to another player",
            "usages": ["/tpa <player>"],
            "permissions": ["funplugins.tpa"],
        },
        "tpaccept": {
            "description": "Accept a pending teleport request",
            "usages": ["/tpaccept"],
            "permissions": ["funplugins.tpaccept"],
        },
        "tpdeny": {
            "description": "Deny a pending teleport request",
            "usages": ["/tpdeny"],
            "permissions": ["funplugins.tpdeny"],
        },
    }

    permissions = {
        "funplugins.coinflip": {
            "description": "Flip a coin",
            "default": True,
        },
        "funplugins.roll": {
            "description": "Roll a die",
            "default": True,
        },
        "funplugins.magic8ball": {
            "description": "Ask the magic 8-ball a question",
            "default": True,
        },
        "funplugins.sethome": {
            "description": "Set your home",
            "default": True,
        },
        "funplugins.home": {
            "description": "Teleport to your home",
            "default": True,
        },
        "funplugins.tpa": {
            "description": "Request to teleport to another player",
            "default": True,
        },
        "funplugins.tpaccept": {
            "description": "Accept teleport requests",
            "default": True,
        },
        "funplugins.tpdeny": {
            "description": "Deny teleport requests",
            "default": True,
        },
    }

    def on_enable(self) -> None:
        self.homes = {}
        self.tpa_requests = {}
        self.logger.info("Fun command utilities enabled.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name == "coinflip":
            sender.send_message(f"Coin flip: {secrets.choice(('Heads', 'Tails'))}!")
            return True

        if command.name == "roll":
            if len(args) > 1:
                sender.send_message("Error: Usage: /roll [sides]")
                return True
            if args:
                try:
                    sides = int(args[0])
                except ValueError:
                    sender.send_message("Error: Sides must be a whole number from 2 to 1000.")
                    return True
            else:
                sides = ROLL_DEFAULT_SIDES
            if not 2 <= sides <= ROLL_MAX_SIDES:
                sender.send_message("Error: Sides must be from 2 to 1000.")
                return True
            sender.send_message(f"You rolled {secrets.randbelow(sides) + 1} (d{sides}).")
            return True

        if command.name == "magic8ball":
            if not args:
                sender.send_message("Error: Usage: /magic8ball <question>")
                return True
            sender.send_message(f"Magic 8-ball: {secrets.choice(EIGHT_BALL_ANSWERS)}")
            return True

        if command.name in ("sethome", "home", "tpa", "tpaccept", "tpdeny"):
            if not isinstance(sender, Player):
                sender.send_message("Error: This command can only be used by a player.")
                return True

        if command.name == "sethome":
            if args:
                sender.send_message("Error: Usage: /sethome")
                return True
            self.homes[sender.unique_id] = sender.location
            sender.send_message("Home set at your current location.")
            return True

        if command.name == "home":
            if args:
                sender.send_message("Error: Usage: /home")
                return True
            location = self.homes.get(sender.unique_id)
            if location is None:
                sender.send_message("Error: You have not set a home yet.")
                return True
            if sender.teleport(location):
                sender.send_message("Teleported to your home.")
            else:
                sender.send_message("Error: Could not teleport you to your home.")
            return True

        if command.name == "tpa":
            if len(args) != 1:
                sender.send_message("Error: Usage: /tpa <player>")
                return True
            target = self.server.get_player(args[0])
            if target is None:
                sender.send_message("Error: That player is not online.")
                return True
            if target.unique_id == sender.unique_id:
                sender.send_message("Error: You cannot request to teleport to yourself.")
                return True
            self.tpa_requests[target.unique_id] = sender.unique_id
            target.send_message(
                f"{sender.name} requested to teleport to you. Use /tpaccept or /tpdeny."
            )
            sender.send_message(f"Teleport request sent to {target.name}.")
            return True

        if command.name == "tpaccept":
            if args:
                sender.send_message("Error: Usage: /tpaccept")
                return True
            requester_id = self.tpa_requests.pop(sender.unique_id, None)
            if requester_id is None:
                sender.send_message("Error: You have no pending teleport requests.")
                return True
            requester = self.server.get_player(requester_id)
            if requester is None:
                sender.send_message("Error: The requesting player is no longer online.")
                return True
            if requester.teleport(sender.location):
                requester.send_message(f"{sender.name} accepted your teleport request.")
                sender.send_message(f"Teleported {requester.name} to you.")
            else:
                requester.send_message("Error: Your teleport request could not be completed.")
                sender.send_message("Error: Could not teleport the requesting player.")
            return True

        if command.name == "tpdeny":
            if args:
                sender.send_message("Error: Usage: /tpdeny")
                return True
            requester_id = self.tpa_requests.pop(sender.unique_id, None)
            if requester_id is None:
                sender.send_message("Error: You have no pending teleport requests.")
                return True
            requester = self.server.get_player(requester_id)
            sender.send_message("Teleport request denied.")
            if requester is not None:
                requester.send_message(f"{sender.name} denied your teleport request.")
            return True

        return False
