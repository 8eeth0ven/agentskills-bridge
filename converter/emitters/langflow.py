"""Langflow emitter:AgentIR -> flow.json(Langflow 官方导出格式,1.12 实测)。

链路(与官方 Basic Prompting starter 同构):
    ChatInput --message--> Prompt --prompt(system_message)--> LanguageModelComponent
    LanguageModelComponent --text_output--> ChatOutput

格式要点(依据 langflow main@1.12.5 官方源码与 starter fixtures 调研):
    - reactflow 外层 type="genericNode",id = "{PascalCaseType}-{5位随机}";
    - data.type 为 PascalCase 短类名(ChatInput/Prompt/LanguageModelComponent/ChatOutput);
    - handle 字符串 = json.dumps 后 '"'→'œ'(U+0153),边 data 里另附结构化对象(官方双写);
    - Prompt 的提示词文本在 data.node.template.template.value;
    - LLM 用 LanguageModelComponent(model_name/provider/api_key),Prompt 输出接 system_message。

2026-10 真实引擎验证修复(langflow 1.12.5,evaluation/runtime/test_langflow_runtime.py):
    - bug:模板缺 `template.code` 字段。引擎 Graph.from_payload 默认实例化组件,
      instantiate_class 里 `custom_params.pop("code")` 直接 KeyError('code'),
      flow 无法通过真实引擎加载(官方导出一律内嵌组件完整源码)。
      修复:每个节点模板补 `code` 字段,value 为 1.12.5 规范组件源码
      (取自已装 lfx 包 lfx/_assets/component_index.json,与官方同版导出逐字一致);
      旧版 langflow(<1.4,lfx 包拆分前)exec 该源码会 ImportError,属预期。
    - bug:ChatInput field_order 写了不存在的 "store_message"(实际字段名
      should_store_message),前端按 field_order 排序会对不上;顺手改正。

产出:
    <out>/flow.json      可导入 Langflow 的完整 flow
    <out>/knowledge/*.md 知识文档按 filename 拷贝(不随 flow.json 导入)
    <out>/README.md      UI 导入方式 + Knowledge 两步上传 API 说明
"""

from __future__ import annotations

import json
import random
import string
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from converter.ir import AgentIR

_SUFFIX_CHARS = string.ascii_letters + string.digits
_OE = "\u0153"  # œ —— langflow 全栈约定的 handle 引号替身

# ---- 内置组件规范源码(langflow 1.12.5)----
# 引擎加载 flow 时按 template.code exec 组件类(instantiate_class 里
# params.pop("code") 为必需字段);官方导出把组件完整源码内嵌在
# template.code.value。以下四段取自 langflow 1.12.5(lfx 1.12.5)发行包
# lfx/_assets/component_index.json 的 code.value,与官方导出逐字一致。
# BEGIN VENDORED COMPONENT CODE (langflow 1.12.5)

_CHATINPUT_CODE = 'from lfx.base.data.utils import IMG_FILE_TYPES, TEXT_FILE_TYPES\nfrom lfx.base.io.chat import ChatComponent\nfrom lfx.inputs.inputs import BoolInput\nfrom lfx.io import (\n    DropdownInput,\n    FileInput,\n    MessageTextInput,\n    MultilineInput,\n    Output,\n)\nfrom lfx.schema.image import get_file_paths\nfrom lfx.schema.message import Message\nfrom lfx.services.deps import get_settings_service\nfrom lfx.utils.constants import (\n    MESSAGE_SENDER_AI,\n    MESSAGE_SENDER_NAME_USER,\n    MESSAGE_SENDER_USER,\n)\nfrom lfx.utils.file_path_security import (\n    component_file_access_scopes,\n    enforce_local_file_access,\n    is_local_file_access_restricted,\n)\n\n\nclass ChatInput(ChatComponent):\n    display_name = "Chat Input"\n    description = "Get chat inputs from the Playground."\n    documentation: str = "https://docs.langflow.org/chat-input-and-output"\n    icon = "MessagesSquare"\n    name = "ChatInput"\n    minimized = True\n\n    inputs = [\n        MultilineInput(\n            name="input_value",\n            display_name="Input Text",\n            value="",\n            info="Message to be passed as input.",\n            input_types=[],\n        ),\n        BoolInput(\n            name="should_store_message",\n            display_name="Store Messages",\n            info="Store the message in the history.",\n            value=True,\n            advanced=True,\n        ),\n        DropdownInput(\n            name="sender",\n            display_name="Sender Type",\n            options=[MESSAGE_SENDER_AI, MESSAGE_SENDER_USER],\n            value=MESSAGE_SENDER_USER,\n            info="Type of sender.",\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="sender_name",\n            display_name="Sender Name",\n            info="Name of the sender.",\n            value=MESSAGE_SENDER_NAME_USER,\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="session_id",\n            display_name="Session ID",\n            info="The session ID of the chat. If empty, the current session ID parameter will be used.",\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="context_id",\n            display_name="Context ID",\n            info="The context ID of the chat. Adds an extra layer to the local memory.",\n            value="",\n            advanced=True,\n        ),\n        FileInput(\n            name="files",\n            display_name="Files",\n            file_types=TEXT_FILE_TYPES + IMG_FILE_TYPES,\n            info="Files to be sent with the message.",\n            advanced=True,\n            is_list=True,\n            temp_file=True,\n        ),\n    ]\n    outputs = [\n        Output(display_name="Chat Message", name="message", method="message_response"),\n    ]\n\n    async def message_response(self) -> Message:\n        # Ensure files is a list and filter out empty/None values\n        files = self.files if self.files else []\n        if files and not isinstance(files, list):\n            files = [files]\n        # Filter out None/empty values\n        files = [f for f in files if f is not None and f != ""]\n\n        # Build endpoints inject caller-controlled file references directly into\n        # ChatInput. Resolve and validate local references before the Message can\n        # later read them while constructing model attachment content.\n        if files:\n            settings_service = get_settings_service()\n            storage_type = getattr(getattr(settings_service, "settings", None), "storage_type", "local")\n            # The storage factory falls back to local storage for unsupported\n            # values, so only the explicitly configured S3 backend may bypass\n            # filesystem containment.\n            if str(storage_type).lower() != "s3" and is_local_file_access_restricted():\n                scope_ids = list(component_file_access_scopes(self))\n                # Public executions replace graph.flow_id with a per-visitor\n                # virtual ID. Only the server-populated source provenance may\n                # restore the already-validated public attachment namespace.\n                source_flow_id = getattr(self.graph, "source_flow_id", None)\n                if source_flow_id:\n                    scope_ids.append(source_flow_id)\n                for file_path in get_file_paths(files):\n                    enforce_local_file_access(file_path, scope_ids=scope_ids)\n\n        session_id = self.session_id or self.graph.session_id or ""\n        message = await Message.create(\n            text=self.input_value,\n            sender=self.sender,\n            sender_name=self.sender_name,\n            session_id=session_id,\n            context_id=self.context_id,\n            files=files,\n        )\n        if session_id and isinstance(message, Message) and self.should_store_message:\n            stored_message = await self.send_message(\n                message,\n            )\n            self.message.value = stored_message\n            message = stored_message\n\n        self.status = message\n        return message\n'

