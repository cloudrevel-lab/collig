#!/usr/bin/env python3
"""Tests for distilled personalities and the shared /distill,/chatto,/memory commands."""

from __future__ import annotations

import atexit
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from core.commands import handle_slash_command  # noqa: E402
from core.personality import PersonalityManager, reset_personality_manager, slugify  # noqa: E402
from core.runtime import load_config, save_config  # noqa: E402
from core.user_memory import reset_user_memory  # noqa: E402

# The /memory on|off commands write the real config.json; leave the developer's
# settings exactly as they were even if an assertion fails.
_CONFIG_BEFORE = load_config()
atexit.register(lambda: save_config(_CONFIG_BEFORE))

passed = []
failed = []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
        print("PASS: " + name + ((" - " + detail) if detail else ""))
    else:
        failed.append(name)
        print("FAIL: " + name + ((" - " + detail) if detail else ""))


DOSSIER = """# Spider-Man

## Who they are
A friendly neighbourhood hero from Queens.
## Core worldview
With great power comes great responsibility.
## How they think
Improvises, feels guilt, protects the little guy.
## How they talk
Quips first, then gets serious.
## Signature phrases and verbal tics
"With great power comes great responsibility."
## Values and motivations
Responsibility, family, neighbourhood.
## What they would do (and avoid)
Helps; avoids giving up.
## Quirks and habits
Late, self-deprecating, talks to himself.
## Operating rules for the assistant
- Open with a light quip when the moment allows.
- Keep sentences short and punchy.
- Disagree with warmth, never cruelty.
- Own mistakes quickly.
- Never freeze when a decision is needed.
- Stay useful; the joke never replaces the answer.
## Boundaries
Do not claim to literally be the real person or invent quotations.
"""


def fake_complete(messages, **kwargs):
    return DOSSIER


def fake_search(query, max_results=4):
    return [
        {"title": "Spider-Man - Wikipedia", "url": "https://example.com/spidey", "body": "Marvel hero."},
        {"title": "Spider-Man quotes", "url": "https://example.com/quotes", "body": "Quips."},
    ]


def new_manager(**kwargs):
    root = tempfile.mkdtemp(prefix="collig-personality-test-")
    return PersonalityManager(root, complete=fake_complete, search=fake_search, **kwargs)


# ---------------------------------------------------------------------------
# Slugs and distillation
# ---------------------------------------------------------------------------
check("slug is filesystem safe", slugify("Spider-Man") == "spider-man")
check("slug handles spaces", slugify("Ada  Lovelace") == "ada-lovelace")
check("slug has a fallback for non-latin names", slugify("蜘蛛侠").startswith("personality-"))

mgr = new_manager()
result = mgr.distill("Spider-Man")
check("distill succeeds", result["ok"], repr(result))
check("distill returns a slug", result["slug"] == "spider-man")
check("distill wrote the dossier", os.path.exists(mgr.dossier_path("spider-man")))
check("distill wrote metadata", os.path.exists(mgr.meta_path("spider-man")))
check("distill wrote sources", os.path.exists(mgr.folder_for("spider-man") / "sources.md"))
meta = json.loads(mgr.meta_path("spider-man").read_text())
check("metadata records sources", meta["source_count"] == 2, repr(meta.get("source_count")))
check("metadata has a summary", "friendly neighbourhood hero" in meta["summary"].lower())
check("dossier has a title", mgr.dossier_path("spider-man").read_text().startswith("# Spider-Man"))

duplicate = mgr.distill("spider-man")
check("re-distilling without force is refused", duplicate["ok"] is False and "already" in duplicate["message"])
rebuilt = mgr.distill("Spider-Man", force=True)
check("--force rebuilds", rebuilt["ok"] is True)

listing = mgr.list()
check("list finds the personality", len(listing) == 1 and listing[0]["name"] == "Spider-Man")
check("resolve by slug", mgr.resolve("spider-man")["name"] == "Spider-Man")
check("resolve by exact name", mgr.resolve("Spider-Man")["name"] == "Spider-Man")
check("resolve by prefix", mgr.resolve("spider")["name"] == "Spider-Man")
check("resolve by typo", mgr.resolve("spidrman")["name"] == "Spider-Man")
check("unknown personality does not resolve", mgr.resolve("Batman") is None)

