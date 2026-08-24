import sys
bad = [p for p in sys.path if 'hermes' in p.lower()]
print('HERMES IN PATH:', bad)
import numpy, gymnasium
print('numpy', numpy.__version__, 'gym', gymnasium.__version__)
