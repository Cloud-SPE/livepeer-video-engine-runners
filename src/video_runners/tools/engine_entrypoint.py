"""Launch a Compose-owned engine from the same model catalog as its runner.

Uses only the standard library so upstream GPU images need no runner packages.
Managed mode launches the trusted controller catalog directly instead.
"""

import argparse
import json
import os
from pathlib import Path


def launch_spec(catalog: Path, model: str = "") -> tuple[list[str], dict[str, str]]:
    data = json.loads(catalog.read_text())
    selected = model or data["default"]
    models = {entry["id"]: entry for entry in data["models"]}
    if selected not in models:
        raise ValueError(f"unknown model {selected!r}; choose {sorted(models)}")
    spec = models[selected]
    command = list(spec["command"])
    # A separate engine must listen on its container interface. Change the flag,
    # not arbitrary occurrences of an address inside other arguments.
    if "--host" not in command or command.index("--host") + 1 == len(command):
        raise ValueError("engine catalog requires an explicit --host argument")
    command[command.index("--host") + 1] = "0.0.0.0"
    return command, {key: str(value) for key, value in spec.get("env", {}).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    try:
        command, environment = launch_spec(args.catalog, args.model)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    os.execvpe(command[0], command, {**os.environ, **environment})


if __name__ == "__main__":
    main()
