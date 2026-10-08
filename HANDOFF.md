# Handoff checklist

## Current state
- Branch: `telegram-console-pr`
- Repo: `mr0007-tech/loot-low`
- PR: https://github.com/mr0007-tech/loot-low/pull/1
- Bedrock seed: `757067671151835873`

## Completed
- Bedrock server lifecycle restored around GitHub Actions
- Telegram polling conflict removed
- Authenticated console relay added
- Reverse SSH tunnel path documented and implemented
- External bot instructions captured in the repo docs

## Next actions
1. Run the full test suite and fix any remaining failing tests.
2. Update the stale workflow label assertion in `tests/test_download_deps.py`.
3. Validate `minecraft.yml` and shell checks against the current step names.
4. Confirm the final VM/relay secrets and deployment details.
5. Finish the PR review and merge if the branch is ready.

## Critical reminders
- Do not revert to VM-hosted Bedrock.
- Do not run the Bedrock server locally in a way that writes the repo world state.
- Preserve the reset deletion state and avoid restoring deleted world data.
- Do not commit secrets or real credentials to the repo.
