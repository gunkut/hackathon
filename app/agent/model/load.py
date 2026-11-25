import os

from strands.models.bedrock import BedrockModel

# Latest Claude Sonnet allowed for this account. claude-sonnet-5-5 is blocked by the workshop
# model allowlist (explicit deny), so claude-sonnet-5 is used. Override with MODEL_ID if needed.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-5"


def load_model() -> BedrockModel:
    """Get Bedrock model client using IAM credentials."""
    return BedrockModel(model_id=os.getenv("MODEL_ID", DEFAULT_MODEL_ID))