_CHATOUTPUT_CODE = 'from collections.abc import Generator\nfrom typing import Any\n\nimport orjson\nfrom fastapi.encoders import jsonable_encoder\n\nfrom lfx.base.io.chat import ChatComponent\nfrom lfx.helpers.data import safe_convert\nfrom lfx.inputs.inputs import BoolInput, DropdownInput, HandleInput, MessageTextInput\nfrom lfx.schema.data import Data\nfrom lfx.schema.dataframe import DataFrame\nfrom lfx.schema.message import Message\nfrom lfx.schema.properties import Source\nfrom lfx.template.field.base import Output\nfrom lfx.utils.constants import (\n    MESSAGE_SENDER_AI,\n    MESSAGE_SENDER_NAME_AI,\n    MESSAGE_SENDER_USER,\n)\n\n\nclass ChatOutput(ChatComponent):\n    display_name = "Chat Output"\n    description = "Display a chat message in the Playground."\n    documentation: str = "https://docs.langflow.org/chat-input-and-output"\n    icon = "MessagesSquare"\n    name = "ChatOutput"\n    minimized = True\n\n    inputs = [\n        HandleInput(\n            name="input_value",\n            display_name="Inputs",\n            info="Message to be passed as output.",\n            input_types=["Data", "JSON", "DataFrame", "Table", "Message"],\n            required=True,\n        ),\n        BoolInput(\n            name="should_store_message",\n            display_name="Store Messages",\n            info="Store the message in the history.",\n            value=True,\n            advanced=True,\n        ),\n        DropdownInput(\n            name="sender",\n            display_name="Sender Type",\n            options=[MESSAGE_SENDER_AI, MESSAGE_SENDER_USER],\n            value=MESSAGE_SENDER_AI,\n            advanced=True,\n            info="Type of sender.",\n        ),\n        MessageTextInput(\n            name="sender_name",\n            display_name="Sender Name",\n            info="Name of the sender.",\n            value=MESSAGE_SENDER_NAME_AI,\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="session_id",\n            display_name="Session ID",\n            info="The session ID of the chat. If empty, the current session ID parameter will be used.",\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="context_id",\n            display_name="Context ID",\n            info="The context ID of the chat. Adds an extra layer to the local memory.",\n            value="",\n            advanced=True,\n        ),\n        MessageTextInput(\n            name="data_template",\n            display_name="Data Template",\n            value="{text}",\n            advanced=True,\n            info="Template to convert Data to Text. If left empty, it will be dynamically set to the Data\'s text key.",\n        ),\n        BoolInput(\n            name="clean_data",\n            display_name="Basic Clean Data",\n            value=True,\n            advanced=True,\n            info="Whether to clean data before converting to string.",\n        ),\n    ]\n    outputs = [\n        Output(\n            display_name="Output Message",\n            name="message",\n            method="message_response",\n        ),\n    ]\n\n    def _build_source(self, id_: str | None, display_name: str | None, source: str | None) -> Source:\n        source_dict = {}\n        if id_:\n            source_dict["id"] = id_\n        if display_name:\n            source_dict["display_name"] = display_name\n        if source:\n            # Handle case where source is a ChatOpenAI object\n            if hasattr(source, "model_name"):\n                source_dict["source"] = source.model_name\n            elif hasattr(source, "model"):\n                source_dict["source"] = str(source.model)\n            else:\n                source_dict["source"] = str(source)\n        return Source(**source_dict)\n\n    async def message_response(self) -> Message:\n        # First convert the input to string if needed\n        text = self.convert_to_string()\n\n        # Get source properties\n        source, _, display_name, source_id = self.get_properties_from_source_component()\n\n        # Create or use existing Message object\n        if isinstance(self.input_value, Message) and not self.is_connected_to_chat_input():\n            message = self.input_value\n            # Update message properties\n            message.text = text\n            # Preserve existing session_id from the incoming message if it exists\n            existing_session_id = message.session_id\n        else:\n            message = Message(text=text)\n            existing_session_id = None\n\n        # Set message properties\n        message.sender = self.sender\n        message.sender_name = self.sender_name\n        # Preserve session_id from incoming message, or use component/graph session_id\n        message.session_id = (\n            self.session_id or existing_session_id or (self.graph.session_id if hasattr(self, "graph") else None) or ""\n        )\n        message.context_id = self.context_id\n        message.flow_id = self.graph.flow_id if hasattr(self, "graph") else None\n        message.properties.source = self._build_source(source_id, display_name, source)\n\n        # Store message if needed\n        if message.session_id and self.should_store_message:\n            stored_message = await self.send_message(message)\n            self.message.value = stored_message\n            message = stored_message\n\n        # Set accumulated token usage from all upstream LLM vertices.\n        # This must happen AFTER send_message() because streaming captures\n        # usage from chunks and would overwrite accumulated totals.\n        if hasattr(self, "_vertex") and self._vertex is not None:\n            accumulated_usage = self._vertex._accumulate_upstream_token_usage()  # noqa: SLF001\n            if accumulated_usage:\n                message.properties.usage = accumulated_usage\n                if self.should_store_message and message.get_id():\n                    message = await self._update_stored_message(message)\n                    await self._send_message_event(message, id_=message.get_id())\n\n        self.status = message\n        return message\n\n    def _serialize_data(self, data: Data) -> str:\n        """Serialize Data object to JSON string."""\n        # Convert data.data to JSON-serializable format\n        serializable_data = jsonable_encoder(data.data)\n        # Serialize with orjson, enabling pretty printing with indentation\n        json_bytes = orjson.dumps(serializable_data, option=orjson.OPT_INDENT_2)\n        # Convert bytes to string and wrap in Markdown code blocks\n        return "```json\\n" + json_bytes.decode("utf-8") + "\\n```"\n\n    def _validate_input(self) -> None:\n        """Validate the input data and raise ValueError if invalid."""\n        if self.input_value is None:\n            msg = "Input data cannot be None"\n            raise ValueError(msg)\n        if isinstance(self.input_value, list) and not all(\n            isinstance(item, Message | Data | DataFrame | str) for item in self.input_value\n        ):\n            invalid_types = [\n                type(item).__name__\n                for item in self.input_value\n                if not isinstance(item, Message | Data | DataFrame | str)\n            ]\n            msg = f"Expected Data or DataFrame or Message or str, got {invalid_types}"\n            raise TypeError(msg)\n        if not isinstance(\n            self.input_value,\n            Message | Data | DataFrame | str | list | Generator | type(None),\n        ):\n            type_name = type(self.input_value).__name__\n            msg = f"Expected Data or DataFrame or Message or str, Generator or None, got {type_name}"\n            raise TypeError(msg)\n\n    def convert_to_string(self) -> str | Generator[Any, None, None]:\n        """Convert input data to string with proper error handling."""\n        self._validate_input()\n        clean_data: bool = getattr(self, "clean_data", False)\n        if isinstance(self.input_value, list):\n            return "\\n".join([safe_convert(item, clean_data=clean_data) for item in self.input_value])\n        if isinstance(self.input_value, Generator):\n            return self.input_value\n        return safe_convert(self.input_value, clean_data=clean_data)\n'

