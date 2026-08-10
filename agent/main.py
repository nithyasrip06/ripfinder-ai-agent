import json
from pathlib import Path

from reasoning_engine import RiskInput, calculate_risk
from llm_agent import generate_safety_message


def load_sample_input():
    project_root = Path(__file__).resolve().parent.parent
    input_path = project_root / "sample_inputs" / "sample_input.json"

    with open(input_path, "r") as file:
        return json.load(file)


def main():
    raw_data = load_sample_input()
    risk_input = RiskInput(**raw_data)

    # Step 1: deterministic risk scoring
    risk_output = calculate_risk(risk_input)

    print("\n--- RULE-BASED RISK OUTPUT ---")
    print(risk_output.model_dump_json(indent=2))

    # Step 2: Claude-generated AR safety message
    #safety_message = generate_safety_message(risk_input, risk_output)

    print("\n--- CLAUDE SAFETY MESSAGE ---")
    #print(json.dumps(safety_message, indent=2))


if __name__ == "__main__":
    main()