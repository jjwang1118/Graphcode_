from __future__ import annotations

import types
import openai
from typing import TYPE_CHECKING

from . import types as local_types
from .util import helper
from .. import nothing_above

if TYPE_CHECKING:
    from app.models import Model


def load():
    import json

    try:
        import ujson
    except ImportError:
        ujson = None
    return json, ujson
