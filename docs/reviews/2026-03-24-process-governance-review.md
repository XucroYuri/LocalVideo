# LocalVideo Process Governance Review

Date: 2026-03-24
Branch: `codex/process-governance-review`
Reviewed commits:

- `2214bee` `feat(video): adopt seedance 2.0 kwjm provider`
- `8715c3e` `feat(video): make seedance primary with wan2gp fallback`
- `921552d` `docs(agent): enforce phased delivery workflow`
- `17d86eb` `docs: publish phased development workflow`

## Review Goal

Review the full refactor and history rebuild process, identify development drift, missing detail capture, functional breakpoints, logic closure gaps, and incomplete process closure, then classify the governance work into executable remediation phases.

## Findings

### 1. Capability Surface Drift

**Status:** confirmed

The project direction was narrowed to `Seedance 2.0` as the primary video engine with `Wan2GP` as fallback, but the public video capability surface was not fully converged:

- `backend/app/api/v1/capabilities.py` still exposes `vertex_video_models`, `kling_model_presets`, `vidu_model_presets`, and `minimax_model_presets`
- the response shape still implies those providers remain first-class video options

**Impact**

- frontend consumers can still read stale video catalogs from the backend
- the API contract no longer matches the runtime/provider contract
- future iterations are likely to reintroduce legacy video providers by accident

### 2. Frontend Default Drift

**Status:** confirmed

Some frontend helper code still falls back to legacy video defaults and legacy provider branches:

- `frontend/src/lib/project-detail-helpers.ts`
- `frontend/src/lib/stage-panel-helpers.ts`

Observed drift:

- `Seedance` fallback model still points to `seedance-1-5-pro`
- `Seedance` fallback aspect ratio and resolution still default to `9:16` and `1080p`
- legacy branches for `vertex_ai`, `kling`, and `vidu` still participate in helper resolution

**Impact**

- project detail and stage config rendering can disagree with the actual backend defaults
- users can see stale video defaults even when the mainline video path is already narrowed
- the implementation is vulnerable to silent regression because tests cover runtime behavior more than helper-level display defaults

### 3. Process Closure Gap

**Status:** confirmed

The refactor itself was completed in milestone commits, but the governance closeout was missing:

- no persisted retrospective review artifact existed in the repository
- no classified remediation record was committed
- no governance PR was created to isolate corrective work from the already-pushed mainline history

**Impact**

- review conclusions would otherwise remain trapped in chat history
- the repository lacked an auditable record of what was reviewed, what was fixed, and what remains as compatibility debt

## Governance Plan

### Phase 1: Review Artifact

- write this review document
- classify confirmed findings and impacts
- define remediation phases

### Phase 2: Backend Video Surface Convergence

- narrow the capabilities API so it only exposes the active video surface
- add or update tests to lock the converged contract

### Phase 3: Frontend Video Helper Convergence

- align helper defaults with the actual `Seedance 2.0` runtime defaults
- remove legacy video-provider helper branches from active rendering paths where they no longer apply
- update frontend types to match the converged capabilities contract

### Phase 4: Verification and PR Closure

- run backend tests, lint, frontend lint, typecheck, and production build
- push each governance phase to GitHub
- open a PR documenting the classified findings and remediation outcome

## Deliberate Non-Goals For This Cycle

- removing every legacy provider implementation from the codebase
- deleting legacy persisted settings keys that may still exist for backward compatibility
- refactoring image/audio provider surfaces that were not part of this video-mainline narrowing effort

## Remaining Risk To Watch

Legacy video settings fields still exist in some backend/frontend settings structures for compatibility. They are not treated as active video provider surface after this governance cycle, but a later dedicated cleanup can remove that compatibility layer if the project decides to stop carrying old saved settings forward.
