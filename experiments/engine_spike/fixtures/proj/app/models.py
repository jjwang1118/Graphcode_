class Base:
    def base_method(self):
        return self.run()  #@ run | dyn_dispatch_self: Base.run only; overrides invisible
    def run(self):
        return 0
class Child(Base):
    def run(self):
        return 1
    def call_inherited(self):
        return self.base_method()  #@ base_method | inherited_self
class B:
    def b(self):
        return 1
class Baz:
    def bar(self):
        return 2
class Foo:
    def bar(self):
        return 1
class A:
    def __init__(self, injected=None):
        self.a = B()
        self.inj = injected
    def m(self):
        self.a.b()  #@ b | self_a_b
        self.inj.b()  #@ b | self_attr_unannotated: no type -> should be unresolved
