"""woc_game.py — integration with World of Claudecraft via browser_bridge (:8791).

Per document spec:
- Connects to WoC Gymnasium-like env via browser bridge
- Feeds game state into sensory neurons
- Gets discrete WTA action from engine.py
- Sends step command back to game
"""
import json
import time
import requests
import numpy as np
import torch
import sys
import os

# Add parent to path for engine import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class WoCGameClient:
    """HTTP client to browser_bridge.cjs running on :8791."""
    
    def __init__(self, host='127.0.0.1', port=8791):
        self.base_url = f'http://{host}:{port}'
        self.session = requests.Session()
    
    def snapshot(self):
        """Get current game state."""
        try:
            r = self.session.post(f'{self.base_url}/', json={'action': 'snapshot'}, timeout=5)
            if r.status_code == 200:
                return r.json().get('info', {})
        except Exception as e:
            print(f'[woc] snapshot error: {e}')
        return {}
    
    def step(self, action_idx):
        """Execute action by index."""
        try:
            r = self.session.post(f'{self.base_url}/', json={'action': 'step', 'idx': action_idx}, timeout=5)
            if r.status_code == 200:
                return r.json().get('info', {})
        except Exception as e:
            print(f'[woc] step error: {e}')
        return {}
    
    def raw_move(self, kind):
        """Execute raw movement (forward/back/turnLeft/turnRight)."""
        try:
            r = self.session.post(f'{self.base_url}/', json={'action': 'raw_move', 'kind': kind}, timeout=5)
            if r.status_code == 200:
                return r.json().get('info', {})
        except Exception as e:
            print(f'[woc] raw_move error: {e}')
        return {}
    
    def navigate(self, x, z, max_steps=80):
        """Navigate to coordinate."""
        try:
            r = self.session.post(f'{self.base_url}/', json={'action': 'navigate', 'x': x, 'z': z, 'max_steps': max_steps}, timeout=10)
            if r.status_code == 200:
                return r.json().get('info', {}), r.json().get('arrived', False)
        except Exception as e:
            print(f'[woc] navigate error: {e}')
        return {}, False
    
    def respawn(self):
        """Respawn after death."""
        try:
            r = self.session.post(f'{self.base_url}/', json={'action': 'respawn'}, timeout=5)
            if r.status_code == 200:
                return r.json().get('info', {})
        except Exception as e:
            print(f'[woc] respawn error: {e}')
        return {}
    
    def is_alive(self):
        """Check if player is alive."""
        info = self.snapshot()
        if not info:
            return False
        player = info.get('player', {})
        return player.get('hp', 0) > 0 and not player.get('dead', True)


