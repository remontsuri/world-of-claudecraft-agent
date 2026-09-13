"""play_fly.py — load trained PPO policy and play WoC game."""
import sys
sys.path.insert(0, 'D:/world-of-claudecraft')

import time
import torch
import numpy as np
from stable_baselines3 import PPO

from python.woc_game import WoCGameClient


def main():
    # Load trained model
    print('Loading trained policy...')
    model = PPO.load('data/ppo_fly_offline')
    print('Model loaded')
    
    # Connect to game
    game = WoCGameClient('127.0.0.1', 8791)
    
    # Wait for bridge
    print('Waiting for bridge...')
    for _ in range(30):
        info = game.snapshot()
        if info:
            break
        time.sleep(1)
    
    if not info:
        print('ERROR: bridge not responding')
        return
    
    print('Bridge OK')
    
    # Play
    total_reward = 0
    n_steps = 200
    
    for i in range(n_steps):
        info = game.snapshot()
        if not info:
            time.sleep(0.5)
            continue
        
        player = info.get('player', {})
        if player.get('hp', 0) <= 0 or player.get('dead', False):
            print(f'  [{i}] dead, respawning')
            game.respawn()
            time.sleep(2)
            info = game.snapshot()
        
        # Encode
        obs = encode_observation(info)
        
        # Predict action
        action, _ = model.predict(obs, deterministic=True)
        
        # Execute
        new_info = execute_action(game, action, info)
        
        # Reward
        reward = compute_reward(info, new_info)
        total_reward += reward
        
        if i % 20 == 0:
            print(f'  [{i:3d}] a={action} r={reward:+.2f} tot={total_reward:.1f} '
                  f'hp={player.get("hp",0):.0f} kills={new_info.get("kills",0)}')
        
        time.sleep(0.15)
    
    print(f'\nFinal reward: {total_reward:.1f}')


def encode_observation(info):
    """Encode WoC info dict to observation vector."""
    if not info:
        return np.zeros(16, dtype=np.float32)
    
    player = info.get('player', {})
    player_pos = info.get('player_pos', [0, 0])
    nearby = info.get('nearby', [])
    
    mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
    hostile = [e for e in mobs if e.get('hostile')]
    nearest_mob = min(hostile if hostile else mobs, key=lambda e: e.get('dist', 999)) if mobs else None
    
    npcs = [e for e in nearby if e.get('kind') == 'npc']
    npcs_with_quests = [e for e in npcs if e.get('questIds') or e.get('questId')]
    nearest_npc = min(npcs_with_quests if npcs_with_quests else npcs, key=lambda e: e.get('dist', 999)) if npcs else None
    
    quests = info.get('quests', {})
    active_quests = quests.get('active', [])
    has_quest = len(active_quests) > 0
    
    hp_frac = player.get('hp', 100) / max(player.get('maxHp', 100), 1)
    
    obs = np.array([
        player_pos[0] / 1000,
        player_pos[1] / 1000,
        hp_frac,
        player.get('maxHp', 100) / 100,
        (nearest_mob.get('dist', 100) if nearest_mob else 100) / 100,
        hash(nearest_mob.get('type', '')) % 100 / 100 if nearest_mob else 0.5,
        (nearest_npc.get('dist', 100) if nearest_npc else 100) / 100,
        hash(nearest_npc.get('name', '')) % 100 / 100 if nearest_npc else 0.5,
        info.get('time', 12) / 24,
        (info.get('tick', 0) % 1000) / 1000,
        1.0 if has_quest else 0.0,
        hash(active_quests[0].get('id', '') if active_quests else '') % 10 / 10,
        min(len(info.get('inventory', [])), 64) / 64,
        min(info.get('copper', 0), 10000) / 10000,
        1.0 if player.get('inCombat', False) else 0.0,
        info.get('kills', 0) / 100,
    ], dtype=np.float32)
    
    return obs


