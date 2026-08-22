# Agent Economy Loop — Design

> Status: spec for implementation. Source of truth for game contracts: official
> game src (D:/world-of-claudecraft/src/sim/*), verified live via CDP probes.

## Goal

The agent must run the FULL gameplay loop a player runs:
quest accept → objective (farm/loot/gather) → turn-in → sell junk → buy supplies
→ gather materials → craft needed items. Today it has accept/turn-in/farm/loot/
sell/buy(potion-only)/gather but NO crafting, NO item-name inventory, NO recipe
knowledge, NO stations, NO vendor stocks.

## Game contracts (verified)

| Data | Access | Notes |
|---|---|---|
| inventory slots | `sim.inventory` (Array) | slot: `{itemId\|def.id, count, name, quality}` |
| recipes | `sim.recipeList` (79 entries) | `{id, professionId, resultItemId, resultCount, reagents[{itemId,count}], skillReq}` |
| known recipes | player `meta.knownRecipes: Set<string>` | grandfathered = known w/o training |
| craft stations | `sim.stationPlacements` | `{id, stationType, pos:{x,z}}` (4 in Eastbrook) |
| vendor stock | NPC `vendorItems: string[]` | zone1.ts: trader_wilkes (food/pots/bags), smith_haldren (gear), foreman_odell (pick+flux) |
| buy | `sim.buyItem(npcId, itemId)` | validates against npc.vendorItems (items.ts:946) |
| sell one | `sim.sellItem(itemId, count)` | exists besides sellAllJunk |
| craft | `sim.craftItem(recipeId)` | Craft Cast System: starts a CAST (async), result event later |

## Design decisions

1. **Observation first**: snapshot gains `inventory` with real item ids+counts
   (replacing quality-only), plus `recipes_known[]` (id/resultItemId/reagents),
   plus `stations[]` (id/type/x/z). Vendor stocks read from live entities when
   near, else from static zone1 table (same idiom as FARSHORE_*).
2. **Skills stay flat**: add `craft_item` skill (policy picks recipe via ctx),
   `buy_item` generalized (ctx.itemId replaces hardcoded potion).
3. **Recipe choice is LEARNED, not scripted**: policy candidates include every
   KNOWN recipe whose reagents the agent currently has; Q-table learns which
   crafts pay off. No hard-coded "craft gear at level X" rules.
4. **Craft cast time**: craftItem starts an async cast — bridge holds tab ~2s
   then snapshots; verifier checks inventory delta (resultItemId count up).
5. **Stations**: recipes carry stationType requirement (non-field ones). Policy's
   craft candidate requires being within 8u of matching station OR recipe is
   field-craftable (FIELD_RECIPES set). Navigation to stations uses existing
   navigate handler.
6. **Economy loop stays emergent**: no orchestrator. The FSM keeps quest phases;
   sell/craft/buy are ordinary skills the policy may learn to interleave.

## Changes by file

- `src/bridge/snapshot.cjs`: inventory ids/counts; recipes_known (reagents);
  stations; nearby vendor stock list. Known-recipes resolved via player meta
  path found at runtime (`g.online.playerMeta` / sim resolve fallback).
- `src/bridge/actions.cjs`: case 12 `craft_item(cmd.recipeId)`; case 9 generalized
  to `cmd.buyItemId || 'minor_healing_potion'`; case 4 unchanged (sellAllJunk).
- `python/world_state.py`: expose inv_by_id {itemId: count}, craftable_now[]
  (known recipes with satisfied reagents + station ok), nearest_station.
- `python/policy.py`: SKILL_CRAFT="craft_item"; candidates from ws.craftable_now;
  PHASE_ALLOWED[DO_OBJECTIVE] += craft_item (and SELL_REPAIR phase unchanged).
- `python/hierarchical_env.py`: SKILLS += craft_item (idx 12); mask gate.
- `python/verifiers_py.py`: verify_craft already exists — wire ctx handle
  (recipeId→resultItemId) so it checks the right item delta.
- `python/agent.py` decide(): pass ctx['recipeId'] chosen from candidates.

## Testing (TDD)

Each file gets failing tests first:
- bridge smoke tests (node): snapshot exposes inventory ids/counts & recipes.
- pytest: world_state builds inv_by_id + craftable_now from fixture info;
  policy offers craft_item only when craftable_now non-empty; verifier craft
  success on result-item count increase.

## Out of scope (later)

- Auction/market (the_merchant player-market), enchanting/salvage, fishing rods,
  multi-zone vendors (zone2), commission orders.
