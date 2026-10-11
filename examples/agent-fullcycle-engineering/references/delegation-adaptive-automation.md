# Delegation and Adaptive Automation

Use this reference when splitting engineering work across subagents or when a scheduled task must automatically choose useful optimizations from current evidence.

## 1. Delegation Decision

Prefer delegation when all of these are true:

1. The subtask has a clear objective and bounded output.
2. It can run from explicit inputs without relying on hidden parent context.
3. Its writes are read-only or confined to files no other worker will edit.
4. Success can be checked independently with evidence such as tests, diffs, logs, or a structured review.
5. It does not require the subagent to make permission, approval, irreversible-action, or final integration decisions.
6. Dispatch and integration cost is lower than the expected critical-path time saved.

Strong candidates include independent repository research, separate test or review passes, failure-log analysis, documentation checks, and implementation in disjoint modules. Keep tightly coupled edits, shared-state migrations, final architecture decisions, release approval, and final integration with the parent.

Do not delegate a tiny task only to satisfy a preference. Do not split work when workers would repeatedly wait on each other, edit the same files, or need the same scarce environment.

## 2. Bounded Task Contract

Give every subagent a contract containing:

```text
Task ID:
Objective:
Inputs and source of truth:
Allowed read scope:
Exclusive write scope:
Constraints and inherited permissions:
Expected deliverable and format:
Verification command or acceptance check:
Dependencies and time/work budget:
Stop conditions and escalation data:
Further delegation allowed: no, unless explicitly granted
```

Require the result to state status, evidence, files changed, checks run, failures, assumptions, and unresolved risks. A subagent must stop and return evidence instead of expanding scope when its contract is insufficient.

## 3. Parallelism and Ownership

- Default to no more than three active subagents. Lower the limit for expensive builds, exclusive test environments, rate-limited services, or scarce credentials.
- Raise the limit to at most five only when tasks are truly disjoint, the environment supports it, and integration remains bounded.
- Assign one owner for every writable file, resource, branch, service, or mutable dataset.
- Parallelize read-only discovery freely within the limit. Serialize dependent edits and shared integration tests.
- Do not let subagents create unbounded delegation trees. The parent remains the coordinator and source of truth.
- Cancel, narrow, or serialize work when overlap or contradictory assumptions appear.

## 4. Parent Integration Duties

The parent agent must:

1. Establish the shared baseline, plan, contracts, and exclusive write sets.
2. Track dependencies and prevent overlapping changes.
3. Inspect returned evidence and diffs rather than accepting summaries alone.
4. Reconcile incompatible assumptions and integrate changes in dependency order.
5. Run verification again in the integrated workspace, including relevant regression checks.
6. Confirm that no worker exceeded scope or permissions.
7. Own rollback of changes made by the delegated work, final risk assessment, and the user-facing report.

If subagent tools are unavailable, fail to start, or cannot access required context, keep the same task boundaries and execute them serially in the parent. Do not reduce verification or broaden permissions as a fallback.

## 5. Adaptive Automation Trigger

Adaptive behavior requires an explicit user request for a scheduled task to "automatically optimize", "continuously improve", "choose the next improvement", or equivalent. A request such as "run tests every night" is static and must remain static unless the user asks for adaptive choice.

At setup, define:

- Target project or task and allowed scope.
- Schedule and maximum run duration or cost.
- Evidence sources and success metrics.
- Allowed action classes and prohibited side effects.
- Verification requirements and failure policy.
- Durable checkpoint location.
- Existing permissions and approval boundaries.

Ask for missing information when it changes safety or target scope. Otherwise choose conservative bounds.

## 6. Per-Run Adaptive Loop

Each run follows this loop from fresh state:

