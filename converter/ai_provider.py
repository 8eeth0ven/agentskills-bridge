"""Small, real HTTP model client used by semantic migration.

Credentials come only from explicit process environment variables. Requests and
raw responses are never persisted or retained as telemetry. A successful call
returns a locally validated JSON object; refusals and truncated output fail.
"""
from __future__ import annotations

import json
import http.client
import math
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class ModelError(ValueError):
    """A model/configuration error safe to display without provider payloads."""

    def __init__(self, message: str, *, code: str = "model_error",
                 retryable: bool = False, purpose: str = "generate"):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.purpose = purpose


class ModelOutputError(ModelError):
    """Output cannot be accepted; the caller may request a repaired response."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward Authorization or x-api-key to an HTTP redirect destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _json_object(text: str, purpose: str) -> dict:
    text = text.strip()
    fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text,
                         flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()

    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def nonfinite(_):
        raise ValueError("nonfinite JSON number")

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError, RecursionError):
        raise ModelOutputError("Model did not return one complete JSON object; request corrected JSON.",
                               code="invalid_json", purpose=purpose) from None
    if not isinstance(result, dict):
        raise ModelOutputError("Model output must be a JSON object.", code="invalid_json", purpose=purpose)
    return result


def _validate(value: Any, schema: dict | bool, root: dict, path: str = "$", depth: int = 0) -> None:
    """Validate the JSON Schema subset used for migration response contracts.

    Assertion keywords outside this explicit subset are rejected, not silently
    ignored. Annotation keywords do not change validation semantics.
    """
    if depth > 64:
        raise ValueError(f"{path}: schema recursion limit exceeded")
    if schema is True:
        return
    if schema is False:
        raise ValueError(f"{path}: value is forbidden")
    if not isinstance(schema, dict):
        raise ValueError("schema must be an object or boolean")
    supported = {
        "$schema", "$id", "$ref", "$defs", "definitions", "$comment",
        "title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly", "format",
        "type", "enum", "const", "anyOf", "oneOf", "allOf", "not",
        "properties", "required", "additionalProperties", "minProperties", "maxProperties",
        "items", "prefixItems", "minItems", "maxItems", "uniqueItems",
        "minLength", "maxLength", "pattern", "minimum", "maximum",
        "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    }
    if set(schema) - supported:
        raise ValueError("response schema contains an unsupported assertion keyword")
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise ValueError("only local JSON Schema references are supported")
        target = root
        try:
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise ValueError("unresolved JSON Schema reference") from None
        _validate(value, target, root, path, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if key not in schema:
            continue
        matches = 0
        for choice in schema[key]:
            try:
                _validate(value, choice, root, path, depth + 1)
                matches += 1
            except ValueError:
                pass
        expected = {"anyOf": matches >= 1, "oneOf": matches == 1,
                    "allOf": matches == len(schema[key])}[key]
        if not expected:
            raise ValueError(f"{path}: {key} constraint failed")
    if "not" in schema:
        try:
            _validate(value, schema["not"], root, path, depth + 1)
        except ValueError:
            pass
        else:
            raise ValueError(f"{path}: forbidden schema matched")
    types = {"object": isinstance(value, dict), "array": isinstance(value, list),
             "string": isinstance(value, str), "boolean": type(value) is bool,
             "integer": type(value) is int, "number": type(value) in (int, float),
             "null": value is None}
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(types.get(item, False) for item in allowed):
            raise ValueError(f"{path}: JSON type mismatch")
    def equal(left, right):
        if type(left) is bool or type(right) is bool:
            return type(left) is type(right) and left == right
        return left == right
    if "const" in schema and not equal(value, schema["const"]):
        raise ValueError(f"{path}: const constraint failed")
    if "enum" in schema and not any(equal(value, item) for item in schema["enum"]):
        raise ValueError(f"{path}: enum constraint failed")
    if isinstance(value, dict):
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ValueError(f"{path}: required properties missing: " + ", ".join(missing))
        for keyword, comparison in (("minProperties", len(value) >= schema.get("minProperties", 0)),
                                    ("maxProperties", len(value) <= schema.get("maxProperties", math.inf))):
            if not comparison:
                raise ValueError(f"{path}: {keyword} constraint failed")
        props = schema.get("properties", {})
        for key, item in value.items():
            # Known schema field names are safe diagnostics; unexpected
            # model-controlled names never enter errors or repair prompts.
            child = props.get(key, schema.get("additionalProperties", True))
            _validate(item, child, root, path + ("." + key if key in props else ".additional"), depth + 1)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError(f"{path}: array length constraint failed")
        prefix = schema.get("prefixItems", [])
        for index, item in enumerate(value):
            child = prefix[index] if index < len(prefix) else schema.get("items", True)
            _validate(item, child, root, path + ".item", depth + 1)
        if schema.get("uniqueItems"):
            serialized = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(set(serialized)) != len(serialized):
                raise ValueError(f"{path}: array items must be unique")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            raise ValueError(f"{path}: string length constraint failed")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValueError(f"{path}: string pattern constraint failed")
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            raise ValueError(f"{path}: number must be finite")
        for key, comparison in (("minimum", value >= schema.get("minimum", -math.inf)),
                                ("maximum", value <= schema.get("maximum", math.inf)),
                                ("exclusiveMinimum", value > schema.get("exclusiveMinimum", -math.inf)),
                                ("exclusiveMaximum", value < schema.get("exclusiveMaximum", math.inf))):
            if not comparison:
                raise ValueError(f"{path}: {key} constraint failed")
        if "multipleOf" in schema:
            divisor = schema["multipleOf"]
            if divisor <= 0 or not math.isclose(value / divisor, round(value / divisor), rel_tol=1e-10):
                raise ValueError(f"{path}: multipleOf constraint failed")


class ModelClient:
    """HTTP transport for Anthropic Messages, Responses, and compatible chat.

    No model is silently selected: pass model or set MIGRATION_MODEL / the
    chosen provider's MODEL environment variable. Explicit base URLs are used
    only for this instance; credentials are never loaded from local files.
    """

    def __init__(self, provider: str = "auto", model: str | None = None,
                 base_url: str | None = None, api_key_env: str | None = None,
                 timeout: float = 120, max_output_tokens: int = 16000, retries: int = 2,
                 thinking: str | None = None):
        if provider == "auto":
            explicit_key = os.environ.get(api_key_env, "") if api_key_env else ""
            if explicit_key:
                if "ANTHROPIC" in api_key_env.upper():
                    provider = "anthropic"
                elif "OPENAI" in api_key_env.upper():
                    provider = "openai"
                else:
                    raise ModelError("Specify --provider when using a custom credential environment variable.", code="invalid_configuration")
            elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
                provider = "anthropic"
            elif os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            else:
                raise ModelError("Set a provider credential environment variable before AI migration.",
                                 code="missing_credentials")
        if provider not in ("anthropic", "openai", "openai-chat"):
            raise ModelError("Unsupported model provider; choose anthropic, openai or openai-chat.",
                             code="invalid_configuration")
        self.provider = provider
        if thinking not in (None, "disabled") or (thinking is not None and provider != "anthropic"):
            raise ModelError("Explicit thinking control is available only as disabled for Anthropic Messages.", code="invalid_configuration")
        self.thinking = thinking
        prefix = "ANTHROPIC" if provider == "anthropic" else "OPENAI"
        self.model = model or os.environ.get("MIGRATION_MODEL") or os.environ.get(prefix + "_MODEL")
        if not self.model or not self.model.strip():
            raise ModelError("Specify a model explicitly or set MIGRATION_MODEL / provider MODEL.",
                             code="missing_model")
        if api_key_env:
            credential = os.environ.get(api_key_env, "")
            bearer = api_key_env.upper().endswith("AUTH_TOKEN")
        elif provider == "anthropic":
            credential = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
            bearer = not bool(os.environ.get("ANTHROPIC_API_KEY"))
        else:
            credential, bearer = os.environ.get("OPENAI_API_KEY", ""), True
        if not credential:
            raise ModelError("The selected provider credential environment variable is empty.",
                             code="missing_credentials")
        self._credential = credential
        base = (base_url or os.environ.get(prefix + "_BASE_URL") or
                ("https://api.anthropic.com" if provider == "anthropic" else "https://api.openai.com/v1")).rstrip("/")
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("Provider base URL must be an HTTP(S) endpoint without embedded credentials, query or fragment.",
                             code="invalid_configuration")
        if timeout <= 0 or type(max_output_tokens) is not int or max_output_tokens <= 0 or type(retries) is not int or retries < 0:
            raise ModelError("Timeout, output tokens and retry count must be valid positive limits.",
                             code="invalid_configuration")
        suffix = "/messages" if provider == "anthropic" else ("/responses" if provider == "openai" else "/chat/completions")
        if base.endswith(suffix):
            self._url = base
        else:
            if provider == "anthropic":
                version = "" if parsed.path.rstrip("/").endswith("/v1") else "/v1"
            else:
                # Compatible providers may deliberately version their base as
                # /api/v4, /openai or another prefix. Preserve explicit paths.
                version = "/v1" if not parsed.path.rstrip("/") else ""
            self._url = base + version + suffix
        self.timeout, self.max_output_tokens, self.retries = timeout, max_output_tokens, retries
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if provider == "anthropic":
            self._headers["anthropic-version"] = "2023-06-01"
            self._headers["Authorization" if bearer else "x-api-key"] = ("Bearer " if bearer else "") + credential
        else:
            self._headers["Authorization"] = "Bearer " + credential
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(self, payload: dict, purpose: str) -> dict:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        for attempt in range(self.retries + 1):
            self.calls += 1
            request = urllib.request.Request(self._url, data=body, headers=self._headers, method="POST")
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    raw = response.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ModelOutputError("Provider response exceeded the transport limit.", code="response_too_large", purpose=purpose)
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("invalid provider envelope")
                return result
            except urllib.error.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                # Provider bodies can echo prompts, credentials or local paths.
                # They deliberately never appear in the displayed error.
                exc.close()
                error = ModelError(f"Model provider returned HTTP {exc.code}.",
                                   code=f"http_{exc.code}", retryable=retryable, purpose=purpose)
            except ModelOutputError:
                raise
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                retryable = isinstance(reason, (TimeoutError, socket.timeout, ConnectionError, OSError,
                                                http.client.IncompleteRead, http.client.RemoteDisconnected))
                if isinstance(reason, (ssl.SSLCertVerificationError, ssl.CertificateError)):
                    retryable = False
                error = ModelError("Model provider connection failed or timed out.",
                                   code="connection_error", retryable=retryable, purpose=purpose)
            except (ValueError, UnicodeError):
                raise ModelOutputError("Provider returned an invalid JSON envelope.", code="invalid_envelope", purpose=purpose) from None
            if not error.retryable or attempt == self.retries:
                raise error from None
            time.sleep(min(2 ** attempt, 4))
        raise ModelError("Model provider retry limit exceeded.", purpose=purpose)

    def complete(self, system: str, user: str, schema: dict | None = None,
                 purpose: str = "generate") -> dict:
        """Make an actual model request and return one accepted JSON object."""
        if not isinstance(system, str) or not isinstance(user, str):
            raise ModelError("System and user prompts must be text.", code="invalid_prompt", purpose=purpose)
        instruction = "\nReturn exactly one JSON object, without prose or markdown fences."
        if schema is not None:
            instruction += "\nThe JSON object must match this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False, allow_nan=False)
        if self.provider == "anthropic":
            payload = {"model": self.model, "max_tokens": self.max_output_tokens,
                       "system": system + instruction, "messages": [{"role": "user", "content": user}]}
            if schema is not None:
                # A forced data-return tool avoids asking the model to hand
                # escape whole Python modules inside free-form JSON text.
                # This tool is never executed: its input is the typed result.
                payload["tools"] = [{"name": "migration_output", "description": "Return the requested structured migration data.", "input_schema": schema}]
                payload["tool_choice"] = {"type": "tool", "name": "migration_output"}
            if self.thinking is not None:
                payload["thinking"] = {"type": self.thinking}
        elif self.provider == "openai":
            payload = {"model": self.model, "instructions": system + instruction, "input": user,
                       "max_output_tokens": self.max_output_tokens, "store": False}
            if schema is not None:
                payload["text"] = {"format": {"type": "json_schema", "name": "migration_output", "strict": True, "schema": schema}}
        else:
            payload = {"model": self.model, "messages": [{"role": "system", "content": system + instruction},
                                                         {"role": "user", "content": user}],
                       "max_tokens": self.max_output_tokens,
                       "response_format": {"type": "json_object"}}
        response = self._request(payload, purpose)
        usage = response.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
        if self.provider == "anthropic" and type(input_tokens) is int:
            input_tokens += sum(usage.get(key, 0) for key in ("cache_creation_input_tokens", "cache_read_input_tokens")
                                if type(usage.get(key, 0)) is int)
        self.usage["input_tokens"] += input_tokens if type(input_tokens) is int else 0
        self.usage["output_tokens"] += output_tokens if type(output_tokens) is int else 0
        self.usage["total_tokens"] = self.usage["input_tokens"] + self.usage["output_tokens"]
        structured = None
        if self.provider == "anthropic":
            stop = response.get("stop_reason")
            if stop == "max_tokens":
                raise ModelOutputError("Model output was truncated; raise the output token limit or reduce the requested changes.", code="truncated_output", purpose=purpose)
            if stop not in ("end_turn", "stop_sequence", "tool_use"):
                raise ModelOutputError("Model did not produce a completed JSON answer.", code="refusal_or_incomplete", purpose=purpose)
            content = response.get("content")
            if not isinstance(content, list):
                raise ModelOutputError("Provider response has no text content.", code="invalid_envelope", purpose=purpose)
            if stop == "tool_use":
                returned = [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]
                if schema is None or len(returned) != 1 or returned[0].get("name") != "migration_output" or not isinstance(returned[0].get("input"), dict):
                    raise ModelOutputError("Provider returned an unexpected data tool call.", code="invalid_envelope", purpose=purpose)
                structured = returned[0]["input"]
            text_blocks = [block.get("text") for block in content if isinstance(block, dict) and block.get("type") == "text"]
            if not all(isinstance(block, str) for block in text_blocks):
                raise ModelOutputError("Provider response has malformed text content.", code="invalid_envelope", purpose=purpose)
            text = "".join(text_blocks)
        elif self.provider == "openai":
            if response.get("status") != "completed":
                raise ModelOutputError("Model response is incomplete or failed.", code="truncated_or_incomplete", purpose=purpose)
            output = response.get("output")
            if not isinstance(output, list):
                raise ModelOutputError("Provider response has no output messages.", code="invalid_envelope", purpose=purpose)
            blocks = [block for item in output if isinstance(item, dict) and isinstance(item.get("content"), list)
                      for block in item["content"] if isinstance(block, dict)]
            if any(block.get("type") == "refusal" for block in blocks):
                raise ModelOutputError("Model refused this generation request.", code="refusal", purpose=purpose)
            text_blocks = [block.get("text") for block in blocks if block.get("type") == "output_text"]
            if not all(isinstance(block, str) for block in text_blocks):
                raise ModelOutputError("Provider response has malformed output text.", code="invalid_envelope", purpose=purpose)
            text = "".join(text_blocks)
        else:
            choices = response.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ModelOutputError("Provider response has no single completion.", code="invalid_envelope", purpose=purpose)
            choice = choices[0]
            message = choice.get("message") or {}
            if not isinstance(message, dict):
                raise ModelOutputError("Provider response has a malformed completion message.", code="invalid_envelope", purpose=purpose)
            if choice.get("finish_reason") != "stop" or message.get("refusal"):
                raise ModelOutputError("Model completion was refused or truncated.", code="refusal_or_incomplete", purpose=purpose)
            text = message.get("content")
        if not isinstance(text, str):
            raise ModelOutputError("Model response did not contain JSON text.", code="invalid_envelope", purpose=purpose)
        result = structured if structured is not None else _json_object(text, purpose)
        if schema is not None:
            try:
                _validate(result, schema, schema)
            except (ValueError, TypeError, KeyError, RecursionError) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                error = ModelOutputError("Model JSON does not satisfy the response schema: " + detail[:500], code="schema_mismatch", purpose=purpose)
                # Transient repair input, never included in the error string,
                # telemetry or a persisted request/response log.
                error.candidate = result
                raise error from None
        return result
