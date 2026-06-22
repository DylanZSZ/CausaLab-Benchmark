#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MONITOR_DIR = REPO_ROOT / "output_dir" / "monitoring" / "full_run_monitor"
SENSITIVE_TOKENS = ("api_key", "token", "secret", "password")


@dataclass
class SettingSpec:
    name: str
    root: Path
    expected_count: int
    launch_cmd: List[str]
    launch_env: Dict[str, str] = field(default_factory=dict)
    active_markers: List[str] = field(default_factory=list)


@dataclass
class SuiteSpec:
    name: str
    settings: List[SettingSpec]


def now_dt() -> datetime:
    return datetime.now().astimezone()


def isoformat(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def now_iso() -> str:
    return isoformat(now_dt())


def safe_model_name(model: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in model)


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def ps_output() -> str:
    result = subprocess.run(
        ["ps", "-eo", "pid,ppid,pgid,cmd"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def process_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def latest_run_dir(setting_root: Path) -> Optional[Path]:
    if not setting_root.exists():
        return None
    candidates = sorted(
        (
            path
            for path in setting_root.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        ),
        key=lambda p: p.name,
    )
    if candidates:
        return candidates[-1]
    if list(setting_root.glob("**/*complete.txt")):
        return setting_root
    return None


def summarize_run(run_dir: Optional[Path]) -> Dict[str, object]:
    if run_dir is None or not run_dir.exists():
        return {
            "run_dir": None,
            "complete_count": 0,
            "correct_count": 0,
            "accuracy": None,
        }

    complete_files = sorted(run_dir.glob("**/*complete.txt"))
    correct_count = 0
    for complete_file in complete_files:
        try:
            if complete_file.read_text(encoding="utf-8").strip() == "1":
                correct_count += 1
        except OSError:
            continue

    total = len(complete_files)
    accuracy = (correct_count / total) if total else None
    return {
        "run_dir": str(run_dir),
        "complete_count": total,
        "correct_count": correct_count,
        "accuracy": accuracy,
    }


def format_ratio(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"


def sanitize_command_for_log(command: Iterable[str]) -> str:
    sanitized: List[str] = []
    for token in command:
        lowered = token.lower()
        if any(marker in lowered for marker in SENSITIVE_TOKENS):
            if "=" in token:
                key, _ = token.split("=", 1)
                sanitized.append(f"{key}=***")
            else:
                sanitized.append("***")
        else:
            sanitized.append(token)
    return " ".join(shlex.quote(part) for part in sanitized)


def launch_setting(setting: SettingSpec, base_env: Dict[str, str], logs_dir: Path, suite_name: str) -> int:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{suite_name}__{setting.name}_relaunch.log"
    env = base_env.copy()
    env.update(setting.launch_env)
    sanitized_cmd = sanitize_command_for_log(setting.launch_cmd)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"[{now_iso()}] relaunching suite={suite_name} setting={setting.name} cmd={sanitized_cmd}\n"
        )
        process = subprocess.Popen(
            setting.launch_cmd,
            cwd=REPO_ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    return process.pid


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, payload: Dict[str, object]) -> None:
    lines = [
        "# Full Run Monitor",
        "",
        f"- checked_at: {payload['checked_at']}",
        f"- next_check_at: {payload.get('next_check_at') or ''}",
        f"- interval_seconds: {payload['interval_seconds']}",
        f"- all_done: {payload['all_done']}",
        f"- active_settings: {payload['active_settings']}",
        f"- complete_settings: {payload['complete_settings']}/{payload['total_settings']}",
        "",
        "| suite | active | done | complete_settings | total_completes | total_correct | overall_accuracy |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]

    for suite in payload["suites"]:
        lines.append(
            "| {name} | {active} | {done} | {complete_settings}/{total_settings} | {total_completes} | {total_correct} | {overall_accuracy} |".format(
                name=suite["name"],
                active=suite["active"],
                done=suite["done"],
                complete_settings=suite["complete_settings"],
                total_settings=suite["total_settings"],
                total_completes=suite["total_completes"],
                total_correct=suite["total_correct"],
                overall_accuracy=format_ratio(suite["overall_accuracy"]),
            )
        )

    for suite in payload["suites"]:
        lines.extend(
            [
                "",
                f"## {suite['name']}",
                "",
                "| setting | active | done | complete | correct | accuracy | run_dir |",
                "| --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for setting in suite["settings"]:
            lines.append(
                "| {name} | {active} | {done} | {complete_count} | {correct_count} | {accuracy} | {run_dir} |".format(
                    name=setting["name"],
                    active=setting["active"],
                    done=setting["done"],
                    complete_count=setting["complete_count"],
                    correct_count=setting["correct_count"],
                    accuracy=format_ratio(setting["accuracy"]),
                    run_dir=setting["run_dir"] or "",
                )
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def require_list_of_strings(value: object, field_name: str) -> List[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError(f"{field_name} must be a string or a list of strings")


def merge_string_dicts(base: Optional[Dict[str, object]], override: Optional[Dict[str, object]]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for source in (base or {}, override or {}):
        for key, value in source.items():
            merged[str(key)] = str(value)
    return merged


def parse_suite_specs_payload(payload: object) -> List[SuiteSpec]:
    if isinstance(payload, dict) and "suites" in payload:
        suite_entries = payload["suites"]
    elif isinstance(payload, list):
        suite_entries = payload
    else:
        suite_entries = [payload]

    if not isinstance(suite_entries, list):
        raise ValueError("suite spec payload must contain a list of suites")

    suites: List[SuiteSpec] = []
    for suite_entry in suite_entries:
        if not isinstance(suite_entry, dict):
            raise ValueError("each suite spec must be a JSON object")

        suite_name = str(suite_entry["name"])
        suite_root = suite_entry.get("root")
        suite_root_path = resolve_repo_path(str(suite_root)) if suite_root else None
        suite_launch_cmd = suite_entry.get("launch_cmd")
        suite_launch_env = suite_entry.get("launch_env")
        suite_markers = suite_entry.get("active_markers", [])
        suite_expected_count = suite_entry.get("expected_count")
        settings_data = suite_entry.get("settings")
        if not isinstance(settings_data, list) or not settings_data:
            raise ValueError(f"suite '{suite_name}' must define a non-empty settings list")

        settings: List[SettingSpec] = []
        for raw_setting in settings_data:
            if isinstance(raw_setting, str):
                setting_entry = {"name": raw_setting}
            elif isinstance(raw_setting, dict):
                setting_entry = raw_setting
            else:
                raise ValueError(f"suite '{suite_name}' has an invalid setting entry")

            setting_name = str(setting_entry["name"])
            root_value = setting_entry.get("root")
            if root_value is not None:
                setting_root = resolve_repo_path(str(root_value))
            elif suite_root_path is not None:
                setting_root = suite_root_path / setting_name
            else:
                raise ValueError(f"setting '{suite_name}/{setting_name}' is missing a root path")

            expected_count = setting_entry.get("expected_count", suite_expected_count)
            if expected_count is None:
                raise ValueError(f"setting '{suite_name}/{setting_name}' is missing expected_count")

            launch_cmd_value = setting_entry.get("launch_cmd", suite_launch_cmd)
            if launch_cmd_value is None:
                raise ValueError(f"setting '{suite_name}/{setting_name}' is missing launch_cmd")

            launch_env = merge_string_dicts(suite_launch_env, setting_entry.get("launch_env"))
            active_markers = setting_entry.get("active_markers", suite_markers)
            if not isinstance(active_markers, list) or not all(isinstance(item, str) for item in active_markers):
                raise ValueError(f"setting '{suite_name}/{setting_name}' has invalid active_markers")

            settings.append(
                SettingSpec(
                    name=setting_name,
                    root=setting_root,
                    expected_count=int(expected_count),
                    launch_cmd=require_list_of_strings(launch_cmd_value, f"{suite_name}/{setting_name}.launch_cmd"),
                    launch_env=launch_env,
                    active_markers=list(active_markers),
                )
            )

        suites.append(SuiteSpec(name=suite_name, settings=settings))
    return suites


def load_suite_specs_from_file(path: Path) -> List[SuiteSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_suite_specs_payload(payload)


def default_suites(model: str) -> List[SuiteSpec]:
    safe_model = safe_model_name(model)

    def suite_script(script_name: str) -> List[str]:
        return ["bash", f"scripts/experiments/{script_name}"]

    def main_setting(setting_name: str, root_rel: str, expected_count: int, script_name: str) -> SettingSpec:
        return SettingSpec(
            name=setting_name,
            root=REPO_ROOT / root_rel,
            expected_count=expected_count,
            launch_cmd=suite_script(script_name),
            launch_env={"MODEL": model},
            active_markers=[root_rel, script_name],
        )

    scaling_tags_4 = [
        "3o0i",
        "6o0i",
        "12o0i",
        "24o0i",
        "0o3i",
        "0o6i",
        "0o12i",
        "0o24i",
        "3o3i",
        "3o6i",
        "3o12i",
        "3o24i",
    ]

    suites = [
        SuiteSpec(
            name="oracle_main",
            settings=[
                main_setting(
                    "4nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalOracle_{safe_model}/4nodes_main",
                    50,
                    "run_react_simple-mem_oracle_4nodes_main.sh",
                ),
                main_setting(
                    "6nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalOracle_{safe_model}/6nodes_main",
                    40,
                    "run_react_simple-mem_oracle_6nodes_main.sh",
                ),
            ],
        ),
        SuiteSpec(
            name="oracle_scaling_4nodes",
            settings=[
                SettingSpec(
                    name=setting_tag,
                    root=REPO_ROOT
                    / f"output_dir/react_simple-mem/obs_CausalOracle_{safe_model}/4nodes/scaling/{setting_tag}",
                    expected_count=50,
                    launch_cmd=suite_script("run_react_simple-mem_scaling_oracle_suite.sh"),
                    launch_env={
                        "MODEL": model,
                        "NODE_COUNT": "4",
                        "ONLY_SETTINGS": setting_tag,
                    },
                    active_markers=[],
                )
                for setting_tag in scaling_tags_4
            ],
        ),
        SuiteSpec(
            name="freqparent_main",
            settings=[
                main_setting(
                    "4nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalFreqParent_{safe_model}/4nodes_main",
                    50,
                    "run_react_simple-mem_freqparent_4nodes_main.sh",
                ),
                main_setting(
                    "6nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalFreqParent_{safe_model}/6nodes_main",
                    40,
                    "run_react_simple-mem_freqparent_6nodes_main.sh",
                ),
            ],
        ),
        SuiteSpec(
            name="golden_main",
            settings=[
                main_setting(
                    "4nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalGolden_{safe_model}/4nodes_main",
                    50,
                    "run_react_simple-mem_golden_4nodes_main.sh",
                ),
                main_setting(
                    "6nodes_main",
                    f"output_dir/react_simple-mem/obs_CausalGolden_{safe_model}/6nodes_main",
                    40,
                    "run_react_simple-mem_golden_6nodes_main.sh",
                ),
            ],
        ),
    ]
    return suites


def load_suites(args: argparse.Namespace) -> List[SuiteSpec]:
    custom_specs: List[SuiteSpec] = []

    for raw_json in args.suite_spec:
        custom_specs.extend(parse_suite_specs_payload(json.loads(raw_json)))

    for spec_file in args.suite_spec_file:
        custom_specs.extend(load_suite_specs_from_file(resolve_repo_path(spec_file)))

    if custom_specs:
        return custom_specs
    return default_suites(args.model)


def inspect_setting(setting: SettingSpec, setting_state: Dict[str, object], ps_text: str) -> Dict[str, object]:
    launched_pid = setting_state.get("launched_pid")
    active = any(marker in ps_text for marker in setting.active_markers) or process_alive(launched_pid)

    run_dir = latest_run_dir(setting.root)
    summary = summarize_run(run_dir)
    done = summary["complete_count"] >= setting.expected_count

    if done and "completed_at" not in setting_state:
        setting_state["completed_at"] = now_iso()

    return {
        "name": setting.name,
        "root": str(setting.root),
        "run_dir": summary["run_dir"],
        "active": active,
        "done": done,
        "expected_count": setting.expected_count,
        "complete_count": summary["complete_count"],
        "correct_count": summary["correct_count"],
        "accuracy": summary["accuracy"],
    }


def inspect_suite(
    spec: SuiteSpec,
    state: Dict[str, object],
    ps_text: str,
    base_env: Dict[str, str],
    logs_dir: Path,
) -> Dict[str, object]:
    suite_state = state.setdefault("suites", {}).setdefault(spec.name, {})
    settings_state = suite_state.setdefault("settings", {})

    setting_statuses: List[Dict[str, object]] = []
    restarted_count = 0
    active_settings = 0
    complete_settings = 0
    total_completes = 0
    total_correct = 0

    for setting in spec.settings:
        raw_setting_state = settings_state.setdefault(setting.name, {})
        status = inspect_setting(setting, raw_setting_state, ps_text)

        if status["done"]:
            raw_setting_state.pop("launched_pid", None)
            status["restarted"] = False
        elif not status["active"]:
            launched_pid = launch_setting(setting, base_env, logs_dir, spec.name)
            raw_setting_state["launched_pid"] = launched_pid
            raw_setting_state["last_relaunch_at"] = now_iso()
            status["active"] = True
            status["restarted"] = True
            restarted_count += 1
        else:
            status["restarted"] = False

        if status["active"]:
            active_settings += 1
        if status["done"]:
            complete_settings += 1

        total_completes += int(status["complete_count"])
        total_correct += int(status["correct_count"])
        setting_statuses.append(status)

    overall_accuracy = (total_correct / total_completes) if total_completes else None
    suite_done = complete_settings == len(spec.settings)

    return {
        "name": spec.name,
        "active": active_settings > 0,
        "done": suite_done,
        "restarted_count": restarted_count,
        "active_settings": active_settings,
        "complete_settings": complete_settings,
        "total_settings": len(spec.settings),
        "total_completes": total_completes,
        "total_correct": total_correct,
        "overall_accuracy": overall_accuracy,
        "settings": setting_statuses,
    }


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def monitor_loop(args: argparse.Namespace) -> int:
    monitor_dir = resolve_repo_path(args.monitor_dir)
    monitor_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = monitor_dir / "logs"
    state_path = monitor_dir / "state.json"
    status_json_path = monitor_dir / "status.json"
    status_md_path = monitor_dir / "status.md"

    env = os.environ.copy()
    env.setdefault("MODEL", args.model)
    env.setdefault("SEEDS_PER_GRAPH", str(args.seeds_per_graph))
    env.setdefault("BATCH_SIZE", str(args.batch_size))
    env.setdefault("OPENAI_API_BASE", args.api_base)

    suites = load_suites(args)
    state: Dict[str, object] = {"started_at": now_iso(), "suites": {}}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    while True:
        cycle_started_at = now_dt()
        checked_at = isoformat(cycle_started_at)
        print(f"[{checked_at}] monitor cycle start", flush=True)
        ps_text = ps_output()

        suite_payloads: List[Dict[str, object]] = []
        all_done = True
        active_settings = 0
        complete_settings = 0
        total_settings = 0

        for suite in suites:
            suite_status = inspect_suite(suite, state, ps_text, env, logs_dir)
            suite_payloads.append(suite_status)
            all_done = all_done and bool(suite_status["done"])
            active_settings += int(suite_status["active_settings"])
            complete_settings += int(suite_status["complete_settings"])
            total_settings += int(suite_status["total_settings"])

        next_check_at = None
        if not all_done and not args.once:
            next_check_at = isoformat(cycle_started_at + timedelta(seconds=args.interval_seconds))

        cycle_payload = {
            "checked_at": checked_at,
            "next_check_at": next_check_at,
            "interval_seconds": args.interval_seconds,
            "all_done": all_done,
            "active_settings": active_settings,
            "complete_settings": complete_settings,
            "total_settings": total_settings,
            "suites": suite_payloads,
        }

        write_json(status_json_path, cycle_payload)
        write_markdown(status_md_path, cycle_payload)
        write_json(state_path, state)
        print(f"[{now_iso()}] monitor cycle wrote status to {status_json_path}", flush=True)

        if all_done or args.once:
            return 0

        time.sleep(args.interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor long-running experiment suites, relaunch incomplete settings, and write status snapshots."
    )
    parser.add_argument("--interval-seconds", type=positive_int, default=1800)
    parser.add_argument("--model", default=os.environ.get("MODEL", "gpt-5-mini"))
    parser.add_argument("--api-base", default=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"))
    parser.add_argument("--batch-size", type=positive_int, default=int(os.environ.get("BATCH_SIZE", "10")))
    parser.add_argument("--seeds-per-graph", type=positive_int, default=int(os.environ.get("SEEDS_PER_GRAPH", "1")))
    parser.add_argument("--monitor-dir", default=str(DEFAULT_MONITOR_DIR))
    parser.add_argument(
        "--suite-spec-file",
        action="append",
        default=[],
        help="JSON file with suite specs. May be provided multiple times.",
    )
    parser.add_argument(
        "--suite-spec",
        action="append",
        default=[],
        help="Inline JSON suite spec or top-level {'suites': [...]} object. May be provided multiple times.",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return monitor_loop(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
