local model = std.extVar('MODEL');
local output_dir = std.extVar('OUTPUT_DIR');
local max_env_calls = std.parseInt(std.extVar('MAX_ENV_CALLS'));
local task = std.extVar('TASK');
local diff = std.extVar('DIFF');
local env_seed = std.parseInt(std.extVar('ENV_SEED'));
// Use THREADID_OFFSET from environment variable (always set by the shell script)
local threadid_offset = std.parseInt(std.extVar('THREADID_OFFSET'));
// Get prompt mode from environment variable (will be set by shell script)
local prompt_mode = std.extVar('REACTOR_TASK_PROMPT_MODE');
local generator_params = import "modified_generator_gpt52high.libsonnet";
local action_prompt_file =
    if prompt_mode == "linear_non_dsl" then
        "agents/recoma/prompts/react_simple_memory_prompt_linear_non_dsl.txt"
    else if prompt_mode == "non_dsl" then
        "agents/recoma/prompts/react_simple_memory_prompt_non_dsl.txt"
    else if prompt_mode == "dsl_hidden_freqnode" then
        "agents/recoma/prompts/react_simple_memory_prompt_dsl_hidden_freq.txt"
    else if prompt_mode == "dsl_quad" then
        "agents/recoma/prompts/react_simple_memory_prompt_dsl_quad.txt"
    else
        "agents/recoma/prompts/react_simple_memory_prompt_dsl.txt";
{
    "models": {
        "discoveryworld_init": {
            "type": "discoveryworld_loader",
            "threadid_offset": threadid_offset,
            "next_model": "react"
        },
        "react": {
            "type": "discoveryworld_react_memory_controller",
            "action_model": "action",
            "observation_model": "environment",
            "add_roles": true,
            "max_output_length": 16384,
            "max_history": -1
        },
        "action": {
            "type": "discoveryworld_promptedlm",
            "prompt_file": action_prompt_file,
            "generator_params": generator_params,
        },
        "environment": {
            "type": "discoveryworld_env",
            "output_dir": output_dir,
        },
    },
    "search": {
        "type": "best_first",
        "start_model": "discoveryworld_init",
        "answerer": {
            "type": "discoveryworld_answerer",
            "output_dir": output_dir,
        },
        "stopping_conditions": [
            {"type": "max_env_calls", "max_env_calls": max_env_calls},
            {"type": "max_llm_calls", "max_llm_calls": 1000},
            {"type": "max_llm_cost", "max_llm_cost": 50.00}
        ]
    },
    "reader": {
       "type": "discoveryworld_reader",
       "limit_prefixes": [task],
       "limit_difficulties": [diff],
       "limit_seeds": [env_seed],
    }
}