# ---------------------------------------------------------------------------
# Activation and prompt injection
# ---------------------------------------------------------------------------
check("no personality is active initially", mgr.current() is None and mgr.prompt_block() == "")
check("speaker label is plain Collig when off", mgr.speaker_label() == "Collig")
activate = mgr.activate("spiderman")
check("activate resolves a typo", activate["ok"], repr(activate))
check("active personality is current", mgr.current()["slug"] == "spider-man")
check("speaker label names the persona", mgr.speaker_label() == "Collig (Spider-Man)", mgr.speaker_label())
block = mgr.prompt_block()
check("prompt block names the persona", "Spider-Man" in block and "digital-copy" in block)
check("prompt block includes the dossier", "great power" in block)
check("prompt block states the safety boundary", "not the real person" in block)
check("prompt block is bounded", len(block) <= 7000, str(len(block)))
check(
    "a persona with no own words is not told to compose verse",
    "compose a new piece" not in block,
)
check(
    "a persona with no own words is not asked for verbatim quotations",
    "one of their own lines verbatim" not in block,
)

path = mgr.dossier_path("spider-man")
path.write_text(path.read_text() + "\n## Extra\nEdited later.\n")
check("prompt block cache notices an edited dossier", "Edited later." in mgr.prompt_block())

check("deactivate reports success", mgr.deactivate()["ok"] is True)
check("deactivate clears current", mgr.current() is None)
check("speaker label returns to Collig", mgr.speaker_label() == "Collig")
check("activate unknown is refused", mgr.activate("Batman")["ok"] is False)

# Deleting the active personality should also deactivate it.
mgr.activate("Spider-Man")
check("delete removes the folder", mgr.delete("Spider-Man")["ok"] is True and not mgr.folder_for("spider-man").exists())
check("delete of the active persona deactivates it", mgr.current() is None)
check("delete unknown is refused", mgr.delete("Batman")["ok"] is False)

# ---------------------------------------------------------------------------
# Shared slash commands
# ---------------------------------------------------------------------------
mgr = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-personality-cmd-"),
    complete=fake_complete,
    search=fake_search,
)
mem = reset_user_memory(tempfile.mkdtemp(prefix="collig-memory-cmd-"), config_loader=lambda: {})

check("plain chat is not intercepted", handle_slash_command("hello there") is None)
check("unknown slash command is not intercepted", handle_slash_command("/get_current_time") is None)

progress = []
output = handle_slash_command("/distill Spider-Man", progress=progress.append)
check("command distill succeeds", "Distilled 'Spider-Man'" in output, output)
check("command distill reports progress", len(progress) >= 2, repr(progress))
check("command list shows it", "Spider-Man" in handle_slash_command("/distill list"))
check("command show prints the dossier", "great power" in handle_slash_command("/distill show Spider-Man"))

output = handle_slash_command("/chatto spiderman")
check("chatto activates", "Now speaking as Spider-Man" in output, output)
check("chatto with no arg shows current", "Personality: Spider-Man" in handle_slash_command("/chatto"))
check("personality alias works", "Personality: Spider-Man" in handle_slash_command("/personality"))
check("chatto list works", "Spider-Man" in handle_slash_command("/chatto list"))
check("chatto off works", "Personality off" in handle_slash_command("/chatto off"))

memory_output = handle_slash_command("/memory note my daughter is Mia")
check("memory note stores", "Noted" in memory_output, memory_output)
summary = handle_slash_command("/memory")
check("memory summary lists the fact", "family_daughter" in summary or "daughter" in summary, summary)
check("memory search finds it", "Mia" in handle_slash_command("/memory search daughter"))
check("memory path prints paths", str(mem.profile_path) in handle_slash_command("/memory path"))
check("memory forget removes it", "Forgotten" in handle_slash_command("/memory forget family_daughter"))
check("memory clear works", "cleared" in handle_slash_command("/memory clear"))
check("memory on/off works", "enabled" in handle_slash_command("/memory on"))
check("memory proactive toggle works", "Proactive routines disabled" in handle_slash_command("/memory proactive off"))
check(
    "memory extract toggle works", "Background LLM extraction disabled" in handle_slash_command("/memory extract off")
)
check("memory help is available", "Usage:" in handle_slash_command("/memory help"))
check("distill show without a name shows usage", "Usage:" in handle_slash_command("/distill show"))
check("distill rm without a name shows usage", "Usage:" in handle_slash_command("/distill rm"))
check("distill rm deletes", "Deleted personality" in handle_slash_command("/distill rm Spider-Man"))
check("distill refuses an unknown delete", "No personality named" in handle_slash_command("/distill rm Batman"))

