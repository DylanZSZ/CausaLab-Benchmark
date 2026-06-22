import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from recoma.run_inference import build_configurable_systems

from agents.recoma import *

load_dotenv()  # take environment variables from .env.


def parse_arguments():
    arg_parser = argparse.ArgumentParser(description='Run inference')
    arg_parser.add_argument('--config', type=str, required=True, help="Model and Inference config")
    arg_parser.add_argument('--debug', default=False, help="Debug mode", action="store_true")
    arg_parser.add_argument('--output_dir', type=str, default="output_dir/recoma", help="Output directory")
    return arg_parser.parse_args()

def create_prediction_alldata(example_prediction):
    metadata_json = {}
    try:
        pred_json = json.loads(example_prediction.prediction)
        if not isinstance(pred_json, list) and not isinstance(pred_json, dict):
            pred_json = example_prediction.prediction
        elif isinstance(pred_json, dict):
            # check for metadata and answers
            if "metadata" in pred_json:
                metadata_json = pred_json.pop("metadata")
            if "answer" in pred_json:
                pred_json = pred_json["answer"]
    except Exception:
        pred_json = example_prediction.prediction
    all_data_dict = example_prediction.example.__dict__
    all_data_dict["predicted"] = pred_json
    # Append any metadata from the final state
    if example_prediction.final_state and example_prediction.final_state.data:
        metadata_json = example_prediction.final_state.data | metadata_json
    if metadata_json:
        all_data_dict["metadata"] = metadata_json
    return pred_json, all_data_dict


def dump_predictions(example_predictions, output_dir):
    # Dump Predictions
    with open(output_dir + "/predictions.json", "w") as output_fp, \
            open(output_dir + "/all_data.jsonl", "w") as all_data_fp:
        prediction_dump = {}
        for x in example_predictions:
            pred_json, all_data_dict = create_prediction_alldata(x)
            all_data_fp.write(json.dumps(all_data_dict) + "\n")
            prediction_dump[x.example.unique_id] = pred_json
        json.dump(prediction_dump, output_fp)


def main():
    parsed_args = parse_arguments()
    output_dir = parsed_args.output_dir
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Setup detailed logging
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_file = os.path.join(output_dir, "recoma_execution.log")
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()  # Also log to console
        ]
    )
    
    # Set detailed logging for ReCoMa components
    if parsed_args.debug:
        logging.getLogger('recoma').setLevel(level=logging.DEBUG)
        logging.getLogger('agents.recoma').setLevel(level=logging.DEBUG)
        logging.getLogger('recoma.models').setLevel(level=logging.DEBUG)
        logging.getLogger('recoma.search').setLevel(level=logging.DEBUG)
    else:
        logging.getLogger('recoma').setLevel(level=logging.INFO)
        logging.getLogger('agents.recoma').setLevel(level=logging.INFO)
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting ReCoMa execution with output directory: {output_dir}")
    logger.info(f"Debug mode: {parsed_args.debug}")
    logger.info(f"Config file: {parsed_args.config}")
    example_predictions = []
    config_sys = build_configurable_systems(parsed_args.config, output_dir)
    reader = config_sys.reader
    search_algo = config_sys.search

    with open(output_dir + "/source_config.json", "w") as output_fp:
        output_fp.write(json.dumps(config_sys.source_json, indent=2))
    # Examples are populated by the dataset name in the config file
    logger.info(f"Starting execution on examples...")
    num_examples = 0
    for idx, example in enumerate(reader.get_examples(None)):
        num_examples += 1
        logger.info(f"Processing example {idx+1}: {example.unique_id}")
        
        # Real-time start message
        print(f"\n🚀 STARTING REACT AGENT - Example {idx+1}")
        print(f"{'='*60}")
        print(f"Example ID: {example.unique_id}")
        print(f"Task: {example.__dict__.get('task', 'Unknown')}")
        print(f"{'='*60}\n")
        
        prediction = search_algo.predict(example)
        example_predictions.append(prediction)
        
        # Save detailed results for this example
        _, all_data_dict = create_prediction_alldata(example_predictions[-1])
        example_output_file = output_dir + f"/{example.unique_id}_data.json"
        with open(example_output_file, "w") as output_fp:
            json.dump(all_data_dict, output_fp, indent=2)

        # Safely determine completion flag when final_scorecard may be a dict or a list
        final_scorecard = all_data_dict.get("metadata", {}).get("final_scorecard")
        completed_successfully = False
        if isinstance(final_scorecard, dict):
            completed_successfully = bool(final_scorecard.get("completedSuccessfully"))
        elif isinstance(final_scorecard, list):
            for item in final_scorecard:
                if isinstance(item, dict) and item.get("completedSuccessfully"):
                    completed_successfully = True
                    break
        completion_flag = 1 if completed_successfully else 0
        completion_flag_file = output_dir + f"/{example.unique_id}_complete.txt"
        with open(completion_flag_file, "w") as flag_fp:
            flag_fp.write(f"{completion_flag}\n")

        logger.info(f"Completed example {idx+1}: {example.unique_id}")
        logger.info(f"Results saved to: {example_output_file}")
        logger.info(f"Completion flag written to: {completion_flag_file}")
        
        # Log basic prediction info
        if hasattr(prediction, 'prediction'):
            logger.info(f"Prediction: {prediction.prediction[:200]}..." if len(str(prediction.prediction)) > 200 else f"Prediction: {prediction.prediction}")
        
        # Log metadata if available
        if prediction.final_state and prediction.final_state.data:
            metadata = prediction.final_state.data
            logger.info(f"Final metadata: {metadata}")
    
    if num_examples == 0:
        logger.error(
            "No examples were generated by reader filters. "
            "Check TASK/DIFF/ENV_SEED and scenario availability."
        )
        raise RuntimeError(
            "No examples to run. Reader returned 0 items; verify environment filters."
        )

    logger.info(f"All examples completed. Total: {len(example_predictions)}")


    dump_predictions(example_predictions, output_dir=output_dir)


if __name__ == "__main__":
    main()
