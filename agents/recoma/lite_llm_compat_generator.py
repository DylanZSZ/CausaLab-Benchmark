import json
import logging
import os
import time
import fcntl
from typing import Any, Optional

import litellm
from diskcache import Cache
from litellm import completion, completion_cost
from openai import OpenAI
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_random_exponential

from recoma.models.core.generator import GenerationOutputs, LMGenerator

logger = logging.getLogger(__name__)

litellm.drop_params = True

cache = Cache(os.path.expanduser("~/.cache/litellmcalls"))

_OPENAI_STRICT_COMPAT_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_OPENAI_CHAT_CLIENT_PREFIXES = _OPENAI_STRICT_COMPAT_PREFIXES + ("qwen", "qwen/")


def _response_has_nonempty_content(response: Any) -> bool:
    try:
        for choice in response["choices"]:
            content = choice["message"].get("content")
            if isinstance(content, str) and content.strip():
                return True
    except Exception:
        return True
    return False


def _normalize_openai_model_name(model: str) -> Optional[str]:
    if model.startswith("openai/"):
        return model.split("/", 1)[1]
    return model


def _requires_openai_chat_compat(model: str) -> bool:
    normalized_model = _normalize_openai_model_name(model)
    if normalized_model is None:
        return False
    return normalized_model.startswith(_OPENAI_STRICT_COMPAT_PREFIXES)


def _uses_openai_chat_client(model: str) -> bool:
    normalized_model = _normalize_openai_model_name(model)
    if normalized_model is None:
        return False
    return normalized_model.lower().startswith(_OPENAI_CHAT_CLIENT_PREFIXES)


def _sanitize_response_format(response_format: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not response_format:
        return None
    if response_format.get("type") == "text":
        return None
    return response_format


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "to_dict"):
        return response.to_dict()
    return response


def _get_usage_value(response: Any, key: str) -> Optional[int]:
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(key)
    return getattr(usage, key, None)


def _prepare_openai_request(
    model: str,
    messages: list[dict[str, Any]],
    generator_args: dict[str, Any],
    reasoning_effort: Optional[str] = None,
    extra_body: Optional[dict[str, Any]] = None,
    qwen_enable_thinking: Optional[bool] = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": _normalize_openai_model_name(model) or model,
        "messages": messages,
    }

    strict_compat_model = _requires_openai_chat_compat(model)
    passthrough_keys = ["seed"]
    for key in passthrough_keys:
        value = generator_args.get(key)
        if value is not None:
            request[key] = value

    n = generator_args.get("n")
    if not strict_compat_model and n not in (None, 1):
        request["n"] = n

    if not strict_compat_model:
        optional_passthrough_keys = [
            "temperature",
            "top_p",
            "stop",
            "logprobs",
            "top_logprobs",
            "frequency_penalty",
            "presence_penalty",
        ]
        for key in optional_passthrough_keys:
            value = generator_args.get(key)
            if value is not None:
                request[key] = value

    response_format = _sanitize_response_format(generator_args.get("response_format"))
    if response_format is not None:
        request["response_format"] = response_format

    merged_extra_body = dict(extra_body or {})
    max_tokens = generator_args.get("max_tokens")
    if max_tokens is not None and strict_compat_model:
        merged_extra_body["max_completion_tokens"] = max_tokens
    elif max_tokens is not None:
        request["max_tokens"] = max_tokens
    if reasoning_effort:
        merged_extra_body["reasoning_effort"] = reasoning_effort
    if qwen_enable_thinking is not None:
        merged_extra_body["enable_thinking"] = qwen_enable_thinking
    if merged_extra_body:
        request["extra_body"] = merged_extra_body

    return request