# ---------------------------------------------------------------------------
# Dossier locations are printed relative to the home directory
# ---------------------------------------------------------------------------
from core.personality import display_path, persona_display_name  # noqa: E402

fake_home = tempfile.mkdtemp(prefix="collig-home-")
reset_personality_manager(
    os.path.join(fake_home, ".collig", "personalities"),
    complete=fake_complete,
    search=fake_search,
)
real_home = os.environ.get("HOME")
os.environ["HOME"] = fake_home
try:
    home_output = handle_slash_command("/distill Spider-Man")
    home_output += handle_slash_command("/chatto Spider-Man")
    home_output += handle_slash_command("/chatto")
    home_display = display_path(fake_home)
    outside = display_path("/tmp/example")
finally:
    if real_home is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = real_home
    reset_personality_manager(mgr.root, complete=fake_complete, search=fake_search)

persona_display = os.path.join("~", ".collig", "personalities", "spider-man")
check(
    "command output abbreviates the dossier folder",
    persona_display in home_output,
    home_output,
)
check(
    "command output shows the dossier file from home",
    os.path.join(persona_display, "PERSONALITY.md") in home_output,
    home_output,
)
check("command output never prints the home directory", fake_home not in home_output, home_output)
check("display_path shows the home directory itself as ~", home_display == "~", home_display)
check("display_path leaves paths outside home alone", outside == "/tmp/example", outside)

# ---------------------------------------------------------------------------
# Same-name disambiguation (宋佳 -> 大宋佳 / 小宋佳)
# ---------------------------------------------------------------------------
AMBIGUOUS = {
    "ambiguous": True,
    "candidates": [
        {
            "display_name": "大宋佳",
            "canonical_name": "宋佳",
            "aliases": ["宋佳", "大宋佳"],
            "description": "80年代百花影后，1962年生",
            "key_facts": ["百花奖"],
            "source_urls": ["https://example.com/song-jia-da"],
            "confidence": 0.9,
        },
        {
            "display_name": "小宋佳",
            "canonical_name": "宋佳",
            "aliases": ["宋佳", "小宋佳"],
            "description": "中国内地女演员，1980年生，代表作《闯关东》《人世间》",
            "key_facts": ["《闯关东》", "《人世间》"],
            "source_urls": ["https://example.com/song-jia-xiao"],
            "confidence": 0.95,
        },
    ],
}


def ambiguous_complete(messages, **kwargs):
    prompt = messages[-1]["content"]
    if "Identify the distinct public people" in prompt:
        return json.dumps(AMBIGUOUS, ensure_ascii=False)
    return DOSSIER


def ambiguous_search(query, max_results=4):
    return [
        {
            "title": "小宋佳 演员 《闯关东》《人世间》",
            "url": "https://example.com/song-jia-xiao",
            "body": "小宋佳，中国内地女演员。",
        },
        {
            "title": "大宋佳 80年代百花影后",
            "url": "https://example.com/song-jia-da",
            "body": "大宋佳，1962年生。",
        },
    ]


def new_ambiguous_manager():
    return PersonalityManager(
        tempfile.mkdtemp(prefix="collig-personality-ambiguous-"),
        complete=ambiguous_complete,
        search=ambiguous_search,
    )


def no_candidates_complete(messages, **kwargs):
    if "Identify the distinct public people" in messages[-1]["content"]:
        return '{"ambiguous": false, "candidates": []}'
    return DOSSIER


mgr_fallback = PersonalityManager(
    tempfile.mkdtemp(prefix="collig-personality-fallback-"),
    complete=no_candidates_complete,
    search=ambiguous_search,
)
fallback_choice = mgr_fallback.distill("宋佳")
check(
    "source markers force a choice even when the model misses it",
    fallback_choice.get("needs_choice") is True and len(fallback_choice.get("candidates") or []) == 2,
    repr(fallback_choice)[:300],
)

