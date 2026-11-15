from app.models import A, Foo, Child


class P:
    @property
    def val(self):
        return Foo()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def __add__(self, o):
        return self


def deco(fn):
    def wrapper(*a, **k):
        return fn(*a, **k)
    return wrapper


@deco
def decorated():
    return Foo()


def t():
    a = A()  #@ A | ctor_call: class or __init__?
    P().val.bar()  #@ bar | property_chain
    decorated().bar()  #@ bar | untyped_decorator
    with P() as p:
        p + p  #@ p | operator_dunder: __add__ / __enter__ invisible
    return [c.run() for c in [Child()]]  #@ run | comprehension_call


class S(Child):
    def run(self):
        return super().run()  #@ run | super_call