def _openai_chat_completion(**request: Any) -> dict[str, Any]:
    request_model = str(request.get("model") or "").lower()
    is_qwen_model = request_model.startswith("qwen")
    min_interval = float(os.environ.get("OPENAI_REQUEST_MIN_INTERVAL", "0"))
    if is_qwen_model:
        min_interval = max(min_interval, float(os.environ.get("QWEN_REQUEST_MIN_INTERVAL_FLOOR", "0")))
    lock_dir = os.environ.get("WORK_ROOT") or os.environ.get("TMPDIR") or "/tmp"
    throttle_path = os.path.join(lock_dir, "openai_request_throttle.state")
    if min_interval > 0:
        os.makedirs(lock_dir, exist_ok=True)
        with open(throttle_path, "a+", encoding="utf-8") as throttle_file:
            fcntl.flock(throttle_file.fileno(), fcntl.LOCK_EX)
            throttle_file.seek(0)
            raw_last_request = throttle_file.read().strip()
            try:
                last_request = float(raw_last_request) if raw_last_request else 0.0
            except ValueError:
                last_request = 0.0
            sleep_for = min_interval - (time.monotonic() - last_request)
            if sleep_for > 0:
                time.sleep(sleep_for)
            throttle_file.seek(0)
            throttle_file.truncate()
            throttle_file.write(str(time.monotonic()))
            throttle_file.flush()

    timeout = float(os.environ.get("OPENAI_REQUEST_TIMEOUT", "600"))
    max_retries = int(os.environ.get("OPENAI_CLIENT_MAX_RETRIES", "2"))
    if is_qwen_model:
        max_retries = int(os.environ.get("QWEN_OPENAI_CLIENT_MAX_RETRIES", "0"))
    client = OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_API_BASE") or None,
        timeout=timeout,
        max_retries=max_retries,
    )
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        if is_qwen_model and ("429" in str(exc) or "rate limit" in str(exc).lower()):
            cooldown = float(os.environ.get("QWEN_RATE_LIMIT_COOLDOWN", "8"))
            os.makedirs(lock_dir, exist_ok=True)
            with open(throttle_path, "a+", encoding="utf-8") as throttle_file:
                fcntl.flock(throttle_file.fileno(), fcntl.LOCK_EX)
                throttle_file.seek(0)
                throttle_file.truncate()
                throttle_file.write(str(time.monotonic() + cooldown))
                throttle_file.flush()
        raise
    return _response_to_dict(response)


@cache.memoize()
def _cached_openai_chat_completion(**request: Any) -> dict[str, Any]:
    return _openai_chat_completion(**request)


@cache.memoize()
def _cached_litellm_completion(**request: Any) -> Any:
    return completion(**request)


