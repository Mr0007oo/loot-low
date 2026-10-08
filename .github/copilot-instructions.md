# Copilot instructions for loot-low

## Project goal
This repo is a Bedrock Minecraft server setup where the server process runs in GitHub Actions and the Telegram controller runs on an external VM. The command path uses an authenticated local relay and reverse SSH tunnel instead of Bedrock RCON.

## Required architecture
- Do not revert to a VM-hosted Bedrock server design.
- Keep a single Telegram poller. Never start multiple `getUpdates` consumers with the same bot token.
- Use `GH_PAT` and `REPO_NAME` for workflow dispatch and status tracking.
- Use the authenticated console relay for `/cmd` and `/stop` behavior.
- Keep `scripts/console_relay.py` and `server/start.sh` as the authoritative startup/stop controls.

## Hard constraints
- The Bedrock seed stays at `757067671151835873`.
- Preserve the pending world reset deletion state; do not restore deleted Bedrock world files.
- Never write real secrets or tokens into the repo.
- Do not run the server locally in a way that re-writes world state or persists live world data back to the repository.
- Treat Bedrock as having no RCON support.

## Current todo
- [x] Fix malformed Endstone command usage
- [x] Replace the conflicting Telegram polling behavior
- [x] Restore the Actions-hosted server lifecycle
- [x] Add the authenticated console relay and reverse SSH path
- [ ] Re-run the final unittest suite after the latest workflow edits
- [ ] Fix the stale workflow-name assertion in `tests/test_download_deps.py`
- [ ] Validate shell/YAML checks for the current workflow step names
- [ ] Confirm the final external VM secret names and values
- [ ] Finalize the branch and PR handoff

## Immediate next steps
1. Run the repo test suite and fix any remaining failures.
2. Update any stale workflow label assertions to match the current step names.
3. Validate the YAML and shell checks against the current workflow.
4. Verify the external VM setup secrets before deployment.
5. Keep the handoff branch ready for the next agent or human maintainer.

## Handoff note
This is a continuation branch for the hybrid architecture: Actions hosts the Bedrock server, the external VM hosts the Telegram controller, and commands flow through the reverse-tunnel relay.
