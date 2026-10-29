"""Generation contracts for AI-assisted semantic migration.

These profiles are instructions and acceptance requirements, not evidence that
a framework has run. The validator must obtain independent execution evidence.
No profile equates a preservation capsule with target-runtime compatibility.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_COMMON = """Implement bridge_tools.py with real, typed Python tool functions and
bridge_workflow.py with run(request) that executes the source procedure. Reuse
audited source scripts when available, retaining their paths and behavior;
otherwise implement only operations sufficiently specified by the source. Do
not invent unavailable credentials, APIs, business policies or tool behavior.
List unresolved source requirements explicitly instead of substituting echo,
constant success values, TODO implementations, pass-only tools or mock packages.

Keep imports free of network calls, model initialization and workflow execution.
Use JSON-compatible inputs/results for the frozen acceptance cases. The run
function must encode relevant ordering, branches, failure paths, dependencies
and output rules; copying the instructions into one large prompt is insufficient.
An operation requiring an external service must use a documented configurable
adapter and fail clearly when its configuration is missing. Inject dependencies
for offline verification without replacing the framework or the actual tools.

Preserve source resources separately from the active implementation. A source
capsule is archival evidence, not runtime evidence. Never modify frozen source
acceptance cases, fabricate observations or call validation successful because
generated code prints an 'ok' string. Report source limitations and target
differences, especially memory, permissions, parallelism and side effects.
"""


def _profile(
    target: str,
    files: list[str],
    guidance: str,
    checks: list[str],
    sources: list[str],
    *,
    entrypoint: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "target": target,
        "required_files": ["bridge_tools.py", "bridge_workflow.py", *files],
        "guidance": _COMMON + "\n" + guidance.strip(),
        "runtime_kind": "python_agent" if entrypoint else "external_host",
        "native_checks": checks,
        "sources": sources,
        "entrypoint": entrypoint,
    }


_PROFILES = {
    "langchain": _profile(
        "langchain",
        ["agent.py", "requirements.txt"],
        """Generate agent.py with build_agent(model=None), using the real
langchain.agents.create_agent. An injected model instance must be passed through
unchanged. Register the actual tools, including a source-workflow tool calling
bridge_workflow.run; give every tool a meaningful description and argument
schema. The runtime model calls tools in a loop, so deterministic business
branches belong in executable code rather than relying on a prompt promise.
Use framework-supported middleware or a graph when source orchestration needs
additional state. Do not assume memory/checkpointing, output schema enforcement
or side-effect approval follows from the source text. Expose those differences.
Use project-relative resource paths and explicit model configuration only when
no model is injected. Never import fabricated langchain modules or bypass the
framework when exercising the agent.""",
        [
            "Import the installed LangChain implementation and build_agent with an injected model.",
            "Invoke the real agent graph; observe a real registered tool call and its result.",
            "Execute frozen source cases against bridge_tools and bridge_workflow, including branches.",
            "Verify the final messages contain tool results; graph construction alone is insufficient.",
        ],
        [
            "https://docs.langchain.com/oss/python/langchain/agents",
            "https://reference.langchain.com/python/langchain/agents",
        ],
        entrypoint={"module": "agent.py", "factory": "build_agent", "model_argument": "model"},
    ),
    "deepagents": _profile(
        "deepagents",
        ["agent.py", "requirements.txt", "skills/*/SKILL.md"],
        """Generate agent.py with build_agent(model=None), using the real
