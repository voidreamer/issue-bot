"""
Slash command parser for /issue commands.

Parses sub-commands, project aliases, template names, points, and prompt text.
Priority: sub-command → project alias → template name → points → prompt
"""

import re
from dataclasses import dataclass, field


_ASSIGNEE_RE = re.compile(r"^@([a-zA-Z0-9_.\-]+)$")


@dataclass
class ParsedCommand:
    action: str = "create"          # help, create, list, search, epic, plan
    project: str = ""               # resolved project alias
    points: int = 1                 # story points
    prompt: str = ""                # user's description
    template: str = ""              # bug, feature, chore, etc.
    raw_text: str = ""              # original text
    assignees: list[str] = field(default_factory=list)  # @username tokens

    # search-specific
    search_query: str = ""


# Sub-commands recognized before anything else
SUB_COMMANDS = {"help", "list", "search", "epic", "plan"}


def parse_issue_command(
    text: str,
    project_aliases: set[str] | None = None,
    template_names: set[str] | None = None,
) -> ParsedCommand:
    """Parse a slash command text into a structured ParsedCommand.

    Parsing order per token (left to right):
      1. Sub-command (help, list, search, epic, plan)
      2. Project alias (known project key)
      3. Template name (bug, feature, chore, etc.)
      4. Points (integer)
      5. Everything else is the prompt
    """
    project_aliases = project_aliases or set()
    template_names = template_names or set()
    raw = text.strip()
    cmd = ParsedCommand(raw_text=raw)

    if not raw:
        cmd.action = "help"
        return cmd

    tokens = raw.split()
    pos = 0

    # 1. Check first token for sub-command
    first = tokens[0].lower()
    if first in SUB_COMMANDS:
        cmd.action = first
        pos = 1

        # search: rest is the query
        if cmd.action == "search":
            cmd.search_query = " ".join(tokens[pos:])
            return cmd

        # list: next token might be a project alias
        if cmd.action == "list" and pos < len(tokens):
            candidate = tokens[pos].lower()
            if candidate in {a.lower() for a in project_aliases}:
                cmd.project = _resolve_alias(candidate, project_aliases)
                pos += 1
            # nothing more needed for list
            return cmd

        # help: nothing more to parse
        if cmd.action == "help":
            return cmd

    # Extract @username tokens from remaining tokens (create/epic/plan only)
    rest = tokens[pos:]
    assignee_tokens = []
    filtered = []
    for tok in rest:
        m = _ASSIGNEE_RE.match(tok)
        if m:
            assignee_tokens.append(m.group(1))
        else:
            filtered.append(tok)
    cmd.assignees = assignee_tokens
    tokens = tokens[:pos] + filtered

    # For create / epic / plan — continue parsing remaining tokens
    while pos < len(tokens):
        tok = tokens[pos]
        tok_lower = tok.lower()

        # Project alias
        if not cmd.project and tok_lower in {a.lower() for a in project_aliases}:
            cmd.project = _resolve_alias(tok_lower, project_aliases)
            pos += 1
            continue

        # Template name
        if not cmd.template and tok_lower in {t.lower() for t in template_names}:
            cmd.template = _resolve_name(tok_lower, template_names)
            pos += 1
            continue

        # Points (integer)
        if cmd.points == 1:
            try:
                cmd.points = int(tok)
                pos += 1
                continue
            except ValueError:
                pass

        # Everything remaining is the prompt
        cmd.prompt = " ".join(tokens[pos:])
        break

    return cmd


def _resolve_alias(lower_candidate: str, aliases: set[str]) -> str:
    """Return the original-case alias matching a lowercase candidate."""
    for a in aliases:
        if a.lower() == lower_candidate:
            return a
    return lower_candidate


def _resolve_name(lower_candidate: str, names: set[str]) -> str:
    """Return the original-case name matching a lowercase candidate."""
    for n in names:
        if n.lower() == lower_candidate:
            return n
    return lower_candidate
