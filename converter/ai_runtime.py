"""Native framework probes maintained outside AI-generated project code.

Replay/fake language models make native engine/tool execution deterministic;
these probes are not evidence of live model reasoning or universal equivalence.
The AI migration itself uses a real configured model provider separately.
"""
from __future__ import annotations

import json
import ast
from pathlib import Path
import sys


_NATIVE_RUNNER = r'''
import asyncio, ast, importlib.util, inspect, json, pathlib, re, sys, traceback
root = pathlib.Path.cwd()
specification = json.load(sys.stdin)
sys.path.insert(0, str(root))
target = specification["target"]
marker = "__AGENTSKILLS_BRIDGE_NATIVE__"

def emit(value):
    print(marker + json.dumps(value, ensure_ascii=False, allow_nan=False))

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def native_cases():
    result = []
    for case_index, case in enumerate(specification["acceptance"]):
        if case.get("kind") != "function":
            continue
        for tool in specification["tools"]:
            module = tool.get("implementation_file", "bridge_tools.py")
            function = tool.get("callable", tool["name"])
            if case["module"] == module and case.get("callable") == function:
                result.append((tool["name"], {**case, "_case_index": case_index}))
                break
    missing = sorted({tool["name"] for tool in specification["tools"]} - {name for name, _ in result})
    if missing:
        raise AssertionError("each native tool requires a matching frozen function acceptance case; missing: " + ", ".join(missing))
    return result

def load_agent():
    path = root / "agent.py"
    if not path.is_file():
        raise ValueError("native runtime requires agent.py with an injectable factory")
    spec = importlib.util.spec_from_file_location("bridge_generated_agent", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def skill_body(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise AssertionError("native skill is missing frontmatter")
    name = re.search(r"^name:\s*(.+)$", match.group(1), re.M)
    if name is None:
        raise AssertionError("native skill is missing its name")
    return name.group(1).strip().strip("\"'"), text[match.end():].strip()

def crew_configuration(crew):
    import yaml
    configs = []
    for name in ("agents", "tasks"):
        path = root / "config" / (name + ".yaml")
        if not path.is_file():
            raise AssertionError("CrewAI runtime requires its native " + name + ".yaml")
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value or any(not isinstance(item, dict) for item in value.values()):
            raise AssertionError("CrewAI native " + name + " configuration must be a nonempty mapping")
        configs.append(value)
    agent_config, task_config = configs
    configured_roles = {" ".join(str(item.get("role", "")).split()) for item in agent_config.values()}
    if "" in configured_roles or not configured_roles.issubset({" ".join(str(agent.role).split()) for agent in crew.agents}):
        raise AssertionError("native CrewAI agents do not implement the configured roles")
    if len(crew.tasks) < len(task_config):
        raise AssertionError("native CrewAI crew omitted configured tasks")
    for item in task_config.values():
        if not item.get("description") or not item.get("expected_output"):
            raise AssertionError("native CrewAI task configuration is missing required fields")

try:
    if target in ("langchain", "deepagents"):
        import langchain_core
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage, ToolMessage
        from langgraph.graph.state import CompiledStateGraph
        if target == "langchain":
            import langchain
        else:
            import deepagents
    elif target == "autogen":
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.base import TaskResult
        from autogen_core import FunctionCall
        from autogen_core.models import CreateResult, RequestUsage
        from autogen_ext.models.replay import ReplayChatCompletionClient
    elif target in ("crewai", "crewai-skills"):
        from crewai import Crew
        try:
            from crewai import BaseLLM
        except ImportError:
            from crewai.llms.base_llm import BaseLLM
except (ImportError, ModuleNotFoundError) as error:
    emit({"ok": False, "status": "needs_configuration", "error": "native framework dependency unavailable: " + str(error)})
    sys.exit(0)

try:
    cases = native_cases()
    observations = []
    checked_skills, checked_resources = [], []
    agent_module = load_agent()
    if target in ("langchain", "deepagents"):
        for name, case in cases or [(None, None)]:
            registered = []
            observed_prompts = []
            class ProbeModel(GenericFakeChatModel):
                def bind_tools(self, tools, **kwargs):
                    for item in tools:
                        if hasattr(item, "name"):
                            registered.append(item.name)
                        elif isinstance(item, dict):
                            registered.append(item.get("name", item.get("function", {}).get("name")))
                    return self
                def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                    observed_prompts.extend(str(item.content) for item in messages if getattr(item, "type", "") == "system")
                    return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            responses = [AIMessage(content="bridge-native-probe-complete")]
            if case is not None:
                responses.insert(0, AIMessage(content="", tool_calls=[{"name": name, "args": case["input"], "id": "bridge-native-call", "type": "tool_call"}]))
            model = ProbeModel(messages=iter(responses))
            graph = agent_module.build_agent(model=model)
            if not isinstance(graph, CompiledStateGraph):
                raise AssertionError("build_agent did not return a real LangGraph CompiledStateGraph")
            result = graph.invoke({"messages": [{"role": "user", "content": "Execute the requested verification operation."}]}, config={"recursion_limit": 12})
            messages = result.get("messages", [])
            if case is not None:
                if name not in registered:
                    raise AssertionError("frozen tool was not bound to the real native model: " + name)
                executions = [item for item in messages if isinstance(item, ToolMessage) and item.tool_call_id == "bridge-native-call" and item.name == name]
                if len(executions) != 1:
                    raise AssertionError("real native graph did not emit exactly one matching ToolMessage")
                if getattr(executions[0], "status", "success") == "error":
                    raise AssertionError("native graph tool execution reported an error: " + str(executions[0].content))
                observations.append({"case_index": case["_case_index"], "name": name, "value": executions[0].content, "encoding": "tool_message"})
            if not messages or messages[-1].content != "bridge-native-probe-complete":
                raise AssertionError("real native graph did not complete its injected-model cycle")
        if target == "deepagents":
            skill_files = sorted(root.glob("skills/*/SKILL.md"))
            if not skill_files:
                raise AssertionError("Deep Agents requires its native skill directory")
            for path in skill_files:
                skill_name, instructions = skill_body(path)
                resource_files = sorted(p for p in (path.parent / "references").rglob("*") if p.is_file())
                selected = [path, *resource_files[:1]]
                for resource in selected:
                    virtual_path = "/" + resource.relative_to(root).as_posix()
                    registered, observed_prompts = [], []
                    model = ProbeModel(messages=iter([
                        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": virtual_path}, "id": "bridge-resource-call", "type": "tool_call"}]),
                        AIMessage(content="bridge-native-probe-complete"),
                    ]))
                    graph = agent_module.build_agent(model=model)
                    if not isinstance(graph, CompiledStateGraph):
                        raise AssertionError("Deep Agents factory did not return its real native graph")
                    result = graph.invoke({"messages": [{"role": "user", "content": "Read the packaged skill resource."}]}, config={"recursion_limit": 12})
                    executions = [item for item in result.get("messages", []) if isinstance(item, ToolMessage) and item.tool_call_id == "bridge-resource-call" and item.name == "read_file"]
                    if len(executions) != 1 or getattr(executions[0], "status", "success") == "error":
                        raise AssertionError("native Deep Agents read_file could not access its packaged resource")
                    content = executions[0].content
                    content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                    try:
                        text = resource.read_text(encoding="utf-8")
                    except UnicodeError:
                        raise AssertionError("native skill reference chosen for verification must be UTF-8 text")
                    witness = next((line.strip() for line in text.splitlines() if line.strip() and line.strip() != "---"), "")
                    if witness and witness not in content:
                        raise AssertionError("native resource result does not contain the packaged file's content")
                    prompts = "\n".join(observed_prompts)
                    if skill_name not in prompts or ("/" + path.relative_to(root).as_posix()) not in prompts:
                        raise AssertionError("Deep Agents middleware did not discover the packaged skill in its real model context")
                    checked_resources.append(resource.relative_to(root).as_posix())
                checked_skills.append(path.relative_to(root).as_posix())
    elif target == "autogen":
        async def verify():
            for name, case in cases or [(None, None)]:
                responses = ["bridge-native-probe-complete"]
                if case is not None:
                    responses.insert(0, CreateResult(finish_reason="function_calls", content=[FunctionCall(id="bridge-native-call", name=name, arguments=json.dumps(case["input"]))], usage=RequestUsage(prompt_tokens=0, completion_tokens=0), cached=False))
                client = ReplayChatCompletionClient(responses, model_info={"vision": False, "function_calling": True, "json_output": True, "family": "unknown", "structured_output": False})
                try:
                    factory = agent_module.build_agent
                    kwargs = {"model_client": client} if "model_client" in inspect.signature(factory).parameters else {"model": client}
                    agent = factory(**kwargs)
                    if not isinstance(agent, AssistantAgent):
                        raise AssertionError("build_agent did not return a real AutoGen AssistantAgent")
                    result = await agent.run(task="Execute the requested verification operation.")
                    if not isinstance(result, TaskResult):
                        raise AssertionError("native agent did not return an AutoGen TaskResult")
                    if case is not None:
                        executions = []
                        for event in result.messages:
                            if getattr(event, "type", "") == "ToolCallExecutionEvent":
                                executions.extend(item for item in event.content if item.call_id == "bridge-native-call" and item.name == name)
                        if len(executions) != 1 or executions[0].is_error:
                            raise AssertionError("native AutoGen agent did not execute the requested tool successfully")
                        observations.append({"case_index": case["_case_index"], "name": name, "value": executions[0].content, "encoding": "tool_message"})
                finally:
                    await client.close()
        asyncio.run(verify())
    elif target in ("crewai", "crewai-skills"):
        for name, case in cases or [(None, None)]:
            class ProbeLLM(BaseLLM):
                def __init__(self):
                    super().__init__(model="bridge-native-probe", temperature=0)
                    self._bridge_step = 0
                def supports_function_calling(self):
                    return False
                def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs):
                    self._bridge_step += 1
                    if case is not None and self._bridge_step == 1:
                        return "Thought: I must execute the requested operation.\nAction: " + name + "\nAction Input: " + json.dumps(case["input"])
                    return "Thought: I have completed the operation.\nFinal Answer: bridge-native-probe-complete"
            factory = getattr(agent_module, "build_crew", None)
            if factory is None:
                raise ValueError("CrewAI runtime requires build_crew(llm=None)")
            crew = factory(llm=ProbeLLM())
            if not isinstance(crew, Crew):
                raise AssertionError("build_crew did not return a real CrewAI Crew")
            crew_configuration(crew)
            if target == "crewai-skills":
                from crewai.skills import activate_skill, load_skills
                from crewai.skills.loader import load_skill_resources
                configured = list(getattr(crew, "skills", None) or [])
                for agent in crew.agents:
                    configured.extend(agent.skills or [])
                if not configured:
                    raise AssertionError("native CrewAI crew has not attached the packaged skill")
                activated = [activate_skill(skill) for skill in load_skills(configured, activate=False)]
                skill_files = sorted(root.glob("skills/*/SKILL.md"))
                if not skill_files:
                    raise AssertionError("CrewAI Skills requires its native skill directory")
                for path in skill_files:
                    skill_name, instructions = skill_body(path)
                    candidates = []
                    for skill in activated:
                        location = pathlib.Path(skill.path)
                        location = location / "SKILL.md" if location.is_dir() else location
                        if location.resolve() == path.resolve() and skill.frontmatter.name == skill_name:
                            candidates.append(skill)
                    if len(candidates) != 1 or (candidates[0].instructions or "").strip() != instructions:
                        raise AssertionError("native CrewAI loader did not discover and activate the intended skill body")
                    resource_skill = load_skill_resources(candidates[0])
                    catalog = {pathlib.Path(item).as_posix() for item in
                               (resource_skill.resource_files or {}).get("references", [])}
                    checked_skills.append(path.relative_to(root).as_posix())
                    for resource in sorted((path.parent / "references").rglob("*")):
                        if resource.is_file():
                            relative = resource.relative_to(path.parent / "references").as_posix()
                            if relative not in catalog:
                                raise AssertionError("native CrewAI loader did not catalog the packaged reference")
                            located = resource_skill.references_dir / relative
                            if located.resolve() != resource.resolve():
                                raise AssertionError("native CrewAI resource location differs from its packaged file")
                            located.read_bytes()
                            checked_resources.append(resource.relative_to(root).as_posix())
            observed = []
            if case is not None:
                available = [tool for agent in crew.agents for tool in agent.tools]
                available.extend(tool for task in crew.tasks for tool in task.tools)
                seen = set()
                for tool in available:
                    if id(tool) in seen or tool.name != name:
                        continue
                    seen.add(id(tool))
                    original = tool._run
                    def recorded(*args, _original=original, **kwargs):
                        value = _original(*args, **kwargs)
                        observed.append(value)
                        return value
                    object.__setattr__(tool, "_run", recorded)
                if not seen:
                    raise AssertionError("frozen tool was not registered in the native CrewAI crew: " + name)
            result = crew.kickoff(inputs={"request": "Execute the requested verification operation.", "input": "Execute the requested verification operation."})
            if not getattr(result, "tasks_output", None):
                raise AssertionError("native CrewAI crew returned no task output")
            if case is not None:
                if not observed:
                    raise AssertionError("real CrewAI execution did not invoke the requested tool")
                observations.append({"case_index": case["_case_index"], "name": name, "value": observed[0], "encoding": "json"})
    emit({"ok": True, "status": "passed", "target": target, "observations": observations,
          "native_skills": sorted(set(checked_skills)), "native_resources": sorted(set(checked_resources)),
          "model_mode": "deterministic_injected_model"})
except BaseException as error:
    traceback.print_exc()
    emit({"ok": False, "status": "failed", "error": type(error).__name__ + ": " + str(error)})
    sys.exit(1)
'''


