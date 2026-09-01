#!/usr/bin/env python3
"""Generate game-agent-export.json from official game source.

Parses D:\woc-game\src\sim\content\*.ts to extract quest definitions.
This is a DERIVED cache — not a second source-of-truth.
Regenerate whenever game content changes.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

WOC_ROOT = Path(r"D:\woc-game")
CONTENT_DIR = WOC_ROOT / "src" / "sim" / "content"
OUTPUT_PATH = Path(r"D:\world-of-claudecraft\python\game_agent_export.json")


def parse_quest_block(text, start_pos):
    """Parse a single quest definition starting at 'q_xxx: {'."""
    # Find the quest ID
    m = re.match(r"\s*(q_\w+):\s*\{", text[start_pos:])
    if not m:
        return None, start_pos
    qid = m.group(1)
    pos = start_pos + m.end()

    # Find matching closing brace
    depth = 1
    start = pos
    while pos < len(text) and depth > 0:
        c = text[pos]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        pos += 1

    block = text[start:pos-1]
    return qid, block, pos


def extract_string_field(block, field):
    """Extract a string field like: field: 'value' or field: "value"."""
    m = re.search(r"%s:\s*['\"]([^'\"]*)['\"]" % field, block)
    return m.group(1) if m else None


def extract_int_field(block, field):
    """Extract an integer field like: field: 123."""
    m = re.search(r"%s:\s*(\d+)" % field, block)
    return int(m.group(1)) if m else 0


def extract_objectives(block):
    """Extract objectives array."""
    m = re.search(r"objectives:\s*\[", block)
    if not m:
        return []
    start = m.end()
    depth = 1
    pos = start
    while pos < len(block) and depth > 0:
        c = block[pos]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
        pos += 1
    arr = block[start:pos-1]

    objectives = []
    for om in re.finditer(r"\{([^}]+)\}", arr):
        obj_text = om.group(1)
        obj = {}
        t = extract_string_field(obj_text, "type")
        if t:
            obj["type"] = t
        tid = extract_string_field(obj_text, "targetMobId")
        if tid:
            obj["targetMobId"] = tid
        iid = extract_string_field(obj_text, "itemId")
        if iid:
            obj["itemId"] = iid
        nt = extract_string_field(obj_text, "nodeType")
        if nt:
            obj["nodeType"] = nt
        cnt = extract_int_field(obj_text, "count")
        if cnt:
            obj["count"] = cnt
        lbl = extract_string_field(obj_text, "label")
        if lbl:
            obj["label"] = lbl
        objectives.append(obj)
    return objectives


def main():
    if not CONTENT_DIR.exists():
        print(f"ERROR: {CONTENT_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    quests = {}
    quest_givers = {}
    quest_objectives = {}

    for ts_file in sorted(CONTENT_DIR.glob("zone*.ts")):
        text = ts_file.read_text(encoding="utf-8")
        pos = 0
        while pos < len(text):
            m = re.search(r"\n\s*(q_\w+):\s*\{", text[pos:])
            if not m:
                break
            block_start = pos + m.start()
            qid, block, new_pos = parse_quest_block(text, block_start)
            if qid is None:
                break

            name = extract_string_field(block, "name") or qid
            giver = extract_string_field(block, "giverNpcId")
            turnin = extract_string_field(block, "turnInNpcId")
            xp = extract_int_field(block, "xpReward")
            copper = extract_int_field(block, "copperReward")
            objectives = extract_objectives(block)

            quests[qid] = {
                "id": qid,
                "name": name,
                "giverNpcId": giver,
                "turnInNpcId": turnin,
                "xpReward": xp,
                "copperReward": copper,
                "objectives": objectives,
            }
            if giver:
                quest_givers[qid] = giver
            if objectives:
                quest_objectives[qid] = objectives

            pos = new_pos

    export = {
        "version": "0.38.4",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": "D:\\woc-game\\src\\sim\\content\\zone*.ts",
        "quests": quests,
        "quest_givers": quest_givers,
        "quest_objectives": quest_objectives,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    print(f"Generated {OUTPUT_PATH}")
    print(f"  Quests: {len(quests)}")
    print(f"  Quest givers: {len(quest_givers)}")
    print(f"  Quest objectives: {len(quest_objectives)}")


if __name__ == "__main__":
    main()
