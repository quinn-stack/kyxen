"""Entry point: python3 -m kyxen_keys"""
from .daemon import KyxenDaemon

def main():
    KyxenDaemon().start()

if __name__ == '__main__':
    main()
