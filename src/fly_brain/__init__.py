"""src/fly_brain package — Fly brain integration for World of Claudecraft."""

from src.fly_brain.engine import BrainEngine, SparseLIFModel, get_device, load_sparse_from_parquet
from src.fly_brain.sensor_adapter import SensorAdapter, PhotoreceptorMapper
from src.fly_brain.motor_decoder import MotorDecoder, WinnerTakeAll
from src.fly_brain.da_stdp import DopamineModulatedSTDP
from src.fly_brain.woc_brain_env import WoCFlyBrainEnv
