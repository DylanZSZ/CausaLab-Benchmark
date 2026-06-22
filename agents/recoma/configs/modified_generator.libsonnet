{
    "type": "lite_llm",
    "model": std.extVar("MODEL"),
    "max_tokens": 8192,
    "temperature": 0.1,
    "top_p": 0.95,
    "use_cache": true,
    "seed": std.parseInt(std.extVar("SEED")),
    "stop": [],
}
