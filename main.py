"""TXT Reader — lightweight text reader for Windows with progress tracking.

Progress is tracked via byte-offset into the file, which is the most reliable
method: O(1) seek, immune to encoding drift, and precise to the byte.

Usage:
    python main.py                        # launches the reader
    pyinstaller -F -w main.py             # build standalone .exe
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reader_ui import ReaderApp


def main():
    app = ReaderApp()
    app.run()


if __name__ == '__main__':
    main()