_LLM_CODE = 'from lfx.base.models.model import LCModelComponent\nfrom lfx.base.models.unified_models import (\n    get_language_model_options,\n    get_llm,\n    handle_model_input_update,\n)\nfrom lfx.base.models.watsonx_constants import IBM_WATSONX_URLS\nfrom lfx.components.models_and_agents.model_selection import apply_model_overrides\nfrom lfx.field_typing.constants import LanguageModel\nfrom lfx.field_typing.range_spec import RangeSpec\nfrom lfx.inputs.inputs import BoolInput, DropdownInput, StrInput\nfrom lfx.io import IntInput, MessageInput, ModelInput, MultilineInput, SecretStrInput, SliderInput\n\n\nclass LanguageModelComponent(LCModelComponent):\n    model_provider_policy_mode = "delegate"\n    display_name = "Language Model"\n    description = "Runs a language model given a specified provider."\n    documentation: str = "https://docs.langflow.org/components-models"\n    icon = "brain-circuit"\n    category = "models"\n\n    inputs = [\n        ModelInput(\n            name="model",\n            display_name="Language Model",\n            info="Select your model provider",\n            real_time_refresh=True,\n            required=True,\n        ),\n        StrInput(\n            name="model_name",\n            display_name="Model Name Override",\n            info=(\n                "Optional model name to use instead of the selected model. "\n                "Can be set from a global variable for runtime model selection."\n            ),\n            advanced=True,\n            load_from_db=False,\n        ),\n        StrInput(\n            name="provider",\n            display_name="Provider Override",\n            info=(\n                "Optional provider to use with Model Name Override. Leave blank to use the selected model\'s provider."\n            ),\n            advanced=True,\n            load_from_db=False,\n        ),\n        SecretStrInput(\n            name="api_key",\n            display_name="API Key",\n            info="Overrides global provider settings. Leave blank to use your pre-configured API Key.",\n            required=False,\n            show=True,\n            real_time_refresh=True,\n            advanced=True,\n        ),\n        DropdownInput(\n            name="base_url_ibm_watsonx",\n            display_name="watsonx API Endpoint",\n            info="The base URL of the API (IBM watsonx.ai only)",\n            options=IBM_WATSONX_URLS,\n            value=IBM_WATSONX_URLS[0],\n            combobox=True,\n            show=False,\n            real_time_refresh=True,\n        ),\n        StrInput(\n            name="project_id",\n            display_name="watsonx Project ID",\n            info="The project ID associated with the foundation model (IBM watsonx.ai only)",\n            show=False,\n            required=False,\n        ),\n        StrInput(\n            name="ollama_base_url",\n            display_name="Ollama API URL",\n            info="Endpoint of the Ollama API (Ollama only)",\n            show=False,\n            real_time_refresh=True,\n        ),\n        MessageInput(\n            name="input_value",\n            display_name="Input",\n            info="The input text to send to the model",\n        ),\n        MultilineInput(\n            name="system_message",\n            display_name="System Message",\n            info="A system message that helps set the behavior of the assistant",\n            advanced=False,\n        ),\n        BoolInput(\n            name="stream",\n            display_name="Stream",\n            info="Whether to stream the response",\n            value=False,\n            advanced=True,\n        ),\n        SliderInput(\n            name="temperature",\n            display_name="Temperature",\n            value=0.1,\n            info="Controls randomness in responses",\n            range_spec=RangeSpec(min=0, max=1, step=0.01),\n            advanced=True,\n        ),\n        IntInput(\n            name="max_tokens",\n            display_name="Max Tokens",\n            info="Maximum number of tokens to generate. Set to 0 for no explicit limit. Field name varies by provider.",\n            advanced=True,\n            range_spec=RangeSpec(min=0, max=128000, step=1, step_type="int"),\n        ),\n    ]\n\n    def build_model(self) -> LanguageModel:\n        model = apply_model_overrides(\n            self.model,\n            model_name=getattr(self, "model_name", None),\n            provider=getattr(self, "provider", None),\n            user_id=self.user_id,\n            get_options=get_language_model_options,\n        )\n        return get_llm(\n            model=model,\n            user_id=self.user_id,\n            api_key=self.api_key,\n            temperature=self.temperature,\n            stream=self.stream,\n            max_tokens=getattr(self, "max_tokens", None),\n            watsonx_url=getattr(self, "base_url_ibm_watsonx", None),\n            watsonx_project_id=getattr(self, "project_id", None),\n            ollama_base_url=getattr(self, "ollama_base_url", None),\n        )\n\n    def update_build_config(self, build_config: dict, field_value: str, field_name: str | None = None):\n        """Dynamically update build config with user-filtered model options."""\n        return handle_model_input_update(self, build_config, field_value, field_name)\n'