def native_runtime_probe(root: Path, target: str, acceptance: list[dict], tools: list[dict], *,
                         python_executable: str = sys.executable, timeout: float = 30) -> dict:
    """Exercise an installed native engine using immutable tool assertions."""
    from converter.ai_validation import run_command, redact
    supported = ("langchain", "deepagents", "autogen", "crewai", "crewai-skills")
    if target not in supported:
        return {"kind": "native_runtime", "method": "independent_adapter", "ok": False,
                "status": "needs_configuration", "target": target,
                "stderr": "No independent native runtime adapter for this format; supply an explicit runtime command for its installed engine."}
    if not tools:
        return {"kind": "native_runtime", "method": "independent_adapter", "ok": False,
                "status": "failed", "target": target,
                "stderr": "Native execution requires declared real tools and frozen function cases; construction alone is insufficient."}
    # Oracle values never enter the execution process. A generated function may
    # inspect __main__ or stdin: neither may contain its expected answer.
    child_cases = [{key: case[key] for key in ("kind", "module", "callable", "input") if key in case}
                   for case in acceptance]
    report = run_command([str(python_executable), "-B", "-c", _NATIVE_RUNNER], Path(root),
                         stdin=json.dumps({"target": target, "acceptance": child_cases, "tools": tools}, ensure_ascii=False, allow_nan=False),
                         timeout=timeout, _capture_raw=True)
    raw_output = report.pop("_raw_stdout", "")
    report.update(kind="native_runtime", method="independent_adapter", target=target)
    marker = "__AGENTSKILLS_BRIDGE_NATIVE__"
    try:
        if raw_output.count(marker) != 1:
            raise ValueError("missing or duplicate native runtime result frames")
        payload = json.loads(raw_output.split(marker, 1)[1].strip())
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool:
            raise ValueError("invalid native result envelope")
        report["ok"] = bool(report["ok"] and payload["ok"])
        report["status"] = payload["status"]
        if report["ok"]:
            if payload["status"] != "passed":
                raise ValueError("successful native result must be passed")
            expected_cases = {}
            for index, case in enumerate(acceptance):
                if case.get("kind") != "function":
                    continue
                for tool in tools:
                    if (case["module"] == tool.get("implementation_file", "bridge_tools.py")
                            and case.get("callable") == tool.get("callable", tool["name"])):
                        expected_cases[index] = (tool["name"], case)
                        break
            observations = payload.get("observations")
            if not isinstance(observations, list) or len(observations) != len(expected_cases):
                raise ValueError("native runtime omitted or added tool observations")
            observed_cases = set()
            for observation in observations:
                if not isinstance(observation, dict) or set(observation) != {"case_index", "name", "value", "encoding"}:
                    raise ValueError("native runtime must return actual tool observation data")
                index = observation["case_index"]
                if type(index) is not int or index not in expected_cases or index in observed_cases:
                    raise ValueError("native runtime returned an unknown or duplicate case")
                observed_cases.add(index)
                name, case = expected_cases[index]
                if observation["name"] != name:
                    raise ValueError("native runtime returned a different tool")
                actual = observation["value"]
                if observation["encoding"] == "tool_message":
                    if not isinstance(case["expected"], str) and isinstance(actual, str):
                        try:
                            actual = json.loads(actual)
                        except ValueError:
                            actual = ast.literal_eval(actual)
                elif observation["encoding"] != "json":
                    raise ValueError("unknown native tool observation encoding")
                canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if canonical(actual) != canonical(case["expected"]):
                    raise ValueError("native tool result differs from frozen acceptance: expected "
                                     + canonical(case["expected"]) + "; observed " + canonical(actual))
        if payload.get("error"):
            report["stderr"] += "\n" + redact(payload["error"], Path(root))
        report["evidence"] = {key: value for key, value in payload.items() if key not in ("error", "ok", "status")}
    except (IndexError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        report["ok"] = False
        report["status"] = "failed"
        report["stderr"] += "\nNative runtime probe returned no verifiable result: " + redact(exc, Path(root))
    return report
