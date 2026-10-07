from endstone.command import Command, CommandSender
from endstone.event import PlayerJoinEvent, event_handler
from endstone.plugin import Plugin


class ServerUtilsPlugin(Plugin):
    api_version = "0.11"
    prefix = "ServerUtils"

    commands = {
        "serverinfo": {
            "description": "Show Bedrock server runtime information",
            "usages": ["/serverinfo"],
            "permissions": ["serverutils.serverinfo"],
        }
    }

    permissions = {
        "serverutils.serverinfo": {
            "description": "View server runtime information",
            "default": True,
        }
    }

    def on_enable(self) -> None:
        self.register_events(self)
        self._enable_show_coordinates()
        self._enable_mob_spawning()
        self._enable_normal_difficulty()
        self.logger.info("Server utilities enabled.")

    @event_handler
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        self._enable_show_coordinates()

    def _enable_show_coordinates(self) -> None:
        self.server.dispatch_command(
            self.server.command_sender,
            "gamerule showcoordinates true",
        )

    def _enable_mob_spawning(self) -> None:
        command = "gamerule doMobSpawning true"
        if not self.server.dispatch_command(self.server.command_sender, command):
            self.logger.error(f"Could not apply startup setting: {command}.")
            return
        self.logger.info("Natural mob spawning enabled (gamerule doMobSpawning=true).")

    def _enable_normal_difficulty(self) -> None:
        command = "difficulty normal"
        if not self.server.dispatch_command(self.server.command_sender, command):
            self.logger.error(f"Could not apply startup setting: {command}.")
            return
        self.logger.info("Server difficulty set to normal.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        sender.send_message(
            "This server runs Endstone 0.11.2 with Bedrock Dedicated Server "
            "1.26.3.1 on UDP port 19132."
        )
        return True
