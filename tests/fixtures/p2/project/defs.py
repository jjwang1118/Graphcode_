"""定義抽取的測試檔。"""
LIMIT: int = 10
a, b = 1, 2
LIMIT = 20


class Runner(Base, metaclass=Meta):
    """跑東西。"""

    retries = 3

    def __init__(self, name: str, *args, flag=False, **kwargs) -> None:
        self.name = name

    @staticmethod
    async def fetch(url):
        def inner():
            local = 1
            return local
        return inner

    class Config:
        debug = False


def helper(x, y=1):
    return x


def helper(x):
    return x