_PROMPT_CODE = 'from typing import Any\n\nfrom lfx.base.prompts.api_utils import process_prompt_template\nfrom lfx.custom.custom_component.component import Component\nfrom lfx.inputs.input_mixin import FieldTypes\nfrom lfx.inputs.inputs import DefaultPromptField\nfrom lfx.io import BoolInput, MessageTextInput, Output, PromptInput\nfrom lfx.log.logger import logger\nfrom lfx.schema.dotdict import dotdict\nfrom lfx.schema.message import Message\nfrom lfx.template.utils import update_template_values\nfrom lfx.utils.mustache_security import validate_mustache_template\n\n\nclass PromptComponent(Component):\n    display_name: str = "Prompt Template"\n    description: str = "Create a prompt template with dynamic variables."\n    documentation: str = "https://docs.langflow.org/components-prompts"\n    icon = "prompts"\n    trace_type = "prompt"\n    name = "Prompt Template"\n\n    inputs = [\n        PromptInput(name="template", display_name="Template"),\n        BoolInput(\n            name="use_double_brackets",\n            display_name="Use Double Brackets",\n            value=False,\n            advanced=True,\n            info="Use {{variable}} syntax instead of {variable}.",\n            real_time_refresh=True,\n        ),\n        MessageTextInput(\n            name="tool_placeholder",\n            display_name="Tool Placeholder",\n            tool_mode=True,\n            advanced=True,\n            show=False,\n            info="A placeholder input for tool mode.",\n        ),\n    ]\n\n    outputs = [\n        Output(display_name="Prompt", name="prompt", method="build_prompt"),\n    ]\n\n    def update_build_config(self, build_config: dotdict, field_value: Any, field_name: str | None = None) -> dotdict:\n        """Update the template field type based on the selected mode."""\n        if field_name == "use_double_brackets":\n            # Change the template field type based on mode\n            is_mustache = field_value is True\n            if is_mustache:\n                build_config["template"]["type"] = FieldTypes.MUSTACHE_PROMPT.value\n            else:\n                build_config["template"]["type"] = FieldTypes.PROMPT.value\n\n            # Re-process the template to update variables when mode changes\n            template_value = build_config.get("template", {}).get("value", "")\n            if template_value:\n                # Ensure custom_fields is properly initialized\n                if "custom_fields" not in build_config:\n                    build_config["custom_fields"] = {}\n\n                # Clean up fields from the OLD mode before processing with NEW mode\n                # This ensures we don\'t keep fields with wrong syntax even if validation fails\n                old_custom_fields = build_config["custom_fields"].get("template", [])\n                for old_field in list(old_custom_fields):\n                    # Remove the field from custom_fields and template\n                    if old_field in old_custom_fields:\n                        old_custom_fields.remove(old_field)\n                    build_config.pop(old_field, None)\n\n                # Try to process template with new mode to add new variables\n                # If validation fails, at least we cleaned up old fields\n                try:\n                    # Validate mustache templates for security\n                    if is_mustache:\n                        validate_mustache_template(template_value)\n\n                    # Re-process template with new mode to add new variables\n                    _ = process_prompt_template(\n                        template=template_value,\n                        name="template",\n                        custom_fields=build_config["custom_fields"],\n                        frontend_node_template=build_config,\n                        is_mustache=is_mustache,\n                    )\n                except ValueError as e:\n                    # If validation fails, we still updated the mode and cleaned old fields\n                    # User will see error when they try to save\n                    logger.debug("Template validation failed during mode switch", exc_info=e)\n        return build_config\n\n    async def build_prompt(self) -> Message:\n        use_double_brackets = self.use_double_brackets if hasattr(self, "use_double_brackets") else False\n        template_format = "mustache" if use_double_brackets else "f-string"\n        prompt = await Message.from_template_and_variables(template_format=template_format, **self._attributes)\n        self.status = prompt.text\n        return prompt\n\n    def _update_template(self, frontend_node: dict):\n        prompt_template = frontend_node["template"]["template"]["value"]\n        use_double_brackets = frontend_node["template"].get("use_double_brackets", {}).get("value", False)\n        is_mustache = use_double_brackets is True\n\n        try:\n            # Validate mustache templates for security\n            if is_mustache:\n                validate_mustache_template(prompt_template)\n\n            custom_fields = frontend_node["custom_fields"]\n            frontend_node_template = frontend_node["template"]\n            _ = process_prompt_template(\n                template=prompt_template,\n                name="template",\n                custom_fields=custom_fields,\n                frontend_node_template=frontend_node_template,\n                is_mustache=is_mustache,\n            )\n        except ValueError as e:\n            # If validation fails, don\'t add variables but allow component to be created\n            logger.debug("Template validation failed in _update_template", exc_info=e)\n        return frontend_node\n\n    async def update_frontend_node(self, new_frontend_node: dict, current_frontend_node: dict):\n        """This function is called after the code validation is done."""\n        frontend_node = await super().update_frontend_node(new_frontend_node, current_frontend_node)\n        template = frontend_node["template"]["template"]["value"]\n        use_double_brackets = frontend_node["template"].get("use_double_brackets", {}).get("value", False)\n        is_mustache = use_double_brackets is True\n\n        try:\n            # Validate mustache templates for security\n            if is_mustache:\n                validate_mustache_template(template)\n\n            # Kept it duplicated for backwards compatibility\n            _ = process_prompt_template(\n                template=template,\n                name="template",\n                custom_fields=frontend_node["custom_fields"],\n                frontend_node_template=frontend_node["template"],\n                is_mustache=is_mustache,\n            )\n        except ValueError as e:\n            # If validation fails, don\'t add variables but allow component to be updated\n            logger.debug("Template validation failed in update_frontend_node", exc_info=e)\n        # Now that template is updated, we need to grab any values that were set in the current_frontend_node\n        # and update the frontend_node with those values\n        update_template_values(new_template=frontend_node, previous_template=current_frontend_node["template"])\n        return frontend_node\n\n    def _get_fallback_input(self, **kwargs):\n        return DefaultPromptField(**kwargs)\n'

