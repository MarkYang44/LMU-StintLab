"""Lossless, bounded-memory scratch tables for offline analysis. Files auto-close."""
from collections import OrderedDict
from collections.abc import Sequence
import math,struct,tempfile
from buffers import CompactRow

class Slice(Sequence):
    def __init__(self,source,indices):self.source,self.indices=source,indices
    def __len__(self):return len(self.indices)
    def __getitem__(self,index):
        if isinstance(index,slice):return Slice(self.source,self.indices[index])
        return self.source[self.indices[index]]

class Column(Sequence):
    """Zero-copy column view for bisect and chronological lookup."""
    def __init__(self,source,index=0,offset=0):self.source,self.index,self.offset=source,index,offset
    def __len__(self):return len(self.source)
    def __getitem__(self,index):
        if isinstance(index,slice):return Slice(self,range(len(self))[index])
        return self.source[index][self.index]-self.offset

class DiskTable(Sequence):
    """Fixed-width float64 records; at most two 64 KiB pages retained in Python."""
    def __init__(self,rows,width,directory=None,nullable=False):
        self.width=width;self.nullable=nullable;self.record=struct.Struct('<'+str(width)+'d')
        self._file=tempfile.TemporaryFile(dir=directory);self._cache=OrderedDict();self._size=0;self._sealed=False
        self.page_rows=max(1,65536//self.record.size)
        try:
            for row in rows:self.append(row)
            self.seal()
        except BaseException:self.close();raise
    def append(self,row):
        if len(row)!=self.width:raise ValueError('Scratch row width changed')
        if self._sealed:raise ValueError('Scratch table is sealed')
        self._file.write(self.record.pack(*(math.nan if v is None else v for v in row)));self._size+=1
        self._cache.clear()
    def seal(self):self._file.flush();self._sealed=True;return self
    def __len__(self):return self._size
    def __getitem__(self,index):
        if isinstance(index,slice):return Slice(self,range(self._size)[index])
        if index<0:index+=self._size
        if not 0<=index<self._size:raise IndexError(index)
        if not self._sealed:self._file.flush()
        page=index//self.page_rows
        block=self._cache.pop(page,None)
        if block is None:
            self._file.seek(page*self.page_rows*self.record.size);block=self._file.read(self.page_rows*self.record.size)
        self._cache[page]=block
        while len(self._cache)>2:self._cache.popitem(last=False)
        result=list(self.record.unpack_from(block,(index%self.page_rows)*self.record.size))
        return [None if math.isnan(v) else v for v in result] if self.nullable else result
    def close(self):
        file=getattr(self,'_file',None)
        if file:file.close();self._file=None
        cache=getattr(self,'_cache',None)
        if cache is not None:cache.clear()
    def __del__(self):self.close()

class LapRows(Sequence):
    """Spill exact compact rows plus variable UTF-8 UTC text, including missing fields."""
    def __init__(self,directory):
        self.directory=directory;self.layout=None;self.table=None;self.utc=tempfile.TemporaryFile(dir=directory)
    def __len__(self):return len(self.table) if self.table is not None else 0
    def append(self,row):
        if self.table is None:
            self.layout=row.layout;self.table=DiskTable((),len(self.layout)+2,self.directory);self.table._sealed=False
        if row.layout!=self.layout:raise ValueError('Telemetry layout changed within lap')
        text=row.utc.encode('utf-8');offset=self.utc.tell();self.utc.write(text)
        self.table.append([*row.values,offset,len(text)])
    def seal(self):
        if self.table is not None:self.table.seal()
        self.utc.flush();return self
    def __getitem__(self,index):
        if isinstance(index,slice):return Slice(self,range(len(self))[index])
        row=self.table[index];self.utc.seek(int(row[-2]));utc=self.utc.read(int(row[-1])).decode('utf-8')
        return CompactRow(self.layout,row[:-2],utc)
    def close(self):
        if self.table is not None:self.table.close()
        if self.utc:self.utc.close();self.utc=None
    def __del__(self):
        if hasattr(self,'utc'):self.close()

def median(values):
    """Exact in-place selection on a float64 array; no sorted Python float list."""
    n=len(values)
    if not n:raise ValueError('Median requires data')
    k=n//2;lo=0;hi=n-1
    while lo<hi:
        pivot=values[(lo+hi)//2];lt=lo;i=lo;gt=hi
        while i<=gt:
            if values[i]<pivot:values[lt],values[i]=values[i],values[lt];lt+=1;i+=1
            elif values[i]>pivot:values[i],values[gt]=values[gt],values[i];gt-=1
            else:i+=1
        if k<lt:hi=lt-1
        elif k>gt:lo=gt+1
        else:break
    return values[k] if n%2 else (values[k]+max(values[i] for i in range(k)))/2
