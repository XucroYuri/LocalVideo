# AGENTS.md

This file applies to the entire repository.

## Project Direction

- Treat `Seedance 2.0` via `kwjm.com` as the primary video generation path.
- Treat local generation through `Wan2GP` as the fallback path when the API path is unavailable or unsuitable.
- Keep the product direction, defaults, and documentation aligned with that priority unless the user explicitly requests otherwise.

## Mandatory Delivery Loop

For every development task, iteration, refactor, or bugfix that is more than a trivial text-only change:

1. Break the work into milestone-based phases that follow product logic or functional boundaries.
2. Finish one phase completely before starting the next phase.
3. After each finished phase:
   - run the relevant verification for that phase
   - make one scoped commit for that phase
   - push that commit to GitHub before continuing
4. Continue directly into the next phase unless the user explicitly pauses the work or a real blocker appears.
5. Do not stop at planning or partial implementation when the next executable phase is clear and safe to do.

## Phase Rules

- Each phase must leave the repository in a coherent, working state for the scope it changes.
- Do not mix unrelated work into the same phase commit.
- Do not postpone obvious cleanup that is required for the current phase to make sense.
- Do not batch multiple milestones into a single "catch-all" commit.
- If the user asks to rebuild history, rename the project, or change repo ownership, preserve the requested milestone structure while doing so.

## Verification Rules

- Do not claim a phase is complete without running concrete verification commands.
- Prefer the smallest verification set that proves the current phase, then run broader checks before final completion when appropriate.
- If verification cannot be run, state exactly what could not be run and why.

## Git Workflow

- Use non-interactive git commands only.
- On a new branch that is not yet published, use `git push -u origin <branch>` for the first push.
- After the upstream exists, push each completed phase with `git push origin <branch>`.
- Do not rewrite published history unless the user explicitly asks for it.
- Keep commit messages scoped to the phase that was actually completed.

## Communication Rules

- State the current phase before doing substantial work.
- State what verification is being run before declaring a phase done.
- State when a phase is being committed and pushed.
- If blocked, report the blocker, the affected phase, and the current git state before asking for help.

## Done Criteria

Work is only fully complete when all requested phases have been executed, verified, committed, pushed to GitHub, and the remaining local git state is either clean or explicitly explained.
