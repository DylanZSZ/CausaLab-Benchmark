from __future__ import annotations

import copy
import os
import logging
from re import S
from typing import Any
import json
from agents.recoma.discoveryworld_env_models import SingletonEnvironment, num_interactions
import yaml
from recoma.models.core.base_model import BaseModel
from recoma.models.core.prompted_lm_model import PromptedLMModel
from recoma.models.core.generator import GenerationOutputs
from recoma.search.state import SearchState

logger = logging.getLogger(__name__)


def mkShortInteractableObjectList(observation):
    """Return compact JSON for immediately usable inventory/access objects."""
    ui = observation.get("ui", {}) if isinstance(observation, dict) else {}
    objects = []
    for section in ("inventoryObjects", "accessibleEnvironmentObjects"):
        for obj in ui.get(section, []) or []:
            if not isinstance(obj, dict):
                continue
            objects.append({"name": obj.get("name"), "uuid": obj.get("uuid")})
    return json.dumps(objects, ensure_ascii=False)

def _filter_object_list_by_name(obj_list, exclude_names:set):
    try:
        print("EXCLUDED NAMES: ", exclude_names)
        return [o for o in obj_list if str(o.get("name", "")).lower() not in exclude_names]
    except Exception:
        return obj_list

def filter_observation_ui(ui_dict:dict, exclude_names:set):
    if not isinstance(ui_dict, dict) or not exclude_names:
        return ui_dict

    # Filter accessible environment objects
    if "accessibleEnvironmentObjects" in ui_dict and isinstance(ui_dict["accessibleEnvironmentObjects"], list):
        ui_dict["accessibleEnvironmentObjects"] = _filter_object_list_by_name(ui_dict["accessibleEnvironmentObjects"], exclude_names)

    # Filter inventory minimally (usually not walls/grass/floor, but keep consistent)
    if "inventoryObjects" in ui_dict and isinstance(ui_dict["inventoryObjects"], list):
        ui_dict["inventoryObjects"] = _filter_object_list_by_name(ui_dict["inventoryObjects"], exclude_names)

    # Filter nearby objects per direction
    try:
        nb = ui_dict.get("nearbyObjects", {})
        dirs = nb.get("objects", {})
        if isinstance(dirs, dict):
            for direction, items in dirs.items():
                if isinstance(items, list):
                    dirs[direction] = _filter_object_list_by_name(items, exclude_names)
    except Exception:
        pass
    print("FILTERED UI: ", ui_dict)
    return ui_dict