1. **Identify:** Create a unique run ID and resolve the exact target and current revision or state version.
2. **Lock:** Acquire a target-scoped lease or equivalent atomic lock. If another valid run owns it, no-op.
3. **Load:** Read the durable checkpoint and recent action history. Treat it as memory, not as current truth.
4. **Inspect:** Collect current evidence such as git state, tests, lint, type checks, evals, traces, metrics, issue state, dependencies, and prior verification failures.
5. **Generate:** Produce a small candidate set tied to observed evidence. Exclude candidates outside scope, permissions, budget, or safety rules.
6. **Rank:** Estimate expected value, confidence, risk, cost, reversibility, and verification quality. Choose the highest positive-value bounded candidate.
7. **Recheck:** Refresh target state and ensure the evidence, lease, scope, and action fingerprint are still valid.
8. **Act:** Apply one bounded action by default. Never broaden access or side effects to force completion.
9. **Verify:** Compare before and after evidence, run required regressions, and confirm the intended metric or failure improved without unacceptable regressions.
10. **Persist:** Record outcome, evidence, fingerprints, verification, remaining candidates, and checkpoint version atomically.
11. **Report:** State what was inspected, why the action was chosen, what changed, verification results, remaining risk, or the exact no-op reason.

The scheduled prompt or handler must encode this loop. Repeating a fixed command such as "upgrade dependencies" or "rewrite prompts" is not adaptive optimization.

## 7. Candidate Selection and Bounds

Use a consistent ranking rule. A practical model is:

```text
priority = expected_value * confidence * verification_strength
           - risk - execution_cost - integration_cost
```

Prefer actions that address a measured failure, improve a user-relevant metric, are reversible, and have strong verification. Reject actions with non-positive estimated value or weak evidence.

Unless the user configured different bounds, use conservative defaults:

- One issue and one independently testable change per run.
- No deployment, credential changes, permission changes, destructive migration, or new external service.
- No unrelated refactor bundled with the chosen action.
- Stop when the time or cost budget is reached; do not begin work that cannot be safely verified within the run.

## 8. Persistent Checkpoint

Use the scheduler's durable state store when available. Otherwise use an explicitly approved project-local or external state location. Store no secrets unless the selected store is approved for them.

Recommended fields:

```yaml
schema_version:
target_id:
scope_hash:
last_run_id:
last_observed_revision:
last_run_time:
baseline_summary:
action_history:
action_fingerprints:
verification_history:
open_findings:
deferred_candidates:
failure_count:
lease_owner:
lease_expiry:
```

Version the schema and write checkpoints atomically. If state is missing or corrupt, reconstruct only from trusted current evidence and report the reset.

## 9. Concurrency and Duplicate Protection

- Use a target-scoped lease with owner, acquisition time, and expiry. Renew only while the run is active.
- Form a run idempotency key from the schedule, target, and scheduled occurrence.
- Form an action fingerprint from the target revision, evidence finding, action type, and affected scope.
- Before acting, reject an already successful fingerprint and re-evaluate a previously failed one only when evidence or implementation conditions changed.
- Re-read the target revision immediately before writes. No-op on conflicting user or automation changes unless the action can be recomputed safely.
- Release the lease in success, failure, and no-op paths. Treat stale leases conservatively and record any takeover.

## 10. Verification, Failure, and No-Op

Capture a baseline before changes. Verification must directly test the selected objective and include relevant regressions. Examples include a formerly failing test passing, an eval metric improving above noise, latency or cost improving under the same workload, or a security finding being eliminated.

If verification fails, stop further optimization. Roll back only changes produced by the current run when rollback is safe and ownership is certain; never overwrite user work. Persist the failure evidence and report whether any partial state remains.

Perform a safe no-op when:

- No candidate has positive evidence-backed value.
- The target is dirty, conflicting, unavailable, or changed after selection.
- A valid lease or duplicate fingerprint blocks work.
- Required verification cannot run or would exceed the budget.
- The action needs permissions, approvals, credentials, scope, or side effects not already granted.
- Risk is higher than the configured tolerance.

A no-op is a successful safety outcome when it records inspected evidence and a precise reason.

## 11. Permissions and Reporting

Every run inherits the exact permission and approval envelope of the configured automation. It may use less authority but must never request, infer, persist, or grant broader authority. New tools, credentials, network access, deployment rights, destructive actions, or external notifications require separate explicit authorization.

Report at least:

```text
Run ID and target revision
State and evidence inspected
Candidate actions considered
Chosen action and ranking rationale, or no-op reason
Files/resources changed
Verification and before/after result
Checkpoint update
Remaining risks or next evidence to inspect
```
