"""RED test: explore should NOT be fallback during DO_OBJECTIVE when quest is active.

Per /GOAL п.10: 'Если explore возникает из-за отсутствия objective, исправить
objective/control-flow, а не reward.' Per /GOAL п.22: 'Если policy выбирает
неправильный skill: trace candidate generation/value/update.'

Current state: when ALL skills are masked (no mob in nearby, e.g. wolves 50yd),
mask_candidates() returns ['explore'] and policy.decide() picks explore. This
creates the INCONCLUSIVE explore loop. We want DO_OBJECTIVE to navigate to
mob spawn area, NOT just wander.

RED test: with q_boars ACTIVE and no hostile mob in nearby (all 50+yd away),
available_actions() should return something OTHER than ['explore'] —
specifically, a navigation skill (navigate/navigate_to_coord) that moves
toward a mob-spawn area, not the explore-wander fallback.

Author: Hermes (Phase 2 /GOAL 2026-09-03)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from action_mask import available_actions, mask_candidates


def _obs_active_quest_no_mob():
    """Simulate state: quest active (q_boars 0/5), 0 hostile mobs in nearby."""
    return {
        'player': {'hp': 100, 'maxHp': 100, 'level': 1, 'dead': False, 'class': 'warrior'},
        'mana': 0, 'maxMana': 0,
        'in_combat': False,
        'player_pos': [0, 0],
        'nearby': [],   # no mobs in 50yd
        'quests': {
            'active': [{
                'id': 'q_boars',
                'state': 'active',
                'objectives': [{'type': 'kill', 'mobId': 'boar', 'current': 0, 'required': 5}],
                'turnInNpc': {'x': 4.5, 'z': 5.5},
            }],
            'ready': [],
            'done': [],
        },
        'inventory': [],
        'bags': [],
        'bagCapacity': 16,
        'copper': 0,
    }


def test_no_explore_fallback_during_do_objective():
    """During DO_OBJECTIVE, if all skills masked, available_actions should
    include a navigation/approach skill, NOT just ['explore']."""
    obs = _obs_active_quest_no_mob()
    actions = available_actions(obs)
    print(f'available_actions returned: {actions}')
    # Per /GOAL: explore as universal fallback masks the real control-flow
    # problem (no mob in range -> should navigate toward mob, not wander).
    assert actions != ['explore'], (
        f'RED: available_actions fell back to ["explore"] during DO_OBJECTIVE. '
        f'This is the explore-INCONCLUSIVE loop. Should return a navigation '
        f'skill (e.g. "navigate", "approach_mob") or empty list (caller decides).'
    )


def test_no_explore_fallback_in_mask_candidates():
    """mask_candidates should NOT silently fall back to explore."""
    obs = _obs_active_quest_no_mob()
    cands = ['farm', 'loot', 'gather', 'cast_frostbolt', 'cast_fireball',
             'craft', 'sell']
    masked = mask_candidates(cands, obs)
    print(f'mask_candidates({cands}) -> {masked}')
    # When ALL skills are masked (no mob in range), current code returns
    # ['explore']. This is the silent fallback we want to fix.
    assert masked != ['explore'], (
        f'RED: mask_candidates fell back to ["explore"] when all skills masked. '
        f'Should return empty list (caller decides) or navigation skill.'
    )


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
