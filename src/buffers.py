"""Exact float64 buffers. Allocate on demand, with fixed upper bounds."""
from array import array
from collections.abc import Mapping, Sequence
import math


class NumericRing(Sequence):
    def __init__(self, width, maxlen):
        self.width, self.maxlen = width, maxlen
        self._data = array('d')
        self._capacity = self._start = self._size = 0

    def __len__(self): return self._size

    def _index(self, index):
        if index < 0: index += self._size
        if not 0 <= index < self._size: raise IndexError(index)
        return ((self._start + index) % self._capacity) * self.width

    def __getitem__(self, index):
        if isinstance(index, slice): return [self[i] for i in range(*index.indices(self._size))]
        p = self._index(index)
        return tuple(self._data[p:p+self.width])

    def __setitem__(self, index, row):
        if len(row) != self.width: raise ValueError('Buffer row width changed')
        p = self._index(index)
        self._data[p:p+self.width] = array('d', row)

    def append(self, row):
        if len(row) != self.width: raise ValueError('Buffer row width changed')
        if self._size == self._capacity and self._capacity < self.maxlen:
            capacity = min(self.maxlen, max(64, self._capacity*2))
            data = array('d', [0.0]) * (capacity*self.width)
            for i in range(self._size):
                p = ((self._start+i) % self._capacity)*self.width
                data[i*self.width:(i+1)*self.width] = self._data[p:p+self.width]
            self._data, self._capacity, self._start = data, capacity, 0
        if self._size == self.maxlen:
            self._start = (self._start+1) % self._capacity
            self._size -= 1
        self._size += 1
        self[-1] = row

    def popleft(self):
        value = self[0]
        self._start = (self._start+1) % self._capacity
        self._size -= 1
        return value

    def pop(self):
        value = self[-1]; self._size -= 1
        return value

    def extend(self, rows):
        for row in rows:self.append(row)

    def clear(self):
        self._data = array('d')
        self._capacity = self._start = self._size = 0


class ControlHistory(NumericRing):
    """The raw history has six channels; extrema exist only in display buckets."""
    def __init__(self, maxlen=80001): super().__init__(7, maxlen)
    def append(self, point):
        super().append((point[0], *point[1:4], *point[10:13]))
    def __setitem__(self, index, row): NumericRing.__setitem__(self, index, row)
    def __getitem__(self, index):
        if isinstance(index, slice): return [self[i] for i in range(*index.indices(len(self)))]
        r = NumericRing.__getitem__(self, index)
        return (r[0], *r[1:4], *r[1:4], *r[1:4], *r[4:7], *r[4:7], *r[4:7])


class CompactRow(Mapping):
    """Numeric CSV rows share their schema and retain all missing-value semantics."""
    __slots__ = ('layout', 'values', 'utc')
    def __init__(self, layout, values, utc):
        self.layout, self.values, self.utc = layout, array('d', values), utc
    def __getitem__(self, key):
        if key == 'utc': return self.utc
        value = self.values[self.layout[key]]
        if math.isnan(value): raise KeyError(key)
        return value
    def __iter__(self):
        yield 'utc'
        for key, i in self.layout.items():
            if not math.isnan(self.values[i]): yield key
    def __len__(self): return 1+sum(not math.isnan(x) for x in self.values)
    def __contains__(self, key):
        return key == 'utc' or key in self.layout and not math.isnan(self.values[self.layout[key]])


class NumericTable(Sequence):
    """Contiguous matrix for immutable reference rows; no retained row objects."""
    def __init__(self, rows, width):
        self.width = width
        self.values = array('d', (x for row in rows for x in row))
        if len(self.values) % width: raise ValueError('Invalid numeric matrix')
    def __len__(self): return len(self.values)//self.width
    def __getitem__(self, index):
        if isinstance(index, slice): return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0: index += len(self)
        if not 0 <= index < len(self): raise IndexError(index)
        p = index*self.width
        return tuple(self.values[p:p+self.width])


class NullableTable(NumericTable):
    def __init__(self,rows,width):
        super().__init__(([math.nan if x is None else x for x in row] for row in rows),width)
    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(len(self)))]
        return tuple(None if math.isnan(x) else x for x in super().__getitem__(index))
