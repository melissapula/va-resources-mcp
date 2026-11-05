"""Startup configuration: loads the VA API key from the repo's .env file.

The path is worked out from this file's location, not the working directory, because MCP
clients launch the server from wherever they like. That works because the package is
installed editable, so this file lives in the repo's src/ folder.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
API_KEY_VAR = "VA_API_KEY"


class ConfigError(Exception):
    """Raised when required configuration is missing."""


def load_api_key(env_file: Path = ENV_FILE) -> str:
    """Load .env and return the VA API key.

    A variable already set in the real environment wins over .env (load_dotenv's default),
    so a key passed in an MCP client's env config is used as is.
    """
    load_dotenv(env_file)
    api_key = os.environ.get(API_KEY_VAR, "")
    if not api_key.strip():
        raise ConfigError(
            f"{API_KEY_VAR} is not set. Copy .env.example to .env and add your "
            "VA Lighthouse sandbox key."
        )
    return api_key
