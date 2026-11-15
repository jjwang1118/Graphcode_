"""Local file INSIDE a package: `import openai` must go to site-packages (unless run as a script)."""
from openai import AsyncOpenAI  #@ AsyncOpenAI | shadow_in_pkg_self: expect third-party
def make():
    return AsyncOpenAI()
