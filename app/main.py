import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.api.app import create_app

# The API fails closed by default. For local development servers without tokens set,
# automatically enable development mode.
if not os.getenv("AGENT_PLATFORM_AUTH_MODE") and not os.getenv("AGENT_PLATFORM_API_TOKEN") and not os.getenv("AGENT_PLATFORM_AUTH_TOKENS"):
    os.environ["AGENT_PLATFORM_AUTH_MODE"] = "development"
    os.environ["AGENT_PLATFORM_DEV_MODE"] = "1"

app = create_app()

