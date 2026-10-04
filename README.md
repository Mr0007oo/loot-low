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
Python 3.13 installs and launches Endstone. No custom Python or Java plugins
are installed; the launcher removes the retired `endstone-lootlow-bedrock`
distribution from an existing virtual environment before starting.

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

The workflow restores cached Bedrock world and access data and commits it back
to the current branch after the server stops. The Endstone runtime and
generated virtual environment are downloaded on demand and are not committed.