# END VENDORED COMPONENT CODE

_DEFAULT_MODEL_OPTIONS = [
    "gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    "gpt-4.5-preview", "gpt-4-turbo", "gpt-4-turbo-preview", "gpt-4",
    "gpt-3.5-turbo",
]


def emit_langflow(ir: AgentIR, out_dir: str | Path) -> Path:
    """把 AgentIR 写成 Langflow flow 目录,返回 out_dir。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_knowledge(ir, out)
    (out / "flow.json").write_text(
        json.dumps(_flow(ir), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "README.md").write_text(_readme(ir), encoding="utf-8")
    return out


# ---------- handle 字符串(œ 约定) ----------

def _handle_json(d: Dict[str, Any]) -> str:
    """官方 handle 字符串:json.dumps(默认带空格分隔)后 '"'→'œ'。"""
    return json.dumps(d, ensure_ascii=False).replace('"', _OE)


def _handle_json_compact(d: Dict[str, Any]) -> str:
    """边 id 用的紧凑形态(分隔符无空格,同样替换引号)。"""
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace('"', _OE)


def _src_handle(data_type: str, node_id: str, name: str, output_types: List[str]) -> Dict[str, Any]:
    return {"dataType": data_type, "id": node_id, "name": name, "output_types": list(output_types)}


def _tgt_handle(field_name: str, node_id: str, input_types: List[str], ftype: str) -> Dict[str, Any]:
    return {"fieldName": field_name, "id": node_id, "inputTypes": list(input_types), "type": ftype}


def _edge(src_id: str, src_handle: Dict[str, Any], tgt_id: str, tgt_handle: Dict[str, Any]) -> dict:
    """官方导出形态:handle 双写(字符串 + data 内结构化对象)。"""
    return {
        "animated": False,
        "className": "",
        "data": {"sourceHandle": src_handle, "targetHandle": tgt_handle},
        "id": (
            f"reactflow__edge-{src_id}{_handle_json_compact(src_handle)}"
            f"-{tgt_id}{_handle_json_compact(tgt_handle)}"
        ),
        "selected": False,
        "source": src_id,
        "sourceHandle": _handle_json(src_handle),
        "target": tgt_id,
        "targetHandle": _handle_json(tgt_handle),
    }


# ---------- 节点组装 ----------

def _rand_suffix(n: int = 5) -> str:
    """官方节点 id 后缀:{Type}-{5位随机字母数字}。"""
    return "".join(random.choices(_SUFFIX_CHARS, k=n))


def _field(name: str, display_name: str, ftype: str, value: Any, **extra: Any) -> Dict[str, Any]:
    """输入字段 dict:name/display_name/type/value/show/advanced/input_types/list 至少齐备。

    其余官方键(options/_input_type/multiline/fileTypes/...)通过 kwargs 原样并入。
    """
    advanced = bool(extra.pop("advanced", False))
    show = bool(extra.pop("show", True))
    required = bool(extra.pop("required", False))
    field: Dict[str, Any] = {
        "advanced": advanced,
        "display_name": display_name,
        "dynamic": False,
        "info": extra.pop("info", ""),
        "input_types": list(extra.pop("input_types", [])),
        "list": bool(extra.pop("list_", False)),
        "load_from_db": bool(extra.pop("load_from_db", False)),
        "name": name,
        "placeholder": "",
        "required": required,
        "show": show,
        "title_case": False,
        "trace_as_input": bool(extra.pop("trace_as_input", False)),
        "trace_as_metadata": bool(extra.pop("trace_as_metadata", False)),
        "type": ftype,
        "value": value,
    }
    field.update(extra)
    return field


def _output(name: str, display_name: str, method: str, types: List[str]) -> Dict[str, Any]:
    return {
        "allows_loop": False,
        "cache": True,
        "display_name": display_name,
        "group_outputs": False,
        "method": method,
        "name": name,
        "selected": types[0],
        "tool_mode": True,
        "types": list(types),
        "value": "__UNDEFINED__",
    }


def _code_field(source: str) -> Dict[str, Any]:
    """官方 code 字段形态:引擎 instantiate_class 会 params.pop("code") 后
    eval_custom_component_code(value) 实例化组件类,缺此字段真实引擎直接
    KeyError('code')(官方导出一律携带,键集对齐 Basic Prompting starter)。
    """
    return {
        "advanced": True,
        "api_editable": False,
        "dynamic": True,
        "fileTypes": [],
        "file_path": "",
        "info": "",
        "list": False,
        "load_from_db": False,
        "multiline": True,
        "name": "code",
        "password": False,
        "placeholder": "",
        "required": True,
        "show": True,
        "title_case": False,
        "type": "code",
        "value": source,
    }


def _make_node(
    node_type: str,
    display_name: str,
    description: str,
    position: Dict[str, float],
    fields: List[Dict[str, Any]],
    base_classes: List[str],
    field_order: List[str],
    outputs: List[Dict[str, Any]],
    icon: str,
    custom_fields: Optional[Dict[str, List[str]]] = None,
    selected_output: Optional[str] = None,
    code_source: str = "",
) -> Dict[str, Any]:
    """构造 reactflow 节点:外层 type="genericNode",data.type=PascalCase 类名。

    id = "{node_type}-{5位随机}",data.id 与之一致;template._type="Component"。
    schema 对齐(官方 v1.9 starter fixture 实测):
      - data.display_name / data.description:官方导出把节点元数据双写到 data 层,
        前端画布节点标题显示用(运行时非必需,但对齐官方导出形态);
      - data.node.custom_fields:官方四个节点一致携带(无动态字段时为 {}),
        动态输入口注册表(仅 Prompt 用到非空值);
      - template.code:组件源码,真实引擎实例化必需(见 _code_field);
        field_order 不含 code,与官方一致(引擎遍历 template 全键,不看 field_order)。
    """
    node_id = f"{node_type}-{_rand_suffix()}"
    template: Dict[str, Any] = {"_type": "Component"}
    if code_source:
        template["code"] = _code_field(code_source)
    template.update({f["name"]: f for f in fields})
    data_node: Dict[str, Any] = {
        "base_classes": list(base_classes),
        "custom_fields": custom_fields if custom_fields is not None else {},
        "description": description,
        "display_name": display_name,
        "field_order": list(field_order),
        "frozen": False,
        "icon": icon,
        "outputs": outputs,
        "template": template,
    }
    data: Dict[str, Any] = {
        "description": description,
        "display_name": display_name,
        "id": node_id,
        "node": data_node,
        "type": node_type,
    }
    if selected_output:
        data["selected_output"] = selected_output
    return {
        "data": data,
        "dragging": False,
        "id": node_id,
        "position": dict(position),
        "positionAbsolute": dict(position),
        "selected": False,
        "type": "genericNode",
        "width": 320,
    }


def _chat_input_node(position: Dict[str, float]) -> Dict[str, Any]:
    fields = [
        _field(
            "input_value", "Input Text", "str", "",
            info="Message to be passed as input.", multiline=True,
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "should_store_message", "Store Messages", "bool", True,
            advanced=True, info="Store the message in the history.",
            trace_as_metadata=True, _input_type="BoolInput",
        ),
        _field(
            "sender", "Sender Type", "str", "User",
            advanced=True, info="Type of sender.",
            options=["Machine", "User"], trace_as_metadata=True,
        ),
        _field(
            "sender_name", "Sender Name", "str", "User",
            advanced=True, info="Name of the sender.", input_types=["Message"],
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "session_id", "Session ID", "str", "",
            advanced=True,
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            input_types=["Message"], trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "files", "Files", "file", [],
            advanced=True, info="Files to be sent with the message.",
            list_=True, fileTypes=[], file_path="", temp_file=True,
            trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "ChatInput", "Chat Input", "Get chat inputs from the Playground.", position,
        fields,
        ["Message"],
        ["input_value", "should_store_message", "sender", "sender_name", "session_id", "files"],
        [_output("message", "Chat Message", "message_response", ["Message"])],
        icon="ChatInput",
        custom_fields={},
        selected_output="message",
        code_source=_CHATINPUT_CODE,
    )


def _prompt_node(ir: AgentIR, position: Dict[str, float]) -> Dict[str, Any]:
    """Prompt 组件:提示词全文嵌 template.template.value(type="prompt")。

    custom_fields 注册动态变量 message,使 ChatInput 的输出可接到该输入口。
    """
    fields = [
        _field(
            "template", "Template", "prompt", ir.system_prompt,
            _input_type="PromptInput", tool_mode=False, trace_as_input=True,
        ),
        # 动态字段:模板变量 {message}(形状对齐官方 starter 的动态字段)
        _field(
            "message", "message", "str", "",
            input_types=["Message", "Text"], multiline=True, field_type="str",
            fileTypes=[], file_path="",
        ),
        _field(
            "tool_placeholder", "Tool Placeholder", "str", "",
            advanced=True, info="A placeholder input for tool mode.",
            input_types=["Message"], _input_type="MessageTextInput",
            tool_mode=True, trace_as_input=True, trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "Prompt", "Prompt", "Create a prompt template with dynamic variables.", position,
        fields,
        ["Message"],
        ["template", "tool_placeholder"],
        [_output("prompt", "Prompt", "build_prompt", ["Message"])],
        icon="prompts",
        custom_fields={"template": ["message"]},
        selected_output="prompt",
        code_source=_PROMPT_CODE,
    )


def _llm_node(ir: AgentIR, position: Dict[str, float]) -> Dict[str, Any]:
    model = str(ir.metadata.get("model") or "gpt-4.1")
    fields = [
        _field(
            "provider", "Model Provider", "str", "OpenAI",
            info="Select the model provider",
            options=["OpenAI", "Anthropic", "Google"],
            _input_type="DropdownInput", combobox=False, real_time_refresh=True,
            trace_as_metadata=True,
        ),
        _field(
            "model_name", "Model Name", "str", model,
            info="Select the model to use",
            options=list(_DEFAULT_MODEL_OPTIONS),
            _input_type="DropdownInput", combobox=False,
            trace_as_metadata=True,
        ),
        _field(
            "api_key", "OpenAI API Key", "str", "OPENAI_API_KEY",
            info="Model Provider API key", load_from_db=True, password=True,
            real_time_refresh=True, _input_type="SecretStrInput",
        ),
        _field(
            "input_value", "Input", "str", "",
            info="The input text to send to the model", input_types=["Message"],
            _input_type="MessageInput", trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "system_message", "System Message", "str", "",
            info="A system message that helps set the behavior of the assistant",
            input_types=["Message"], multiline=True, _input_type="MultilineInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "stream", "Stream", "bool", False,
            advanced=True, info="Whether to stream the response",
            _input_type="BoolInput", trace_as_metadata=True,
        ),
        _field(
            "temperature", "Temperature", "slider", 0.1,
            advanced=True, info="Controls randomness in responses",
            _input_type="SliderInput",
            range_spec={"min": 0, "max": 1, "step": 0.01, "step_type": "float"},
        ),
    ]
    return _make_node(
        "LanguageModelComponent", "Language Model",
        "Generates text using a Language Model.", position,
        fields,
        ["LanguageModel", "Message"],
        ["provider", "model_name", "api_key", "input_value",
         "system_message", "stream", "temperature"],
        [
            _output("text_output", "Model Response", "text_response", ["Message"]),
            _output("model_output", "Language Model", "build_model", ["LanguageModel"]),
        ],
        icon="LangChain",
        selected_output="text_output",
        code_source=_LLM_CODE,
    )


def _chat_output_node(position: Dict[str, float]) -> Dict[str, Any]:
    fields = [
        _field(
            "input_value", "Inputs", "str", "",
            info="Message to be passed as output.", required=True,
            input_types=["Data", "DataFrame", "Message"],
            _input_type="MessageInput", trace_as_input=True,
        ),
        _field(
            "should_store_message", "Store Messages", "bool", True,
            advanced=True, info="Store the message in the history.",
            _input_type="BoolInput", trace_as_metadata=True,
        ),
        _field(
            "sender", "Sender Type", "str", "Machine",
            advanced=True, info="Type of sender.",
            options=["Machine", "User"], _input_type="DropdownInput",
            combobox=False, trace_as_metadata=True,
        ),
        _field(
            "sender_name", "Sender Name", "str", "AI",
            advanced=True, info="Name of the sender.", input_types=["Message"],
            _input_type="MessageTextInput", trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "session_id", "Session ID", "str", "",
            advanced=True,
            info="The session ID of the chat. If empty, the current session ID parameter will be used.",
            input_types=["Message"], _input_type="MessageTextInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
        _field(
            "data_template", "Data Template", "str", "{text}",
            advanced=True,
            info="Template to convert Data to Text. If left empty, it will be dynamically set to the Data's text key.",
            input_types=["Message"], _input_type="MessageTextInput",
            trace_as_input=True, trace_as_metadata=True,
        ),
    ]
    return _make_node(
        "ChatOutput", "Chat Output", "Display chat messages from the Playground.", position,
        fields,
        ["Message"],
        ["input_value", "should_store_message", "sender", "sender_name",
         "session_id", "data_template"],
        [_output("message", "Output Message", "message_response", ["Message"])],
        icon="ChatOutput",
        code_source=_CHATOUTPUT_CODE,
    )


# ---------- flow.json 组装 ----------

def _flow(ir: AgentIR) -> dict:
    nodes, edges = _graph(ir)
    return {
        "id": str(uuid.uuid4()),
        "name": ir.title(),
        "description": ir.description or f"Flow generated from skill '{ir.name}'.",
        "endpoint_name": None,
        "is_component": False,
        "tags": ["agents"],
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        },
    }


def _graph(ir: AgentIR) -> Tuple[List[dict], List[dict]]:
    """四节点链 + 三条边;handle 内 id 与节点 id 一致。"""
    nodes = [
        _chat_input_node({"x": 0, "y": 300}),
        _prompt_node(ir, {"x": 384, "y": 300}),
        _llm_node(ir, {"x": 768, "y": 300}),
        _chat_output_node({"x": 1152, "y": 300}),
    ]
    ids = {n["data"]["type"]: n["id"] for n in nodes}
    chat_in, prompt, llm, chat_out = (
        ids["ChatInput"], ids["Prompt"], ids["LanguageModelComponent"], ids["ChatOutput"]
    )
    edges = [
        _edge(
            chat_in,
            _src_handle("ChatInput", chat_in, "message", ["Message"]),
            prompt,
            _tgt_handle("message", prompt, ["Message", "Text"], "str"),
        ),
        _edge(
            prompt,
            _src_handle("Prompt", prompt, "prompt", ["Message"]),
            llm,
            _tgt_handle("system_message", llm, ["Message"], "str"),
        ),
        _edge(
            llm,
            _src_handle("LanguageModelComponent", llm, "text_output", ["Message"]),
            chat_out,
            _tgt_handle("input_value", chat_out, ["Data", "DataFrame", "Message"], "str"),
        ),
    ]
    return nodes, edges


# ---------- 知识文档拷贝 ----------

def _safe_filename(filename: str) -> Optional[str]:
    """过滤非法路径名:为空、. / ..、含 / 或 \\ 或 .. 的一律拒绝。"""
    name = (filename or "").strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name or ".." in name:
        return None
    return name


def _write_knowledge(ir: AgentIR, out: Path) -> List[str]:
    written: List[str] = []
    for doc in ir.knowledge:
        name = _safe_filename(doc.filename)
        if name is None:
            continue
        kdir = out / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / name).write_text(doc.content or "", encoding="utf-8")
        written.append(name)
    return written


# ---------- README ----------

def _readme(ir: AgentIR) -> str:
    docs = [d for d in ir.knowledge if _safe_filename(d.filename)]
    listing = "\n".join(
        f"- knowledge/{_safe_filename(d.filename)} —— {d.title or d.filename}" for d in docs
    ) or "- (本 agent 未附带知识文档)"
    kb_name = (ir.name or "skill").replace("-", "_")
    return f"""# {ir.title()} —— Langflow Flow(由 agentskills-bridge 生成)

