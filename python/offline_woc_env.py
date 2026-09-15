"""offline_woc_env.py — fast synthetic WoC-like env for offline BC/PPO training.

Approximates WoC game dynamics without network calls:
- Player has pos, hp, level, kills, copper, quests_done
- Random mobs spawn with hostile/friendly, hp, dist
- Actions: farm, loot, accept_quest, turn_in, sell
- Rewards: kills, quests, copper, deaths
"""
import numpy as np
import gymnasium as gym
from gymnasium import spaces


class OfflineWoCEnv(gym.Env):
    """Fast synthetic WoC env for offline training."""
    
    metadata = {"render_modes": ["console"]}
    
    def __init__(self, obs_dim=16, action_dim=5, max_steps=500, seed=None):
        super().__init__()
        
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.max_steps = max_steps
        
        self.action_space = spaces.Discrete(action_dim)
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(obs_dim,), dtype=np.float32
        )
        
        # State
        self.player_pos = np.zeros(2)
        self.player_hp = 100.0
        self.player_max_hp = 100.0
        self.player_level = 1
        self.in_combat = False
        
        self.kills = 0
        self.copper = 0
        self.deaths = 0
        self.quests_done = 0
        self.quests_active = 0
        self.xp = 0
        
        self.n_steps = 0
        self.rng = np.random.RandomState(seed)
        
        # Mob state
        self.mobs = []  # list of dicts: {pos, hp, max_hp, hostile, dead, lootable}
        self.npcs = []  # list of dicts: {pos, has_quest, vendor}
        
        self._spawn_entities()
    
    def _spawn_entities(self):
        """Spawn random mobs and NPCs around player."""
        self.mobs = []
        self.npcs = []
        
        # 3-8 mobs
        n_mobs = self.rng.randint(3, 9)
        for _ in range(n_mobs):
            angle = self.rng.uniform(0, 2 * np.pi)
            dist = self.rng.uniform(5, 80)
            self.mobs.append({
                'pos': self.player_pos + np.array([np.cos(angle) * dist, np.sin(angle) * dist]),
                'hp': float(self.rng.randint(30, 100)),
                'max_hp': 100.0,
                'hostile': self.rng.random() < 0.6,
                'dead': False,
                'lootable': False,
            })
        
        # 2-5 NPCs
        n_npcs = self.rng.randint(2, 6)
        for _ in range(n_npcs):
            angle = self.rng.uniform(0, 2 * np.pi)
            dist = self.rng.uniform(10, 60)
            self.npcs.append({
                'pos': self.player_pos + np.array([np.cos(angle) * dist, np.sin(angle) * dist]),
                'has_quest': self.rng.random() < 0.5,
                'vendor': self.rng.random() < 0.3,
            })
    
    def reset(self, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        
        self.player_pos = np.zeros(2)
        self.player_hp = 100.0
        self.player_max_hp = 100.0
        self.player_level = 1
        self.in_combat = False
        self.kills = 0
        self.copper = 0
        self.deaths = 0
        self.quests_done = 0
        self.quests_active = 0
        self.xp = 0
        self.n_steps = 0
        
        self._spawn_entities()
        
        return self._encode(), {}
    
    def step(self, action):
        """Execute action, return (obs, reward, done, truncated, info)."""
        reward = 0.0
        
        # Safety: flee if low HP
        hp_frac = self.player_hp / self.player_max_hp
        hostile_mobs = [m for m in self.mobs if m['hostile'] and not m['dead']]
        close_hostile = [m for m in hostile_mobs if np.linalg.norm(m['pos'] - self.player_pos) < 15]
        
        if hp_frac < 0.4 and hostile_mobs:
            # Flee: move away from mobs
            direction = self.player_pos - np.mean([m['pos'] for m in hostile_mobs[:3]], axis=0)
            dist = np.linalg.norm(direction)
            if dist > 0:
                direction /= dist
            self.player_pos += direction * 8
            reward -= 0.05
        else:
            # Execute action
            if action == 0:  # farm: attack nearest hostile mob
                target = min(hostile_mobs, key=lambda m: np.linalg.norm(m['pos'] - self.player_pos), default=None)
                if target is not None:
                    dist = np.linalg.norm(target['pos'] - self.player_pos)
                    if dist < 45:  # in range
                        # Deal damage
                        target['hp'] -= self.rng.uniform(15, 35)
                        self.in_combat = True
                        if target['hp'] <= 0:
                            target['dead'] = True
                            target['lootable'] = True
                            self.kills += 1
                            self.xp += self.rng.uniform(5, 15)
                            self.copper += self.rng.uniform(1, 10)
                            reward += 10.0
                    else:
                        # Move toward target
                        direction = target['pos'] - self.player_pos
                        direction /= max(np.linalg.norm(direction), 0.1)
                        self.player_pos += direction * 5
                self.in_combat = True
                
                # Mobs fight back
                for m in hostile_mobs:
                    if not m['dead']:
                        dist = np.linalg.norm(m['pos'] - self.player_pos)
                        if dist < 10:
                            self.player_hp -= self.rng.uniform(2, 8)
            
            elif action == 1:  # loot: move to nearest lootable mob
                lootable = [m for m in self.mobs if m['lootable'] and m['dead']]
                if lootable:
                    target = min(lootable, key=lambda m: np.linalg.norm(m['pos'] - self.player_pos))
                    dist = np.linalg.norm(target['pos'] - self.player_pos)
                    if dist < 5:
                        self.copper += self.rng.uniform(5, 20)
                        target['lootable'] = False
                        reward += 3.0
                    else:
                        direction = target['pos'] - self.player_pos
                        direction /= max(np.linalg.norm(direction), 0.1)
                        self.player_pos += direction * 5
            
            elif action == 2:  # accept quest: move to NPC with quest
                quest_npcs = [n for n in self.npcs if n['has_quest']]
                if quest_npcs:
                    target = min(quest_npcs, key=lambda n: np.linalg.norm(n['pos'] - self.player_pos))
                    dist = np.linalg.norm(target['pos'] - self.player_pos)
                    if dist < 8:
                        self.quests_active += 1
                        target['has_quest'] = False
                        reward += 5.0
                    else:
                        direction = target['pos'] - self.player_pos
                        direction /= max(np.linalg.norm(direction), 0.1)
                        self.player_pos += direction * 5
            
            elif action == 3:  # turn in quest
                if self.quests_active > 0:
                    # Find any NPC
                    if self.npcs:
                        target = min(self.npcs, key=lambda n: np.linalg.norm(n['pos'] - self.player_pos))
                        dist = np.linalg.norm(target['pos'] - self.player_pos)
                        if dist < 8:
                            self.quests_active -= 1
                            self.quests_done += 1
                            self.xp += self.rng.uniform(20, 50)
                            self.copper += self.rng.uniform(10, 30)
                            reward += 20.0
                        else:
                            direction = target['pos'] - self.player_pos
                            direction /= max(np.linalg.norm(direction), 0.1)
                            self.player_pos += direction * 5
            
            elif action == 4:  # sell junk: move to vendor
                vendors = [n for n in self.npcs if n['vendor']]
                if vendors:
                    target = min(vendors, key=lambda n: np.linalg.norm(n['pos'] - self.player_pos))
                    dist = np.linalg.norm(target['pos'] - self.player_pos)
                    if dist < 8:
                        self.copper += self.rng.uniform(5, 15)
                        reward += 2.0
                    else:
                        direction = target['pos'] - self.player_pos
                        direction /= max(np.linalg.norm(direction), 0.1)
                        self.player_pos += direction * 5
        
        # Check death
        if self.player_hp <= 0:
            self.player_hp = self.player_max_hp
            self.deaths += 1
            self.player_pos = np.zeros(2)
            reward -= 15.0
            self._spawn_entities()
        
        # Heal slowly
        self.player_hp = min(self.player_hp + 1, self.player_max_hp)
        
        # Respawn dead mobs occasionally
        if self.rng.random() < 0.1:
            self._spawn_entities()
        
        self.n_steps += 1
        
        obs = self._encode()
        done = self.n_steps >= self.max_steps
        
        return obs, float(reward), done, False, {
            'kills': self.kills,
            'copper': self.copper,
            'quests_done': self.quests_done,
            'deaths': self.deaths,
            'hp': self.player_hp,
        }
    
    def _encode(self):
        """Encode state to observation vector [obs_dim]."""
        hp_frac = self.player_hp / self.player_max_hp
        
        # Nearest hostile mob
        hostile = [m for m in self.mobs if m['hostile'] and not m['dead']]
        nearest_hostile = min(hostile, key=lambda m: np.linalg.norm(m['pos'] - self.player_pos), default=None)
        
        # Nearest NPC with quest
        quest_npcs = [n for n in self.npcs if n['has_quest']]
        nearest_quest_npc = min(quest_npcs, key=lambda n: np.linalg.norm(n['pos'] - self.player_pos), default=None)
        
        # Nearest lootable
        lootable = [m for m in self.mobs if m['lootable'] and m['dead']]
        nearest_loot = min(lootable, key=lambda m: np.linalg.norm(m['pos'] - self.player_pos), default=None)
        
        obs = np.array([
            self.player_pos[0] / 1000,
            self.player_pos[1] / 1000,
            hp_frac,
            self.player_max_hp / 100,
            np.linalg.norm(nearest_hostile['pos'] - self.player_pos) / 100 if nearest_hostile is not None else 1.0,
            hash(str(id(nearest_hostile))) % 100 / 100 if nearest_hostile is not None else 0.5,
            np.linalg.norm(nearest_quest_npc['pos'] - self.player_pos) / 100 if nearest_quest_npc is not None else 1.0,
            hash(str(id(nearest_quest_npc))) % 100 / 100 if nearest_quest_npc is not None else 0.5,
            0.5,  # time of day (placeholder)
            (self.n_steps % 1000) / 1000,
            1.0 if self.quests_active > 0 else 0.0,
            self.quests_active / 10,
            min(self.quests_active, 64) / 64,
            min(self.copper, 10000) / 10000,
            1.0 if self.in_combat else 0.0,
            self.kills / 100,
        ], dtype=np.float32)
        
        return obs[:self.obs_dim]


if __name__ == '__main__':
    env = OfflineWoCEnv(max_steps=100)
    obs, _ = env.reset()
    
    total_reward = 0
    for i in range(100):
        action = env.action_space.sample()
        obs, reward, done, _, info = env.step(action)
        total_reward += reward
        if i % 20 == 0:
            print(f'step {i}: a={action} r={reward:+.2f} tot={total_reward:.1f} kills={info["kills"]} hp={info["hp"]:.0f}')
        if done:
            break
    
    print(f'\nTotal reward: {total_reward:.1f}')
