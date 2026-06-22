import copy
from dataclasses import dataclass
from hmac import new
import json
import logging
from multiprocessing.managers import ValueProxy
from typing import List, Any, Tuple, Optional
import re
import os
from pathlib import Path

from matplotlib.pyplot import hist
from numpy import isin
from recoma.models.core.base_model import BaseModel
from recoma.models.core.base_react_controller import BaseReactController
from recoma.search.state import SearchState, SearchNode

from agents.recoma.causal_tool import OnlineInterventionCausalTool
from agents.recoma.discoveryworld_env_models import task_completed, num_interactions

logger = logging.getLogger(__name__)


@dataclass
class Action:
    action_str: str
    action_json: dict[Any, Any]


@dataclass
class Observation:
    raw_observation: str


@BaseModel.register("discoveryworld_react_controller")
class DiscoveryWorldReactController(BaseReactController):
    """
    React Controller for DiscoveryWorld environment
    """
    def __init__(self, eoq="[EOQ]", max_history=-1, termination_suggestion=-1,
                 ignore_multiple_calls = True, **kwargs):
        super().__init__(**kwargs)
        self.eoq = eoq
        self.ignore_multiple_jsons = ignore_multiple_calls
        self.max_history = max_history
        self.termination_suggestion = termination_suggestion
        # The stop token may be "```" and wont appear here. So need to consider it.
        self.partial_code_regex = r".*```json\n(.*)"
        self.full_code_regex = r"```json\n(.*?)```"

    def summarize_history(self, history: List[Any]) -> str:
        """Summarize the history of the conversation"""
        summary = ""
        for message in history:
            if isinstance(message, Action):
                summary += "Action:\n + ```\n" + message.action_str + "```\n"
            else:
                summary += "Observation:\n + ```\n" + message.raw_observation + "```\n"
        return summary

    def next_step_and_observation_input(self, state: SearchState,
                                        last_child: SearchNode) -> Tuple[int, str]:
        """
        This method returns the next step and observation input for the controller.
        """
        last_message = self.get_history(self.get_react_node(state))[-1]
        if not isinstance(last_message, Action):
            raise ValueError("Last message is not an action but calling observation model!")
        if last_message.action_json is None:
            raise ValueError("No JSON extracted from last action!")
        return self.OBSERVATION, last_message.action_str

    def next_step_and_action_input(self, state: SearchState,
                                   last_child: SearchNode) -> Tuple[int, str]:
        """
        This function determines the next step and action input based on the current state and the
          last child node.
        """
        current_node = self.get_react_node(state)
        history = self.get_history(current_node)
        new_history = copy.deepcopy(history)
        if self.max_history > 0 and len(new_history) > self.max_history:
            new_history = new_history[-self.max_history:]
            output_str = current_node.input_str + "\n\nHistory of action-observations:\n"
            output_str += "[TRIMMED HISTORY]\n\n"
            output_str += self.build_message_thread2(new_history, self.max_output_length-len(output_str))
        else:
            output_str = current_node.input_str + "\n\nHistory of action-observations:\n"
            output_str += self.build_message_thread2(history, self.max_output_length-len(output_str))

        while len(output_str) > self.max_output_length:
            output_str = current_node.input_str + "\n\nHistory of action-observations:\n"
            output_str += "[TRIMMED HISTORY]\n\n"
            new_history = new_history[1:]
            output_str += self.build_message_thread2(new_history, self.max_output_length-len(output_str))
            print(len(output_str), self.max_output_length)

        if self.termination_suggestion > 0  and len(history) > 2 * self.termination_suggestion:
            output_str += "\n**ARE YOU SURE YOU WANT TO CONTINUE? CONSIDER SUBMITTING WITH FAILURE**\n"
        return self.ACTION, output_str

    def terminate_with_output(self, state: SearchState, last_child: SearchNode) -> Optional[str]:
        """
        This function determines if the controller should terminate with output. Set to None
        if the controller should not terminate.
        """

        if last_child is not None:
            last_message = self.get_history(self.get_react_node(state))[-1]
            if isinstance(last_message, Action):
                if "action" in last_message.action_json and last_message.action_json["action"] == "SUBMIT":
                    result = last_message.action_json["arg1"] + last_message.action_json.get("thought", "")
                    print(f"\n🏁 TERMINATION - SUBMIT ACTION:")
                    print(f"{'='*60}")
                    print(f"Result: {result}")
                    print(f"{'='*60}\n")
                    return result

        if task_completed():
            terminal_output = self._get_terminal_output(state, last_child)
            print(f"\n🏁 TERMINATION - TASK COMPLETED:")
            print(f"{'='*60}")
            print(f"Output: {terminal_output}")
            print(f"{'='*60}\n")
            return terminal_output
        return None

    def _get_terminal_output(self, state: SearchState, last_child: Optional[SearchNode]) -> str:
        """
        Return a safe terminal output even when the environment finishes before any child step
        has been executed.
        """
        if last_child is not None and last_child.output is not None:
            return last_child.output

        history = self.get_history(self.get_react_node(state))
        if history:
            last_message = history[-1]
            if isinstance(last_message, Action):
                return last_message.action_str
            if isinstance(last_message, Observation):
                return last_message.raw_observation

        return "Task completed before any agent action or observation was recorded."

    def append_message_to_history(self, current_history: List[Any], last_child: SearchNode) -> None:
        """
        Append the message from the last child to the current history
        """
        step_type = self.get_step(last_child)
        if step_type == self.OBSERVATION:
            obs = Observation(raw_observation=last_child.output)
            current_history.append(obs)
            # Real-time output for observations
            print(f"\n🔍 OBSERVATION (Step {len(current_history)//2}):")
            print(f"{'='*60}")
            print(obs.raw_observation[:500] + "..." if len(obs.raw_observation) > 500 else obs.raw_observation)
            print(f"{'='*60}\n")
        else:
            action_json = self.extract_json_output(last_child)
            # Check if action_json is None or empty
            if action_json is None or (isinstance(action_json, str) and action_json.strip() == ""):
                print(f"\n⚠️  NO JSON FOUND IN OUTPUT:")
                print(f"{'='*60}")
                print(f"Raw output: {last_child.output[:500]}{'...' if len(last_child.output) > 500 else ''}")
                print(f"Extracted JSON: {action_json}")
                print(f"{'='*60}")
                # Create a dummy action to continue execution
                formatted_json = {"action": "WAIT", "thought": "No valid JSON found in output"}
                action_str = json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)
                return
                
            try:
                formatted_json = json.loads(action_json)
                action_str = action_json if isinstance(action_json, str) else json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)
                # Real-time output for actions
                print(f"\n🤖 ACTION (Step {len(current_history)//2})):")
                print(f"{'='*60}")
                print(f"Raw Output: {last_child.output[:300]}{'...' if len(last_child.output) > 300 else ''}")
                print(f"Parsed JSON: {formatted_json}")
                print(f"{'='*60}\n")
            except json.JSONDecodeError as e:
                print(f"\n❌ JSON DECODE ERROR:")
                print(f"{'='*60}")
                print(f"Raw output: {last_child.output[:500]}{'...' if len(last_child.output) > 500 else ''}")
                print(f"Extracted JSON: {action_json}")
                print(f"JSON Error: {e}")
                print(f"{'='*60}")
                # Create a dummy action to continue execution
                formatted_json = {"action": "WAIT", "thought": f"JSON decode error: {e}"}
                action_str = json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)


    def build_message_thread(self, history):
        output_str = ""
        for message in history:
            if isinstance(message, Action):
                # Small hack to make sure that "Task: " always matches the input task.
                output_str +="Action:\n```json\n" + \
                    message.action_str.replace("Task:", "Task :") + "\n```\n\n"
            elif isinstance(message, Observation):
                output_str += "Observation:\n```json\n" + message.raw_observation + "```\n\n"

            else:
                raise ValueError("Unknown message type: {}".format(message))
        return output_str


    def build_message_thread2(self, history, max_output_length):
        output = []
        char_count = 0
        for message in history[::-1]:
            if isinstance(message, Action):
                # Small hack to make sure that "Task: " always matches the input task.
                output.append("Action:\n```json\n" + message.action_str.replace("Task:", "Task :") + "\n```\n\n")
                char_count += len(output[-1])
                if char_count > max_output_length:
                    output = output[:-1]
                    break
            elif isinstance(message, Observation):
                print("We don't add observation history since it's too long")
                pass
                # output.append("Observation:\n```json\n" + message.raw_observation + "```\n\n")
            else:
                raise ValueError("Unknown message type: {}".format(message))

        output_str = "".join(output[::-1])
        return output_str

    def extract_json_output(self, last_child: SearchNode) -> str:
        action_output = last_child.output
        # 1) Drop any <think>...</think> segments (Qwen-style thinking)
        action_output = re.sub(r"<think>[\s\S]*?</think>", "", action_output, flags=re.IGNORECASE)
        # 2) If the model returned a fenced JSON block, prefer that path below; otherwise we'll try raw JSON.
        output_code = ""
        match_end = 0
        # Handle multiple JSONs
        for re_match in re.finditer(self.full_code_regex, action_output, flags=re.DOTALL):
            code = re_match.group(1).strip()
            if self.ignore_multiple_jsons:
                last_child.output = code
                print(code)
                return code
            output_code += code + "\n"
            match_end = re_match.end()

        # check for partial code match at end (no terminating ```)  following the last match
        partial_m = re.match(self.partial_code_regex, action_output[match_end:], flags=re.DOTALL)
        if partial_m:
            output_code += partial_m.group(1).strip()
            # terminated due to stop condition. Add stop condition to output.
            if not last_child.output.endswith("\n"):
                last_child.output = last_child.output + "\n"
            last_child.output = output_code
        if len(output_code) == 0:
            # 3) No fenced block. Try direct JSON parse first.
            try:
                action_json = json.loads(action_output)
                return action_output
            except json.JSONDecodeError:
                pass

            # 4) Fallback: scan for the last balanced top-level JSON object and parse it.
            #    This helps when the model prints prose then a JSON object.
            s = action_output
            brace_stack = 0
            start_idx = -1
            candidate = None
            for i, ch in enumerate(s):
                if ch == '{':
                    if brace_stack == 0:
                        start_idx = i
                    brace_stack += 1
                elif ch == '}':
                    if brace_stack > 0:
                        brace_stack -= 1
                        if brace_stack == 0 and start_idx != -1:
                            candidate = s[start_idx:i+1]
            if candidate:
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass

            print("Could not decode JSON from {}".format(action_output))
            return None
        else:
            return output_code

    def next_step_and_input(self, state: SearchState, last_child: SearchNode) -> Tuple[int, str]:
        """
        This function determines the next step type and input based on the current state and the
        last child node.
        """
        # Observation always follows an action step
        if last_child is not None and self.get_step(last_child) == self.ACTION:
            # Assuming code was extracted from the last action
            last_message = self.get_history(self.get_react_node(state))[-1]
            if not isinstance(last_message, Action):
                raise ValueError("Last message is not an action but last step was an action!")
            if last_message.action_json is not None:
                return self.next_step_and_observation_input(state, last_child)

        return self.next_step_and_action_input(state, last_child)


