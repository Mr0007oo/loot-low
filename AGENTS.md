# Copilot handoff for loot-low

## Current mission
This repo is in the middle of a Bedrock server handoff: the Bedrock process runs in GitHub Actions, while the Telegram controller runs on an external VM. Do not revert to an older VM-hosted Bedrock design.

## Architecture
- Bedrock server: GitHub Actions runner
- Telegram bot: external VM, one poller only, no duplicate `getUpdates` calls
- Workflow dispatch: bot uses `GH_PAT` and repository name to trigger the server workflow
- Console relay: authenticated local JSON/TCP relay writes commands into the Bedrock FIFO and supports graceful stop
- Reverse tunnel: VM connects back to the Actions runner over SSH so the bot can reach the relay without exposing a public port
- Persistence: `scripts/persist_world.py` and `server/start.sh` remain the authoritative lifecycle hooks

## Hard requirements
- Keep the server seed at `757067671151835873`
- Preserve the pending world reset deletion state; do not restore or reintroduce deleted Bedrock world files
- Do not run the Bedrock server or persistence workflow locally in a way that writes the live world back to the repo
- Do not commit secrets or real token values into code
- Bedrock does not support RCON; the relay is the supported command path
- The repo should not include multiple active Telegram polling loops

## Working notes
- `server/start.sh` handles the startup/stop lifecycle and optional console FIFO
- `scripts/console_relay.py` is the authenticated command bridge to the running server
- `.github/workflows/minecraft.yml` is the live Actions producer for the server lifecycle
- `Telegram_Bot/telegram_console.py` is the external bot/controller, not the server itself
- `README.md` and `TelegramBot.md` are the primary user-facing docs for the external bot setup

## Todo list
- [x] Replace malformed Endstone command usage
- [x] Remove the conflicting Telegram poller behavior
- [x] Add the authenticated console relay and reverse SSH control path
- [x] Restore the Actions-based server lifecycle
- [ ] Re-run the final Python unittest suite after the latest workflow edits
- [ ] Fix the stale workflow contract assertion in `tests/test_download_deps.py`
- [ ] Validate shell/YAML checks for the current workflow step name
- [ ] Confirm the final secret names for the VM and relay environment
- [ ] Open or update the PR and leave the branch ready for the next copilot

## Immediate next steps for the next agent
1. Run the repo test suite and inspect any remaining failures.
2. Update the stale workflow-name assertion in `tests/test_download_deps.py` to match the current step label.
3. Re-run YAML and shell validation against the current workflow file.
4. Confirm the final external-VM deployment secrets: `VM_SSH_HOST`, `VM_SSH_USER`, `VM_SSH_PRIVATE_KEY`, `VM_SSH_KNOWN_HOSTS`, `CONSOLE_RELAY_TOKEN`, `GH_PAT`, `REPO_NAME`, and Telegram token/chat values.
5. Only then open or finalize the PR and proceed with deployment or cleanup.

## Final note
This handoff is intentionally focused on the architecture that was already validated: GitHub Actions hosts the Bedrock server, the external VM runs the Telegram bot, and commands flow through the reverse-tunnel relay instead of RCON.
