"""Configuration: loads the VA API key from the environment or the repo's .env file.

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
    """Raised when required configuration is missing or unusable."""


def is_sendable_api_key(api_key: str) -> bool:
    """Whether the key can go in an HTTP header.

    httpx only accepts ASCII header values, and h11 also rejects control characters and
    leading or trailing whitespace (a key pasted with a trailing newline).
    """
    return api_key.isascii() and api_key.isprintable() and api_key == api_key.strip()


def load_api_key(env_file: Path = ENV_FILE) -> str:
    """Load .env and return the VA API key, raising ConfigError if it's missing or unusable.

    A non-blank variable already set in the real environment wins over .env (load_dotenv's
    default), so a key passed in an MCP client's env config is used as is.
    """
    # load_dotenv never overwrites an existing variable, even an empty one, so a placeholder
    # left blank in an MCP client's env config would hide the key in .env.
    if not os.environ.get(API_KEY_VAR, "").strip():
        os.environ.pop(API_KEY_VAR, None)
    load_dotenv(env_file)
    api_key = os.environ.get(API_KEY_VAR, "")
    if not api_key.strip():
        raise ConfigError(
            f"{API_KEY_VAR} is not set. Copy .env.example to .env and add your "
            "VA Lighthouse sandbox key."
        )
    if not is_sendable_api_key(api_key):
        raise ConfigError(
            f"{API_KEY_VAR} contains spaces or characters that aren't allowed. Check it in "
            ".env, or in your MCP client's env config if it's set there."
        )
    return api_key
