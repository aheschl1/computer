# Self-Modification Protocol

## Goal
Modify the agent's source code safely, restart the server, and maintain rollback capability.

## Current State
- Agent runs in tmux
- Git repository initialized with one commit
- No remote configured

## Constraints
- Must rollback on failure
- Must not lose conversation history
- Must maintain uptime as much as possible

## Proposed Plan

### 1. Branch Strategy
- Every modification gets its own branch: `feature/` or `hotfix/`
- Main branch is always stable/production
- PR-style review before merge (even if self-review)

### 2. Pre-Modification Steps
1. Create new branch from main
2. Document changes in commit message
3. Test changes in isolated environment if possible
4. Save current state (git tag, branch backup)

### 3. Modification Process
1. Checkout new branch
2. Make changes
3. Commit with descriptive message
4. Test locally (if CLI) or in detached tmux session
5. If successful, merge to main
6. If failed, rollback to previous state

### 4. Restart Strategy
- Create `restart_agent.sh` script that:
  - Saves tmux session state
  - Kills current tmux session
  - Starts new tmux session with agent
  - Restores session state if possible

### 5. Rollback Plan
- If new code fails:
  - Kill new tmux session
  - Checkout previous commit/branch
  - Restart agent
  - Verify functionality

### 6. Safety Mechanisms
- Pre-commit hooks to prevent obvious errors
- Unit tests for critical components
- Health check endpoint before full deployment
- Automatic rollback on health check failure

## Implementation Steps

1. Create `restart_agent.sh` script
2. Create `roll_back.sh` script
3. Set up pre-commit hooks
4. Create CI/CD pipeline (local) for testing
5. Document the process in this file

## Open Questions

1. Should we use git tags for versioning releases?
2. How to handle state persistence during restarts?
3. Should we have a staging branch for testing?
4. What level of testing should happen before merge?