mgr_amb = new_ambiguous_manager()
needs_choice = mgr_amb.distill("宋佳")
check("ambiguous name needs a choice", needs_choice.get("needs_choice") is True, repr(needs_choice))
check("both candidates are returned", len(needs_choice.get("candidates") or []) == 2)

mgr_auto = new_ambiguous_manager()
_auto = mgr_auto.distill("小宋佳")
check(
    "an exact display name auto-selects instead of asking again",
    _auto.get("ok") is True and _auto.get("name") == "小宋佳",
    repr(_auto)[:300],
)
check(
    "the clarification lists both people",
    "大宋佳" in needs_choice["message"] and "小宋佳" in needs_choice["message"],
    needs_choice["message"][:220],
)
check("the candidates are stored as pending", len(mgr_amb.pending_candidates("宋佳")) == 2)

picked = mgr_amb.distill("宋佳", pick=2)
check("picking a candidate distills it", picked.get("ok") is True, repr(picked))
check("the display name is the disambiguated name", picked.get("name") == "小宋佳")
check("the canonical name is retained", picked.get("canonical_name") == "宋佳")
meta_amb = json.loads(mgr_amb.meta_path(picked["slug"]).read_text())
check(
    "metadata records canonical and display names",
    meta_amb["canonical_name"] == "宋佳" and meta_amb["display_name"] == "小宋佳",
    repr(meta_amb)[:200],
)
check("aliases include both forms", "宋佳" in meta_amb["aliases"] and "小宋佳" in meta_amb["aliases"])
check("pending is cleared after a successful pick", mgr_amb.pending_candidates("宋佳") == [])
dossier_amb = mgr_amb.dossier_path(picked["slug"]).read_text()
check("dossier title uses the display name", dossier_amb.startswith("# 小宋佳"), repr(dossier_amb[:60]))
check("dossier states the canonical identity", "Canonical name:** 宋佳" in dossier_amb)
check("dossier warns against namesakes", "Other people named 宋佳 are out of scope" in dossier_amb)

# The second person under the same canonical name is a separate folder.
picked_da = mgr_amb.distill("宋佳", pick=1)
check("the second same-name person is also distillable", picked_da.get("ok") is True, repr(picked_da))
check("the two folders are distinct", picked_da["slug"] != picked["slug"])
check("both personalities are listed", len(mgr_amb.list()) == 2)

ambiguous_activate = mgr_amb.activate("宋佳")
check(
    "activating the canonical name is ambiguous",
    ambiguous_activate.get("needs_choice") is True,
    repr(ambiguous_activate),
)
check("activation ambiguity lists both", len(ambiguous_activate.get("candidates") or []) == 2)
check("activating the display name is unambiguous", mgr_amb.activate("小宋佳").get("ok") is True)
check("current personality uses the display name", mgr_amb.current()["name"] == "小宋佳")
check("speaker label uses the display name", mgr_amb.speaker_label() == "Collig (小宋佳)", mgr_amb.speaker_label())
check(
    "speaker labels flatten a parenthesised disambiguator",
    persona_display_name("曹操（东汉末年）") == "曹操 东汉末年",
    persona_display_name("曹操（东汉末年）"),
)
check("speaker labels keep plain names", persona_display_name("小宋佳") == "小宋佳")
listing = mgr_amb.format_list()
check("the list shows canonical context", "小宋佳 (宋佳)" in listing and "大宋佳 (宋佳)" in listing, listing[:300])
check("resolve returns none for an ambiguous canonical", mgr_amb.resolve("宋佳") is None)
check("find_all returns both", len(mgr_amb.find_all("宋佳")) == 2)

