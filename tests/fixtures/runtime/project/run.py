from lib import Sub, dynamic


def helper_wrap():
    return 1


def main():
    Sub().run()
    dynamic("step")
    return [helper_wrap() for _ in range(2)]


main()
