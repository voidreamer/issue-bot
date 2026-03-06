"""
LLM abstraction — supports OpenAI, Anthropic, Ollama, and Gemini providers.
"""

import json
import re
import logging

import httpx

log = logging.getLogger("issue-bot")

PROVIDER_DEFAULTS = {
    "openai":    {"model": "gpt-4o",                      "url": "https://api.openai.com/v1/chat/completions"},
    "anthropic": {"model": "claude-sonnet-4-5-20250514",   "url": "https://api.anthropic.com/v1/messages"},
    "ollama":    {"model": "llama3",                       "url": "http://localhost:11434/v1/chat/completions"},
    "gemini":    {"model": "gemini-2.0-flash",             "url": "https://generativelanguage.googleapis.com/v1beta/chat/completions"},
}

SYSTEM_PROMPT = """You are an expert project manager for a software team. When given a short description \
and story-point weight, you produce a well-structured GitLab issue in Markdown.

RULES:
1. Generate a concise title using a short prefix (e.g. "MVP-XX:" or "INFRA-XX:" or "FIX-XX:") followed by a clear title.
2. The body MUST contain these sections:
   ## Summary
   (1-3 sentences)

   ## Context & Motivation
   (why this matters)

   ## Acceptance Criteria
   - [ ] criterion 1
   - [ ] criterion 2

   ## Technical Notes
   (optional implementation hints)

3. Suggest 1-4 labels from this list: {labels}
   Pick only labels that genuinely fit.
4. If PROJECT CONTEXT is provided, consider existing issues and milestones. \
Reference related issues by number (e.g. "Related: #42") when relevant. Avoid duplicating existing work.
5. Respond ONLY with valid JSON, no markdown fences, no extra text:
   {{"title": "...", "description": "...", "labels": ["label1","label2"]}}"""

EPIC_SYSTEM_PROMPT = """You are an expert project manager. Given a high-level goal and story-point budget, \
break it into a parent epic issue and 3-8 child issues.

RULES:
1. The parent issue is an overview/tracking issue.
2. Each child issue is a concrete, actionable task.
3. Distribute points across children (they should roughly sum to the budget).
4. Use labels from: {labels}
5. If PROJECT CONTEXT is provided, consider existing issues and milestones. \
Reference related issues by number when relevant. Avoid duplicating existing work.
6. Respond ONLY with valid JSON:
   {{"parent": {{"title": "...", "description": "...", "labels": ["..."]}},
    "children": [{{"title": "...", "description": "...", "labels": ["..."], "points": N}}, ...]}}"""

PLAN_SYSTEM_PROMPT = """You are an expert project manager. Given a list of goals, generate 4-8 \
independent, well-structured issues for a sprint.

RULES:
1. Each issue should be self-contained and actionable.
2. Assign reasonable point values (1-8) based on complexity.
3. Use the same issue structure as single issues (Summary, Context, Acceptance Criteria, Technical Notes).
4. Use labels from: {labels}
5. If PROJECT CONTEXT is provided, consider existing issues and milestones. \
Reference related issues by number when relevant. Avoid duplicating existing work.
6. Respond ONLY with valid JSON:
   {{"issues": [{{"title": "...", "description": "...", "labels": ["..."], "points": N}}, ...]}}"""


def format_system_prompt(labels: str, template_extra: str = "") -> str:
    prompt = SYSTEM_PROMPT.format(labels=labels)
    if template_extra:
        prompt += "\n\n" + template_extra
    return prompt


