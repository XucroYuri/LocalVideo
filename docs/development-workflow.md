# LocalVideo Development Workflow

This repository uses a mandatory milestone-based delivery loop for feature work, refactors, and non-trivial fixes.

## Core Rule

Every meaningful task must be executed as a sequence of phases. Each phase must be completed, verified, committed, and pushed to GitHub before the next phase begins.

## Required Loop

1. Split the requested work into milestone-based phases that match product behavior or functional boundaries.
2. Implement only the current phase.
3. Run the verification that proves the current phase works.
4. Create one scoped commit for that phase.
5. Push the phase commit to GitHub.
6. Continue into the next phase immediately unless a real blocker appears.

## Constraints

- Do not batch multiple milestones into one commit.
- Do not leave a phase in a knowingly broken state.
- Do not stop after planning if the next phase can already be executed safely.
- Do not rewrite published history unless explicitly requested.
- Keep `Seedance 2.0` through `kwjm.com` as the primary video path.
- Keep `Wan2GP` as the local fallback path when the API path is unavailable.

## Verification Standard

- Never mark a phase complete without concrete verification commands.
- Prefer fast, phase-scoped checks during implementation.
- Run broader validation before declaring the full request complete when the scope justifies it.
- If a check cannot be run, record exactly what was skipped and why.

## Completion Standard

The work is only done when all planned phases have been executed, verified, committed, pushed, and the remaining local git state is clean or explicitly explained.
