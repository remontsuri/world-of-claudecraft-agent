"""wow_env.py (в tools/) — ЗАГЛУШКА игрового окружения для тестов.

Настоящий wow_env живёт в чекауте игры (python/wow_env.py) и запускает node-симу.
Этот файл даёт тот же интерфейс, чтобы можно было запускать train.py/progress_eval.py
без игры — например, для проверки устройства (tools/test_device.py) или CLI:

    WOC_PYTHON_PATH=tools python3 train.py --help

Ничего общего с настоящей игрой он не делает: obs — случайный шум.
"""
from fake_wow_env import WoWClassicEnv  # noqa: F401

__all__ = ["WoWClassicEnv"]