class _CompatLiteLLMMixin:
    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(int(os.environ.get("OPENAI_COMPLETION_BACKOFF_ATTEMPTS", "30"))),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
    )
    def completion_with_backoff(self, function, **kwargs) -> dict[Any, Any]:
        return function(**kwargs)

    def _generate_with_optional_reasoning(
        self,
        input_str,
        state,
        reasoning_effort: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
        qwen_enable_thinking: Optional[bool] = None,
    ):
        messages_json = self.extract_role_messages(input_str)
        formatted_messages = json.dumps(messages_json, indent=2)
        logger.debug("Messages:\n{}\n...\n{}".format(formatted_messages[:200], formatted_messages[-200:]))

        generator_args = self.generator_params_to_args(self.generator_params)
        generator_args["messages"] = messages_json
        generator_args["model"] = self.model

        if _uses_openai_chat_client(self.model):
            request = _prepare_openai_request(
                model=self.model,
                messages=messages_json,
                generator_args=generator_args,
                reasoning_effort=reasoning_effort,
                extra_body=extra_body,
                qwen_enable_thinking=qwen_enable_thinking,
            )
            if self.use_cache and self.generator_params.temperature == 0:
                function = _cached_openai_chat_completion
            else:
                function = _openai_chat_completion
            response = self.completion_with_backoff(function=function, **request)
            empty_content_retries = int(os.environ.get("QWEN_EMPTY_CONTENT_RETRIES", "2"))
            normalized_model = (_normalize_openai_model_name(self.model) or self.model).lower()
            if normalized_model.startswith("qwen"):
                empty_content_retries = max(empty_content_retries, 4)
            for retry_idx in range(empty_content_retries):
                if _response_has_nonempty_content(response):
                    break
                logger.warning(
                    "Received empty content from %s; retrying request (%d/%d).",
                    self.model,
                    retry_idx + 1,
                    empty_content_retries,
                )
                response = self.completion_with_backoff(function=_openai_chat_completion, **request)
        else:
            if reasoning_effort:
                generator_args["reasoning_effort"] = reasoning_effort
            if extra_body:
                generator_args["extra_body"] = extra_body
            if qwen_enable_thinking is not None:
                generator_args["extra_body"] = dict(generator_args.get("extra_body") or {})
                generator_args["extra_body"]["enable_thinking"] = qwen_enable_thinking
            if self.use_cache and self.generator_params.temperature == 0:
                function = _cached_litellm_completion
            else:
                function = completion
            response = self.completion_with_backoff(function=function, **generator_args)

        try:
            prompt_tokens = _get_usage_value(response, "prompt_tokens")
            completion_tokens = _get_usage_value(response, "completion_tokens")
            if prompt_tokens is not None and completion_tokens is not None:
                first_choice = response["choices"][0]["message"]["content"]
                cost = completion_cost(
                    model=_normalize_openai_model_name(self.model) or self.model,
                    messages=messages_json,
                    completion=first_choice or "",
                )
                state.update_counter("litellm.{}.cost".format(self.model), cost)
        except Exception:
            pass

        state.update_counter("litellm.{}.calls".format(self.model), 1)
        for usage_key in ["completion_tokens", "prompt_tokens", "total_tokens"]:
            count = _get_usage_value(response, usage_key)
            if count is not None:
                state.update_counter("litellm.{}.{}".format(self.model, usage_key), count)

        generation_outputs = GenerationOutputs(outputs=[], scores=[])
        for choice in response["choices"]:
            text_response = choice["message"]["content"]
            if text_response is None:
                text_response = ""
            for stop_t in self.generator_params.stop:
                if stop_t in text_response:
                    stop_idx = text_response.index(stop_t)
                    text_response = text_response[:stop_idx]
            generation_outputs.outputs.append(text_response.lstrip())

        if len(messages_json) > 1:
            open_node = state.get_open_node()
            open_node.add_input_output_prompt(formatted_messages, generation_outputs)

        return generation_outputs


@LMGenerator.register("lite_llm", override=True)
class CompatLiteLLMGenerator(_CompatLiteLLMMixin, LMGenerator):
    def __init__(
        self,
        model: str,
        use_cache: bool = False,
        extra_body: Optional[dict[str, Any]] = None,
        qwen_enable_thinking: Optional[bool] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.use_cache = use_cache
        self.model = model
        self.extra_body = extra_body
        self.qwen_enable_thinking = qwen_enable_thinking

    def generate(self, input_str, state):
        return self._generate_with_optional_reasoning(
            input_str,
            state,
            extra_body=self.extra_body,
            qwen_enable_thinking=self.qwen_enable_thinking,
        )


@LMGenerator.register("lite_llm_reasoning", override=True)
class CompatLiteLLMReasoningGenerator(_CompatLiteLLMMixin, LMGenerator):
    def __init__(
        self,
        model: str,
        use_cache: bool = False,
        reasoning_effort: Optional[str] = None,
        extra_body: Optional[dict[str, Any]] = None,
        qwen_enable_thinking: Optional[bool] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.use_cache = use_cache
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.extra_body = extra_body
        self.qwen_enable_thinking = qwen_enable_thinking

    def generate(self, input_str, state):
        return self._generate_with_optional_reasoning(
            input_str,
            state,
            reasoning_effort=self.reasoning_effort,
            extra_body=self.extra_body,
            qwen_enable_thinking=self.qwen_enable_thinking,
        )
