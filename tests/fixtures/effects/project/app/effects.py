import os
import subprocess

from app import util

TOTAL = 0


class Store:
    count = 0

    def save(self, path, data):
        global TOTAL
        self.last = path
        if not data:
            raise ValueError("empty")
        with open(path, "w") as handle:
            handle.write(data)
        return self.count


def cleanup(path):
    os.remove(path)
    subprocess.run(["ls"])
    return util.helper()


def outer(path):
    cleanup(path)
    print("done")


def pure(x):
    return x + 1
