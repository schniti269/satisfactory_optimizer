"""
Satisfactory 1.1 - AWESOME Sink Point Optimizer
Maximizes AWESOME Sink points/min using ALL resource nodes on the map.

Usage:
    python main.py                  # Run full optimization + flowchart
    python main.py --no-flowchart   # Run optimization only (no Graphviz needed)
    python main.py --no-alternates  # Exclude alternate recipes
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Satisfactory 1.1 AWESOME Sink Optimizer"
    )
    parser.add_argument(
        "--no-flowchart", action="store_true",
        help="Skip flowchart generation (no Graphviz dependency needed)"
    )
    parser.add_argument(
        "--no-alternates", action="store_true",
        help="Exclude alternate recipes from optimization"
    )
    parser.add_argument(
        "--output", default="satisfactory_flowchart",
        help="Output file path for flowchart (without extension)"
    )
    args = parser.parse_args()

    # Step 1: Load game data
    print("=" * 60)
    print("  Satisfactory 1.1 - AWESOME Sink Optimizer")
    print("=" * 60)
    print()

    from satisfactory_data import load_all_data
    data = load_all_data()

    # Optionally filter out alternate recipes
    if args.no_alternates:
        original_count = len(data["recipes"])
        data["recipes"] = [
            r for r in data["recipes"]
            if not r["name"].startswith("Alternate:")
        ]
        print(f"Filtered alternates: {original_count} -> {len(data['recipes'])} recipes")

    # Step 2: Run optimizer
    from satisfactory_optimizer import build_and_solve
    solution = build_and_solve(data, verbose=True)

    if not solution:
        print("Optimization failed!")
        sys.exit(1)

    # Step 3: Generate flowchart
    if not args.no_flowchart:
        print("\n" + "=" * 60)
        print("  Generating Flowchart")
        print("=" * 60)
        try:
            from satisfactory_flowchart import generate_flowchart
            generate_flowchart(solution, data["resource_supply"], args.output)
        except ImportError as e:
            print(f"Flowchart generation requires 'graphviz' package: {e}")
            print("Install with: pip install graphviz")
        except Exception as e:
            print(f"Flowchart generation error: {e}")
            import traceback
            traceback.print_exc()

    print("\nDone!")


if __name__ == "__main__":
    main()