class WoCConnectomeAgent:
    """Connectome-based agent playing WoC.
    
    Uses FlyBrainEngine for decision making, WoCGameClient for game interaction.
    Maps WTA motor groups to WoC actions.
    """
    
    def __init__(self, bridge_host='127.0.0.1', bridge_port=8791, use_engine=True):
        """
        Args:
            bridge_host: browser_bridge host
            bridge_port: browser_bridge port
            use_engine: use FlyBrainEngine (True) or ConnectomePolicy (False)
        """
        self.game = WoCGameClient(bridge_host, bridge_port)
        
        # Initialize engine
        if use_engine:
            from engine import FlyBrainEngine
            self.engine = FlyBrainEngine(device='cpu')
            self.policy_type = 'engine'
        else:
            from connectome_policy import ConnectomePolicy, WoCObservationEncoder
            self.engine = ConnectomePolicy(obs_dim=16, action_dim=4)
            self.engine.eval()
            self.policy_type = 'policy'
        
        # Action mapping (WoC bridge action indices)
        # From browser_bridge.cjs applyAction:
        # 0: farm (attack), 1: loot, 2: accept_quest, 3: turn_in_quest, 4: sell_junk
        self.action_map = {
            'move_forward': 5,   # NOOP + raw_move (handled separately)
            'turn': 5,           # NOOP + raw_move
            'attack': 0,         # farm
            'interact': 1,       # loot
        }
        
        # State
        self.total_steps = 0
        self.total_reward = 0.0
        self.prev_info = None
        
        print(f'[agent] policy={self.policy_type}')
    
    def encode_observation(self, info):
        """Convert WoC info dict to observation vector [16]."""
        if not info:
            return torch.zeros(16)
        
        player = info.get('player', {})
        player_pos = info.get('player_pos', [0, 0])
        nearby = info.get('nearby', [])
        quests = info.get('quests', {})
        
        # Nearest mob
        mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
        nearest_mob = min(mobs, key=lambda e: e.get('dist', 999)) if mobs else None
        
        # Nearest NPC
        npcs = [e for e in nearby if e.get('kind') == 'npc']
        nearest_npc = min(npcs, key=lambda e: e.get('dist', 999)) if npcs else None
        
        # Active quest
        active_quests = quests.get('active', [])
        has_quest = len(active_quests) > 0
        
        features = [
            player_pos[0] / 1000,  # x
            player_pos[1] / 1000,  # z
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
        
        return torch.tensor(features, dtype=torch.float32)
    
    def get_action(self, obs):
        """Get action from policy."""
        if self.policy_type == 'engine':
            # Engine takes numpy/tensor obs
            obs_np = obs.numpy() if isinstance(obs, torch.Tensor) else obs
            action = self.engine.get_action(obs_np)
            return action
        else:
            # ConnectomePolicy
            with torch.no_grad():
                obs_batch = obs.unsqueeze(0)
                action, _, _, _ = self.engine.get_action(obs_batch, deterministic=False)
                return action.item()
    
    def execute_action(self, action, info):
        """Execute action in WoC with pre-navigation."""
        nearby = info.get('nearby', [])
        
        if action == 0:  # farm/attack - navigate to mob
            mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
            if mobs:
                nearest = min(mobs, key=lambda e: e.get('dist', 999))
                if nearest and nearest.get('dist', 999) > 10:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=20)
            return self.game.step(0)
        
        elif action == 1:  # loot - navigate to lootable
            lootables = [e for e in nearby if e.get('lootable', False) and not e.get('looted', False)]
            if lootables:
                nearest = min(lootables, key=lambda e: e.get('dist', 999))
                if nearest and nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=15)
            return self.game.step(1)
        
        elif action == 2:  # accept quest - navigate to NPC with quests
            npcs_with_quests = [e for e in nearby 
                                if e.get('kind') == 'npc' and 
                                (e.get('questIds') or e.get('questId'))]
            if npcs_with_quests:
                nearest = min(npcs_with_quests, key=lambda e: e.get('dist', 999))
                if nearest and nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=20)
            return self.game.step(2)
        
        elif action == 3:  # turn in quest - navigate to quest target
            npcs_with_quests = [e for e in nearby 
                                if e.get('kind') == 'npc' and 
                                (e.get('questIds') or e.get('questId'))]
            if npcs_with_quests:
                nearest = min(npcs_with_quests, key=lambda e: e.get('dist', 999))
                if nearest and nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=20)
            return self.game.step(3)
        
        elif action == 4:  # sell junk - navigate to vendor
            vendors = [e for e in nearby if e.get('kind') == 'npc' and e.get('vendor', False)]
            if vendors:
                nearest = min(vendors, key=lambda e: e.get('dist', 999))
                if nearest and nearest.get('dist', 999) > 8:
                    self.game.navigate(nearest['x'], nearest['z'], max_steps=20)
            return self.game.step(4)
        
        else:
            # NOOP - explore toward mobs or quest NPCs
            targets = [e for e in nearby if e.get('kind') == 'mob']
            targets += [e for e in nearby 
                        if e.get('kind') == 'npc' and 
                        (e.get('questIds') or e.get('questId'))]
            if targets:
                nearest = min(targets, key=lambda e: e.get('dist', 999))
                self.game.navigate(nearest['x'], nearest['z'], max_steps=15)
                return self.game.snapshot()
            return info
    
    def compute_reward(self, prev_info, info):
        """Compute reward from info delta."""
        if not prev_info or not info:
            return 0.0
        
        reward = 0.0
        
        # Kills
        prev_kills = prev_info.get('kills', 0)
        curr_kills = info.get('kills', 0)
        if curr_kills > prev_kills:
            reward += 10.0 * (curr_kills - prev_kills)
        
        # Quests done
        prev_quests_done = prev_info.get('quests_done', 0)
        curr_quests_done = info.get('quests_done', 0)
        if curr_quests_done > prev_quests_done:
            reward += 20.0 * (curr_quests_done - prev_quests_done)
        
        # Copper
        prev_copper = prev_info.get('copper', 0)
        curr_copper = info.get('copper', 0)
        if curr_copper > prev_copper:
            reward += 0.01 * (curr_copper - prev_copper)
        
        # Death penalty
        prev_deaths = prev_info.get('deaths', 0)
        curr_deaths = info.get('deaths', 0)
        if curr_deaths > prev_deaths:
            reward -= 15.0
        
        # XP
        prev_xp = prev_info.get('xp', 0)
        curr_xp = info.get('xp', 0)
        if curr_xp > prev_xp:
            reward += 0.1 * (curr_xp - prev_xp)
        
        return reward
    
    def run_episode(self, n_steps=100, verbose=True):
        """Run one episode of n_steps."""
        print(f'[agent] starting episode ({n_steps} steps)')
        
        # Reset
        if self.policy_type == 'engine':
            self.engine.reset()
        else:
            self.engine.reset_state(batch_size=1)
        
        self.total_steps = 0
        self.total_reward = 0.0
        self.prev_info = None
        
        for i in range(n_steps):
            # 1. Observe
            info = self.game.snapshot()
            if not info:
                print(f'  [{i}] no info, skipping')
                time.sleep(0.5)
                continue
            
            # Check alive
            player = info.get('player', {})
            hp_frac = player.get('hp', 0) / max(player.get('maxHp', 100), 1)
            
            if player.get('hp', 0) <= 0 or player.get('dead', False):
                print(f'  [{i}] dead, respawning')
                self.game.respawn()
                time.sleep(2.0)
                info = self.game.snapshot()
                continue
            
            # Safety: flee if low HP
            if hp_frac < 0.3:
                # Move away from mobs
                nearby = info.get('nearby', [])
                mobs = [e for e in nearby if e.get('kind') == 'mob' and not e.get('dead', False)]
                if mobs:
                    # Calculate escape direction (away from mobs)
                    ex, ez = 0, 0
                    for m in mobs[:3]:
                        dx = info['player_pos'][0] - m['x']
                        dz = info['player_pos'][1] - m['z']
                        d = max((dx**2 + dz**2)**0.5, 0.1)
                        ex += dx / d
                        ez += dz / d
                    # Normalize
                    emag = max((ex**2 + ez**2)**0.5, 0.1)
                    ex, ez = ex/emag, ez/emag
                    # Target: 20 yards away
                    tx = info['player_pos'][0] + ex * 20
                    tz = info['player_pos'][1] + ez * 20
                    self.game.navigate(tx, tz, max_steps=5)
                    if i % 10 == 0:
                        print(f'  [{i}] FLEE: hp={hp_frac:.0%}')
                    time.sleep(0.5)
                    continue
            
            # 2. Encode observation
            obs = self.encode_observation(info)
            
            # 3. Get action
            action = self.get_action(obs)
            
            # 4. Execute
            new_info = self.execute_action(action, info)
            
            # 5. Compute reward
            reward = self.compute_reward(self.prev_info, new_info)
            self.total_reward += reward
            self.total_steps += 1
            self.prev_info = new_info
            
            if verbose and i % 10 == 0:
                print(f'  [{i:4d}] a={action} r={reward:+.2f} tot_r={self.total_reward:.1f} '
                      f'hp={player.get("hp", 0):.0f} kills={new_info.get("kills", 0)} '
                      f'qdone={new_info.get("quests_done", 0)}')
            
            # Small delay to not overwhelm bridge
            time.sleep(0.1)
        
        print(f'[agent] episode done: steps={self.total_steps} reward={self.total_reward:.1f}')
        return self.total_reward
    
    def run_forever(self, step_delay=0.2):
        """Run indefinitely."""
        print('[agent] running forever (Ctrl+C to stop)')
        
        if self.policy_type == 'engine':
            self.engine.reset()
        else:
            self.engine.reset_state(batch_size=1)
        
        step = 0
        while True:
            try:
                # Observe
                info = self.game.snapshot()
                if not info:
                    time.sleep(step_delay)
                    continue
                
                player = info.get('player', {})
                if player.get('hp', 0) <= 0 or player.get('dead', False):
                    self.game.respawn()
                    time.sleep(1.0)
                    continue
                
                # Encode
                obs = self.encode_observation(info)
                
                # Get action
                action = self.get_action(obs)
                
                # Execute
                self.execute_action(action, info)
                
                step += 1
                if step % 50 == 0:
                    print(f'  [{step}] kills={info.get("kills", 0)} copper={info.get("copper", 0)}')
                
                time.sleep(step_delay)
            
            except KeyboardInterrupt:
                print(f'[agent] stopped at step {step}')
                break
            except Exception as e:
                print(f'  [{step}] error: {e}')
                time.sleep(1.0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='WoC Connectome Agent')
    parser.add_argument('--host', default='127.0.0.1', help='bridge host')
    parser.add_argument('--port', type=int, default=8791, help='bridge port')
    parser.add_argument('--steps', type=int, default=100, help='episode steps')
    parser.add_argument('--policy', choices=['engine', 'policy'], default='engine',
                        help='policy type: engine (LIF+WTA) or policy (SNN)')
    parser.add_argument('--forever', action='store_true', help='run forever')
    args = parser.parse_args()
    
    agent = WoCConnectomeAgent(
        bridge_host=args.host,
        bridge_port=args.port,
        use_engine=(args.policy == 'engine'),
    )
    
    if args.forever:
        agent.run_forever()
    else:
        agent.run_episode(n_steps=args.steps)