@BaseModel.register("discoveryworld_promptedlm")
class DiscoveryWorldPromptedLMModel(PromptedLMModel):

    def __init__(self, max_prompt_length: int = 24000, **kwargs):
        super().__init__(**kwargs)
        self.max_prompt_length = max_prompt_length

    # def truncate_input(self, input_str):
    #     # last mention of goal
    #     max_prompt_length = self.max_prompt_length
    #     goal_index = input_str.rfind("Task:")
    #     if goal_index == -1:
    #         raise ValueError("No goal found in input string:\n{}".format(input_str))
    #     next_new_line_index = input_str.find("\n", goal_index) + 1
    #     init_prompt = input_str[:next_new_line_index]
    #     prompt = input_str[next_new_line_index:]
    #     if len(init_prompt) > max_prompt_length:
    #         print("="*40)
    #         print(input_str[next_new_line_index-50:next_new_line_index+50])
    #         print("*"*40)
    #         print(init_prompt, str(len(init_prompt)))
    #         raise ValueError("Input prompt longer than max allowed length")
    #     if len(prompt) > max_prompt_length - len(init_prompt):
    #         new_prompt =  prompt[-(max_prompt_length-len(init_prompt)):]
    #         cmd_index = new_prompt.find("ASSISTANT:") if "ASSISTANT:" in new_prompt else 0
    #         prompt = "\n[TRIMMED HISTORY]\n\n" + new_prompt[cmd_index:]
    #     return init_prompt + prompt

    # def generate_output(self, state) -> GenerationOutputs:
    #     """
    #     Generate the output string using this prompted LM by first building the LM input prompt and
    #     calling the generator to produce the output
    #     :return: generator outputs
    #     """
    #     open_node = state.get_open_node()
    #     if open_node is None:
    #         raise ValueError("Model called without any open node!!")

    def generate_output(self, state) -> GenerationOutputs:
        """
        Generate model output and record raw input/output for tracking.
        """
        open_node = state.get_open_node()
        if open_node is None:
            raise ValueError("Model called without any open node!!")

        lm_input = self.build_lm_input(self.prompt, open_node.input_str, state)
        output = self.generator.generate(lm_input, state)

        # Store raw input/output for downstream logging
        try:
            state.data["last_raw_io"] = {
                "step": num_interactions(),
                "raw_input": lm_input,
                "raw_output": output.outputs[0] if hasattr(output, "outputs") else None,
            }
        except Exception:
            pass
        # Best-effort: attach to node history if supported
        try:
            open_node.add_input_output_prompt(lm_input, output)
        except Exception:
            pass

        logger.debug("Input: ..." + lm_input[-200:])
        try:
            logger.debug("Output: " + (output.outputs[0] if hasattr(output, "outputs") else str(output)))
        except Exception:
            pass
        return output

    def populate_template_dictionary(self, input_str: str, state: SearchState) -> dict[str, Any]:
        param_dict = super().populate_template_dictionary(input_str, state)
        env = SingletonEnvironment().env
        observation = env.getAgentObservation(agentIdx=0)
        param_dict["facing_direction"] = observation["ui"]["agentLocation"]["faceDirection"]
        param_dict["valid_dirs"]= observation["ui"]["agentLocation"]["directions_you_can_move"]
        param_dict["additional_instructions"] = env.additionalActionDescriptionString()

        task_description = ""
        for task in observation["ui"]["taskProgress"]:
            task_description += task["description"] + "\n"
            task_description += " Progress: " + str(task["completed"]) + "\n\n"
        param_dict["task_str"] = task_description

        # Deep copy the observation dictionary
        observationNoVision = copy.deepcopy(observation)
        # Remove the 'vision' key from the observation
        observationNoVision.pop("vision", None)
        # Not needed since we already have task status above
        observationNoVision["ui"].pop("taskProgress", None)

        # Simplify observation UI by excluding low-value objects (e.g., wall, grass, floor)
        exclude_env = os.environ.get("REACT_EXCLUDE_OBJECTS", "wall,grass,floor")
        exclude_names = set([x.strip().lower() for x in exclude_env.split(",") if x.strip()])
        filtered_ui = filter_observation_ui(copy.deepcopy(observationNoVision["ui"]), exclude_names)
        observationFiltered = copy.deepcopy(observationNoVision)
        observationFiltered["ui"] = filtered_ui

        # Use the filtered observation as model input
        param_dict["observation"] = json.dumps(observationFiltered, indent=4, sort_keys=True)

        param_dict["known_actions"] = json.dumps(env.listKnownActions(limited=False), indent=4, sort_keys=True)
        param_dict["teleport_destinations"] = json.dumps(env.listTeleportLocationsDict(), indent=4, sort_keys=True)
        # Interactable objects based on filtered observation
        param_dict["interactable_objects"] = mkShortInteractableObjectList(observation=observationFiltered)

        # For dialog
        param_dict["in_dialog"] = env.isAgentInDialog(agentIdx=0)
        param_dict["dialog_box"] = json.dumps(observationFiltered["ui"]["dialog_box"], indent=4, sort_keys=True)
        
        # Detect if we're in value input mode (property manipulator value input)
        # Check if the dialogIn contains the instruction to provide a 'value' field
        is_value_input = False
        if param_dict["in_dialog"]:
            dialog_box_dict = observationFiltered["ui"]["dialog_box"]
            dialog_text = dialog_box_dict.get("dialogIn", "")
            # Value input mode is indicated by specific instruction text
            if "INSTRUCTION: Provide the numeric 'value' field" in dialog_text:
                is_value_input = True
        param_dict["is_value_input_mode"] = is_value_input
        
        return param_dict