deepagents.create_deep_agent and passing an injected tool-calling model through.
Register real bridge tools and a workflow tool, not only a copied skill prompt.
Preserve the skill directory and supporting resources. Configure a real backend
whose virtual paths agree with skills paths; a host filesystem is not magically
visible inside a state backend. When using disk resources, root the filesystem
backend at the generated project, never at a developer-specific directory.
Memory, subagents and filesystem access are explicit runtime capabilities, not
implied equivalents of a skill. Do not enable unrestricted shell or filesystem
capabilities merely because the source mentions scripts. Keep the installed
backend's supported configuration and discovery behavior observable.""",
        [
            "Build with the installed Deep Agents SDK and an injected tool-calling model.",
            "Run the actual agent graph and observe execution of a real bridge tool.",
            "Confirm the configured backend can discover the generated skill and read a resource.",
            "Execute frozen source tools/workflow cases separately from skill discovery.",
        ],
        [
            "https://docs.langchain.com/oss/python/deepagents/quickstart",
            "https://docs.langchain.com/oss/python/deepagents/skills",
            "https://docs.langchain.com/oss/python/deepagents/backends",
        ],
        entrypoint={"module": "agent.py", "factory": "build_agent", "model_argument": "model"},
    ),
    "crewai": _profile(
        "crewai",
        ["agent.py", "config/agents.yaml", "config/tasks.yaml", "requirements.txt"],
        """Generate agent.py with build_crew(llm=None), creating real CrewAI
Agent, Task and Crew objects from the project configuration. Pass an injected
LLM through to every agent that needs one. Attach real BaseTool or @tool
implementations from bridge_tools and a tool invoking bridge_workflow.run.
Translate source roles into actual task ownership and context dependencies.
Sequential Crew tasks do not express arbitrary conditional graphs: implement
the specified branch rules in bridge_workflow and, when needed, a real CrewAI
Flow. A hierarchical process requires its actual manager configuration.
Preserve constraints as executable guards where the source permits doing so;
do not claim agent backstory enforces permissions or tool side-effect policy.""",
        [
            "Load the generated configuration using the installed CrewAI objects.",
            "Call build_crew with an injected LLM, then kickoff a real crew task.",
            "Observe the registered bridge tool executing; construction or YAML parsing is insufficient.",
            "Check source task ownership, dependencies and branch results with frozen cases.",
        ],
        [
            "https://docs.crewai.com/en/concepts/agents",
            "https://docs.crewai.com/en/concepts/crews",
            "https://docs.crewai.com/en/concepts/tools",
            "https://docs.crewai.com/en/concepts/flows",
        ],
        entrypoint={"module": "agent.py", "factory": "build_crew", "model_argument": "llm"},
    ),
    "crewai-skills": _profile(
        "crewai-skills",
        ["agent.py", "config/agents.yaml", "config/tasks.yaml", "skills/*/SKILL.md", "requirements.txt"],
        """Generate agent.py with build_crew(llm=None) using real CrewAI
objects and real bridge tools. Retain native skills directories with complete
resources and reference them through the installed version's supported skills
discovery or activated Skill objects. Confirm discovery rather than guessing
that a directory path has loaded its body. Skill instructions provide expertise;
they do not implement executable actions, so attach the actual tools separately.
Map source roles and dependencies to tasks, and conditional business rules to
bridge_workflow or a real Flow. Keep progressive loading behavior explicit:
discovering metadata alone does not prove the source procedure was activated.
Pass the injected LLM through and avoid model setup at module import.""",
        [
            "Discover the intended skill with the installed CrewAI skills loader and activate its body.",
            "Build a real crew with an injected LLM and kickoff a task using an actual bridge tool.",
            "Check supporting skill resources are accessible from the package's own directory.",
            "Execute frozen branch/tool cases; metadata discovery is not semantic execution.",
        ],
        [
            "https://docs.crewai.com/en/concepts/skills",
            "https://docs.crewai.com/en/concepts/agents",
            "https://docs.crewai.com/en/concepts/crews",
            "https://docs.crewai.com/en/concepts/tools",
        ],
        entrypoint={"module": "agent.py", "factory": "build_crew", "model_argument": "llm"},
    ),
    "autogen": _profile(
        "autogen",
        ["agent.py", "requirements.txt"],
        """Target Microsoft AutoGen AgentChat, not the unrelated AG2 API.
Generate agent.py with build_agent(model=None); model is an injected AgentChat
ChatCompletionClient and must be passed as model_client to the real
autogen_agentchat.agents.AssistantAgent. Register typed real functions as tools,
including a wrapper that invokes bridge_workflow.run. Do not pass an LLM string
where a model client is required. Use valid runtime identifiers for agent/tool
names while preserving source names in metadata. Run is asynchronous and
stateful: use await agent.run(task=...) and deliberately manage termination,
client lifetime and state between requests. Teams, handoffs and source DAGs
need explicit orchestration; one AssistantAgent's system_message is not a team.
An official ReplayChatCompletionClient can provide deterministic model events
while the installed framework and tool functions execute normally.""",
        [
            "Import installed autogen_agentchat and create the actual AssistantAgent with an injected client.",
            "Await agent.run and observe the registered tool executing, not merely an assistant text event.",
            "Check the returned TaskResult and tool execution events correspond to frozen source cases.",
            "Do not count a generated imitation of AutoGen or an unexecuted coroutine as runtime validation.",
        ],
        [
            "https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/agents.html",
            "https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.agents.html",
            "https://microsoft.github.io/autogen/stable/reference/python/autogen_ext.models.replay.html",
        ],
        entrypoint={"module": "agent.py", "factory": "build_agent", "model_argument": "model"},
    ),
    "langflow": _profile(
        "langflow",
        ["flow.json"],
        """Generate importable native Langflow flow.json with real component
types, parameters, ports and edges for the target installation. Supply complete
custom component implementation where the flow calls generated tools; do not
invent component IDs that have no installed implementation. Route the source
workflow through connected execution nodes or a real component calling
bridge_workflow.run. Model, secrets and service URLs must remain external
configuration. A Python implementation beside a flow is not connected until
the actual flow component invokes it. JSON syntax and node counting do not
prove component construction, edge compatibility or correct flow execution.
Use an explicitly configured runtime command/API adapter to import and execute
the flow in a real Langflow installation, checking observable tool results.""",
        [
            "Import flow.json into the actual target Langflow runtime and instantiate its components.",
            "Run the flow with frozen inputs through connected nodes and compare observable results.",
            "Validate tool component execution and source branch paths, not a copied source-skill field.",
            "Without the installed engine and explicit runtime adapter, report needs_configuration.",
        ],
        ["https://docs.langflow.org/api-reference-api-examples"],
    ),
    "n8n": _profile(
        "n8n",
        ["workflow.json"],
        """Generate native n8n workflow.json with supported node types,
versions and connections, including an actual trigger for the chosen execution
mode. Translate source branches to real IF/Switch routes and item semantics;
preserve merge dependencies instead of flattening the graph. Native AI Agent
nodes need their actual model/tool subnodes connected. Implement deterministic
operations in actual Code nodes or supported service/tool nodes. The Python
bridge files provide source acceptance logic; n8n cannot execute them merely
because they are adjacent. If using a Python command or HTTP adapter, document
and wire its real deployment prerequisite rather than assuming n8n Cloud can
run arbitrary local shell commands. Keep credential bindings external. Require
an explicit command/API adapter to run the workflow in an actual n8n instance.""",
        [
            "Import the workflow into the configured n8n engine and resolve all required nodes/credentials.",
            "Execute frozen source inputs and inspect actual item outputs across source branch routes.",
            "Observe connected tool nodes or code nodes running; JSON validation alone is insufficient.",
            "Without a real n8n engine and explicit runtime adapter, report needs_configuration.",
        ],
        [
            "https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent",
            "https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md",
        ],
    ),
    "openai": _profile(
        "openai",
        ["agents/openai.yaml", "instructions.md"],
        """This repository's openai target is a Codex skill/interface package,
not the OpenAI Agents SDK and not a Python execution engine. Generate the
agents/openai.yaml interface and clear instructions.md, with real relative
instructions for invoking bridge_tools and bridge_workflow through the host's
available tools. Interface display/default-prompt fields do not define tool
implementations, grant permissions or create a workflow runner. Keep host
configuration separate and preserve source capability restrictions. Do not
invent an 'openai' runtime import or claim a saved YAML file has executed.
Actual host verification requires an explicitly configured Codex/host adapter
that loads this package, invokes the migrated operation and returns evidence.""",
        [
            "Validate interface fields and referenced local resources.",
            "Execute frozen Python tool/workflow cases separately from host verification.",
            "Use an explicit host runtime command to load the package and observe source behavior.",
            "Without host execution evidence, report needs_configuration, not engine-verified.",
        ],
        ["https://learn.chatgpt.com/docs/build-skills"],
    ),
    "claude-subagent": _profile(
        "claude-subagent",
        [".claude/agents/*.md"],
        """Generate a Claude Code subagent Markdown definition with supported
frontmatter and explicit instructions referencing the generated real tools and
workflow files. Source tool names do not automatically become available host
tools: map actions to enabled built-ins, concrete scripts or configured MCP
servers. Preserve tool restrictions; do not silently widen permissions or
assume a parent agent's skills, state and tool results are shared. Distinguish
subagent context/memory from source framework memory. A subagent Markdown file
is configuration for the actual host, not an executable Python Agent. Require
an explicit Claude host command/adapter to invoke the subagent and collect
observable outputs before reporting target runtime verification.""",
        [
            "Check the subagent frontmatter and all script/resource references.",
            "Execute frozen Python tool/workflow cases independently of host configuration.",
            "Invoke the actual subagent through an explicit configured host adapter and compare outputs.",
            "Without host execution evidence, report needs_configuration.",
        ],
        ["https://code.claude.com/docs/en/sub-agents"],
    ),
    "generic": _profile(
        "generic",
        ["agent.json"],
        """Generate the repository's generic AgentIR JSON representation,
alongside real bridge tools and workflow code. Store the active source-derived
contracts and declared target limitations. JSON fields are serialized data;
they do not run tools or enforce roles, memory, policy or orchestration.
Define how an external consumer loads the JSON and calls the Python entrypoints.
Do not invent a generic framework package or report a JSON parse as an engine
execution. Frozen source cases establish generated Python behavior; only an
explicit consumer runtime adapter can establish deployment behavior.""",
        [
            "Parse agent.json with the repository's actual AgentIR representation.",
            "Execute source-derived bridge tool/workflow cases against the generated implementation.",
            "Require explicit external consumer evidence for target runtime verification.",
            "Without a consumer runtime adapter, report needs_configuration.",
        ],
        ["https://github.com/8eeth0ven/agentskills-bridge/blob/main/INTERFACE.md"],
    ),
    "mermaid-workflow": _profile(
        "mermaid-workflow",
        ["workflow.md"],
        """Generate workflow.md with valid Mermaid flowchart syntax that
expresses source decisions, conditions, dependency joins and failure exits.
Link node explanations to the actual bridge_workflow implementation and real
tool contracts. Escape labels and use safe node identifiers. A Mermaid diagram
documents a process; rendering it does not execute its steps. Keep the runnable
Python counterpart clearly labeled and do not claim Mermaid itself invokes
tools or agents. Require an explicit consuming runtime adapter before declaring
target runtime verification; diagram syntax/render checks remain static.""",
        [
            "Parse or render the diagram using a genuine Mermaid implementation when available.",
            "Check source branch labels/dependencies match the actual Python workflow.",
            "Execute frozen source Python cases; distinguish this from diagram rendering.",
            "Without an explicit consuming runtime adapter, report needs_configuration.",
        ],
        ["https://mermaid.js.org/syntax/flowchart.html"],
    ),
    "skill": _profile(
        "skill",
        ["SKILL.md"],
        """Generate a valid Agent Skills directory with SKILL.md and relative
references to the migrated bridge tools/workflow. Preserve supporting scripts,
references and assets. Frontmatter describes discovery; natural-language steps
must be grounded in actual callable operations where the source specifies them.
Declare compatibility and any missing external tool/service requirements.
The Agent Skills specification is a packaging convention, not an execution
engine or a permission mechanism. Local Python source cases check the migrated
implementation; actual skill activation and use require an explicit chosen
host runtime adapter. Do not claim that reading SKILL.md executes its procedure.""",
        [
            "Validate required skill frontmatter and all referenced resources.",
            "Execute frozen source-derived bridge tool/workflow cases.",
            "Require an explicit host adapter to activate and use the skill for runtime verification.",
            "Without a real host execution, report needs_configuration.",
        ],
        ["https://agentskills.io/specification"],
    ),
}


SUPPORTED_AI_TARGETS = tuple(_PROFILES)


def target_profile(target: str) -> dict[str, Any]:
    """Return an independent target contract, rejecting unknown formats."""
    if target not in _PROFILES:
        raise ValueError(f"unsupported AI migration target: {target!r}")
    return deepcopy(_PROFILES[target])
