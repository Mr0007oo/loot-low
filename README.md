# loot-low Bedrock Server

This repository runs Minecraft Bedrock Dedicated Server with
[Endstone](https://github.com/EndstoneMC/endstone). The server runs in GitHub
Actions and exposes Bedrock traffic over UDP; it is not a Java server and does
not support RCON.

## Server setup

| Service | Port | Protocol |
| --- | ---: | --- |
| Minecraft Bedrock | 19132 | UDP |

Configure the FRP network rules to allow UDP 19132. The workflow requires the
`FRP_SERVER_IP` and `FRP_TOKEN` repository secrets. Endstone 0.11.2 and its
supported Bedrock server build are installed by the workflow. Server settings,
including the world seed (`9064150133272194`), are in `server/server.properties`.

The server uses Xbox Live authentication. Do not expose command control through
an unauthenticated public endpoint; Bedrock does not provide RCON.

## Plugins

- **Server Utilities:** `/serverinfo` shows server version and connection
  information.
- **Fun Plugins:** `/coinflip`, `/roll [sides]`, `/magic8ball <question>`,
  `/sethome`, `/home`, `/setwaypoint <name>`, `/waypointlist`,
  `/waypoint <name>`, `/tpa <player>`, `/tpaccept`, and `/tpdeny`. Shortcuts
  include `/cf`, `/r`, `/m8`, `/sh`, `/h`, `/sw`, `/wp`, `/wl`, `/tpr`, `/tpy`,
  and `/tpn`. Homes and waypoints are saved; teleport requests are temporary.
- **Vein Miner:** `/veinmine` toggles mining connected matching ores or logs
  while in survival mode.
- **Remote Ender Chest:** `/ec` opens a chest-style menu showing the player's
  real Ender Chest; click an item to withdraw it while keeping items that do
  not fit stored. `/ec store <inventory_slot> <ender_store_slot>` and
  `/ec take <ender_take_slot>` remain available.
- **PvP Duels:** `/pvp <player>` opens a kit menu and sends the selected-kit
  challenge to that player. Once accepted with `/pvpaccept` (or the accept
  button), both players receive the selected loadout and teleport to the sky
  arena. `/pvpdeny` declines a challenge, and `/spawngolem` is the operator
  arena command.
- **Land Claims:** `/claim`, `/unclaim`, `/trust <player>`, and
  `/untrust <player>` manage chunk protection.
- **World Edit:** `/pos1`, `/pos2`, and `/wefill <block_type>` edit a selected
  area. Fills are limited to 512 blocks and respect claims.

## Worlds and persistence

The server uses Bedrock's native world format. Existing Java worlds are not
loaded or automatically converted. Back up worlds before converting them.

The workflow preserves world progress and access data during regular syncs and
graceful shutdown. The Bedrock world cache is tied to the configured seed, so
changing the seed starts a separate world. The server runtime is downloaded
when needed and is not committed to the repository.
