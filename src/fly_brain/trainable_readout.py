"""trainable_readout.py — trainable readout over fixed MaleCNS connectome.

Pattern from Fly Dino (cobanov/flyjump), fly-craftax (liuzihe02), FLYT3 (seanphan):
the connectome wiring is FIXED; only a small readout on top of descending-neuron
activity is trained. Training: Cross-Entropy Method (CEM) — no backprop through
the spiking network, just score readout weights by game reward.

Why CEM (vs PPO): CEM needs no gradient estimator over a 211K-neuron spiking
graph, converges in ~100-300 episodes for 20-50 params, and is what Fly Dino
used successfully with 243 parameters on 80 neurons.
"""
import numpy as np


class ReadoutPolicy:
    """Linear readout: descending-neuron rates -> 7 WoC action scores.

    action = argmax(W @ rates + b),  W: (7, n_readout), b: (7,)
    Fixed connectome, trainable readout only.
    """

    N_ACTIONS = 7  # MOVE_FORWARD, TURN_LEFT, TURN_RIGHT, ATTACK, TARGET, LOOT, REST

    def __init__(self, n_readout, seed=0):
        self.n_readout = n_readout
        self.rng = np.random.RandomState(seed)
        self.reset_params()

    def reset_params(self):
        self.W = np.zeros((self.N_ACTIONS, self.n_readout))
        self.b = np.zeros(self.N_ACTIONS)

    def param_vector(self):
        return np.concatenate([self.W.ravel(), self.b])

    def set_params(self, vec):
        n_w = self.N_ACTIONS * self.n_readout
        self.W = vec[:n_w].reshape(self.N_ACTIONS, self.n_readout)
        self.b = vec[n_w:]

    @property
    def n_params(self):
        return self.N_ACTIONS * self.n_readout + self.N_ACTIONS

    def act(self, rates):
        """rates: (n_readout,) descending-neuron firing rates -> action id."""
        rates = np.asarray(rates, dtype=np.float32)
        scores = self.W @ rates + self.b
        return int(np.argmax(scores))

    def act_with_noise(self, rates, noise=0.1):
        scores = self.W @ np.asarray(rates, dtype=np.float32) + self.b
        scores += self.rng.normal(0, noise, scores.shape)
        return int(np.argmax(scores))


class CEMTrainer:
    """Cross-Entropy Method: train readout weights by game reward.

    Elite fraction keeps the top-k parameter vectors per generation,
    re-samples the next generation from their mean/covariance.
    """

    def __init__(self, n_params, pop_size=48, elite_frac=0.25, noise=0.05, seed=0):
        self.n_params = n_params
        self.pop_size = pop_size
        self.n_elite = max(2, int(pop_size * elite_frac))
        self.noise = noise
        self.rng = np.random.RandomState(seed)
        self.mu = np.zeros(n_params)
        self.sigma = np.ones(n_params) * noise
        self.generation = 0
        self.best_score = -np.inf
        self.best_params = None

    def sample_population(self):
        pop = np.stack([
            self.rng.normal(self.mu, self.sigma) for _ in range(self.pop_size)
        ])
        return pop

    def update(self, population, scores):
        """population: (pop_size, n_params), scores: (pop_size,)"""
        order = np.argsort(scores)[::-1][: self.n_elite]
        elite = population[order]
        self.mu = elite.mean(axis=0)
        self.sigma = elite.std(axis=0) + 1e-6
        self.generation += 1
        if scores[order[0]] > self.best_score:
            self.best_score = scores[order[0]]
            self.best_params = elite[0].copy()
        return self.mu.copy()

    def save(self, path):
        np.savez(path, mu=self.mu, sigma=self.sigma, best_params=self.best_params,
                 best_score=self.best_score, generation=self.generation)

    def load(self, path):
        d = np.load(path)
        self.mu = d["mu"]
        self.sigma = d["sigma"]
        self.best_params = d["best_params"]
        self.best_score = float(d["best_score"])
        self.generation = int(d["generation"])


if __name__ == "__main__":
    # Smoke test
    pol = ReadoutPolicy(n_readout=5, seed=42)
    trainer = CEMTrainer(n_params=pol.n_params, pop_size=16, elite_frac=0.25)
    print(f"[readout] n_params={pol.n_params}")
    pop = trainer.sample_population()
    # dummy scores
    scores = np.array([i for i in range(16)], dtype=float)
    trainer.update(pop, scores)
    print(f"[readout] CEM gen={trainer.generation}, best={trainer.best_score:.2f}")
    rates = np.random.rand(5)
    print(f"[readout] action for random rates: {pol.act(rates)}")
    print("[readout] OK")