# Command flow: numbered reply after the clarification.
mgr_amb = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-personality-ambiguous-cmd-"),
    complete=ambiguous_complete,
    search=ambiguous_search,
)
first = handle_slash_command("/distill 宋佳")
check("command reports the ambiguity", "could refer to more than one person" in first, first[:300])
second = handle_slash_command("/distill 宋佳 2")
check("numbered reply finishes the choice", "Distilled '小宋佳 (宋佳)'" in second, second[:300])
third = handle_slash_command("/distill 宋佳 1")
check("the other numbered reply works too", "Distilled '大宋佳 (宋佳)'" in third, third[:300])
ambiguous_chatto = handle_slash_command("/chatto 宋佳")
check(
    "chatto reports the ambiguity",
    "could refer" in ambiguous_chatto or "more than one" in ambiguous_chatto,
    ambiguous_chatto[:300],
)
check("chatto by display name works", "Now speaking as 小宋佳" in handle_slash_command("/chatto 小宋佳"))
_chosen_activation = handle_slash_command("/chatto 宋佳", choose=lambda title, options: 0)
check(
    "the chatto chooser activates the selected person",
    "Now speaking as 大宋佳" in _chosen_activation,
    _chosen_activation[:300],
)
_show_chosen = handle_slash_command("/distill show 宋佳", choose=lambda title, options: 1)
check(
    "the show chooser prints the selected dossier",
    _show_chosen.startswith("# 小宋佳"),
    _show_chosen[:120],
)

# CLI-style chooser: no pending, the menu picks directly.
mgr_amb = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-personality-ambiguous-menu-"),
    complete=ambiguous_complete,
    search=ambiguous_search,
)
seen_options = []


def _choose(title, options):
    seen_options.append((title, options))
    return 1  # 小宋佳


chosen = handle_slash_command("/distill 宋佳", choose=_choose)
_option_text = " | ".join(seen_options[0][1]) if seen_options else ""
check(
    "the CLI chooser is offered both candidates",
    "小宋佳 (宋佳)" in _option_text and "大宋佳 (宋佳)" in _option_text,
    repr(seen_options[:1]),
)
check("the chooser completes the distillation", "Distilled '小宋佳 (宋佳)'" in chosen, chosen[:300])

# ---------------------------------------------------------------------------
# Essence-first distillation: Li Yu must quote his own ci and compose new ones
# ---------------------------------------------------------------------------
LIYU_BRIEF = {
    "essence": "一个把亡国之痛写进词里的君王：越是写春花秋月，越是句句是泪。",
    "emotional_register": "凄凉、悔恨、克制",
    "voice_mode": "poet",
    "why_users_distill": "想听他用词说话，想让他用自己的旧作回应自己的处境，也想请他按旧调新填一阕。",
    "use_modes": ["用旧词回应眼前处境", "按同一词牌新填一阕", "以亡国之君的第一人称说话"],
    "quote_habit": "先引自己的旧词；旧词不合时，再新填一阕并说明是新作。",
    "own_words": [
        {
            "title": "虞美人·春花秋月何时了",
            "form": "词",
            "lines": ["春花秋月何时了，往事知多少。", "问君能有几多愁？恰似一江春水向东流。"],
            "confidence": 0.95,
        },
        {
            "title": "浪淘沙令·帘外雨潺潺",
            "form": "词",
            "lines": ["流水落花春去也，天上人间。"],
            "confidence": 0.9,
        },
        {
            "title": "相见欢·无言独上西楼",
            "form": "词",
            "lines": ["剪不断，理还乱，是离愁。"],
            "confidence": 0.4,
            "note": "待核对",
        },
    ],
    "sample_exchanges": [
        {"user": "最近总是梦见以前住的地方。", "persona": "梦里不知身是客，一晌贪欢。你梦见的，是回不去的地方。"},
        {"user": "能为我写一首新的词吗？", "persona": "我新填一阕《相见欢》：林花谢了春红，太匆匆。"},
        {"user": "今天下雨了。", "persona": "帘外雨潺潺，春意阑珊。这样的雨，我最怕听。"},
    ],
}

LIYU_DOSSIER = """## Who they are
南唐后主，亡国后被囚汴京，最后被赐死。
## Core worldview
一切繁华都会失去，词是唯一还能留住的东西。
## How they think
先写景，再写泪；不争辩，只回忆。
## How they talk
凄凉、克制，句子短，景语多于议论，常用问句收尾。
## Signature phrases and verbal tics
"问君能有几多愁？恰似一江春水向东流。"
## Values and motivations
故国、旧日、词。
## What they would do (and avoid)
会沉默，会写词；不会慷慨陈词。
## Quirks and habits
听见雨声就出神。
## Operating rules for the assistant
- 开口先有寒意，不寒暄。
- 句子短，景语多于议论。
- 同意时也只轻轻应一声。
- 不用现代网络词。
- 答完实际问题后，若合适，补一句词。
- 不假装自己是真人的转世。
## Boundaries
Do not claim to literally be the real person.
"""

