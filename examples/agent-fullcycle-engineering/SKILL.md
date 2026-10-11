---
name: agent-fullcycle-engineering
description: End-to-end AI agent engineering workflow for designing, building, debugging, testing, evaluating, observing, deploying, and improving LLM or AI agents, including CrewAI-style multi-agent flows, delegated engineering work, and adaptive scheduled optimization. Use when Codex needs to plan or implement agent systems, tool calling, RAG, memory, orchestration, prompts, safety controls, evals, tests, observability, release handoff, production debugging, or evidence-driven recurring improvement.
---

# Agent Fullcycle Engineering

## Overview

Use this skill to turn an agent idea into a working, testable, operable system. Treat an agent as a production workflow: user goal, model behavior, tools, state, retrieval, safety, evaluation, debugging, deployment, and feedback.

## Response Modes

Choose the response mode from the user's intent:

- **Beginner learning**: explain concepts from simple to deep, use plain language, and include concrete examples.
- **Interview preparation**: use senior-interviewer standards, include tradeoffs, failure modes, metrics, and what a qualified answer must cover.
- **Project delivery**: drive the full lifecycle from brief to architecture, implementation, tests, observability, release, and handoff.
- **Debugging or review**: collect evidence first, isolate the failing layer, patch narrowly, and add regression coverage.

When the user is new to agents, explain in this order:

1. An agent is an AI system that can understand a goal, decide next actions, call tools, observe results, and continue until it reaches a stopping condition.
2. A reliable agent is not only a prompt. It needs typed inputs, tool contracts, state, error handling, tests, evaluation data, logging, and human override paths.
3. Agent engineering spans product thinking, prompt/context design, software engineering, data/RAG, testing/evals, debugging, security, deployment, observability, git handoff, and iteration.
4. Start with the smallest useful workflow before adding memory, planner loops, or multi-agent collaboration.

## Reference Routing

For a complete beginner-friendly article with examples, terms, and use cases, read `references/beginner-agent-engineer-guide.md`.
For a senior-interviewer acceptance review of that article and the professional depth required for real interviews, read `references/senior-interviewer-acceptance.md`.
For a full advanced-but-readable interview preparation article with architecture tradeoffs, tools, RAG, evals, safety, observability, deployment, terms, and a complete customer-support Agent case, read `references/advanced-agent-engineer-practical-guide.md`.
For a shorter beginner-friendly learning path, read `references/agent-engineer-roadmap.md`.

Use these task-specific references only when relevant:

- Architecture selection, state, memory, workflow, planner/executor, or multi-agent choices: `references/architecture-patterns.md`.
- Coding process, task breakdown, tests, review, and PR handoff: `references/development-workflow.md`.
- Tests, eval datasets, quality metrics, release gates, and regression strategy: `references/evaluation-testing.md`.
- Runtime failures, bad answers, broken tools, loops, and root-cause isolation: `references/debugging-playbook.md`.
- Trace fields, logs, metrics, costs, alerts, and production support: `references/observability-operations.md`.
- CrewAI crews, flows, YAML, memory, tracing, deployment, and CLI verification: `references/crewai-patterns.md`.
- Requirements, design review, QA, security, launch, git, PR, and post-release checklists: `references/delivery-checklists.md`.
- Subagent delegation or scheduled tasks that automatically optimize a project: `references/delegation-adaptive-automation.md`. Read it before delegating substantial work or defining adaptive automation.

## Full Lifecycle Workflow

Follow this order unless the user asks for a narrow task:

1. Clarify the job: user, target outcome, non-goals, allowed actions, success criteria, and failure consequences.
2. Map the environment: available data, tools/APIs, permissions, latency/cost limits, privacy constraints, and required human approvals.
3. Choose the simplest architecture:
   - Use deterministic code when rules are clear.
   - Use a single LLM call when no tools or long-running state are needed.
   - Use tool calling when the agent must inspect or change external systems.
   - Use RAG when answers depend on private or changing knowledge.
   - Use workflow orchestration when steps are known but some steps need LLM judgment.
   - Use planner/executor or multi-agent designs only when simpler designs cannot handle the task boundaries.
4. Design contracts: input schema, output schema, tool schemas, state model, error model, permissions, and audit trail.
5. Plan the development loop: brainstorm brief, implementation plan, code tasks, review, test, debug, observe, deploy, and commit/PR handoff.
6. Build a vertical slice: one real user request, one path through the loop, real or mocked tools, and a visible result.
7. Add tests and evals before broadening scope: unit tests, tool contract tests, integration tests, golden cases, regression cases, and safety probes.
8. Add operations: tracing, metrics, cost tracking, retry policy, rate limits, fallbacks, redaction, and runbooks.
9. Release in stages: internal demo, shadow mode if possible, limited rollout, measured feedback, rollback readiness, and regression protection.

For coding workflow, read `references/development-workflow.md`.
For architecture choices, read `references/architecture-patterns.md`.
For testing and evals, read `references/evaluation-testing.md`.
For systematic debugging, read `references/debugging-playbook.md`.
For observability and production operations, read `references/observability-operations.md`.
For CrewAI-specific crews, flows, YAML, tracing, deploy, and CLI work, read `references/crewai-patterns.md`.
For review, release, git, and PR gates, read `references/delivery-checklists.md`.

## Engineering Defaults