@BaseModel.register("discoveryworld_react_memory_controller")
class DiscoveryWorldReactMemoryController(DiscoveryWorldReactController):
    """
    ReAct controller variant that maintains state (DSL or simple memory).
    - DSL mode: maintains past_data and hypothesis
    - Non-DSL mode: maintains memory
    Controlled by REACTOR_TASK_PROMPT_MODE environment variable.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Read environment variable to determine mode
        self.prompt_mode = os.environ.get("REACTOR_TASK_PROMPT_MODE", "dsl").lower()
        dsl_modes = {"dsl", "dsl_hidden", "dsl_hidden_freqnode", "dsl_quad"}
        non_dsl_modes = {"non_dsl", "linear_non_dsl"}
        if self.prompt_mode not in dsl_modes | non_dsl_modes:
            self.prompt_mode = "dsl"
        self.is_dsl_mode = self.prompt_mode in dsl_modes

        self.causal_tool_enabled = os.environ.get("CAUSAL_TOOL_ENABLED", "0") == "1"
        self.causal_tool = (
            OnlineInterventionCausalTool()
            if self.causal_tool_enabled and self.is_dsl_mode
            else None
        )
        self.latest_past_data_obj: list[dict[str, Any]] = []
        self.latest_causal_tool_summary = ""
        self.pending_experiment: Optional[dict[str, Any]] = None
        self.last_observed_entry: Optional[dict[str, Any]] = None
        
        # Initialize state variables based on mode
        if self.is_dsl_mode:
            self.latest_past_data: str = ""
            self.latest_hypothesis: str = ""
            self.latest_memory: str = ""
        else:  # non_dsl
            self.latest_memory: str = ""

        if self.is_dsl_mode:
            bootstrap_entries = self._load_bootstrap_past_data()
            if bootstrap_entries:
                self.latest_past_data_obj = copy.deepcopy(bootstrap_entries)
                self.latest_past_data = json.dumps(
                    bootstrap_entries, ensure_ascii=False
                )[:4000]
                if self.causal_tool_enabled:
                    self._preload_causal_tool_from_bootstrap(bootstrap_entries)
        
        print(
            "[DiscoveryWorldReactMemoryController] Initialized with mode: "
            f"{self.prompt_mode}, causal_tool_enabled={self.causal_tool_enabled}"
        )

    @staticmethod
    def _normalize_dsl_block(block) -> Optional[str]:
        if block is None:
            return None
        if isinstance(block, str):
            return block
        try:
            return json.dumps(block, ensure_ascii=False)
        except Exception:
            return str(block)

    @staticmethod
    def _valid_bootstrap_past_data(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        return [
            entry
            for entry in payload
            if isinstance(entry, dict) and isinstance(entry.get("props"), dict)
        ]

    @staticmethod
    def _extract_bootstrap_intervention(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
        intervention = entry.get("intervention")
        if not isinstance(intervention, dict):
            return None
        if not intervention.get("target_prop"):
            return None
        if intervention.get("target_value") is None:
            return None
        return intervention

    def _load_bootstrap_past_data(self) -> list[dict[str, Any]]:
        raw_payload = os.environ.get("REACTOR_BOOTSTRAP_PAST_DATA_JSON", "").strip()
        if raw_payload:
            try:
                parsed = json.loads(raw_payload)
                entries = self._valid_bootstrap_past_data(parsed)
                if entries:
                    return entries
            except Exception:
                logger.warning("Failed to parse REACTOR_BOOTSTRAP_PAST_DATA_JSON")

        config_path = os.environ.get("CAUSAL_GRAPH_CONFIG", "").strip()
        if not config_path:
            return []
        try:
            payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except Exception:
            return []
        return self._valid_bootstrap_past_data(payload.get("bootstrap_past_data"))

    def _preload_causal_tool_from_bootstrap(
        self,
        bootstrap_entries: list[dict[str, Any]],
    ) -> None:
        if not self.causal_tool_enabled or self.causal_tool is None:
            return
        if not bootstrap_entries:
            return

        latest_entry = None
        for entry in bootstrap_entries:
            intervention = self._extract_bootstrap_intervention(entry)
            if latest_entry is not None and intervention is not None:
                self.causal_tool.add_transition(latest_entry, entry, intervention)
            else:
                self.causal_tool.filter_with_entry(entry)
            latest_entry = entry

        self.last_observed_entry = latest_entry
        self.latest_causal_tool_summary = self.causal_tool.format_summary()

    def next_step_and_action_input(self, state: SearchState,
                                   last_child: SearchNode) -> Tuple[int, str]:
        current_node = self.get_react_node(state)
        history = self.get_history(current_node)
        new_history = copy.deepcopy(history)
        output_str = ""
        causal_tool_section = ""
        if self.causal_tool_enabled and self.latest_causal_tool_summary:
            causal_tool_section = (
                "\n\n## Deterministic Candidate Graphs\n"
                "These are the currently consistent graph candidates under the configured graph family and this environment's base-value intervention semantics.\n"
                "```json\n"
                + self.latest_causal_tool_summary
                + "\n```"
            )
        
        if self.max_history > 0 and len(new_history) > self.max_history:
            new_history = new_history[-self.max_history:]
            if self.is_dsl_mode:
                output_str = current_node.input_str + "\n\n## Previous State (Use as base for incremental updates)\nLast past_data:\n```json\n" + (self.latest_past_data or "[]") + "\n```\n\nLast hypothesis:\n```json\n" + (self.latest_hypothesis or '{"edges":[],"freq_equation":"","coefficients":{}}') + "\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n```" + causal_tool_section + "\n\nHistory of action-observations:\n"
            else:  # non_dsl
                output_str = current_node.input_str + "\n\n## Previous State\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n\nHistory of action-observations:\n"
            output_str += "[TRIMMED HISTORY]\n\n"
            output_str += self.build_message_thread2(new_history, self.max_output_length-len(output_str))
        else:
            if self.is_dsl_mode:
                output_str = current_node.input_str + "\n\n## Previous State (Use as base for incremental updates)\nLast past_data:\n```json\n" + (self.latest_past_data or "[]") + "\n```\n\nLast hypothesis:\n```json\n" + (self.latest_hypothesis or '{"edges":[],"freq_equation":"","coefficients":{}}') + "\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n```" + causal_tool_section + "\n\nHistory of action-observations:\n"
            else:  # non_dsl
                output_str = current_node.input_str + "\n\n## Previous State\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n\nHistory of action-observations:\n"
            output_str += self.build_message_thread2(history, self.max_output_length-len(output_str))

        while len(output_str) > self.max_output_length:
            # If there's no more history to trim, hard-truncate the string to avoid an infinite loop.
            if not new_history:
                output_str = output_str[:self.max_output_length]
                break

            if self.is_dsl_mode:
                output_str = current_node.input_str + "\n\n## Previous State (Use as base for incremental updates)\nLast past_data:\n```json\n" + (self.latest_past_data or "[]") + "\n```\n\nLast hypothesis:\n```json\n" + (self.latest_hypothesis or '{"edges":[],"freq_equation":"","coefficients":{}}') + "\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n```" + causal_tool_section + "\n\nHistory of action-observations:\n"
            else:  # non_dsl
                output_str = current_node.input_str + "\n\n## Previous State\nLast memory:\n" + (self.latest_memory or "(empty)") + "\n\nHistory of action-observations:\n"
            output_str += "[TRIMMED HISTORY]\n\n"
            new_history = new_history[1:]
            output_str += self.build_message_thread2(new_history, self.max_output_length - len(output_str))
            # print(len(output_str), self.max_output_length)

        if self.termination_suggestion > 0  and len(history) > 2 * self.termination_suggestion:
            output_str += "\n**ARE YOU SURE YOU WANT TO CONTINUE? CONSIDER SUBMITTING WITH FAILURE**\n"
        return self.ACTION, output_str

    def _update_causal_tool(self, formatted_json: dict[str, Any]) -> None:
        if not self.causal_tool_enabled or self.causal_tool is None:
            return

        past_data = formatted_json.get("past_data")
        if not isinstance(past_data, list):
            past_data = []

        valid_entries = [
            entry
            for entry in past_data
            if isinstance(entry, dict) and isinstance(entry.get("props"), dict)
        ]

        if len(valid_entries) < len(self.latest_past_data_obj):
            # The model may have dropped history. Re-anchor to the latest entry
            # instead of replaying noisy partial history.
            if valid_entries:
                self.causal_tool.filter_with_entry(valid_entries[-1])
                self.last_observed_entry = valid_entries[-1]
            else:
                self.last_observed_entry = None
            self.latest_past_data_obj = valid_entries
        else:
            new_entries = valid_entries[len(self.latest_past_data_obj):]
            if self.last_observed_entry is None and valid_entries:
                self.causal_tool.filter_with_entry(valid_entries[-1])
                self.last_observed_entry = valid_entries[-1]
            else:
                for entry in new_entries:
                    entry_intervention = self._extract_bootstrap_intervention(entry)
                    effective_intervention = entry_intervention or self.pending_experiment
                    if effective_intervention and self.last_observed_entry is not None:
                        self.causal_tool.add_transition(
                            self.last_observed_entry,
                            entry,
                            effective_intervention,
                        )
                    else:
                        self.causal_tool.filter_with_entry(entry)
                    self.last_observed_entry = entry
            self.latest_past_data_obj = valid_entries

        experiment = formatted_json.get("experiment")
        if (
            isinstance(experiment, dict)
            and experiment.get("target_prop")
            and "value" in formatted_json
        ):
            self.pending_experiment = experiment
        else:
            self.pending_experiment = None

        self.latest_causal_tool_summary = self.causal_tool.format_summary()

    def append_message_to_history(self, current_history: List[Any], last_child: SearchNode) -> None:
        step_type = self.get_step(last_child)
        if step_type == self.OBSERVATION:
            obs = Observation(raw_observation=last_child.output)
            current_history.append(obs)
            print(f"\n🔍 OBSERVATION (Step {len(current_history)//2}):")
            print(f"{'='*60}")
            print(obs.raw_observation[:500] + "..." if len(obs.raw_observation) > 500 else obs.raw_observation)
            print(f"{'='*60}\n")
        else:
            # Extract JSON from output
            action_json = self.extract_json_output(last_child)
            
            # Case 1: No JSON found in output
            if action_json is None or (isinstance(action_json, str) and action_json.strip() == ""):
                print(f"\n⚠️  NO JSON FOUND IN OUTPUT:")
                print(f"{'='*60}")
                print(f"Raw output: {last_child.output[:500]}{'...' if len(last_child.output) > 500 else ''}")
                print(f"Extracted JSON: {action_json}")
                print(f"{'='*60}")
                
                # Create fallback action preserving current state
                if self.is_dsl_mode:
                    # Safely parse past_data
                    try:
                        past_data_obj = json.loads(self.latest_past_data) if self.latest_past_data and self.latest_past_data.strip() else []
                    except (json.JSONDecodeError, ValueError):
                        past_data_obj = []
                    
                    # Safely parse hypothesis
                    try:
                        hyp_obj = json.loads(self.latest_hypothesis) if self.latest_hypothesis and self.latest_hypothesis.strip() else {"edges": [], "freq_equation": "", "coefficients": {}}
                    except (json.JSONDecodeError, ValueError):
                        hyp_obj = {"edges": [], "freq_equation": "", "coefficients": {}}
                    
                    formatted_json = {
                        "memory": self.latest_memory or "",
                        "thought": "No valid JSON found in output",
                        "past_data": past_data_obj,
                        "hypothesis": hyp_obj,
                        "experiment": {},
                        "action": "WAIT",
                    }
                else:
                    formatted_json = {
                        "memory": self.latest_memory or "",
                        "thought": "No valid JSON found in output",
                        "experiment": {},
                        "action": "WAIT",
                    }
                action_str = json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)
                return
            
            # Case 2: JSON found, try to parse it
            try:
                formatted_json = json.loads(action_json)
                if not isinstance(formatted_json, dict):
                    raise ValueError("Parsed JSON is not a dictionary")
                
                # Extract and update state based on mode
                if self.is_dsl_mode:
                    # DSL mode: extract past_data and hypothesis
                    pd = self._normalize_dsl_block(formatted_json.get("past_data"))
                    hyp = self._normalize_dsl_block(formatted_json.get("hypothesis"))
                    if pd:
                        self.latest_past_data = pd[:4000]
                    if hyp:
                        self.latest_hypothesis = hyp[:4000]
                    mem = formatted_json.get("memory")
                    if mem:
                        if isinstance(mem, str):
                            self.latest_memory = mem[:4000]
                        else:
                            self.latest_memory = json.dumps(mem, ensure_ascii=False)[:4000]
                    self._update_causal_tool(formatted_json)
                else:  # non_dsl
                    # Non-DSL mode: extract memory
                    mem = formatted_json.get("memory")
                    if mem:
                        if isinstance(mem, str):
                            self.latest_memory = mem[:4000]
                        else:
                            self.latest_memory = json.dumps(mem, ensure_ascii=False)[:4000]
                
                # Create action with parsed JSON
                action_str = action_json if isinstance(action_json, str) else json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)
                # print(f"\n🤖 ACTION (Step {len(current_history)//2})):")
                # print(f"{'='*60}")
                # print(f"Raw Output: {last_child.output[:300]}{'...' if len(last_child.output) > 300 else ''}")
                # print(f"Parsed JSON: {formatted_json}")
                # print(f"{'='*60}\n")
                
            except (json.JSONDecodeError, ValueError) as e:
                # Case 3: JSON parsing failed
                print(f"\n❌ JSON DECODE ERROR:")
                print(f"{'='*60}")
                print(f"Raw output: {last_child.output[:500]}{'...' if len(last_child.output) > 500 else ''}")
                print(f"Extracted JSON: {action_json}")
                print(f"JSON Error: {e}")
                print(f"{'='*60}")
                
                # Create fallback action preserving current state
                if self.is_dsl_mode:
                    # Safely parse past_data
                    try:
                        past_data_obj = json.loads(self.latest_past_data) if self.latest_past_data and self.latest_past_data.strip() else []
                    except (json.JSONDecodeError, ValueError):
                        past_data_obj = []
                    
                    # Safely parse hypothesis
                    try:
                        hyp_obj = json.loads(self.latest_hypothesis) if self.latest_hypothesis and self.latest_hypothesis.strip() else {"edges": [], "freq_equation": "", "coefficients": {}}
                    except (json.JSONDecodeError, ValueError):
                        hyp_obj = {"edges": [], "freq_equation": "", "coefficients": {}}
                    
                    formatted_json = {
                        "memory": self.latest_memory or "",
                        "thought": f"JSON decode error: {e}",
                        "past_data": past_data_obj,
                        "hypothesis": hyp_obj,
                        "experiment": {},
                        "action": "WAIT"
                    }
                else:
                    formatted_json = {
                        "memory": self.latest_memory or "",
                        "thought": f"JSON decode error: {e}",
                        "experiment": {},
                        "action": "WAIT"
                    }
                action_str = json.dumps(formatted_json)
                action = Action(action_str=action_str, action_json=formatted_json)
                current_history.append(action)
