import sys, traceback
try:
    import numpy
    print("numpy OK", numpy.__version__)
except Exception:
    traceback.print_exc()
    # also print sys.path entry holding numpy
    import os
    for p in sys.path:
        if os.path.isdir(os.path.join(p, "numpy")):
            print("NUMPY SITEDIR:", os.path.join(p, "numpy"))
