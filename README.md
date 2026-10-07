# loot-low Bedrock Server

This repository runs a native Minecraft Bedrock Dedicated Server through
[Endstone](https://github.com/EndstoneMC/endstone). It has no Java server,
protocol translator, Java plugin, or Java client endpoint. Bedrock traffic is
forwarded directly over UDP.

## Server endpoint

| Service | Public port | Protocol |
| --- | ---: | --- |
| Minecraft Bedrock | 19132 | UDP |

Configure the FRP host firewall and provider network rules to allow UDP 19132.
The workflow requires the `FRP_SERVER_IP` and `FRP_TOKEN` repository secrets.
RCON is enabled on TCP 25575 for local server integration; the workflow reads
the password from the `RCON_PASSWORD` repository secret and requires at least
32 characters. Do not expose TCP 25575 publicly. Any remote RCON client must
use the same secret and connect through a separately secured network path.
The runtime is pinned to Endstone 0.11.2 and its supported BDS 1.26.3.1 build.
The Endstone wheel and official Mojang BDS archive are SHA-256 verified before
installation. The server keeps `allow-outdated-client=true` for older clients
that the BDS protocol accepts, including a potential 1.26.2 client.

The Bedrock server uses Xbox Live authentication (`online-mode=true`). Endstone
0.11.2 targets BDS 1.26.3.1; `allow-outdated-client=true` allows older protocol
clients where supported, but only a real 1.26.2 client handshake can confirm
playability. The dependency setup purges the previous BDS runtime while
preserving worlds and server access configuration, verifies the binary against
Mojang's published archive digest, and checks Endstone's embedded target before
the server process starts. CI uses Endstone's `--yes --no-interactive` options.
Python 3.13 installs and launches Endstone and all six plugins. The launcher
removes the retired `endstone-lootlow-bedrock` distribution from an existing
virtual environment before starting.

## Server utilities

The `endstone-server-utils` plugin provides `/serverinfo`, which displays the
pinned Endstone and Bedrock runtime versions and the public UDP port. Its
Endstone entry point is named `server-utils` to match the distribution name
under Endstone's `endstone-<entry-point>` validation rule. It does not register
event listeners.

The `endstone-fun-plugins` package adds `/coinflip`, `/roll [sides]` (2-1000),
`/magic8ball <question>`, `/sethome`, `/home`, `/tpa <player>`, `/tpaccept`,
and `/tpdeny`. Homes and pending teleport requests are held in memory and do
not survive a plugin/server restart. These commands are available to all
players and do not register event listeners or perform world-wide operations.

The `endstone-vein-miner` plugin automatically breaks up to 32 connected,
identical ores or logs in survival mode. Use `/veinmine` to toggle it on or off
per player. It traverses only face-adjacent blocks and does not delete or reset
world directories or server configuration. Bonus ore drops use basic drop
amounts and do not simulate tool enchantments or durability use.

The `endstone-container-plugins` package adds `/ec`, which opens a Bedrock
ActionForm menu for remotely depositing and withdrawing items from the
caller's `player.ender_chest` without visiting a physical Ender Chest. The menu
moves stacks into empty slots and preserves items if the player's inventory is
full. `/ec store <inventory_slot> <ender_store_slot>` and
`/ec take <ender_take_slot>` are also available as command alternatives.
`/backpack` provides a 27-slot, in-memory portable bag; use
`/backpack store <inventory_slot> <bag_store_slot>` and
`/backpack take <bag_take_slot>` to move items. Backpacks do not persist across
server restarts.

The `endstone-pvp-duels` package builds a sky arena centered at Z=1000. Its
platform and walls are limited to X=-11..11, Y=150..155, and Z=989..1011.

The `endstone-land-claims` package adds `/claim`, `/unclaim`, `/trust <player>`,
and `/untrust <player>`. Claims cover the current 16-by-16 chunk and are saved
as JSON in the plugin's data folder. Block breaking and placement are denied in
another player's claim unless the actor is trusted there. Right-click while
holding a Golden Stick (`golden_rod`) or a stick named `Claim Wand` to claim
your current chunk; sneak-right-click with the same item to unclaim it.
Right-clicking another player's chest, barrel, shulker box, furnace, or other
supported container in a claimed chunk is cancelled unless you are trusted.

The `endstone-world-edit` package adds `/pos1`, `/pos2`, and
`/wefill <block_type>` (using a distinct command name to avoid Bedrock's
built-in `/fill` command).
Fills are capped at 512 blocks and pre-check every affected claim before
changing any blocks. World Edit depends on Land Claims and fails closed if the
protection plugin is unavailable.

The server listens on UDP 19132, binds to `0.0.0.0`, allows supported outdated
clients, and disables server telemetry in `server/server.properties`. The
configured view distance is 8 chunks and tick distance is 4 chunks to limit
server workload while retaining normal gameplay.

## World data

The server stores worlds in `server/bedrock_server/worlds/` using Bedrock's
native format.
Existing Java Anvil worlds in `server/world`, `server/world_nether`, and
`server/world_the_end` are left untouched as repository data, but are not
loaded by the Bedrock server and are not automatically converted. Back up or
convert any world you want to keep before using a Bedrock-compatible world
converter.

The workflow preserves Bedrock world and access data and pushes world progress
to `main` hourly and after a graceful shutdown or workflow cancellation. The
sync also includes the explicitly tracked `server/world/` and `server/worlds/`
directories when present; transient lock and temporary files are excluded.
Only those world paths, the active Bedrock world, and Bedrock access files are
staged for persistence.
The Endstone runtime and generated virtual environment are downloaded on
demand and are not committed.
To recover a missing legacy world directory from a Git commit, set the
repository variable `WORLD_RECOVERY_COMMIT` (for example, `d34607d`). Recovery
restores only a missing `server/world/` or `server/worlds/` directory and never
overwrites an existing workspace copy.
