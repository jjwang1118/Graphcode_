import yaml  #@ yaml | shadow_root: local yaml.py wins at runtime (cwd=proj)
import app.use_cases
yaml.dump_local(1)  #@ dump_local | shadow_root_attr
import colorsys  #@ colorsys | shadow_root_stdlib: runtime picks LOCAL colorsys.py
