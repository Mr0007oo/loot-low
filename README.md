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
Set the optional `ENDSTONE_VERSION` repository variable to pin an Endstone
release; when unset, the downloader uses the latest stable Linux x86_64 release
and verifies its GitHub-published SHA-256 digest. `BEDROCK_CLIENT_VERSION`
defaults to `1.26.2` and can be set to the client version the deployment should
accept.

The Bedrock server uses Xbox Live authentication (`online-mode=true`). Its
`allow-outdated-client` setting permits older compatible clients, but clients
must still use a protocol accepted by the selected Endstone/BDS release. The
downloader reports the release's declared Bedrock version and warns when it
differs from the requested client version; the older-client setting is not a
substitute for confirming the handshake with a real 1.26.2 client.
Endstone downloads and extracts the matching native Bedrock Dedicated Server
into `server/bedrock_server/` on startup. The CI launcher uses Endstone's
`--yes --no-interactive` options so first-run downloads and version updates do
not prompt for console input. Python 3.13 is used to install and launch
Endstone and the in-repository plugin.

## Native plugin features

The Endstone plugin in `server/plugins/lootlow_bedrock/` provides:

- `/sethome [name]` and `/home [name]` for personal homes.
- `/setwarp <name>` and `/warp [name]` for operator-managed server warps.
- `/claim` and `/unclaim` for one 17-by-17 area per player, protecting blocks,
  block interactions, and explosion damage.
- `/enderchest` for a Bedrock form-based view of the player's native Ender
  Chest, with item transfers to and from the player's inventory.
- `/backpack` for a persistent 27-slot personal backpack. Item type, count,
  and Bedrock item data are stored; custom item metadata is not supported.
- `/worldedit pos1`, `/worldedit pos2`, and `/worldedit set <block>` (also
  `/bedrockedit` or `/we`) for operator-only cuboid edits, capped at 32,768
  blocks. The selection corners use the player's current block positions and
  edits are applied in small batches to avoid long server ticks.

Homes, warps, claims, and backpack data are stored in
`server/plugins/lootlow_bedrock/data/` and persisted by the workflow.

## Health display

The former TAB plugin fabricated a below-name value with `%health%` and a heart
glyph, which produced raw health numbers and a stray icon for Bedrock players.
That Java overlay has been removed. The Endstone plugin now registers a native
scoreboard objective with the `HEARTS` render type in the `BELOW_NAME` display
slot and updates it once per second from each player's health.

## World data

The new server stores worlds in `server/worlds/` using Bedrock's native format.
Existing Java Anvil worlds in `server/world`, `server/world_nether`, and
`server/world_the_end` are left untouched as repository data, but are not
loaded by the Bedrock server and are not automatically converted. Back up or
convert any world you want to keep before using a Bedrock-compatible world
converter.

The workflow restores cached Bedrock world/plugin data and commits it back to
the current branch after the server stops. The Endstone runtime and generated
virtual environment are downloaded on demand and are not committed.
