{
    "type": "lite_llm_reasoning",
    "model": std.extVar("MODEL"),
    "reasoning_effort": "high",
    "max_tokens": 16384,
    "temperature": 0.1,
    "top_p": 0.95,
    "use_cache": true,
    "seed": std.parseInt(std.extVar("SEED")),
    "stop": [],
}

