#!/usr/bin/env python3
"""
Main script: ABAC Policy Engine -> WireGuard & nftables Generator
Complete pipeline from nodes/policies to WireGuard configs and firewall rules
"""

import sys
import argparse
from pathlib import Path
from abac_engine import generate_input_json
from generator import main as generator_main
import json


def main():
    parser = argparse.ArgumentParser(
        description="TrivialTier Policy Generator: ABAC -> WireGuard & nftables"
    )
    parser.add_argument("nodes_file", help="Path to nodes YAML/JSON file")
    parser.add_argument("policies_file", help="Path to policies YAML/JSON file")
    parser.add_argument("-o", "--output-dir", default="output", help="Output directory (default: output)")
    parser.add_argument("--private-keys", help="Path to private_keys.json (optional)")
    parser.add_argument("--intermediate", help="Path to save intermediate input.json (optional)")
    parser.add_argument("--env-threat-level", type=int, default=2, help="Global threat level (default: 2)")
    
    args = parser.parse_args()
    
    nodes_file = Path(args.nodes_file)
    policies_file = Path(args.policies_file)
    output_dir = Path(args.output_dir)
    
    if not nodes_file.exists():
        print(f"Error: Nodes file not found: {nodes_file}", file=sys.stderr)
        sys.exit(1)
    
    if not policies_file.exists():
        print(f"Error: Policies file not found: {policies_file}", file=sys.stderr)
        sys.exit(1)
    
    # Step 1: Generate input.json from ABAC evaluation
    intermediate_file = Path(args.intermediate) if args.intermediate else output_dir / "input.json"
    intermediate_file.parent.mkdir(parents=True, exist_ok=True)
    
    env_context = {
        "global": {
            "threat_level": args.env_threat_level
        }
    }
    
    print("Step 1: Evaluating ABAC policies...")
    generate_input_json(nodes_file, policies_file, intermediate_file, env_context)
    
    # Step 2: Generate WireGuard configs and nftables policies
    print("\nStep 2: Generating WireGuard configs and nftables policies...")
    
    # Temporarily modify sys.argv for generator_main
    old_argv = sys.argv[:]
    try:
        sys.argv = ["generator.py", str(intermediate_file), str(output_dir)]
        if args.private_keys:
            sys.argv.append(args.private_keys)
        generator_main()
    finally:
        sys.argv = old_argv
    
    print(f"\nComplete! Output directory: {output_dir}")
    print(f"  - Intermediate input.json: {intermediate_file}")
    print(f"  - WireGuard configs: {output_dir}/*.conf")
    print(f"  - nftables policies: {output_dir}/*.nft")


if __name__ == "__main__":
    main()