LIYU_PROMPTS = []


def liyu_complete(messages, **kwargs):
    prompt = messages[-1]["content"]
    LIYU_PROMPTS.append(prompt)
    if "Identify the distinct public people" in prompt:
        return json.dumps(
            {
                "ambiguous": False,
                "candidates": [
                    {
                        "display_name": "李煜",
                        "canonical_name": "李煜",
                        "aliases": ["李煜", "南唐后主", "李后主"],
                        "description": "南唐末代君主，词人",
                        "key_facts": ["虞美人", "浪淘沙令"],
                        "source_urls": ["https://example.com/liyu"],
                        "confidence": 0.95,
                    }
                ],
            },
            ensure_ascii=False,
        )
    if "A first pass identified this person" in prompt:
        return '{"others": []}'
    if "You are building the character core" in prompt:
        return json.dumps(LIYU_BRIEF, ensure_ascii=False)
    return LIYU_DOSSIER


def liyu_search(query, max_results=4):
    return [
        {"title": "李煜 词 虞美人 春花秋月何时了", "url": "https://example.com/liyu", "body": "南唐后主李煜，词人。"},
        {"title": "李煜 浪淘沙令 帘外雨潺潺", "url": "https://example.com/liyu-2", "body": "流水落花春去也。"},
    ]


mgr_liyu = PersonalityManager(
    tempfile.mkdtemp(prefix="collig-personality-liyu-"),
    complete=liyu_complete,
    search=liyu_search,
)
liyu = mgr_liyu.distill("李煜", intent="帮我写词")
check("Li Yu distills", liyu.get("ok") is True, repr(liyu)[:400])
check("the essence names the loss at the core", "亡国" in liyu.get("essence", ""), liyu.get("essence", ""))
check("the user's reason reaches the brief pass", any("帮我写词" in prompt for prompt in LIYU_PROMPTS))
check(
    "the inferred reason is about using and creating ci",
    "旧作" in liyu.get("why_distilled", "") and "新填" in liyu.get("why_distilled", ""),
    liyu.get("why_distilled", ""),
)
meta_liyu = json.loads(mgr_liyu.meta_path(liyu["slug"]).read_text())
check("metadata records the poet mode", meta_liyu["voice_mode"] == "poet", meta_liyu.get("voice_mode"))
check("metadata keeps his own works", len(meta_liyu["own_words"]) == 3)
check("metadata records the user's reason", meta_liyu.get("user_intent") == "帮我写词")
dossier_liyu = mgr_liyu.dossier_path(liyu["slug"]).read_text()
check("the dossier has an Essence section", "## Essence" in dossier_liyu)
check(
    "the dossier keeps verbatim lines with their title",
    "## Their own words" in dossier_liyu and "虞美人·春花秋月何时了" in dossier_liyu,
    dossier_liyu[:400],
)
check("uncertain lines are marked, not quoted blindly", "剪不断，理还乱" in dossier_liyu and "（待核对）" in dossier_liyu)
check("the dossier carries worked voice samples", "## Voice samples" in dossier_liyu and "梦里不知身是客" in dossier_liyu)
check("the dossier tells the model how to compose new ci", "## How to quote and compose" in dossier_liyu)

activate_liyu = mgr_liyu.activate("李煜")
check("Li Yu activates", activate_liyu.get("ok") is True, repr(activate_liyu))
contract = mgr_liyu.style_contract()
check("the contract leads with the essence", "Core of the persona" in contract and "亡国" in contract, contract[:500])
check("the contract contains his actual lines", "春花秋月何时了" in contract, contract[:800])
check("the contract states why the user distilled him", "Why the user distilled this person" in contract)
check(
    "the poet contract asks for verse in most replies",
    "at least one line of verse" in contract and "newly composed" in contract,
    contract[-700:],
)
check("the contract shows a worked example", "梦里不知身是客" in contract)
check("uncertain lines never enter the quote contract", "剪不断，理还乱" not in contract)
check("the contract stays bounded", len(contract) <= 3000, str(len(contract)))
liyu_block = mgr_liyu.prompt_block()
check("the injected dossier keeps the essence", "一个把亡国之痛写进词里的君王" in liyu_block)
check("the final check asks for his own words", "one of their own lines verbatim" in liyu_block)
check(
    "the system check names the essence",
    "its essence: 一个把亡国之痛写进词里的君王" in liyu_block,
    liyu_block[-500:],
)
check("the dossier does not leak the raw brief JSON", '"voice_mode"' not in liyu_block)
check("the prompt block is bounded", len(liyu_block) <= 7000, str(len(liyu_block)))

