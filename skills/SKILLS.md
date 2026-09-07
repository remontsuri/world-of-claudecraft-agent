# WoC Agent Skills

This directory contains WoC Agent-specific skills — specialized knowledge for the autonomous game agent project.

## Directory Structure

- `agent-stuck-pattern-diagnostics/` — stuck loop detection and resolution
- `fsm-state-trace/` — FSM transition tracing
- `quest-lifecycle-trace/` — quest objective debugging
- `reward-policy-debug/` — reward signal analysis

## How to Use

Skills are loaded automatically by Hermes Agent when a Kanban task is dispatched to a profile. They provide:
- Step-by-step diagnostic procedures
- Common bug patterns and root causes
- Resolution protocols with evidence requirements

## Project-Specific Knowledge

All skills assume:
- Repository: remontsuri/world-of-claudecraft-agent (backup branch)
- Runtime: D:\world-of-claudecraft\python\play_autonomous.py
- Game: D:\woc-game (port 5173)
- Bridge: D:\world-of-claudecraft\browser_bridge.cjs (port 8791)
- CDP: port 9222
