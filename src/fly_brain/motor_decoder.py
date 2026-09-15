"""motor_decoder.py — decode MaleCNS descending neuron spikes to WoC actions.

Real MaleCNS v1.0 readout neurons (found via body-annotations, superclass=descending_neuron):
- DNg13 (bodyId 11074 L / 512006 R) → TURN_LEFT / TURN_RIGHT
- DNp01 Giant Fiber (bodyId 10001 R / 10010 L) → ATTACK
- DNg56 (bodyId 10033 R / 12621 L, exits to LB leg neuromere) → MOVE_FORWARD
- DNg30 (bodyId 10123 L / 10237 R) → TARGET_NEAREST
- DNg08 (largest DN group, leg control) → LOOT_QUEST

Both DNg13 active → MOVE_FORWARD. No activity → REST.
Fixed connectome + fixed readout (doomfly / fly-craftax pattern).
"""
import numpy as np
import torch


class FixedThresholdDecoder:
    """Decode spikes from MaleCNS descending neurons to actions.

    threshold: Hz, minimum firing rate to trigger action
    cooldown: minimum steps between actions
    """

    ACTION_NAMES = {
        0: 'MOVE_FORWARD',
        1: 'TURN_LEFT',
        2: 'TURN_RIGHT',
        3: 'ATTACK',
        4: 'TARGET_NEAREST',
        5: 'LOOT_QUEST',
        6: 'REST',
    }

    # MaleCNS v1.0 readout: neuron name → (bodyId L, bodyId R)
    # Must be remapped to engine indices by set_mapping().
    READOUT_NAMES = {
        'DNg13':   (11074, 512006),   # leg/gnathal steering
        'DNp01':   (10010, 10001),    # Giant Fiber escape → attack
        'DNg56':   (12621, 10033),    # LB leg neuromere → forward
        'DNg30':   (10123, 10237),    # steering/targeting
        'DNg08':   (None, None),      # largest group, filled dynamically
    }

    def __init__(self, threshold=0.05, cooldown=4, n_neurons=211577):
        self.threshold = threshold
        self.cooldown = cooldown
        self.n_neurons = n_neurons
        self.steps_since_action = cooldown
        self.last_action = 6
        self.group_rates = {k: 0.0 for k in self.READOUT_NAMES}
        # resolved engine indices after set_mapping
        self.idx = {k: None for k in self.READOUT_NAMES}

    def set_mapping(self, body2idx):
        """Map bodyIds → engine indices using MaleCNS annotation mapping."""
        mapped = {}
        for name, (l, r) in self.READOUT_NAMES.items():
            if name == 'DNg08':
                continue
            li = body2idx.get(l)
            ri = body2idx.get(r)
            if li is not None and ri is not None:
                mapped[name] = (li, ri)
            else:
                print(f"[motor] WARN: {name} bodies {l},{r} not in mapping")
        self.idx.update(mapped)
        return mapped

    def update_rates(self, spike_counts, window_steps, dt_ms=0.1):
        duration_s = max(window_steps * dt_ms / 1000.0, 1e-6)
        for name, pair in self.idx.items():
            if pair is None:
                continue
            li, ri = pair
            if li < len(spike_counts) and ri < len(spike_counts):
                self.group_rates[name] = (spike_counts[li] + spike_counts[ri]) / duration_s
            else:
                self.group_rates[name] = 0.0
        self.steps_since_action += 1

    def decode(self, spikes=None, n_steps=1, dt_ms=0.1):
        """Decode spikes to action (0-6)."""
        if spikes is not None:
            if isinstance(spikes, torch.Tensor):
                spikes = spikes.detach().cpu().numpy().reshape(-1)
            self.update_rates(spikes, n_steps, dt_ms)

        if self.steps_since_action < self.cooldown:
            return self.last_action

        l13 = self.group_rates['DNg13']
        gf = self.group_rates['DNp01']
        dng56 = self.group_rates['DNg56']
        dng30 = self.group_rates['DNg30']

        action = 6  # REST

        # Giant Fiber → ATTACK (highest priority)
        if gf > self.threshold:
            action = 3
        # Both DNg13 active → MOVE_FORWARD
        elif l13 > self.threshold and dng56 > self.threshold:
            action = 0
        elif l13 > self.threshold:
            action = 2  # TURN_LEFT (left DNg13 dominates)
        elif dng56 > self.threshold:
            action = 1  # TURN_RIGHT
        elif dng30 > self.threshold:
            action = 4  # TARGET_NEAREST

        self.last_action = action
        if action != 6:
            self.steps_since_action = 0

        return action

    def get_action_name(self, action_id):
        return self.ACTION_NAMES.get(action_id, 'UNKNOWN')


# Backwards compat
MotorDecoder = FixedThresholdDecoder


if __name__ == "__main__":
    decoder = FixedThresholdDecoder(threshold=0.05, cooldown=3, n_neurons=211577)
    print('[motor_decoder] FixedThresholdDecoder ready for MaleCNS')
    print('[motor_decoder] Call set_mapping(body2idx) after loading annotations')
