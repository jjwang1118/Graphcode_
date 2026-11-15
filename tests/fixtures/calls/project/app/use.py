import os

from app import util
from app.models import Base, Foo, Invoker
from app.pkg import thing


def param_shadow(helper):
    return helper()


def local_instance():
    x = Foo()
    return x.go()


def alias():
    fn = util.helper
    return fn()


def union(flag):
    obj = Foo() if flag else Base()
    return obj.step()


def dynamic(d, k):
    d[k]()
    return getattr(util, "helper")()


def external():
    return os.path.join("a", "b")


def reexport():
    return thing()


def ref_only(xs):
    return list(map(util.helper, xs))


def untyped(obj):
    return obj.bar()


@util.deco
def decorated():
    return util.LIMIT


def instance_call():
    c = Invoker()
    return c()


def annotated(item: Foo) -> Base:
    return item


top = util.helper()


class Child(Foo):
    pass


class Ext(dict):
    pass