- Prefer repo-local frameworks and patterns. If no framework exists, implement a small explicit loop before adding orchestration libraries.
- Start with the least complex architecture that satisfies the job: deterministic code, single LLM call, RAG, tool calling, workflow, planner/executor, then multi-agent.
- Prefer subagents for suitable independent subtasks. This is an execution tactic, not a reason to make the product itself multi-agent.
- Delegate only bounded, independently verifiable work with disjoint write ownership and lower integration cost than expected time saved. Use a task contract covering objective, inputs, allowed scope, deliverable, constraints, verification, and stop conditions.
- Run at most three subagents concurrently by default and never assign overlapping writes. The parent agent owns planning, permission decisions, integration, conflict resolution, final verification, and the user-facing result.
- If subagents are unavailable or unsuitable, preserve the decomposition and execute it serially without blocking the task.
- Keep prompts versioned near the code that uses them. Include purpose, input variables, output contract, and known failure cases.
- Use structured outputs or typed schemas for agent decisions that downstream code consumes.
- Validate and sanitize every tool input. Treat model-generated tool arguments as untrusted.
- Make side-effecting tools idempotent when possible. Require confirmation for irreversible, expensive, or externally visible actions.
- For RAG, require chunk strategy, metadata, permission filtering, freshness handling, citations, and negative-case behavior before treating it as production-ready.
- Separate planning, acting, observing, and final answering in code or traces so failures can be debugged.
- Log enough to replay behavior: request id, model, prompt version, tool name, sanitized arguments, tool result status, latency, token/cost estimates, and final outcome.
- Define eval gates before release: task success, tool selection, argument accuracy, groundedness, refusal correctness, latency, cost, and high-risk case pass rate.
- Design for refusal and escalation. A production agent must know when to stop, ask for clarification, or hand off to a human.
- Keep development artifacts traceable: feature brief, plan, task id, code changes, tests, review notes, deployment version, and rollback path.
- During debugging, patch the narrowest failing layer and add a regression case before broad refactors.

## Adaptive Scheduled Optimization

- Enable adaptive optimization only when the user explicitly requests a scheduled task to automatically optimize, improve, tune, or choose its own next useful action. Do not silently convert a static schedule into an adaptive one.
- Each run must inspect current project state and fresh evidence, load a durable checkpoint, rank safe bounded candidates, and choose the highest-value action that fits the configured scope and budget. Never replay a static optimization merely because it ran previously.
- Protect each target with a lease or equivalent lock plus run and action fingerprints to prevent concurrent or duplicate work. Recheck state immediately before applying changes.
- Apply one bounded action by default, verify the result against a baseline, persist the outcome, and report evidence, changes, checks, and remaining risk.
- Perform a safe no-op and report why when no evidence-backed action is worthwhile, state is conflicting, verification is unavailable, another run owns the target, or required permission is absent.
- Inherit the automation's existing permissions and approval rules exactly. Never broaden permissions, scope, credentials, or side-effect authority to complete an optimization.

Use `references/delegation-adaptive-automation.md` for decision criteria, contracts, checkpoint fields, selection rules, duplicate protection, verification, and reporting.

## Senior Acceptance Gates

Before presenting an agent design as interview-ready or production-ready, ensure it answers:

- Why use an agent instead of deterministic code, a single LLM call, RAG only, or a fixed workflow?
- What are the system boundary, data flow, allowed tools, denied tools, side effects, and human approval points?
- How are tool schemas validated, permissions enforced, idempotency handled, and errors classified?
- How does RAG handle chunking, metadata, permissions, reranking, citations, freshness, and no-answer cases?
- What offline evals, online metrics, thresholds, and regression gates prove quality?
- How are prompt injection, tool injection, data leakage, and unauthorized actions blocked?
- Which trace fields, logs, metrics, and alert rules make failures diagnosable?
- How are cost, latency, rate limits, rollout, rollback, and human escalation controlled?

## CrewAI Development Mode

When the project uses CrewAI or CrewAI-like concepts:

- Map vague ideas into a feature brief with user stories, acceptance criteria, constraints, agent assignments, and risks.
- Convert the brief into `agents.yaml`, `tasks.yaml`, flow state, dependency chains, guardrails, and validation commands.
- Prefer YAML for agent/task definitions when the project already follows that pattern.
- For Flow projects, check `@start`, `@listen`, `@router`, state field names, persistence, and branch conditions.
- During debug, collect CLI evidence first, then diagnose by category: agent, task, flow, memory/knowledge, deploy, chat, or observability.
- Use `crewai test`, `crewai run`, `crewai replay`, `crewai log-tasks-outputs`, `crewai traces status`, and `crewai deploy --status` when available.

## Project Scaffold

To create starter planning artifacts for a new agent project, run:

```bash
python path/to/agent-fullcycle-engineering/scripts/scaffold_agent_project.py --name my-agent --output .
```

The script creates templates for the agent brief, feature brief, architecture, architecture decision matrix, tool contracts, RAG plan, CrewAI plan, eval plan, test plan, safety model, debug report, observability plan, runbook, deployment plan, delegation plan, adaptive automation state, senior readiness review, review checklist, and PR handoff.

Use it when starting a new agent repo, preparing for an agent system-design interview, or adding production discipline to an existing demo. For interview prep, fill `architecture_decision.md`, `tool_contracts.md`, `rag_plan.md`, `eval_plan.md`, `safety_model.md`, `observability_plan.md`, and `senior_readiness.md` first.

## Minimum Done Definition

An agent task is not complete until these are handled or explicitly waived:

- The user goal and acceptance criteria are written down.
- Tool and data permissions are explicit.
- At least one happy path and one failure path are tested.
- Model outputs consumed by code are schema-validated.
- A small eval set exists for likely user requests and known edge cases.
- Safety and privacy risks have controls or documented tradeoffs.
- Debug and rollback procedures exist for the most likely failures.
- Observability exists for debugging real runs.
- Review, deployment, and git/PR handoff are complete.
- The final response tells the user what was changed, what was tested, and what risk remains.