## 文件

- flow.json —— Langflow 导出格式(可导入的完整 flow)
- knowledge/ —— 参考知识文档(flow.json 不包含其内容):
{listing}

## 导入方式(UI)

- 打开 Langflow -> 左上角「+ 新建 Flow」-> 「Import JSON」(或直接把 flow.json 拖入画布),即可载入本 flow。
- 导入后在 Language Model 组件里确认 `api_key` 已选中全局变量 `OPENAI_API_KEY`(Settings -> Environment Variables 中配置),点右上角 Playground 即可对话。

## Flow 结构

ChatInput --message--> Prompt(system_prompt 内嵌源 agent 的完整系统提示词)
  --prompt(system_message)--> LanguageModelComponent(gpt-4.1 / provider=OpenAI)
  --text_output--> ChatOutput

注意:Prompt 输出接到 LanguageModelComponent 时,targetHandle 字段是 `system_message`
(接 Agent 组件才是 `system_prompt`);handle 字符串使用 Langflow 的 `œ` 引号约定。

## 知识文件挂载(Knowledge Bases 两步上传)

knowledge/ 不会随 flow.json 导入。Langflow 1.12 起 Knowledge Base 与 flow 解耦,
正确姿势是先经 REST API 上传,再在 flow 里引用:

1. 建知识库(名字最短 3 字符,空格会转下划线):

    curl -X POST http://localhost:7860/api/v1/knowledge_bases \\
      -H "Content-Type: application/json" \\
      -d {{"name": "{kb_name}"}}

2. multipart 上传知识文件(可多个;chunk_size 默认 1000,chunk_overlap 默认 200):

    curl -X POST http://localhost:7860/api/v1/knowledge_bases/{kb_name}/ingest \\
      -F "files=@knowledge/guide.md" \\
      -F "files=@knowledge/other.md"

上传完成后,在 flow 画布里添加 `Knowledge` 组件(选刚建的 KB、mode=Retrieve),
把其输出接到 Prompt 或 Agent 的输入口,模型回答即可引用知识内容。
若只是临时问答,也可退一步用 ChatInput 的 `files` 字段直接挂 txt/md/pdf 等文件。
"""
