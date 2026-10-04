import secrets

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
    }

    def on_enable(self) -> None:
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

        return False
