"""Small GDI+ raster backend. Uses Windows fonts/codecs; no Pillow runtime."""
import ctypes as C
from pathlib import Path
import uuid


class Rect(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('width',C.c_float),('height',C.c_float)]


class Startup(C.Structure):
    _fields_=[('version',C.c_uint32),('debug',C.c_void_p),('suppress_thread',C.c_int),('suppress_codecs',C.c_int)]


class GUID(C.Structure):
    _fields_=[('data1',C.c_uint32),('data2',C.c_uint16),('data3',C.c_uint16),('data4',C.c_ubyte*8)]
    @classmethod
    def parse(cls,value):return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def argb(color):return int(color.lstrip('#'),16)|0xff000000


class Canvas:
    def __init__(self,width,height):
        self.dll=C.WinDLL('gdiplus');self.token=C.c_size_t();self.image=C.c_void_p();self.graphics=C.c_void_p()
        self.fonts={};self.brushes={};self.family=C.c_void_p();self.format=C.c_void_p()
        ptr=C.c_void_p;integer=C.c_int;real=C.c_float;out=C.POINTER(ptr)
        signatures={
            'GdiplusStartup':([C.POINTER(C.c_size_t),C.POINTER(Startup),ptr],integer),
            'GdiplusShutdown':([C.c_size_t],None),
            'GdipCreateBitmapFromScan0':([integer,integer,integer,integer,ptr,out],integer),
            'GdipGetImageGraphicsContext':([ptr,out],integer),
            'GdipDeleteGraphics':([ptr],integer),'GdipDisposeImage':([ptr],integer),
            'GdipGraphicsClear':([ptr,C.c_uint32],integer),
            'GdipSetSmoothingMode':([ptr,integer],integer),
            'GdipSetTextRenderingHint':([ptr,integer],integer),
            'GdipSetInterpolationMode':([ptr,integer],integer),
            'GdipCreateSolidFill':([C.c_uint32,out],integer),'GdipDeleteBrush':([ptr],integer),
            'GdipFillRectangle':([ptr,ptr,real,real,real,real],integer),
            'GdipCreateFontFamilyFromName':([C.c_wchar_p,ptr,out],integer),
            'GdipDeleteFontFamily':([ptr],integer),
            'GdipCreateFont':([ptr,real,integer,integer,out],integer),'GdipDeleteFont':([ptr],integer),
            'GdipCreateStringFormat':([integer,integer,out],integer),
            'GdipSetStringFormatTrimming':([ptr,integer],integer),'GdipDeleteStringFormat':([ptr],integer),
            'GdipSetStringFormatAlign':([ptr,integer],integer),
            'GdipDrawString':([ptr,C.c_wchar_p,integer,ptr,C.POINTER(Rect),ptr,ptr],integer),
            'GdipCreateBitmapFromFile':([C.c_wchar_p,out],integer),
            'GdipGetImageWidth':([ptr,C.POINTER(C.c_uint32)],integer),
            'GdipGetImageHeight':([ptr,C.POINTER(C.c_uint32)],integer),
            'GdipDrawImageRectRect':([ptr,ptr,*([real]*8),integer,ptr,ptr,ptr],integer),
            'GdipSaveImageToFile':([ptr,C.c_wchar_p,C.POINTER(GUID),ptr],integer),
        }
        for name,(args,result) in signatures.items():
            function=getattr(self.dll,name);function.argtypes=args;function.restype=result
        self.check('GdiplusStartup',C.byref(self.token),C.byref(Startup(1,None,0,0)),None)
        try:
            self.check('GdipCreateBitmapFromScan0',width,height,0,2498570,None,C.byref(self.image))
            self.check('GdipGetImageGraphicsContext',self.image,C.byref(self.graphics))
            self.check('GdipSetSmoothingMode',self.graphics,4)
            self.check('GdipSetTextRenderingHint',self.graphics,4)
            self.check('GdipSetInterpolationMode',self.graphics,7)
            for family in ('Microsoft YaHei UI','Microsoft YaHei','Segoe UI','Arial'):
                if self.dll.GdipCreateFontFamilyFromName(family,None,C.byref(self.family))==0:break
            else:raise OSError('No usable Windows font')
            self.check('GdipCreateStringFormat',4096,0,C.byref(self.format))
            self.check('GdipSetStringFormatTrimming',self.format,3)
        except BaseException:
            self.close();raise

    def check(self,name,*args):
        status=getattr(self.dll,name)(*args)
        if status:raise OSError(f'{name} failed (GDI+ {status})')

    def brush(self,color):
        if color not in self.brushes:
            value=C.c_void_p();self.check('GdipCreateSolidFill',argb(color),C.byref(value));self.brushes[color]=value
        return self.brushes[color]

    def fill(self,x,y,width,height,color):
        self.check('GdipFillRectangle',self.graphics,self.brush(color),x,y,width,height)

    def clear(self,color):self.check('GdipGraphicsClear',self.graphics,argb(color))

    def text(self,value,x,y,width,height=45,size=27,color='#edf3fc',bold=False,align=0):
        key=(size,bold)
        if key not in self.fonts:
            font=C.c_void_p();self.check('GdipCreateFont',self.family,size,int(bold),2,C.byref(font));self.fonts[key]=font
        self.check('GdipSetStringFormatAlign',self.format,align)
        # GDI+ expects UTF-16 code units. -1 avoids incorrect lengths for emoji.
        self.check('GdipDrawString',self.graphics,str(value),-1,self.fonts[key],
                   C.byref(Rect(x,y,width,height)),self.format,self.brush(color))

    def photo(self,path,bounds,destination):
        """Fit a manually calibrated source rectangle; never modify the artwork."""
        image=C.c_void_p();self.check('GdipCreateBitmapFromFile',str(Path(path)),C.byref(image))
        try:
            width,height=C.c_uint32(),C.c_uint32()
            self.check('GdipGetImageWidth',image,C.byref(width));self.check('GdipGetImageHeight',image,C.byref(height))
            left,top,right,bottom=bounds
            sx,sy,sw,sh=left*width.value,top*height.value,(right-left)*width.value,(bottom-top)*height.value
            x,y,w,h=destination;scale=min(w/sw,h/sh);dw,dh=sw*scale,sh*scale
            self.check('GdipDrawImageRectRect',self.graphics,image,x+(w-dw)/2,y+(h-dh)/2,dw,dh,
                       sx,sy,sw,sh,2,None,None,None)
        finally:self.check('GdipDisposeImage',image)

    def save(self,path):
        encoder=GUID.parse('557cf406-1a04-11d3-9a73-0000f81ef32e')
        self.check('GdipSaveImageToFile',self.image,str(Path(path)),C.byref(encoder),None)

    def close(self):
        for font in self.fonts.values():self.dll.GdipDeleteFont(font)
        for brush in self.brushes.values():self.dll.GdipDeleteBrush(brush)
        self.fonts.clear();self.brushes.clear()
        if self.format:self.dll.GdipDeleteStringFormat(self.format);self.format=None
        if self.family:self.dll.GdipDeleteFontFamily(self.family);self.family=None
        if self.graphics:self.dll.GdipDeleteGraphics(self.graphics);self.graphics=None
        if self.image:self.dll.GdipDisposeImage(self.image);self.image=None
        if self.token:self.dll.GdiplusShutdown(self.token);self.token=C.c_size_t()

    def __enter__(self):return self
    def __exit__(self,*_):self.close()
