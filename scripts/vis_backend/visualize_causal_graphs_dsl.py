#!/usr/bin/env python3
"""
可视化因果图和动作链条的脚本
从 tracking.jsonl 和 graph_config.json 中提取数据，生成用于前端展示的 JSON
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set
import re
import bisect


def load_tracking_entries(tracking_file: str) -> List[Dict[str, Any]]:
    """加载 tracking 文件，兼容 JSONL 和多行 JSON 对象格式"""
    with open(tracking_file, 'r', encoding='utf-8') as f:
        content = f.read()

    entries: List[Dict[str, Any]] = []
    lines = content.strip().split('\n')

    # 先尝试标准 JSONL（每行一个 JSON）
    jsonl_success = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                entries.append(entry)
                jsonl_success = True
        except json.JSONDecodeError:
            continue

    # 若失败，则按大括号平衡提取多行 JSON 对象
    if not jsonl_success or len(entries) == 0:
        entries = []
        json_obj = ""
        brace_count = 0

        for line in lines:
            json_obj += line + '\n'
            brace_count += line.count('{') - line.count('}')

            if brace_count == 0 and json_obj.strip() and json_obj.strip() not in [',', '']:
                try:
                    entry = json.loads(json_obj.strip().rstrip(','))
                    if isinstance(entry, dict):
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass
                json_obj = ""

    return entries


def get_ui_from_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """兼容两种 tracking schema，提取 ui 字段"""
    if not isinstance(entry, dict):
        return {}
    observation = entry.get('observation')
    if isinstance(observation, dict):
        ui = observation.get('ui')
        if isinstance(ui, dict):
            return ui
    # simple tracking: dialog_box 在顶层
    if 'dialog_box' in entry:
        return {'dialog_box': entry.get('dialog_box', {})}
    return {}


def infer_property_name_for_value_action(action: Dict[str, Any], dialog_text: str) -> str:
    """为 value 输入动作推断属性名"""
    # 支持 "Temperature (°C) Value Setting" 这类标题
    match = re.search(r'([A-Za-z_][A-Za-z0-9_ ()°/\-]*)\s+Value\s+Setting', dialog_text)
    if match:
        raw_name = match.group(1).strip()
        # 清理单位等括号内容，避免生成 "Temperature (°C)"
        cleaned = re.sub(r'\s*\([^)]*\)', '', raw_name).strip()
        if cleaned:
            return cleaned
        return raw_name

    experiment = action.get('experiment', {})
    if isinstance(experiment, dict):
        target_prop = experiment.get('target_prop')
        if isinstance(target_prop, str) and target_prop.strip():
            return target_prop.strip()

    return "value"


def extract_dialog_actions(jsonl_file: str) -> List[Dict[str, Any]]:
    """从 tracking.jsonl 文件中提取对话和动作"""
    dialog_action_pairs = []

    entries = load_tracking_entries(jsonl_file)

    # 处理条目以查找对话-动作对
    past_dialog_box = None

    for i, entry in enumerate(entries):
        current_action = entry.get('action', {})
        if current_action is None:
            current_action = {}
        if not isinstance(current_action, dict):
            current_action = {}

        ui = get_ui_from_entry(entry)
        current_dialog_box = ui.get('dialog_box', {}) if isinstance(ui, dict) else {}

        is_dialog_action = (
            'chosen_dialog_option_int' in current_action or
            'value' in current_action
        )

        if past_dialog_box is not None and is_dialog_action:
            entry_step = entry.get('step')
            if not isinstance(entry_step, int):
                entry_step = i + 1

            dialog_info = {
                'step': entry_step,
                'dialog': {
                    'dialog_text': past_dialog_box.get('dialogIn', ''),
                    'dialog_options': past_dialog_box.get('dialogOptions', {}),
                },
                'action': current_action.copy(),
                'chosen_option_int': None,
                'chosen_option_name': None,
                'value': None,
                'action_type': None,  # 'option_selection' or 'value_input'
            }

            # 检查是否是选项选择模式
            if 'chosen_dialog_option_int' in current_action:
                chosen_int = current_action['chosen_dialog_option_int']
                dialog_options = past_dialog_box.get('dialogOptions', {})
                chosen_option_name = dialog_options.get(str(chosen_int), 'Unknown option')

                dialog_info['chosen_option_int'] = chosen_int
                dialog_info['chosen_option_name'] = chosen_option_name
                dialog_info['action_type'] = 'option_selection'

            # 检查是否是值输入模式
            elif 'value' in current_action:
                dialog_info['value'] = current_action['value']
                dialog_info['action_type'] = 'value_input'
                dialog_text = past_dialog_box.get('dialogIn', '')
                property_name = infer_property_name_for_value_action(current_action, dialog_text)
                dialog_info['chosen_option_name'] = f"Set {property_name} to {current_action['value']}"

            dialog_action_pairs.append(dialog_info)

        if isinstance(current_dialog_box, dict) and current_dialog_box.get('is_in_dialog', False):
            past_dialog_box = current_dialog_box
    
    return dialog_action_pairs


def parse_action(action_name: str) -> Tuple[str, str, float]:
    """
    解析动作名称，提取属性名、操作类型和变化量
    返回: (property_name, operation_type, delta_value)
    
    支持的格式：
    - "Adjust XXX" -> (XXX, 'select', 0.0)
    - "Set XXX to YYY" -> (XXX, 'set_value', YYY)
    - "Increase by X" -> (None, 'increase', X)
    - "Decrease by X" -> (None, 'decrease', -X)
    """
    # 匹配 "Set XXX to YYY" (新的值输入模式)
    set_match = re.match(r'Set\s+(.+?)\s+to\s+([\d.]+)', action_name, re.IGNORECASE)
    if set_match:
        property_name = set_match.group(1).strip()
        value = float(set_match.group(2))
        return (property_name, 'set_value', value)
    
    # 匹配 "Adjust XXX" 或直接的属性名
    adjust_match = re.match(r'Adjust\s+(.+)', action_name, re.IGNORECASE)
    if adjust_match:
        property_name = adjust_match.group(1).strip()
        return (property_name, 'select', 0.0)
    
    # 匹配 "Increase by X" 或 "Decrease by X"
    increase_match = re.match(r'Increase\s+by\s+([\d.]+)', action_name, re.IGNORECASE)
    if increase_match:
        value = float(increase_match.group(1))
        return (None, 'increase', value)
    
    decrease_match = re.match(r'Decrease\s+by\s+([\d.]+)', action_name, re.IGNORECASE)
    if decrease_match:
        value = float(decrease_match.group(1))
        return (None, 'decrease', -value)
    
    return (None, 'other', 0.0)


def normalize_property_name(name: str) -> str:
    """标准化属性名称以便匹配"""
    return name.replace(' ', '').replace('(', '').replace(')', '').replace('°', '')


def find_matching_property(raw_name: str, graph_config: Dict) -> str:
    """在图配置中找到与原始名称匹配的属性名"""
    normalized_prop = normalize_property_name(raw_name)
    for key in graph_config['nodes'].keys():
        normalized_key = normalize_property_name(key)
        if normalized_prop.lower() in normalized_key.lower() or normalized_key.lower() in normalized_prop.lower():
            return key
    return ""


def parse_dialog_values(dialog_text: str, graph_config: Dict) -> Dict[str, float]:
    """从 dialog 文本中解析属性值"""
    if not dialog_text:
        return {}
    values = {}
    for line in dialog_text.splitlines():
        match = re.match(r'^\s*([^:]+)\s*:\s*(-?\d+(?:\.\d+)?)\s*$', line)
        if not match:
            continue
        raw_name = match.group(1).strip()
        value = float(match.group(2))
        matched_prop = find_matching_property(raw_name, graph_config)
        if matched_prop:
            values[matched_prop] = value
    return values


def simulate_action_chain(dialog_actions: List[Dict], graph_config: Dict) -> List[Dict[str, Any]]:
    """
    模拟动作链条，计算每一步所有属性的值
    """
    # 初始化属性值（优先从 dialog 文本获取）
    current_values: Dict[str, float] = {}
    action_chain = []
    current_property = None  # 当前正在调整的属性
    
    for i, action_info in enumerate(dialog_actions):
        action_name = action_info.get('chosen_option_name', '')
        if not action_name or action_name == 'Unknown option':
            continue

        dialog_text = action_info.get('dialog', {}).get('dialog_text', '')
        dialog_values = parse_dialog_values(dialog_text, graph_config)
        if dialog_values:
            current_values.update(dialog_values)
        before_values = current_values.copy()

        next_values = {}
        if i + 1 < len(dialog_actions):
            next_dialog_text = dialog_actions[i + 1].get('dialog', {}).get('dialog_text', '')
            next_values = parse_dialog_values(next_dialog_text, graph_config)

        prop_name, op_type, value_or_delta = parse_action(action_name)
        
        # 如果是选择属性
        if op_type == 'select' and prop_name:
            found_prop = find_matching_property(prop_name, graph_config)
            if found_prop:
                current_property = found_prop
        
        # 如果是直接设置值操作（新的值输入模式）
        elif op_type == 'set_value' and prop_name:
            found_prop = find_matching_property(prop_name, graph_config)
            if found_prop:
                old_value = before_values.get(found_prop, current_values.get(found_prop, 0.0))

                if next_values:
                    after_values = current_values.copy()
                    after_values.update(next_values)
                    new_value = after_values.get(found_prop, value_or_delta)
                    current_values = after_values
                else:
                    new_value = value_or_delta
                    current_values[found_prop] = new_value

                passively_changed = []
                if next_values:
                    for prop in graph_config['nodes'].keys():
                        if prop != found_prop:
                            old_val = before_values.get(prop, 0)
                            new_val = current_values.get(prop, 0)
                            if abs(new_val - old_val) > 0.001:
                                passively_changed.append(prop)
                action_chain.append({
                    'step': action_info['step'],
                    'action_name': action_name,
                    'modified_property': found_prop,
                    'passively_changed': passively_changed,
                    'delta': new_value - old_value,
                    'old_value': old_value,
                    'new_value': new_value,
                    'all_values': current_values.copy()
                })

                current_property = found_prop
        
        # 如果是增加/减少操作
        elif op_type in ['increase', 'decrease'] and current_property:
            # 更新当前属性的值
            old_value = before_values.get(current_property, current_values.get(current_property, 0.0))

            if next_values:
                after_values = current_values.copy()
                after_values.update(next_values)
                new_value = after_values.get(current_property, old_value + value_or_delta)
                current_values = after_values
            else:
                new_value = old_value + value_or_delta
                current_values[current_property] = new_value

            passively_changed = []
            if next_values:
                for prop_name in graph_config['nodes'].keys():
                    if prop_name != current_property:
                        old_val = before_values.get(prop_name, 0)
                        new_val = current_values.get(prop_name, 0)
                        if abs(new_val - old_val) > 0.001:
                            passively_changed.append(prop_name)
            action_chain.append({
                'step': action_info['step'],
                'action_name': action_name,
                'modified_property': current_property,
                'passively_changed': passively_changed,
                'delta': new_value - old_value,
                'old_value': old_value,
                'new_value': new_value,
                'all_values': current_values.copy()
            })
    
    return action_chain


def load_graph_config(config_file: str) -> Dict[str, Any]:
    """加载因果图配置"""
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_hypotheses_from_tracking(tracking_file: str) -> List[Dict[str, Any]]:
    """
    从 tracking.jsonl 文件中提取每一步的 hypothesis
    返回: List[Dict] 每个元素包含 step, hypothesis, raw_output
    """
    hypotheses = []
    
    entries = load_tracking_entries(tracking_file)
    
    # 提取每一步的 hypothesis
    for i, entry in enumerate(entries):
        step = entry.get('step')
        if not isinstance(step, int):
            step = i + 1
        
        # 首先尝试从 action 字段中获取
        action = entry.get('action', {})
        if isinstance(action, dict):
            hypothesis = action.get('hypothesis', {})
            if hypothesis:
                hypotheses.append({
                    'step': step,
                    'hypothesis': hypothesis,
                    'edges': hypothesis.get('edges', []),
                    'freq_equation': hypothesis.get('freq_equation', ''),
                    'coefficients': hypothesis.get('coefficients', {}),
                    'raw_output': entry.get('raw_output', '')
                })
                continue
        
        # 如果 action 中没有，尝试从 raw_output 中解析
        raw_output = entry.get('raw_output', '')
        if not raw_output:
            continue
        
        # 尝试从 raw_output 中解析 JSON
        try:
            # raw_output 可能是 JSON 字符串
            if isinstance(raw_output, str):
                output_json = json.loads(raw_output)
            else:
                output_json = raw_output
            
            hypothesis = output_json.get('hypothesis', {})
            if hypothesis:
                hypotheses.append({
                    'step': step,
                    'hypothesis': hypothesis,
                    'edges': hypothesis.get('edges', []),
                    'freq_equation': hypothesis.get('freq_equation', ''),
                    'coefficients': hypothesis.get('coefficients', {}),
                    'raw_output': raw_output
                })
        except (json.JSONDecodeError, AttributeError) as e:
            # 如果解析失败，尝试用正则表达式提取
            try:
                # 尝试提取 hypothesis 部分
                hypothesis_match = re.search(r'"hypothesis"\s*:\s*(\{[^}]*(?:\{[^}]*\}[^}]*)*\})', raw_output)
                if hypothesis_match:
                    hypothesis_str = hypothesis_match.group(1)
                    hypothesis = json.loads(hypothesis_str)
                    hypotheses.append({
                        'step': step,
                        'hypothesis': hypothesis,
                        'edges': hypothesis.get('edges', []),
                        'freq_equation': hypothesis.get('freq_equation', ''),
                        'coefficients': hypothesis.get('coefficients', {}),
                        'raw_output': raw_output
                    })
            except Exception:
                continue
    
    return hypotheses


def build_hypothesis_timeline_by_action_step(
    hypotheses: List[Dict[str, Any]],
    action_chain: List[Dict[str, Any]],
    true_edges: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """构建按动作步数对齐的 hypothesis 时间线（含 step 0）"""
    if not action_chain:
        return []

    mapped_hypotheses = map_hypotheses_to_action_steps(hypotheses, action_chain)
    mapped_hypotheses.sort(key=lambda x: x.get('step', 0))

    latest_by_action_step: Dict[int, Dict[str, Any]] = {}
    for hyp in mapped_hypotheses:
        action_step = hyp.get('action_step', 0)
        latest_by_action_step[action_step] = hyp

    total_steps = len(action_chain)
    timeline: List[Dict[str, Any]] = []
    last_hyp = latest_by_action_step.get(0)
    for step in range(0, total_steps + 1):
        if step in latest_by_action_step:
            last_hyp = latest_by_action_step[step]

        if last_hyp:
            predicted_edges = last_hyp.get('edges', [])
            metrics = compute_edge_metrics(predicted_edges, true_edges)
            timeline.append({
                'action_step': step,
                'source_step': last_hyp.get('step', 0),
                'edges': predicted_edges,
                'num_correct': metrics['num_correct'],
                'num_true': metrics['num_true'],
                'precision': metrics['precision'],
                'recall': metrics['recall'],
                'f1': metrics['f1']
            })
        else:
            timeline.append({
                'action_step': step,
                'source_step': None,
                'edges': [],
                'num_correct': 0,
                'num_true': len({tuple(normalize_edge(e)) for e in true_edges}),
                'precision': 0.0,
                'recall': 0.0,
                'f1': 0.0
            })
    return timeline


def normalize_edge(edge: Dict[str, str]) -> Tuple[str, str]:
    """
    标准化边，返回 (from, to) 元组
    处理属性名称的变体（如 freq, resonanceFreq, frequency 等）
    """
    from_node = edge.get('from', '').strip()
    to_node = edge.get('to', '').strip()
    
    # 标准化频率相关的名称
    freq_variants = ['freq', 'resonancefreq', 'resonance_freq', 'frequency', 'resonancefrequency']
    for variant in freq_variants:
        if from_node.lower() == variant:
            from_node = 'resonanceFreq'
        if to_node.lower() == variant:
            to_node = 'resonanceFreq'
    
    return (from_node, to_node)


def compute_edge_metrics(predicted_edges: List[Dict], true_edges: List[Dict]) -> Dict[str, Any]:
    """
    计算边的准确率和召回率
    
    返回:
    {
        'precision': float,  # 准确率：预测正确的边 / 所有预测的边
        'recall': float,     # 召回率：预测正确的边 / 所有真实的边
        'f1': float,         # F1 分数
        'true_positives': List[Dict],  # 正确预测的边
        'false_positives': List[Dict], # 错误预测的边
        'false_negatives': List[Dict]  # 遗漏的真实边
    }
    """
    # 标准化真实边
    true_edge_set = set()
    for edge in true_edges:
        normalized = normalize_edge(edge)
        true_edge_set.add(normalized)
    
    # 标准化预测边
    pred_edge_set = set()
    for edge in predicted_edges:
        normalized = normalize_edge(edge)
        pred_edge_set.add(normalized)
    
    # 计算 TP, FP, FN
    true_positives = pred_edge_set & true_edge_set
    false_positives = pred_edge_set - true_edge_set
    false_negatives = true_edge_set - pred_edge_set
    
    # 转换为原始格式的列表
    tp_list = [{'from': e[0], 'to': e[1]} for e in true_positives]
    fp_list = [{'from': e[0], 'to': e[1]} for e in false_positives]
    fn_list = [{'from': e[0], 'to': e[1]} for e in false_negatives]
    
    # 计算指标
    precision = len(true_positives) / len(pred_edge_set) if len(pred_edge_set) > 0 else 0.0
    recall = len(true_positives) / len(true_edge_set) if len(true_edge_set) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'true_positives': tp_list,
        'false_positives': fp_list,
        'false_negatives': fn_list,
        'num_predicted': len(pred_edge_set),
        'num_true': len(true_edge_set),
        'num_correct': len(true_positives)
    }


def compute_weight_accuracy(predicted_coefficients: Dict[str, Any], true_params: Dict[str, Any], 
                           freq_equation: str) -> Dict[str, Any]:
    """
    计算权重（系数）的准确率
    
    对 graph_config 的每一个 coeff_{prop}_freq 参数，检查 hypothesis 的 coefficients 中是否存在对应的 c_{prop} 且值相同。
    
    例如：
    - true_params 中的 coeff_radiation_freq: 2 对应 predicted_coefficients 中的 c_radiation
    - true_params 中的 coeff_density_freq: 3 对应 predicted_coefficients 中的 c_density
    """
    # 从 true_params 中找到所有 coeff_{prop}_freq 格式的系数
    freq_coeffs = {}
    for key, value in true_params.items():
        # 匹配 coeff_{prop}_freq 格式
        match = re.match(r'coeff_(.+)_freq$', key)
        if match:
            prop_name = match.group(1)
            freq_coeffs[prop_name] = {
                'true_param_name': key,
                'true_value': value,
                'property': prop_name
            }
    
    if not freq_coeffs:
        return {
            'weight_precision': 0.0,
            'weight_recall': 0.0,
            'weight_f1': 0.0,
            'weight_accuracy': 1.0,  # 无系数可比较时视为完美
            'num_predicted_weights': 0,
            'num_true_weights': 0,
            'num_correct_weights': 0,
            'num_freq_coefficients': 0,
            'num_correct_coefficients': 0,
            'weight_details': []
        }
    
    # 对每个 freq 系数，查找对应的预测系数
    weight_details = []
    num_correct = 0
    num_predicted = 0
    
    # 常见缩写映射：graph 的 coeff_*_freq 可能用缩写，agent 的 coefficients 用完整属性名
    # 例如 coeff_temp_freq -> c_temperatureC
    PROP_ABBREV_TO_FULL = {'temp': 'temperatureC', 'ph': 'ph'}
    for prop_name, true_info in freq_coeffs.items():
        # 尝试多种可能的预测系数名称：c_{prop}、c_{完整名}、c_{prop前4字符}
        possible_pred_names = [
            f"c_{prop_name}",  # c_radiation, c_conductivity
        ]
        if prop_name in PROP_ABBREV_TO_FULL:
            possible_pred_names.append(f"c_{PROP_ABBREV_TO_FULL[prop_name]}")  # c_temperatureC
        if len(prop_name) >= 4:
            possible_pred_names.append(f"c_{prop_name[:4]}")  # c_radi
        
        # 查找匹配的预测系数
        found = False
        for pred_name in possible_pred_names:
            if pred_name in predicted_coefficients:
                pred_value = predicted_coefficients[pred_name]
                if pred_value is not None:
                    num_predicted += 1
                    # 比较值是否相同（允许小的数值误差）
                    is_correct = abs(pred_value - true_info['true_value']) < 0.01
                    
                    weight_details.append({
                        'property': prop_name,
                        'true_param_name': true_info['true_param_name'],
                        'true_value': true_info['true_value'],
                        'predicted_name': pred_name,
                        'predicted_value': pred_value,
                        'correct': is_correct
                    })
                    
                    if is_correct:
                        num_correct += 1
                    found = True
                    break
        
        if not found:
            # 没有找到对应的预测系数
            weight_details.append({
                'property': prop_name,
                'true_param_name': true_info['true_param_name'],
                'true_value': true_info['true_value'],
                'predicted_name': None,
                'predicted_value': None,
                'correct': False
            })
    
    # 计算准确率
    num_freq_coeffs = len(freq_coeffs)
    
    precision = num_correct / num_predicted if num_predicted > 0 else 0.0
    recall = num_correct / num_freq_coeffs if num_freq_coeffs > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    # weight_accuracy: 正确预测系数 / 真实系数总数（与前端 drawWeightAccuracyChart 期望的字段一致）
    weight_accuracy = num_correct / num_freq_coeffs if num_freq_coeffs > 0 else 1.0
    
    return {
        'weight_precision': precision,
        'weight_recall': recall,
        'weight_f1': f1,
        'weight_accuracy': weight_accuracy,
        'num_predicted_weights': num_predicted,
        'num_true_weights': num_freq_coeffs,
        'num_correct_weights': num_correct,
        'num_freq_coefficients': num_freq_coeffs,
        'num_correct_coefficients': num_correct,
        'weight_details': weight_details
    }


def detect_hypothesis_changes(hypotheses: List[Dict[str, Any]], interventions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    检测哪些干预后改变了 hypothesis
    interventions: 包含 step 和 action_name 的列表
    """
    changes = []
    
    if len(hypotheses) < 2:
        return changes
    
    # 按 step 排序
    hypotheses_sorted = sorted(hypotheses, key=lambda x: x['step'])
    
    # 创建干预步骤的集合
    intervention_steps = {interv['step'] for interv in interventions}
    
    prev_edges = set()
    prev_step = None
    
    for i, hyp in enumerate(hypotheses_sorted):
        current_edges = {tuple(normalize_edge(e)) for e in hyp['edges']}
        current_step = hyp['step']
        
        if i > 0:
            # 检查是否有变化
            if current_edges != prev_edges:
                # 找到最近的干预步骤
                recent_intervention = None
                for interv in interventions:
                    if interv['step'] < current_step and (recent_intervention is None or interv['step'] > recent_intervention['step']):
                        recent_intervention = interv
                
                changes.append({
                    'step': current_step,
                    'previous_step': prev_step,
                    'changed': True,
                    'previous_edges': [{'from': e[0], 'to': e[1]} for e in prev_edges],
                    'current_edges': [{'from': e[0], 'to': e[1]} for e in current_edges],
                    'recent_intervention': recent_intervention,
                    'edges_added': [{'from': e[0], 'to': e[1]} for e in current_edges - prev_edges],
                    'edges_removed': [{'from': e[0], 'to': e[1]} for e in prev_edges - current_edges]
                })
        
        prev_edges = current_edges
        prev_step = current_step
    
    return changes


