from openai import AsyncOpenAI  #@ AsyncOpenAI | shadow_from_tests: expect third-party
from srcpkg.core import core_fn  #@ core_fn | src_layout: only resolvable if src/ on path
import nsdir.sub.leaf  #@ leaf | namespace_pkg
