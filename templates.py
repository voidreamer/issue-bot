"""
Issue templates — predefined structures for common issue types.

Each template has:
  - system_prompt_extra: appended to the base system prompt for LLM guidance
  - default_labels: labels automatically suggested for this template type
"""


TEMPLATES = {
    "default": {
        "system_prompt_extra": "",
        "default_labels": [],
    },
    "bug": {
        "system_prompt_extra": (
            "ADDITIONAL TEMPLATE INSTRUCTIONS (Bug Report):\n"
            "The issue body MUST also contain these sections after Technical Notes:\n"
            "   ## Steps to Reproduce\n"
            "   1. Step 1\n"
            "   2. Step 2\n\n"
            "   ## Expected Behavior\n"
            "   (what should happen)\n\n"
            "   ## Actual Behavior\n"
            "   (what actually happens)\n"
        ),
        "default_labels": ["bug"],
    },
    "feature": {
        "system_prompt_extra": (
            "ADDITIONAL TEMPLATE INSTRUCTIONS (Feature Request):\n"
            "The issue body MUST also contain these sections after Technical Notes:\n"
            "   ## User Story\n"
            "   As a [type of user], I want [goal] so that [benefit].\n\n"
            "   ## Design Notes\n"
            "   (UI/UX considerations, wireframe references, or design decisions)\n"
        ),
        "default_labels": ["enhancement"],
    },
    "chore": {
        "system_prompt_extra": (
            "ADDITIONAL TEMPLATE INSTRUCTIONS (Chore/Maintenance):\n"
            "This is a maintenance or housekeeping task, not a user-facing feature.\n"
            "Focus on technical debt, dependency updates, refactoring, or infrastructure.\n"
            "Keep the description concise and technical.\n"
        ),
        "default_labels": ["infrastructure"],
    },
}


def get_template(name: str) -> dict:
    """Get a template by name, falling back to 'default'."""
    return TEMPLATES.get(name, TEMPLATES["default"])


def get_template_names() -> set[str]:
    """Return the set of available template names (excluding 'default')."""
    return {k for k in TEMPLATES if k != "default"}
