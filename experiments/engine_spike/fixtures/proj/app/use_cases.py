import os
import types  #@ types | shadow_in_pkg_stdlib: expect stdlib
import json  # unused import
import app.sideeffect  # side-effect only import
from typing import TYPE_CHECKING
from openai import AsyncOpenAI  #@ AsyncOpenAI | shadow_in_pkg_other: expect third-party
from app.util import helper, foo as foo_alias
from app.util import *
from app.pkg import Thing  #@ Thing | reexport_import
from app.models import Foo, Baz, Child, Base, A
if TYPE_CHECKING:
    from app.models import B  # typing-only import

def f(helper):
    return helper()  #@ helper | param_shadow: must NOT link to app.util.helper

def g():
    from app.util import foo
    return foo()  #@ foo | func_level_import_inside

def h():
    return foo()  #@ foo | func_level_import_outside: star import makes this legal here

def h2():
    return helper2()  #@ helper2 | undefined_name: must be unresolved

def xcall():
    x = Foo()
    return x.bar()  #@ bar | local_var_call

def reexp():
    return Thing().go()  #@ go | reexport_method

def inh():
    return Child().base_method()  #@ base_method | inherited_call

def star():
    return starred()  #@ starred | star_import

def dyn(name):
    obj = Foo()
    getattr(obj, "bar")()  #@ getattr | getattr_literal
    return getattr(obj, name)()  #@ getattr | getattr_dynamic

def union(flag):
    x = Foo() if flag else Baz()
    return x.bar()  #@ bar | union_receiver: expect BOTH Foo.bar and Baz.bar

def unann(obj):
    return obj.bar()  #@ bar | unannotated_param: expect unresolved

def ann(b: Base):
    return b.run()  #@ run | annotated_base: Base.run (Child.run also reachable at runtime)

def typed_only(b: "B"):
    return b.b()  #@ b | type_checking_import

def cb():
    return list(map(helper, [1]))  #@ helper | callback_reference (use without call)

def alias():
    fn = foo_alias
    return fn()  #@ fn | alias_call

def table(k):
    d = {"a": foo_alias, "b": helper}
    return d[k]()  #@ d | dict_dispatch

def ext():
    return os.path.join("a", "b")  #@ join | stdlib_attr
