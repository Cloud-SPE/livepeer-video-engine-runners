"""Small, explicit standard-library helpers for checkout-based operator tools."""

from pathlib import Path
import subprocess


def read_env(*paths: Path) -> dict[str, str]:
    """Read initializer-style KEY=value files; later files override earlier ones.

    Values are literal, with optional surrounding quotes. This is not a shell
    or a Compose dotenv interpreter: never execute or expand private settings.
    Missing files are optional, as in the validation commands using this helper.
    """
    values = {}
    for path in paths:
        if path.exists():
            for line in path.read_text().splitlines():
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
    return values


def command_output(*args: str, cwd: Path | None = None) -> str:
    """Capture a checked command without invoking a shell or choosing resources."""
    return subprocess.check_output(args, cwd=cwd, text=True).strip()
