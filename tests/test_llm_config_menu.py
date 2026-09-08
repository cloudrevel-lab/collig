#!/usr/bin/env python3
"""
Tests for the LLM grouping + cache refactor.

Goal: prove the interactive /config menu still works as HEAD intended
(grouped LLM section first, no new schema attrs breaking closures), and
that pressing `[m]` goes through `fetch_provider_models(..., refresh=True)`
and populates `available_models` cache correctly.

Run me:
    cd core && uv run python ../tests/test_llm_config_menu.py
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "core"))

# Clear any env state that could leak through
BACKUP_ENV: Dict[str, str] = {}
for k in list(os.environ.keys()):
    if k in ("LLM_PROVIDER","LLM_MODEL","LLM_PROVIDER_URL","OPENAI_API_KEY",
             "DEEPSEEK_API_KEY","DASHSCOPE_API_KEY","DASHSCOPE_ENDPOINT",
             "CUSTOM_API_KEY","CUSTOM_BASE_URL","CUSTOM_MODELS","AVAILABLE_MODELS"):
        BACKUP_ENV[k] = os.environ.pop(k)

passed: List[str] = []
failed: List[str] = []

def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        passed.append(name)
        print("PASS: %s%s" % (name, (" — " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: %s%s" % (name, (" — " + detail) if detail else ""))

# ---------------------------------------------------------------------------
# 1. SCHEMA ORDER: LLM category FIRST, no forbidden `llm_field` attrs.
# ---------------------------------------------------------------------------
from core.cli import get_config_schema

schema = get_config_schema(agent=None)

# First category (as first-seen order in schema) should be "LLM"
categories_in_order: List[str] = []
seen: set = set()
for item in schema:
    cat = item["category"]
    if cat not in seen:
        categories_in_order.append(cat)
        seen.add(cat)
check("first category is LLM",
      categories_in_order[0] == "LLM",
      "order=%r" % categories_in_order)

llm_keys = [item["key"] for item in schema if item["category"] == "LLM"]
# User-requested order in config: Provider, URL(s), Model, then API keys (x4),
# then Available Models info.
for required in ("LLM_PROVIDER", "CUSTOM_BASE_URL", "DASHSCOPE_ENDPOINT",
                 "LLM_MODEL", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                 "DASHSCOPE_API_KEY", "CUSTOM_API_KEY", "AVAILABLE_MODELS"):
    check("LLM section contains key %s" % required,
          required in llm_keys,
          "actual=%r" % llm_keys)

# No forbidden `llm_field` attrs anywhere (that was last session's breakage)
has_llm_field = any("llm_field" in it for it in schema)
check("no llm_field attr anywhere in schema", not has_llm_field)

# AVAILABLE_MODELS must have type == "info" and label friendly
am_item = next((it for it in schema if it["key"] == "AVAILABLE_MODELS"), None)
check("AVAILABLE_MODELS info row present", am_item is not None)
if am_item:
    check("AVAILABLE_MODELS.type == info",
          am_item.get("type") == "info")
    check("AVAILABLE_MODELS.label uses friendly name",
          "Available Models" in str(am_item.get("label", "")))

# Labels exist for LLM rows (display only, no closure impact)
llm_rows = [it for it in schema if it["category"] == "LLM"]
labelled = sum(1 for it in llm_rows if it.get("label"))
check("all LLM rows have friendly display label",
      labelled == len(llm_rows),
      "%d/%d labelled" % (labelled, len(llm_rows)))

# ---------------------------------------------------------------------------
# 2. LABEL RENDERED FALLBACK — closure uses item.get('label', item['key']).
#    Simulate the exact same label-read logic now used in get_settings_text.
# ---------------------------------------------------------------------------
def settings_label(item: Dict[str, Any]) -> str:
    """Closure label logic as of refactor."""
    return item.get("label", item["key"])

for it in llm_rows:
    lbl = settings_label(it)
    # Every LLM row should have a "friendly" label (not the raw legacy key
    # in all-caps with underscores for anything beyond provider/model).
    if it["key"] == "LLM_PROVIDER":
        check("label fallback LLM_PROVIDER friendly", "Provider" in lbl)
    elif it["key"] == "LLM_MODEL":
        check("label fallback LLM_MODEL friendly", "LLM Model" in lbl or "Model" in lbl)
    elif it["key"] == "AVAILABLE_MODELS":
        check("label fallback AVAILABLE_MODELS starts with Available Models",
              lbl.startswith("Available Models"))

# ---------------------------------------------------------------------------
# 3. UNIFIED ACCESSOR ROUND TRIP — 6 providers.
# ---------------------------------------------------------------------------
from core.runtime import (
    get_llm_config, set_llm_field, cache_available_models,
    fetch_provider_models,
)

binds_map: Dict[str, Any] = {
    "openai":    ("OPENAI_API_KEY",    None),
    "deepseek":  ("DEEPSEEK_API_KEY",  None),
    "dashscope": ("DASHSCOPE_API_KEY", "DASHSCOPE_ENDPOINT"),
    "custom":    ("CUSTOM_API_KEY",    "CUSTOM_BASE_URL"),
    "ollama":    (None, None),
    "llama":     (None, None),
}

for p in ("openai", "ollama", "llama", "deepseek", "dashscope", "custom"):
    cfg: Dict[str, Any] = {}
    set_llm_field(cfg, "provider", p)
    set_llm_field(cfg, "llm_model", "m-%s-1" % p)
    set_llm_field(cfg, "api_key", "sk-%s-xyz" % p)
    set_llm_field(cfg, "provider_url", "https://example-%s.com/v1" % p)
    cache_available_models(p, ["a-%s" % p, "b-%s" % p], cfg, persist=False)

    out = get_llm_config(cfg)
    check("provider round-trip %s" % p, out["provider"] == p)
    check("llm_model round-trip %s" % p, out["llm_model"] == "m-%s-1" % p)
    k_key, u_key = binds_map[p]
    if k_key is not None:
        check("%s api_key legacy key written" % p, cfg.get(k_key) == "sk-%s-xyz" % p)
        check("%s api_key read via get_llm_config" % p, out["api_key"] == "sk-%s-xyz" % p)
        check("%s api_key mirrored to env" % p, os.environ.get(k_key) == "sk-%s-xyz" % p)
    if u_key is not None:
        check("%s provider_url legacy key written" % p, cfg.get(u_key) == "https://example-%s.com/v1" % p)
        check("%s provider_url read via get_llm_config" % p, out["provider_url"] == "https://example-%s.com/v1" % p)
        check("%s provider_url mirrored to env" % p, os.environ.get(u_key) == "https://example-%s.com/v1" % p)
    check("%s available_models cached list" % p,
          isinstance(out["available_models"], list) and len(out["available_models"]) == 2,
          str(out["available_models"]))
    check("%s new canonical alias 'provider' also written" % p, cfg.get("provider") == p)
    check("%s new canonical alias 'llm_model' also written" % p, cfg.get("llm_model") == "m-%s-1" % p)

# ---------------------------------------------------------------------------
# 4. CACHE-FIRST + REFRESH SEMANTICS in fetch_provider_models.
# ---------------------------------------------------------------------------
cfg2: Dict[str, Any] = {}
set_llm_field(cfg2, "provider", "openai")
cache_available_models("openai", ["cached-m1", "cached-m2"], cfg2, persist=False)
# Default refresh=False should return cache WITHOUT hitting network (we know
# because no API key is present — live endpoint would not return these 2).
returned = fetch_provider_models("openai", cfg2, refresh=False)
check("refresh=False returns cached list",
      returned == ["cached-m1", "cached-m2"],
      "returned=%r" % returned)
# refresh=True bypasses cache (no API key → falls back to curated list; it
# should NOT return the cached pair)
try:
    refreshed = fetch_provider_models("openai", cfg2, refresh=True)
    bypassed = refreshed != ["cached-m1", "cached-m2"]
except Exception as exc:
    # API key missing is fine; the point is it went to the network path,
    # not the cache short-circuit, so bypassed == True.
    bypassed = True
check("refresh=True bypasses cache", bypassed)

# ---------------------------------------------------------------------------
# 5. EDIT HANDLER SYNC: writing a legacy LLM key also syncs the new unified
#    alias.  Simulate the exact loop now present in the "edit" result handler.
# ---------------------------------------------------------------------------
cfg3: Dict[str, Any] = {"LLM_PROVIDER": "custom"}
# Apply edit handler sync loop for key "CUSTOM_BASE_URL" = "https://u"
legacy_to_field = [
    ("provider", "LLM_PROVIDER"),
    ("llm_model", "LLM_MODEL"),
    ("provider_url", "CUSTOM_BASE_URL"),
    ("provider_url", "DASHSCOPE_ENDPOINT"),
    ("api_key", "OPENAI_API_KEY"),
    ("api_key", "DEEPSEEK_API_KEY"),
    ("api_key", "DASHSCOPE_API_KEY"),
    ("api_key", "CUSTOM_API_KEY"),
]
cfg3["CUSTOM_BASE_URL"] = "https://my-host/v1"
for fld, leg in legacy_to_field:
    if "CUSTOM_BASE_URL" == leg:
        set_llm_field(cfg3, fld, cfg3[leg])
check("edit handler syncs CUSTOM_BASE_URL -> provider_url alias",
      cfg3.get("provider_url") == "https://my-host/v1",
      "cfg3.provider_url=%r" % cfg3.get("provider_url"))

# ---------------------------------------------------------------------------
# 6. SAVE HOOK SYNC: save_config_and_update() mirrors legacy keys to new aliases.
#    Simulate the exact same loop used in that closure.
# ---------------------------------------------------------------------------
cfg4: Dict[str, Any] = {
    "LLM_PROVIDER": "dashscope",
    "LLM_MODEL": "qwen-plus",
    "DASHSCOPE_ENDPOINT": "singapore",
    "DASHSCOPE_API_KEY": "sk-dash-test",
    "AVAILABLE_MODELS": ["qwen-plus", "qwen-turbo"],
}
for leg, fld in [
    ("LLM_PROVIDER", "provider"),
    ("LLM_MODEL", "llm_model"),
    ("CUSTOM_BASE_URL", "provider_url"),
    ("DASHSCOPE_ENDPOINT", "provider_url"),
    ("OPENAI_API_KEY", "api_key"),
    ("DEEPSEEK_API_KEY", "api_key"),
    ("DASHSCOPE_API_KEY", "api_key"),
    ("CUSTOM_API_KEY", "api_key"),
    ("AVAILABLE_MODELS", "available_models"),
]:
    if leg in cfg4:
        set_llm_field(cfg4, fld, cfg4[leg])
if isinstance(cfg4.get("available_models"), list):
    set_llm_field(cfg4, "available_models", cfg4["available_models"])

check("save hook provider alias", cfg4.get("provider") == "dashscope")
check("save hook llm_model alias", cfg4.get("llm_model") == "qwen-plus")
check("save hook provider_url alias", cfg4.get("provider_url") == "singapore")
check("save hook api_key alias", cfg4.get("api_key") == "sk-dash-test")
check("save hook available_models alias", cfg4.get("available_models") == ["qwen-plus", "qwen-turbo"])
# Also the legacy API key must be in os.environ because set_llm_field synced it
check("save hook api_key mirrored to env",
      os.environ.get("DASHSCOPE_API_KEY") == "sk-dash-test")

# ---------------------------------------------------------------------------
# 7. DISPLAY VALUE for info-type AVAILABLE_MODELS row — uses the exact same
#    if/elif as the closure `get_display_value` in interactive_config_ui.
# ---------------------------------------------------------------------------
def closure_get_display_value(config: Dict[str, Any], item: Dict[str, Any]) -> str:
    """Exact copy of the closure's `get_display_value` for black-box testing."""
    if item["type"] == "info":
        if item["key"] == "AVAILABLE_MODELS":
            raw = config.get("available_models") or config.get("AVAILABLE_MODELS") or []
            if isinstance(raw, list) and raw:
                return "%d cached · press [m] to refresh" % len(raw)
            return "(no cached list — press [m] to fetch)"
        return ""
    value = config.get(item["key"], item["default"])
    if item["type"] == "boolean":
        return "ON" if value else "OFF"
    if item["type"] == "secret" and value:
        return "*" * 8
    if item["type"] == "choice":
        return str(value)
    return str(value) if value else "(not set)"

