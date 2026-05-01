"""Entry point: python3 -m openlogikey"""
from .daemon import OpenLogiKeyDaemon

def main():
    OpenLogiKeyDaemon().start()

if __name__ == '__main__':
    main()
