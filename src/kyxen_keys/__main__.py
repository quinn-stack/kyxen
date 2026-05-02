"""Entry point: python3 -m kyxen_keys"""
from .daemon import OpenLogiKeyDaemon

def main():
    OpenLogiKeyDaemon().start()

if __name__ == '__main__':
    main()