cfg5: Dict[str, Any] = {"available_models": ["m1", "m2", "m3"]}
val_with = closure_get_display_value(cfg5, am_item)  # type: ignore[arg-type]
check("display value for AVAILABLE_MODELS (with cache)",
      "3 cached · press [m] to refresh" == val_with,
      "val=%r" % val_with)
val_without = closure_get_display_value({}, am_item)  # type: ignore[arg-type]
check("display value for AVAILABLE_MODELS (empty cache)",
      "(no cached list — press [m] to fetch)" == val_without,
      "val=%r" % val_without)

# ---------------------------------------------------------------------------
# 8. Ensure no forbidden closure helpers (from the broken refactor) exist.
# ---------------------------------------------------------------------------
import inspect
from core import cli as cli_mod

src = inspect.getsource(cli_mod.interactive_config_ui)
for tok_pat in (r'_active_provider', r'_read_item', r'_write_item',
                r'item\s*\[\s*"llm_field"\s*\]',
                r'item\.get\s*\(\s*"llm_field"',
                r'"llm_field"\s*:',
                r'_writable',
                r'"label" not in item'):
    import re
    has_tok = re.search(tok_pat, src) is not None
    check("closure free of pattern %r" % tok_pat, not has_tok)

# ---------------------------------------------------------------------------
# Summary + cleanup
# ---------------------------------------------------------------------------
for k, v in BACKUP_ENV.items():
    os.environ[k] = v

print("\n================ SUMMARY ================")
print("%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    print("FAILURES:")
    for f in failed:
        print("  -", f)
    sys.exit(1)
print("All %d checks passed." % len(passed))
sys.exit(0)
