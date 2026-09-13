"""dataset_collector.py — collect random play dataset for BC training."""
import sys, json, time, os, numpy as np

sys.path.insert(0, 'D:/world-of-claudecraft')

# Direct import (no python. prefix)
from python.woc_game import WoCGameClient

def encode_observation(info):
    """Convert WoC info dict to observation vector [16]."""
    if not info:
        return np.zeros(16)
    
    player = info.get('player', {})
    player_pos = info.get('player_pos', [0, 0])
    nearby = info.get('nearby', [])
    
    mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
    nearest_mob = min(mobs, key=lambda e: e.get('dist', 999)) if mobs else None
    
    npcs = [e for e in nearby if e.get('kind') == 'npc']
    nearest_npc = min(npcs, key=lambda e: e.get('dist', 999)) if npcs else None
    
    quests = info.get('quests', {})
    active_quests = quests.get('active', [])
    has_quest = len(active_quests) > 0
    
    features = [
        player_pos[0] / 1000,
        player_pos[1] / 1000,
        player.get('hp', 100) / 100,
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
    ]
    return np.array(features, dtype=np.float32)


def execute_action(game, action, info):
    nearby = info.get('nearby', [])
    
    if action == 0:  # farm
        mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
        if mobs:
            nearest = min(mobs, key=lambda e: e.get('dist', 999))
            if nearest and nearest.get('dist', 999) > 10:
                game.navigate(nearest['x'], nearest['z'], max_steps=15)
        return game.step(0)
    elif action == 1:  # loot
        lootables = [e for e in nearby if e.get('lootable', False) and not e.get('looted', False)]
        if lootables:
            nearest = min(lootables, key=lambda e: e.get('dist', 999))
            if nearest and nearest.get('dist', 999) > 8:
                game.navigate(nearest['x'], nearest['z'], max_steps=10)
        return game.step(1)
    elif action == 2:  # accept quest
        return game.step(2)
    elif action == 3:  # turn in quest
        return game.step(3)
    elif action == 4:  # sell junk
        return game.step(4)
    else:
        return info


def compute_reward(prev_info, info):
    if not prev_info or not info:
        return 0.0
    
    reward = 0.0
    
    prev_kills = prev_info.get('kills', 0)
    curr_kills = info.get('kills', 0)
    if curr_kills > prev_kills:
        reward += 10.0 * (curr_kills - prev_kills)
    
    prev_quests_done = prev_info.get('quests_done', 0)
    curr_quests_done = info.get('quests_done', 0)
    if curr_quests_done > prev_quests_done:
        reward += 20.0 * (curr_quests_done - prev_quests_done)
    
    prev_copper = prev_info.get('copper', 0)
    curr_copper = info.get('copper', 0)
    if curr_copper > prev_copper:
        reward += 0.01 * (curr_copper - prev_copper)
    
    prev_deaths = prev_info.get('deaths', 0)
    curr_deaths = info.get('deaths', 0)
    if curr_deaths > prev_deaths:
        reward -= 15.0
    
    prev_xp = prev_info.get('xp', 0)
    curr_xp = info.get('xp', 0)
    if curr_xp > prev_xp:
        reward += 0.1 * (curr_xp - prev_xp)
    
    return reward


def main():
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
    
    dataset = []
    total_reward = 0
    n_steps = 500
    
    print(f'Collecting {n_steps} random samples...')
    
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
        
        obs = encode_observation(info)
        
        # Biased random: prefer action 0 (farm) and 2 (accept_quest)
        probs = [0.4, 0.1, 0.3, 0.1, 0.1]  # farm, loot, accept, turn_in, sell
        action = np.random.choice(5, p=probs)
        
        new_info = execute_action(game, action, info)
        reward = compute_reward(info, new_info)
        total_reward += reward
        
        new_obs = encode_observation(new_info)
        
        dataset.append({
            'obs': obs.tolist(),
            'action': int(action),
            'reward': float(reward),
            'new_obs': new_obs.tolist(),
            'done': bool(player.get('hp', 0) <= 0)
        })
        
        if i % 50 == 0:
            print(f'  [{i:3d}] a={action} r={reward:+.2f} tot={total_reward:.1f} hp={player.get("hp",0):.0f} kills={info.get("kills",0)}')
        
        time.sleep(0.15)
    
    # Save
    os.makedirs('data', exist_ok=True)
    with open('data/woc_dataset.json', 'w') as f:
        json.dump(dataset, f)
    
    print(f'\nDataset saved: {len(dataset)} samples')
    print(f'Total reward: {total_reward:.1f}')
    print(f'Avg reward: {total_reward/len(dataset):.4f}')
    
    # Stats
    actions = [d['action'] for d in dataset]
    rewards = [d['reward'] for d in dataset]
    print(f'Action distribution: {dict(zip(*np.unique(actions, return_counts=True)))}')
    print(f'Reward > 0: {sum(1 for r in rewards if r > 0)}')
    print(f'Reward < 0: {sum(1 for r in rewards if r < 0)}')


if __name__ == '__main__':
    main()
