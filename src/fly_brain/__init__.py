"""src/fly_brain package — Fly brain integration for World of Claudecraft."""

from src.fly_brain.engine import (
    BrainEngine,
    SparseLIFModel,
    get_device,
    load_sparse_weights,
    load_male_cns_weights,
    load_connectome,
)
from src.fly_brain.sensor_adapter import SensorAdapter, PhotoreceptorMapper
from src.fly_brain.motor_decoder import FixedThresholdDecoder, MotorDecoder
from src.fly_brain.da_stdp import DopamineModulatedSTDP
from src.fly_brain.woc_brain_env import WoCFlyBrainEnv
from src.fly_brain.fly_brain import FlyBrain
from src.fly_brain.agent import FlyBrainReadout, MLPControl
from src.fly_brain.woc_features import extract_features