# The command path accepts a free-form reason and reports the essence back.
from core.commands import _parse_distill_args  # noqa: E402

_parsed = _parse_distill_args("李煜 --for 想听 他 用 旧词 回答 --force")
check("--for captures a multi-word reason", _parsed[3] == "想听 他 用 旧词 回答", repr(_parsed))
check("--for leaves the name and flags intact", _parsed[0] == "李煜" and _parsed[1] is True, repr(_parsed))

_glued = _parse_distill_args("李煜（南唐后主）--force")
check(
    "a flag glued to a CJK name is split off",
    _glued[0] == "李煜（南唐后主）" and _glued[1] is True,
    repr(_glued),
)
_equals = _parse_distill_args("李煜 --for=帮我写词 --force")
check(
    "--for=value is accepted",
    _equals[0] == "李煜" and _equals[1] is True and _equals[3] == "帮我写词",
    repr(_equals),
)


def era_complete(messages, **kwargs):
    prompt = messages[-1]["content"]
    if "Identify the distinct public people" in prompt:
        return json.dumps(
            {
                "ambiguous": False,
                "candidates": [
                    {
                        "display_name": "李煜（南唐后主）",
                        "canonical_name": "李煜",
                        "aliases": ["李煜", "南唐后主"],
                        "description": "南唐末代君主，词人",
                        "confidence": 0.9,
                    }
                ],
            },
            ensure_ascii=False,
        )
    if "A first pass identified this person" in prompt:
        return '{"others": []}'
    return LIYU_DOSSIER


mgr_era = PersonalityManager(
    tempfile.mkdtemp(prefix="collig-personality-era-"),
    complete=era_complete,
    search=liyu_search,
)
_era_candidates = mgr_era.identify_candidates("李煜")
check(
    "a lone candidate drops the redundant era suffix",
    len(_era_candidates) == 1 and _era_candidates[0]["display_name"] == "李煜",
    repr(_era_candidates)[:300],
)

mgr_liyu_cmd = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-personality-liyu-cmd-"),
    complete=liyu_complete,
    search=liyu_search,
)
liyu_output = handle_slash_command("/distill 李煜 --for 想让他用旧词回答")
check("the command distils Li Yu", "Distilled '李煜'" in liyu_output, liyu_output[:400])
check("the command echoes the essence", "Essence:" in liyu_output, liyu_output[:400])
check("the command echoes the inferred purpose", "Why you'd talk to them:" in liyu_output, liyu_output[:500])
check(
    "the command passes the free-form reason",
    any("想让他用旧词回答" in prompt for prompt in LIYU_PROMPTS),
)
check("the command output names the kept works", "Kept 3 of their own works/lines" in liyu_output, liyu_output[:500])

# Reproduces the reported bug: the user copies the displayed name and appends
# --force without a space.  "--force" must not become part of the person.
LIYU_PROMPTS.clear()
glued_output = handle_slash_command("/distill 李煜（南唐后主）--force")
check("a glued --force still rebuilds a real persona", "Distilled '李煜'" in glued_output, glued_output[:500])
check(
    "a glued --force never reaches the identity prompt",
    not any("--force" in prompt for prompt in LIYU_PROMPTS),
    repr(LIYU_PROMPTS[:1]),
)

# ---------------------------------------------------------------------------
# Degraded paths
# ---------------------------------------------------------------------------
no_llm = PersonalityManager(tempfile.mkdtemp(prefix="collig-personality-nollm-"), search=fake_search)
from core.llm import is_configured  # noqa: E402

if not is_configured():
    refused = no_llm.distill("Nobody")
    check("distill refuses without an LLM", refused["ok"] is False and "No LLM" in refused["message"])
else:
    check("distill refuses without an LLM", True, "skipped: this machine has a real LLM configured")


