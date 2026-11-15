class Base:
    def run(self):
        return self.step()

    def step(self):
        return 1


class Sub(Base):
    def step(self):
        return helper()


def helper():
    return 2


def dynamic(name):
    return getattr(Sub(), name)()


def unused():
    return helper()
