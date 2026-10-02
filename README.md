# loot-low

## Server endpoints

| Service | Public port | Protocol |
| --- | ---: | --- |
| Minecraft Java | 25565 | TCP |
| Minecraft Bedrock | 19132 | UDP |
| Simple Voice Chat | 24454 | UDP |

FRP forwards all three endpoints. The FRP host firewall and provider network rules must allow UDP 19132 and 24454. Simple Voice Chat is installed as the Paper 1.21.1 Bukkit plugin; Java players need the matching Simple Voice Chat client mod. Bedrock clients can join through Geyser but cannot use Simple Voice Chat natively.

Java players with the Simple Voice Chat client mod can open its in-game controls with the default `V` key. The client GUI provides microphone and voice-output controls, per-player volume, mute/deafen, and group controls; each player configures their own microphone and output device. The server plugin alone does not add these controls to an unmodded client.

Player chat is enabled by default; Minecraft has no `enable-chat` key in `server.properties`. `online-mode=true` with Geyser's Floodgate authentication and `enforce-secure-profile=false` supports cross-play while keeping Java account authentication enabled.

Players can request a teleport with `/tpa <player>`. The target accepts with `/tpaccept` or refuses with `/tpdeny`. At startup the workflow grants those EssentialsX permissions to LuckPerms' `default` group, so they are available to ordinary players without operator access.

Geyser-Spigot is pinned to 2.10.1 build 1184 and is rejected unless its JAR includes `bedrock/runtime_item_states.26_20.json`. Floodgate-Spigot is pinned to 2.2.5 build 141. The workflow caches `server/plugins/` so generated plugin settings and Floodgate keys survive between runs.