async def call_llm(
    http_client: httpx.AsyncClient,
    cfg: dict,
    prompt: str,
    points: int,
    labels: str = "",
    template_extra: str = "",
    context: str = "",
) -> dict:
    """Call the configured LLM provider and return parsed JSON."""
    provider = cfg["llm_provider"].lower()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])
    model    = cfg["llm_model"] or defaults["model"]
    base_url = cfg["llm_base_url"] or defaults["url"]
    system   = format_system_prompt(labels, template_extra)
    user_msg = f"Story points: {points}\nDescription: {prompt}"
    if context:
        user_msg += f"\n\n--- PROJECT CONTEXT ---\n{context}"

    if provider == "anthropic":
        resp = await http_client.post(base_url, headers={
            "x-api-key": cfg["llm_api_key"], "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={"model": model, "max_tokens": 2048, "system": system,
                 "messages": [{"role": "user", "content": user_msg}]})
    else:
        headers = {"content-type": "application/json"}
        if cfg["llm_api_key"]:
            headers["Authorization"] = f"Bearer {cfg['llm_api_key']}"
        resp = await http_client.post(base_url, headers=headers, json={
            "model": model, "temperature": 0.4,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user_msg}]})

    resp.raise_for_status()
    body = resp.json()
    text = (body["content"][0]["text"] if provider == "anthropic"
            else body["choices"][0]["message"]["content"])
    return _parse_llm_json(text)


async def call_llm_epic(
    http_client: httpx.AsyncClient,
    cfg: dict,
    prompt: str,
    points: int,
    labels: str = "",
    context: str = "",
) -> dict:
    """Call LLM with the epic system prompt. Returns {parent, children}."""
    provider = cfg["llm_provider"].lower()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])
    model    = cfg["llm_model"] or defaults["model"]
    base_url = cfg["llm_base_url"] or defaults["url"]
    system   = EPIC_SYSTEM_PROMPT.format(labels=labels)
    user_msg = f"Total story points budget: {points}\nGoal: {prompt}"
    if context:
        user_msg += f"\n\n--- PROJECT CONTEXT ---\n{context}"

    if provider == "anthropic":
        resp = await http_client.post(base_url, headers={
            "x-api-key": cfg["llm_api_key"], "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={"model": model, "max_tokens": 4096, "system": system,
                 "messages": [{"role": "user", "content": user_msg}]})
    else:
        headers = {"content-type": "application/json"}
        if cfg["llm_api_key"]:
            headers["Authorization"] = f"Bearer {cfg['llm_api_key']}"
        resp = await http_client.post(base_url, headers=headers, json={
            "model": model, "temperature": 0.4,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user_msg}]})

    resp.raise_for_status()
    body = resp.json()
    text = (body["content"][0]["text"] if provider == "anthropic"
            else body["choices"][0]["message"]["content"])
    return _parse_llm_json(text)


async def call_llm_plan(
    http_client: httpx.AsyncClient,
    cfg: dict,
    goals: str,
    labels: str = "",
    context: str = "",
) -> dict:
    """Call LLM with the plan system prompt. Returns {issues: [...]}."""
    provider = cfg["llm_provider"].lower()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])
    model    = cfg["llm_model"] or defaults["model"]
    base_url = cfg["llm_base_url"] or defaults["url"]
    system   = PLAN_SYSTEM_PROMPT.format(labels=labels)
    user_msg = f"Sprint goals: {goals}"
    if context:
        user_msg += f"\n\n--- PROJECT CONTEXT ---\n{context}"

    if provider == "anthropic":
        resp = await http_client.post(base_url, headers={
            "x-api-key": cfg["llm_api_key"], "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={"model": model, "max_tokens": 4096, "system": system,
                 "messages": [{"role": "user", "content": user_msg}]})
    else:
        headers = {"content-type": "application/json"}
        if cfg["llm_api_key"]:
            headers["Authorization"] = f"Bearer {cfg['llm_api_key']}"
        resp = await http_client.post(base_url, headers=headers, json={
            "model": model, "temperature": 0.4,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user_msg}]})

    resp.raise_for_status()
    body = resp.json()
    text = (body["content"][0]["text"] if provider == "anthropic"
            else body["choices"][0]["message"]["content"])
    return _parse_llm_json(text)


def _parse_llm_json(text: str) -> dict:
    """Strip markdown fences and parse JSON from LLM response."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)
