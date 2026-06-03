"""File handler: line indexing, encoding detection, efficient line retrieval."""

import os
import struct
import bisect


class FileHandler:
    """Handles text file loading, line indexing, and efficient random access."""

    def __init__(self):
        self.filepath = None
        self.line_index = []       # byte offset of each line start
        self.file_size = 0
        self._encoding = 'utf-8'

    def load_file(self, filepath):
        self.filepath = filepath
        self.file_size = os.path.getsize(filepath)
        self._detect_encoding()
        self._build_index()

    def _detect_encoding(self):
        try:
            with open(self.filepath, 'rb') as f:
                bom = f.read(4)
                if bom[:2] == b'\xff\xfe':
                    self._encoding = 'utf-16-le'
                elif bom[:2] == b'\xfe\xff':
                    self._encoding = 'utf-16-be'
                elif bom[:3] == b'\xef\xbb\xbf':
                    self._encoding = 'utf-8-sig'
        except Exception:
            pass

    def _index_cache_path(self):
        return self.filepath + '.ridx'

    def _build_index(self):
        cache_path = self._index_cache_path()

        # Try cached index first
        if os.path.exists(cache_path):
            try:
                if os.path.getmtime(cache_path) >= os.path.getmtime(self.filepath):
                    with open(cache_path, 'rb') as f:
                        count = struct.unpack('I', f.read(4))[0]
                        data = f.read(count * 8)
                        if len(data) == count * 8:
                            self.line_index = list(struct.unpack(f'{count}Q', data))
                            # Drop sentinel if present (from older builds)
                            if len(self.line_index) > 1 and self.line_index[-1] >= self.file_size:
                                self.line_index.pop()
                            return
            except Exception:
                pass

        # Build index from scratch
        self.line_index = [0]
        with open(self.filepath, 'rb') as f:
            offset = 0
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                pos = 0
                while True:
                    nl = chunk.find(b'\n', pos)
                    if nl == -1:
                        break
                    self.line_index.append(offset + nl + 1)
                    pos = nl + 1
                offset += len(chunk)

        # Remove trailing sentinel if file ends with newline
        if len(self.line_index) > 1 and self.line_index[-1] >= self.file_size:
            self.line_index.pop()

        # Persist cache
        try:
            with open(cache_path, 'wb') as f:
                f.write(struct.pack('I', len(self.line_index)))
                f.write(struct.pack(f'{len(self.line_index)}Q', *self.line_index))
        except Exception:
            pass

    @property
    def line_count(self):
        return len(self.line_index)

    def get_lines(self, start_line, count):
        """Read `count` lines starting from `start_line` (0-indexed)."""
        if start_line >= len(self.line_index):
            return []

        end_line = min(start_line + count, len(self.line_index))
        lines = []

        with open(self.filepath, 'rb') as f:
            f.seek(self.line_index[start_line])
            for _ in range(end_line - start_line):
                raw = f.readline()
                try:
                    text = raw.decode(self._encoding, errors='replace')
                except Exception:
                    try:
                        text = raw.decode('gbk', errors='replace')
                    except Exception:
                        text = raw.decode('latin-1', errors='replace')
                lines.append(text.rstrip('\n\r'))

        return lines

    def line_to_offset(self, line_num):
        if 0 <= line_num < len(self.line_index):
            return self.line_index[line_num]
        return 0

    def offset_to_line(self, byte_offset):
        idx = bisect.bisect_right(self.line_index, byte_offset) - 1
        return max(0, idx)

    def progress_percent(self, byte_offset):
        if self.file_size == 0:
            return 0.0
        return (byte_offset / self.file_size) * 100.0

    def unload(self):
        self.filepath = None
        self.line_index = []
        self.file_size = 0