def execute_action(game, action, info):
    """Execute action with proper navigation toward target."""
    nearby = info.get('nearby', [])
    player_pos = info.get('player_pos', [0, 0])
    player_facing = info.get('player', {}).get('facing', 0)
    
    def move_toward(tx, tz, max_steps=10):
        """Navigate toward target using raw_move with proper turning."""
        nonlocal player_pos, player_facing
        for _ in range(max_steps):
            dx = tx - player_pos[0]
            dz = tz - player_pos[1]
            dist = (dx**2 + dz**2)**0.5
            if dist < 5:
                return True
            
            # Calculate desired facing
            desired = np.arctan2(dx, -dz)
            diff = desired - player_facing
            # Normalize to [-pi, pi]
            diff = (diff + np.pi) % (2 * np.pi) - np.pi
            
            if abs(diff) > 0.3:
                # Turn
                if diff > 0:
                    game.raw_move('turnRight')
                else:
                    game.raw_move('turnLeft')
                time.sleep(0.15)
            else:
                # Move forward
                game.raw_move('forward')
                time.sleep(0.15)
            
            # Re-read position
            new_info = game.snapshot()
            if new_info:
                player_pos = new_info.get('player_pos', player_pos)
                player_facing = new_info.get('player', {}).get('facing', player_facing)
        return False
    
    if action == 0:  # farm: move to nearest hostile mob, attack
        mobs = [e for e in nearby if e.get('kind') == 'mob' and e.get('hostile', False) and not e.get('dead', False)]
        if mobs:
            nearest = min(mobs, key=lambda e: e.get('dist', 999))
            move_toward(nearest['x'], nearest['z'], max_steps=15)
        return game.step(0)
    
    elif action == 1:  # loot
        lootables = [e for e in nearby if e.get('lootable', False) and not e.get('looted', False)]
        if lootables:
            nearest = min(lootables, key=lambda e: e.get('dist', 999))
            move_toward(nearest['x'], nearest['z'], max_steps=8)
        return game.step(1)
    
    elif action == 2:  # accept quest: move to NPC with quests
        npcs = [e for e in nearby if e.get('kind') == 'npc' and (e.get('questIds') or e.get('questId'))]
        if npcs:
            nearest = min(npcs, key=lambda e: e.get('dist', 999))
            move_toward(nearest['x'], nearest['z'], max_steps=10)
        return game.step(2)
    
    elif action == 3:  # turn in quest: move to any NPC
        npcs = [e for e in nearby if e.get('kind') == 'npc']
        if npcs:
            nearest = min(npcs, key=lambda e: e.get('dist', 999))
            move_toward(nearest['x'], nearest['z'], max_steps=10)
        return game.step(3)
    
    elif action == 4:  # sell: move to vendor
        vendors = [e for e in nearby if e.get('kind') == 'npc' and e.get('vendor')]
        if vendors:
            nearest = min(vendors, key=lambda e: e.get('dist', 999))
            move_toward(nearest['x'], nearest['z'], max_steps=10)
        return game.step(4)
    
    else:
        return info


def compute_reward(prev_info, info):
    if not prev_info or not info:
        return 0.0
    
    reward = 0.0
    
    d_kills = info.get('kills', 0) - prev_info.get('kills', 0)
    if d_kills > 0:
        reward += 10.0 * d_kills
    
    d_quests = info.get('quests_done', 0) - prev_info.get('quests_done', 0)
    if d_quests > 0:
        reward += 20.0 * d_quests
    
    d_copper = info.get('copper', 0) - prev_info.get('copper', 0)
    if d_copper > 0:
        reward += 0.01 * d_copper
    
    d_deaths = info.get('deaths', 0) - prev_info.get('deaths', 0)
    if d_deaths > 0:
        reward -= 15.0 * d_deaths
    
    d_xp = info.get('xp', 0) - prev_info.get('xp', 0)
    if d_xp > 0:
        reward += 0.1 * d_xp
    
    return reward


if __name__ == '__main__':
    main()
