import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor", "vlib"))
from inner import inner_fn  #@ inner_fn | syspath_insert: local via runtime sys.path edit
import yaml  #@ yaml | entrypoint_dependent: run as `python scripts/run.py` -> sys.path[0]=scripts -> PyYAML, NOT local yaml.py
