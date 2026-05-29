#!/usr/bin/env python3
"""
ABAC Policy Engine
Evaluates Attribute-Based Access Control policies and generates access matrix
"""

import json
import yaml
from typing import Dict, List, Any, Optional, Union
from pathlib import Path


def get_nested_attribute(obj: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Get nested attribute from object using dot notation.
    Example: get_nested_attribute(node, "system.os") -> node["system"]["os"]
    """
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    return value if value is not None else default


def evaluate_predicate(predicate: Dict[str, Any], attributes: Dict[str, Any]) -> bool:
    """
    Evaluate a single predicate against node attributes.
    
    Args:
        predicate: Dictionary with 'attribute', 'operator', and 'value' keys
        attributes: Node attributes dictionary
    
    Returns:
        True if predicate matches, False otherwise
    """
    attr_path = predicate.get("attribute")
    operator = predicate.get("operator", "==")
    expected_value = predicate.get("value")
    
    actual_value = get_nested_attribute(attributes, attr_path)
    
    # Handle different operators
    if operator == "==":
        return actual_value == expected_value
    elif operator == "!=":
        return actual_value != expected_value
    elif operator == ">":
        return actual_value > expected_value if isinstance(actual_value, (int, float)) else False
    elif operator == ">=":
        return actual_value >= expected_value if isinstance(actual_value, (int, float)) else False
    elif operator == "<":
        return actual_value < expected_value if isinstance(actual_value, (int, float)) else False
    elif operator == "<=":
        return actual_value <= expected_value if isinstance(actual_value, (int, float)) else False
    elif operator == "in":
        if isinstance(expected_value, list):
            return actual_value in expected_value
        return False
    elif operator == "not in":
        if isinstance(expected_value, list):
            return actual_value not in expected_value
        return True
    else:
        raise ValueError(f"Unsupported operator: {operator}")


def evaluate_constraint_group(constraint_group: Dict[str, Any], attributes: Dict[str, Any]) -> bool:
    """
    Evaluate a constraint group (all/any/none logic).
    
    Args:
        constraint_group: Dictionary with 'all', 'any', or 'none' keys containing lists of predicates
        attributes: Node attributes dictionary
    
    Returns:
        True if constraint group matches, False otherwise
    """
    # Evaluate 'all' (AND logic)
    if "all" in constraint_group:
        predicates = constraint_group["all"]
        return all(evaluate_predicate(pred, attributes) for pred in predicates)
    
    # Evaluate 'any' (OR logic)
    if "any" in constraint_group:
        predicates = constraint_group["any"]
        return any(evaluate_predicate(pred, attributes) for pred in predicates)
    
    # Evaluate 'none' (NOT logic)
    if "none" in constraint_group:
        predicates = constraint_group["none"]
        return not any(evaluate_predicate(pred, attributes) for pred in predicates)
    
    return False


def evaluate_environment(environment: List[Dict[str, Any]], env_context: Optional[Dict[str, Any]] = None) -> bool:
    """
    Evaluate environment constraints.
    
    Args:
        environment: List of environment predicates
        env_context: Optional environment context (defaults to empty dict if not provided)
    
    Returns:
        True if all environment constraints are satisfied
    """
    if not environment:
        return True
    
    env = env_context or {}
    
    for env_pred in environment:
        variable = env_pred.get("variable")
        operator = env_pred.get("operator", "==")
        expected_value = env_pred.get("value")
        
        # Get variable value from context (supports nested paths like "global.threat_level")
        actual_value = get_nested_attribute(env, variable, default=None)
        
        # Direct comparison (not using evaluate_predicate to avoid attribute path issues)
        if operator == "==":
            result = actual_value == expected_value
        elif operator == "!=":
            result = actual_value != expected_value
        elif operator == ">":
            result = actual_value > expected_value if isinstance(actual_value, (int, float)) else False
        elif operator == ">=":
            result = actual_value >= expected_value if isinstance(actual_value, (int, float)) else False
        elif operator == "<":
            result = actual_value < expected_value if isinstance(actual_value, (int, float)) else False
        elif operator == "<=":
            result = actual_value <= expected_value if isinstance(actual_value, (int, float)) else False
        elif operator == "in":
            result = actual_value in expected_value if isinstance(expected_value, list) else False
        elif operator == "not in":
            result = actual_value not in expected_value if isinstance(expected_value, list) else True
        else:
            raise ValueError(f"Unsupported operator: {operator}")
        
        if not result:
            return False
    
    return True


def evaluate_policy(
    policy: Dict[str, Any],
    subject_attributes: Dict[str, Any],
    object_attributes: Dict[str, Any],
    env_context: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Evaluate if a policy matches for given subject and object.
    
    Args:
        policy: Policy dictionary
        subject_attributes: Subject (source) node attributes
        object_attributes: Object (destination) node attributes
        env_context: Optional environment context
    
    Returns:
        True if policy matches, False otherwise
    """
    # Check subject constraints
    if "subject" in policy:
        if not evaluate_constraint_group(policy["subject"], subject_attributes):
            return False
    
    # Check object constraints
    if "object" in policy:
        if not evaluate_constraint_group(policy["object"], object_attributes):
            return False
    
    # Check environment constraints
    if "environment" in policy:
        if not evaluate_environment(policy["environment"], env_context):
            return False
    
    return True


def extract_l4_rules(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract L4 enforcement rules from policy.
    Only extracts ACCEPT rules (DROP rules are handled by default deny).
    
    Args:
        policy: Policy dictionary
    
    Returns:
        List of L4 rules in format: [{"proto": "tcp", "ports": [22], "action": "accept"}, ...]
    """
    l4_rules = []
    
    # Check both enforcement.layer4.rules and l4_enforcement (for JSON format)
    rules_list = []
    
    if "enforcement" in policy and "layer4" in policy["enforcement"]:
        layer4 = policy["enforcement"]["layer4"]
        if "rules" in layer4:
            rules_list = layer4["rules"]
    elif "l4_enforcement" in policy:
        rules_list = policy["l4_enforcement"]
    
    for rule in rules_list:
        action = rule.get("action", "ACCEPT").upper()
        
        # Skip DROP rules (they're handled by default deny in firewall)
        if action == "DROP" or action == "DENY":
            continue
        
        # Only process ACCEPT rules
        if action not in ["ACCEPT", "ALLOW"]:
            continue
        
        l4_rule = {"action": "accept"}
        
        if "proto" in rule:
            l4_rule["proto"] = rule["proto"].lower()
        
        # Handle port mappings: dport -> ports
        if "dport" in rule:
            dport = rule["dport"]
            if isinstance(dport, list):
                l4_rule["ports"] = dport
            else:
                l4_rule["ports"] = [dport]
        elif "ports" in rule:
            ports = rule["ports"]
            if isinstance(ports, list):
                l4_rule["ports"] = ports
            else:
                l4_rule["ports"] = [ports]
        
        # Only add if we have at least a protocol
        if "proto" in l4_rule:
            l4_rules.append(l4_rule)
    
    return l4_rules


def merge_l4_rules(rule_lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Merge multiple L4 rule lists, combining ports for same protocol.
    
    Args:
        rule_lists: List of L4 rule lists
    
    Returns:
        Merged and deduplicated L4 rules
    """
    # Group rules by protocol and action
    rule_map: Dict[tuple, set] = {}  # (proto, action) -> set of ports
    
    for rules in rule_lists:
        for rule in rules:
            proto = rule.get("proto", "").lower()
            action = rule.get("action", "accept").lower()
            ports = rule.get("ports", [])
            
            key = (proto, action)
            
            if key not in rule_map:
                rule_map[key] = set()
            
            if ports:
                rule_map[key].update(ports)
            else:
                # For protocols without ports (like ICMP), use empty set as marker
                rule_map[key] = set() if proto else rule_map[key]
    
    # Convert back to list format
    merged_rules = []
    for (proto, action), ports in rule_map.items():
        if proto:  # Skip empty protocols
            rule = {"proto": proto, "action": action}
            if ports:
                rule["ports"] = sorted(list(ports))
            merged_rules.append(rule)
    
    return merged_rules


def generate_access_matrix(
    nodes: List[Dict[str, Any]],
    policies: List[Dict[str, Any]],
    env_context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Generate access matrix by evaluating all policies for all node pairs.
    
    Args:
        nodes: List of node dictionaries
        policies: List of policy dictionaries
        env_context: Optional environment context
    
    Returns:
        Access matrix in format: [{"source": "node_a", "destination": "node_b", "connectivity": True, "l4_rules": [...]}, ...]
    """
    # Build node lookup by ID
    node_map = {node["id"]: node for node in nodes}
    
    access_matrix = []
    
    # Evaluate all node pairs
    for source_node in nodes:
        source_id = source_node["id"]
        source_attrs = source_node.get("attributes", {})
        
        for dest_node in nodes:
            dest_id = dest_node["id"]
            
            # Skip self-connections
            if source_id == dest_id:
                continue
            
            dest_attrs = dest_node.get("attributes", {})
            
            # Find all matching policies
            matching_policies = []
            for policy in policies:
                if policy.get("action") == "ALLOW":
                    if evaluate_policy(policy, source_attrs, dest_attrs, env_context):
                        matching_policies.append(policy)
            
            # Determine connectivity and collect L4 rules
            connectivity = len(matching_policies) > 0
            l4_rules = []
            
            if connectivity:
                # Merge L4 rules from all matching policies
                all_l4_rules = [extract_l4_rules(p) for p in matching_policies]
                l4_rules = merge_l4_rules(all_l4_rules)
            
            access_matrix.append({
                "source": source_id,
                "destination": dest_id,
                "connectivity": connectivity,
                "l4_rules": l4_rules
            })
    
    return access_matrix


def load_nodes_yaml(file_path: Path) -> List[Dict[str, Any]]:
    """Load nodes from YAML file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get("nodes", [])


def load_policies_yaml(file_path: Path) -> List[Dict[str, Any]]:
    """Load policies from YAML file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get("policies", [])


def convert_nodes_to_input_format(nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Convert node list to input.json format.
    
    Args:
        nodes: List of node dictionaries with YAML structure
    
    Returns:
        Dictionary mapping node IDs to node config in input.json format
    """
    result = {}
    
    for node in nodes:
        node_id = node["id"]
        
        # Extract network info - try different possible structures
        internal_ip = None
        public_key = None
        endpoint = None
        listen_port = 51820
        
        # Check for network section (JSON format)
        if "network" in node:
            net_info = node["network"]
            internal_ip = net_info.get("internal_ip") or net_info.get("ipv4")
            public_key = net_info.get("public_key")
            endpoint = net_info.get("endpoint")
            listen_port = net_info.get("listen_port", 51820)
        
        # Check top-level fields (YAML format)
        if not internal_ip:
            internal_ip = node.get("ipv4")
        if not public_key:
            public_key = node.get("identity") or node.get("public_key")
        if not endpoint:
            endpoint = node.get("endpoint")
        
        # Fallback: check attributes
        attributes = node.get("attributes", {})
        if not internal_ip:
            internal_ip = attributes.get("internal_ip")
        if not public_key:
            public_key = attributes.get("public_key")
        if not endpoint:
            endpoint = attributes.get("endpoint")
        
        if not internal_ip:
            raise ValueError(f"Missing internal_ip/ipv4 for node {node_id}")
        if not public_key:
            raise ValueError(f"Missing public_key/identity for node {node_id}")
        
        # Parse endpoint to ensure it has port
        if endpoint:
            if ":" not in str(endpoint):
                endpoint = f"{endpoint}:{listen_port}"
        else:
            # If no endpoint specified, we need external IP which we don't have
            # Use a placeholder that should be replaced
            endpoint = f"<EXTERNAL_IP>:{listen_port}"
        
        result[node_id] = {
            "internal_ip": str(internal_ip),
            "public_key": str(public_key),
            "listen_port": int(listen_port),
            "endpoint": str(endpoint)
        }
    
    return result


def generate_input_json(
    nodes_file: Path,
    policies_file: Path,
    output_file: Path,
    env_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Generate input.json from nodes and policies files.
    
    Args:
        nodes_file: Path to nodes YAML/JSON file
        policies_file: Path to policies YAML/JSON file
        output_file: Path to output JSON file
        env_context: Optional environment context
    """
    # Load nodes and policies
    if nodes_file.suffix in ['.yml', '.yaml']:
        nodes = load_nodes_yaml(nodes_file)
    else:
        with open(nodes_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            nodes = data.get("nodes", [])
    
    if policies_file.suffix in ['.yml', '.yaml']:
        policies = load_policies_yaml(policies_file)
    else:
        with open(policies_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            policies = data.get("policies", [])
    
    # Generate access matrix
    access_matrix = generate_access_matrix(nodes, policies, env_context)
    
    # Convert nodes to input format
    nodes_dict = convert_nodes_to_input_format(nodes)
    
    # Generate output JSON
    output_data = {
        "version": "1.0",
        "description": "SD-WAN Access Matrix Resolved IR",
        "nodes": nodes_dict,
        "access_matrix": access_matrix
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Generated input.json: {output_file}")
    print(f"  - Nodes: {len(nodes_dict)}")
    print(f"  - Access matrix entries: {len(access_matrix)}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python abac_engine.py <nodes.yml> <policies.yml> [output.json]", file=sys.stderr)
        sys.exit(1)
    
    nodes_file = Path(sys.argv[1])
    policies_file = Path(sys.argv[2])
    output_file = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("input.json")
    
    # Optional: you can provide environment context here
    env_context = {
        "global": {
            "threat_level": 2  # Example: low threat level
        }
    }
    
    generate_input_json(nodes_file, policies_file, output_file, env_context)