def compute_edge_metrics_over_time(hypotheses: List[Dict[str, Any]], true_edges: List[Dict]) -> List[Dict[str, Any]]:
    """
    计算每一步的边准确率和召回率
    返回时间序列数据，用于绘制折线图
    """
    metrics_over_time = []
    
    # 按 step 排序
    hypotheses_sorted = sorted(hypotheses, key=lambda x: x['step'])
    
    for hyp in hypotheses_sorted:
        predicted_edges = hyp.get('edges', [])
        metrics = compute_edge_metrics(predicted_edges, true_edges)
        
        metrics_over_time.append({
            'step': hyp['step'],
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1': metrics['f1'],
            'num_predicted': metrics['num_predicted'],
            'num_true': metrics['num_true'],
            'num_correct': metrics['num_correct']
        })
    
    return metrics_over_time


def map_hypotheses_to_action_steps(
    hypotheses: List[Dict[str, Any]],
    action_chain: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """将 hypothesis 的 step 映射到动作步数（按动作顺序计数）"""
    action_steps = sorted(action.get('step', 0) for action in action_chain)
    if not action_steps:
        return hypotheses

    mapped = []
    for hyp in sorted(hypotheses, key=lambda x: x['step']):
        hyp_step = hyp.get('step', 0)
        action_index = bisect.bisect_right(action_steps, hyp_step)
        hyp_with_step = hyp.copy()
        hyp_with_step['action_step'] = action_index
        mapped.append(hyp_with_step)
    return mapped


def compute_edge_metrics_over_time_by_action_step(
    hypotheses: List[Dict[str, Any]],
    true_edges: List[Dict],
    action_chain: List[Dict[str, Any]],
    true_params: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """按动作步数统计边指标（每个动作步数取最后一次 hypothesis），可选包含 weight 准确率"""
    return compute_edge_metrics_over_time_by_action_step_filtered(
        hypotheses, true_edges, action_chain, None, true_params
    )


def compute_edge_metrics_over_time_by_action_step_filtered(
    hypotheses: List[Dict[str, Any]],
    true_edges: List[Dict],
    action_chain: List[Dict[str, Any]],
    filter_predicted,
    true_params: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """按动作步数统计边指标（可选过滤预测边），可选包含 weight 准确率"""
    mapped_hypotheses = map_hypotheses_to_action_steps(hypotheses, action_chain)
    metrics_by_step: Dict[int, Dict[str, Any]] = {}
    for hyp in mapped_hypotheses:
        predicted_edges = hyp.get('edges', [])
        if filter_predicted:
            predicted_edges = filter_predicted(predicted_edges)
        metrics = compute_edge_metrics(predicted_edges, true_edges)
        action_step = hyp.get('action_step', 0)
        step_metrics = {
            'step': action_step,
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1': metrics['f1'],
            'num_predicted': metrics['num_predicted'],
            'num_true': metrics['num_true'],
            'num_correct': metrics['num_correct']
        }
        # 若提供 true_params，计算 weight 准确率供前端 Weight Accuracy 图表使用
        if true_params:
            weight_m = compute_weight_accuracy(
                hyp.get('coefficients', {}),
                true_params,
                hyp.get('freq_equation', '')
            )
            step_metrics['weight_accuracy'] = weight_m['weight_accuracy']
            step_metrics['num_freq_coefficients'] = weight_m['num_freq_coefficients']
            step_metrics['num_correct_coefficients'] = weight_m['num_correct_coefficients']
        metrics_by_step[action_step] = step_metrics
    total_steps = len(action_chain)
    filled_metrics: List[Dict[str, Any]] = []
    last_metrics = metrics_by_step.get(0)
    for step in range(1, total_steps + 1):
        if step in metrics_by_step:
            last_metrics = metrics_by_step[step]
        if last_metrics:
            step_metrics = last_metrics.copy()
            step_metrics['step'] = step
            filled_metrics.append(step_metrics)
    return filled_metrics


def filter_edges_targeting_frequency(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只保留指向 frequency 节点的边"""
    filtered = []
    for edge in edges:
        target = edge.get('to', '')
        if 'freq' in str(target).lower():
            filtered.append(edge)
    return filtered


def generate_visualization_data(tracking_file: str, config_file: str, output_file: str):
    """生成可视化数据"""
    print(f"Processing tracking file: {tracking_file}")
    print(f"Loading graph config: {config_file}")
    
    # 提取对话-动作对
    dialog_actions = extract_dialog_actions(tracking_file)
    print(f"Found {len(dialog_actions)} dialog-action pairs")
    
    # 加载图配置
    graph_config = load_graph_config(config_file)
    print(f"Loaded graph with {len(graph_config['nodes'])} nodes and {len(graph_config['edges'])} edges")
    
    # 初始值来自第一次打开 dialog 时的文本
    initial_values = {}
    if dialog_actions:
        first_dialog_text = dialog_actions[0].get('dialog', {}).get('dialog_text', '')
        initial_values = parse_dialog_values(first_dialog_text, graph_config)

    # 模拟动作链条
    action_chain = simulate_action_chain(dialog_actions, graph_config)
    print(f"Simulated {len(action_chain)} actions")
    
    # 提取每一步的 hypothesis
    hypotheses = extract_hypotheses_from_tracking(tracking_file)
    print(f"Extracted {len(hypotheses)} hypotheses")
    
    # 获取真实边
    true_edges = graph_config.get('edges', [])
    true_params = graph_config.get('params', {})
    
    # 计算每一步的边准确率和召回率（按动作步数），包含 weight 准确率供前端图表使用
    edge_metrics_over_time = compute_edge_metrics_over_time_by_action_step(
        hypotheses, true_edges, action_chain, true_params
    )
    print(f"Computed edge metrics for {len(edge_metrics_over_time)} steps")

    # 指向 frequency 的边指标
    freq_true_edges = filter_edges_targeting_frequency(true_edges)
    freq_metrics_over_time = compute_edge_metrics_over_time_by_action_step_filtered(
        hypotheses, freq_true_edges, action_chain, filter_edges_targeting_frequency
    )

    # 基于 tracking.jsonl 首尾 hypothesis 的端点指标（用于曲线起止时刻）
    endpoint_metrics = None
    endpoint_metrics_frequency = None
    if hypotheses:
        hypotheses_sorted = sorted(hypotheses, key=lambda x: x.get('step', 0))
        first_hyp = hypotheses_sorted[0]
        last_hyp = hypotheses_sorted[-1]
        first_edge_metrics = compute_edge_metrics(first_hyp.get('edges', []), true_edges)
        last_edge_metrics = compute_edge_metrics(last_hyp.get('edges', []), true_edges)
        endpoint_metrics = {
            'start': {
                'source_step': first_hyp.get('step', 0),
                'precision': first_edge_metrics['precision'],
                'recall': first_edge_metrics['recall'],
                'f1': first_edge_metrics['f1'],
                'num_correct': first_edge_metrics['num_correct'],
                'num_true': first_edge_metrics['num_true']
            },
            'end': {
                'source_step': last_hyp.get('step', 0),
                'precision': last_edge_metrics['precision'],
                'recall': last_edge_metrics['recall'],
                'f1': last_edge_metrics['f1'],
                'num_correct': last_edge_metrics['num_correct'],
                'num_true': last_edge_metrics['num_true']
            }
        }

        first_freq_metrics = compute_edge_metrics(
            filter_edges_targeting_frequency(first_hyp.get('edges', [])),
            freq_true_edges
        )
        last_freq_metrics = compute_edge_metrics(
            filter_edges_targeting_frequency(last_hyp.get('edges', [])),
            freq_true_edges
        )
        endpoint_metrics_frequency = {
            'start': {
                'source_step': first_hyp.get('step', 0),
                'precision': first_freq_metrics['precision'],
                'recall': first_freq_metrics['recall'],
                'f1': first_freq_metrics['f1'],
                'num_correct': first_freq_metrics['num_correct'],
                'num_true': first_freq_metrics['num_true']
            },
            'end': {
                'source_step': last_hyp.get('step', 0),
                'precision': last_freq_metrics['precision'],
                'recall': last_freq_metrics['recall'],
                'f1': last_freq_metrics['f1'],
                'num_correct': last_freq_metrics['num_correct'],
                'num_true': last_freq_metrics['num_true']
            }
        }
    
    # 计算最终边准确率和召回率
    final_metrics = None
    if hypotheses:
        final_hyp = max(hypotheses, key=lambda x: x['step'])
        final_metrics = compute_edge_metrics(final_hyp['edges'], true_edges)
        
        # 计算权重准确率
        weight_metrics = compute_weight_accuracy(
            final_hyp.get('coefficients', {}),
            true_params,
            final_hyp.get('freq_equation', '')
        )
        final_metrics.update(weight_metrics)

    # frequency 目标边最终指标
    final_freq_metrics = None
    if hypotheses:
        final_hyp = max(hypotheses, key=lambda x: x['step'])
        final_freq_metrics = compute_edge_metrics(
            filter_edges_targeting_frequency(final_hyp.get('edges', [])),
            freq_true_edges
        )

    # 最佳边预测（用于展示“曾经达到过最好结果”的时刻）
    best_metrics = None
    if edge_metrics_over_time:
        best_metrics = max(
            edge_metrics_over_time,
            key=lambda m: (
                m.get('num_correct', 0),
                m.get('f1', 0.0),
                m.get('recall', 0.0),
                m.get('precision', 0.0)
            )
        )

    hypothesis_timeline = build_hypothesis_timeline_by_action_step(
        hypotheses, action_chain, true_edges
    )
    
    # 检测哪些干预后改变了 hypothesis
    # 从 action_chain 中提取干预步骤
    interventions = [
        {
            'step': action['step'],
            'action_name': action['action_name'],
            'modified_property': action.get('modified_property')
        }
        for action in action_chain
    ]
    
    hypothesis_changes = detect_hypothesis_changes(hypotheses, interventions)
    print(f"Detected {len(hypothesis_changes)} hypothesis changes after interventions")
    
    # 生成输出数据
    output_data = {
        'graph': graph_config,
        'initial_values': initial_values,
        'action_chain': action_chain,
        'summary': {
            'total_actions': len(action_chain),
            'action_sequence': [item['action_name'] for item in action_chain]
        },
        'edge_metrics': {
            'over_time': edge_metrics_over_time,  # 用于绘制折线图
            'final': final_metrics,  # 最终指标
            'best': best_metrics,  # 历史最佳指标
            'endpoints': endpoint_metrics,  # tracking.jsonl 首尾 hypothesis 端点
            'true_edges': true_edges,
            'final_predicted_edges': hypotheses[-1]['edges'] if hypotheses else []
        },
        'edge_metrics_frequency': {
            'over_time': freq_metrics_over_time,
            'final': final_freq_metrics,
            'endpoints': endpoint_metrics_frequency,
            'true_edges': freq_true_edges,
            'final_predicted_edges': filter_edges_targeting_frequency(
                hypotheses[-1]['edges'] if hypotheses else []
            )
        },
        'hypothesis_changes': hypothesis_changes,  # 哪些干预后改变了hypothesis
        'hypotheses': hypotheses,  # 所有步骤的hypothesis
        'hypothesis_timeline': hypothesis_timeline  # 按动作步数对齐的 hypothesis 图
    }
    
    # 保存到文件
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Saved visualization data to: {output_file}")
    if final_metrics:
        print(f"Final edge precision: {final_metrics['precision']:.3f}, recall: {final_metrics['recall']:.3f}")
    
    return output_data


def compute_multi_rollout_statistics(rollout_dirs: List[str]) -> Dict[str, Any]:
    """
    计算多个 rollout 的统计信息
    rollout_dirs: 包含 tracking.jsonl 和 graph_config.json 的目录列表
    """
    all_final_metrics = []
    all_edge_metrics_over_time = []
    
    for rollout_dir in rollout_dirs:
        rollout_path = Path(rollout_dir)
        
        # 查找 tracking.jsonl 和 graph_config.json
        tracking_files = list(rollout_path.glob('*_tracking.jsonl'))
        config_file = rollout_path / 'graph_config.json'
        
        if not tracking_files or not config_file.exists():
            print(f"Warning: Skipping {rollout_dir} - missing files")
            continue
        
        tracking_file = tracking_files[0]
        
        try:
            # 提取 hypotheses
            hypotheses = extract_hypotheses_from_tracking(str(tracking_file))
            if not hypotheses:
                continue
            
            # 加载图配置
            graph_config = load_graph_config(str(config_file))
            true_edges = graph_config.get('edges', [])
            
            # 计算边指标
            edge_metrics_over_time = compute_edge_metrics_over_time(hypotheses, true_edges)
            all_edge_metrics_over_time.append(edge_metrics_over_time)
            
            # 计算最终指标
            final_hyp = max(hypotheses, key=lambda x: x['step'])
            final_metrics = compute_edge_metrics(final_hyp['edges'], true_edges)
            final_metrics['rollout_dir'] = str(rollout_dir)
            all_final_metrics.append(final_metrics)
            
        except Exception as e:
            print(f"Error processing {rollout_dir}: {e}")
            continue
    
    # 计算平均值
    if not all_final_metrics:
        return {
            'num_rollouts': 0,
            'average_final_precision': 0.0,
            'average_final_recall': 0.0,
            'average_final_f1': 0.0,
            'all_final_metrics': []
        }
    
    avg_precision = sum(m['precision'] for m in all_final_metrics) / len(all_final_metrics)
    avg_recall = sum(m['recall'] for m in all_final_metrics) / len(all_final_metrics)
    avg_f1 = sum(m['f1'] for m in all_final_metrics) / len(all_final_metrics)
    
    # 计算平均时间序列（对齐步骤）
    # 找到所有步骤的最大值
    max_steps = []
    for metrics in all_edge_metrics_over_time:
        if metrics:
            max_steps.append(max(m['step'] for m in metrics))
    
    if max_steps:
        max_step = max(max_steps)
        
        # 为每个步骤计算平均值
        avg_metrics_over_time = []
        for step in range(1, max_step + 1):
            step_metrics = []
            for metrics in all_edge_metrics_over_time:
                # 找到该步骤或之前最近的步骤
                step_data = None
                for m in metrics:
                    if m['step'] <= step:
                        step_data = m
                    else:
                        break
                
                if step_data:
                    step_metrics.append(step_data)
            
            if step_metrics:
                avg_metrics_over_time.append({
                    'step': step,
                    'precision': sum(m['precision'] for m in step_metrics) / len(step_metrics),
                    'recall': sum(m['recall'] for m in step_metrics) / len(step_metrics),
                    'f1': sum(m['f1'] for m in step_metrics) / len(step_metrics),
                    'num_rollouts': len(step_metrics)
                })
    else:
        avg_metrics_over_time = []
    
    return {
        'num_rollouts': len(all_final_metrics),
        'average_final_precision': avg_precision,
        'average_final_recall': avg_recall,
        'average_final_f1': avg_f1,
        'all_final_metrics': all_final_metrics,
        'average_metrics_over_time': avg_metrics_over_time  # 用于绘制平均折线图
    }


def find_all_valid_folders(base_dir: str) -> List[Dict[str, str]]:
    """在目录树中查找所有包含 graph_config.json 和 tracking.jsonl 的文件夹"""
    import os
    base_path = Path(base_dir)
    valid_folders = []
    
    # 使用 os.walk 正确遍历目录树
    for root, dirs, files in os.walk(base_dir):
        root_path = Path(root)
        
        # 查找 graph_config.json
        config_file = root_path / 'graph_config.json'
        if not config_file.exists():
            continue
        
        # 查找 tracking 文件（兼容 *_tracking.jsonl 与 *_tracking_simple.jsonl）
        tracking_files = list(root_path.glob('*_tracking.jsonl'))
        if not tracking_files:
            tracking_files = list(root_path.glob('*_tracking_simple.jsonl'))
        if not tracking_files:
            continue
        
        # 检查完成状态
        complete_files = list(root_path.glob('*_complete.txt'))
        completed = False
        if complete_files:
            try:
                with open(complete_files[0], 'r') as f:
                    content = f.read().strip()
                    completed = (content == '1')
            except Exception:
                completed = False
        
        # 添加到列表
        for tracking_file in tracking_files:
            valid_folders.append({
                'folder': str(root_path),
                'config': str(config_file),
                'tracking': str(tracking_file),
                'relative_path': str(root_path.relative_to(base_path)),
                'completed': completed
            })
    
    return valid_folders


def main():
    parser = argparse.ArgumentParser(
        description='Generate visualization data for causal graph interactions'
    )
    parser.add_argument(
        '--tracking_file',
        type=str,
        help='Path to the tracking.jsonl file'
    )
    parser.add_argument(
        '--config_file',
        type=str,
        help='Path to the graph_config.json file'
    )
    parser.add_argument(
        '--output_file',
        type=str,
        default='visualization_data.json',
        help='Output file for visualization data'
    )
    parser.add_argument(
        '--scan_dir',
        type=str,
        help='Scan directory for all valid folders'
    )
    parser.add_argument(
        '--multi_rollout_dirs',
        type=str,
        nargs='+',
        help='Multiple rollout directories to compute statistics across'
    )
    
    args = parser.parse_args()
    
    if args.scan_dir:
        # 扫描目录
        print(f"Scanning directory: {args.scan_dir}")
        valid_folders = find_all_valid_folders(args.scan_dir)
        print(f"Found {len(valid_folders)} valid folders")
        
        # 保存列表
        output_file = Path(args.scan_dir) / 'available_visualizations.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(valid_folders, f, indent=2, ensure_ascii=False)
        print(f"Saved folder list to: {output_file}")
        
    elif args.multi_rollout_dirs:
        # 计算多个 rollout 的统计信息
        print(f"Computing statistics across {len(args.multi_rollout_dirs)} rollouts")
        stats = compute_multi_rollout_statistics(args.multi_rollout_dirs)
        
        # 保存统计结果
        output_file = Path(args.output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        
        print(f"Saved multi-rollout statistics to: {output_file}")
        print(f"Average final precision: {stats['average_final_precision']:.3f}")
        print(f"Average final recall: {stats['average_final_recall']:.3f}")
        print(f"Average final F1: {stats['average_final_f1']:.3f}")
        
    elif args.tracking_file and args.config_file:
        # 生成单个可视化
        generate_visualization_data(args.tracking_file, args.config_file, args.output_file)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
