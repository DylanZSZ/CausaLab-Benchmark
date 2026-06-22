{
    "type": "lite_llm",
    "model": std.extVar("MODEL"),
    "max_tokens": 2048,
    "temperature": 0.0,
    "use_cache": true,
    "seed": std.parseInt(std.extVar("SEED")),
    "stop": [],
}