from app import util


class Base:
    def run(self):
        return self.step()

    def step(self):
        return 1


class Helper:
    def work(self):
        return util.helper()


class Foo(Base):
    def __init__(self):
        self.b = Helper()

    def step(self):
        return 2

    def go(self):
        self.b.work()
        return super().run()


class Invoker:
    def __call__(self):
        return 1
