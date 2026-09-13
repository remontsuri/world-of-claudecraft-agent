import sys
sys.path.insert(0, 'D:/world-of-claudecraft')

import torch, numpy as np, time
from python.connectome_policy import ConnectomePolicy, WoCObservationEncoder

print('=== ConnectomePolicy Performance Test ===')

t0 = time.time()
policy = ConnectomePolicy(obs_dim=16, action_dim=4)
t_init = time.time() - t0
print(f'Init: {t_init:.2f}s')

obs = torch.randn(1, 16)
policy.reset_state(batch_size=1)

times = []
for i in range(100):
    t0 = time.time()
    logits, value, h = policy.forward(obs)
    times.append(time.time() - t0)

print(f'Forward: {np.mean(times)*1000:.2f}ms ± {np.std(times)*1000:.2f}ms')

t0 = time.time()
for i in range(1000):
    action, log_prob, val, h_new = policy.get_action(obs)
t_action = time.time() - t0
print(f'get_action (1000 calls): {t_action*1000:.2f}ms, {t_action:.4f}ms/call')

total_params = sum(p.numel() for p in policy.parameters())
trainable = sum(p.numel() for p in policy.parameters() if p.requires_grad)
W_params = policy.W._nnz()
print(f'Parameters: total={total_params:,}, trainable={trainable:,}, W_synapses={W_params:,}')

print(f'\nConfig: {policy.get_config()}')