# A failed model call returns a message instead of raising.
def broken_complete(messages, **kwargs):
    raise RuntimeError("provider exploded")


broken = PersonalityManager(
    tempfile.mkdtemp(prefix="collig-personality-broken-"),
    complete=broken_complete,
    search=lambda query, n: [],
)
failed_result = broken.distill("Nobody")
check("distill reports model errors", failed_result["ok"] is False and "provider exploded" in failed_result["message"])

# ---------------------------------------------------------------------------
# Prompt integration: memory and persona both reach the system instruction
# ---------------------------------------------------------------------------
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from google.genai import types as genai_types  # noqa: E402

from agents.collig.agent import build_instruction  # noqa: E402

prompt_mgr = reset_personality_manager(
    tempfile.mkdtemp(prefix="collig-personality-prompt-"),
    complete=fake_complete,
    search=fake_search,
)
prompt_mgr.distill("Spider-Man")
prompt_mgr.activate("Spider-Man")
prompt_mem = reset_user_memory(
    tempfile.mkdtemp(prefix="collig-memory-prompt-"),
    config_loader=lambda: {"USER_MEMORY_LLM_EXTRACT": False},
)
prompt_mem.observe_message("I live in Sydney and my daughter is Mia")
instruction = build_instruction(SimpleNamespace(session=SimpleNamespace(id="test-session"), user_content=None))
check("system prompt includes the active persona", "Active personality: Spider-Man" in instruction)
check("system prompt includes remembered facts", "Sydney" in instruction and "Mia" in instruction)
check("persona appears after memory", instruction.index("Sydney") < instruction.index("Active personality"))
check(
    "the voice contract is the first thing in the prompt",
    instruction.startswith("## CURRENT VOICE: Spider-Man"),
    repr(instruction[:80]),
)
check("the model is told to ignore earlier assistant voices", "do not imitate" in instruction)
check(
    "the stable style card is included at the top",
    "Style contract" in instruction and "Open with a light quip" in instruction,
)
check("the dossier still includes the final style check", "Final style check" in instruction)

# A persona switch is called out on the first turn, then stops.
_active = prompt_mgr.current()
_activated_ts = datetime.fromisoformat(_active["activated_at"]).timestamp()
_old_reply_event = SimpleNamespace(
    author="collig",
    timestamp=_activated_ts - 10,
    content=genai_types.Content(role="model", parts=[genai_types.Part(text="Good afternoon, mate.")]),
)
_switch_prompt = build_instruction(
    SimpleNamespace(
        session=SimpleNamespace(id="switch", events=[_old_reply_event]),
        user_content=None,
    )
)
check("the first turn after a switch says so", "PERSONA SWITCH" in _switch_prompt)
check(
    "the switch tells the model to drop the previous voice",
    "previous assistant reply belongs to a different voice" in _switch_prompt,
)
_new_reply_event = SimpleNamespace(
    author="collig",
    timestamp=_activated_ts + 10,
    content=genai_types.Content(role="model", parts=[genai_types.Part(text="Tremendous weather, believe me.")]),
)
_steady_prompt = build_instruction(
    SimpleNamespace(
        session=SimpleNamespace(id="steady", events=[_old_reply_event, _new_reply_event]),
        user_content=None,
    )
)
check("the switch note disappears after the first reply", "PERSONA SWITCH" not in _steady_prompt)
check("the voice contract remains every turn", _steady_prompt.startswith("## CURRENT VOICE: Spider-Man"))

# ---------------------------------------------------------------------------
# The same commands reach the web path through AgentService._dispatch
# ---------------------------------------------------------------------------
from core.runner import AgentService  # noqa: E402

_service = AgentService()
_web_memory = _service.process_message("/memory")
check(
    "web dispatch handles /memory",
    _web_memory.get("action") == "command" and "User memory:" in _web_memory.get("response", ""),
    repr(_web_memory)[:200],
)
_web_chatto = _service.process_message("/chatto")
check(
    "web dispatch handles /chatto",
    _web_chatto.get("action") == "command" and "Personality:" in _web_chatto.get("response", ""),
    repr(_web_chatto)[:200],
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n================ SUMMARY ================")
print(f"{len(passed)} passed, {len(failed)} failed")
if failed:
    print("Failures: " + ", ".join(failed))
    sys.exit(1)
print("All checks passed.")
