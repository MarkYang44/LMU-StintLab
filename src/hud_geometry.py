"""Pure HUD geometry and cached steering-wheel drawing."""
import math


def steering_angle(value):
    """The requested 540 degree total visual lock is -270 left to +270 right."""
    return max(-1,min(1,value))*270


def rotate_wheel(points, cx, cy, scale, degrees):
    angle = math.radians(degrees)
    cosine,sine = math.cos(angle),math.sin(angle)
    return [coordinate for x,y in points for coordinate in
            (cx+scale*(x*cosine-y*sine),cy+scale*(x*sine+y*cosine))]


def hud_layout(w, h, clean=False, controls=False):
    s = min(w/640,h/228)
    if clean:
        if controls:
            s = min(w/600,h/100)
            panel = (w-170*s,2,w-2,h-2)
            px0 = panel[0]
            return dict(scale=s,plot=(2,px0-12*s,2,h-2),panel=panel,
                        pedals=((px0+8*s,8*s,px0+20*s,h-8*s),
                                (px0+32*s,8*s,px0+44*s,h-8*s)),
                        wheel=(px0+113*s,h/2,min(40*s,(h-12*s)/2)))
        return dict(scale=s,plot=(2,w-2,2,h-2),panel=None)
    panel = (w-194*s,89*s,w-14*s,h-27*s)
    x0,y0,x1,y1 = panel
    radius = min(36*s,(y1-y0-42*s)/2)
    return dict(scale=s,plot=(24*s,w-210*s,94*s,h-32*s),panel=panel,
                pedals=((x0+15*s,y0+25*s,x0+29*s,y1-23*s),
                        (x0+43*s,y0+25*s,x0+57*s,y1-23*s)),
                wheel=(x0+119*s,(y0+y1)/2,radius))


def pedal_fill(bounds, value):
    x0,y0,x1,y1 = bounds
    return (x0,y1-(y1-y0)*max(0,min(1,value)),x1,y1)


class WheelDisplay:
    """Cached vector interpretation of the Fanatec BMW M4 GT3 front face.

    Reference: Fanatec's official product photo, P_SW_BMW_GT3_H-01.webp.
    The open shoulders, side grips, flat bottom and three colored rotaries
    are drawn here; no vendor raster asset or image processing is needed.
    """
    def __init__(self, canvas, cx, cy, radius, background='#121d2b'):
        self.canvas,self.cx,self.cy,self.scale = canvas,cx,cy,radius/1.13
        self.parts = []
        self.angle = None
        canvas.tk.eval('''namespace eval ::inputscope {}
            proc ::inputscope::wheel_coords {canvas updates} {
                foreach coords $updates { $canvas coords {*}$coords }
            }''')
        def polygon(points,fill,outline='',smooth=False,width=1):
            item = canvas.create_polygon(*rotate_wheel(points,cx,cy,self.scale,0),
                                         fill=fill,outline=outline,smooth=smooth,
                                         splinesteps=12,width=width,tags='wheel')
            self.parts.append(('polygon',item,points))
        def line(points,color,width=1):
            item = canvas.create_line(*rotate_wheel(points,cx,cy,self.scale,0),
                                      fill=color,width=width,capstyle='round',tags='wheel')
            self.parts.append(('polygon',item,points))
        def circle(x,y,radius,fill,outline='',width=1):
            item = canvas.create_oval(0,0,1,1,fill=fill,outline=outline,width=width,tags='wheel')
            self.parts.append(('circle',item,(x,y,radius)))
        # The silhouette's grip and lower rim surround the carbon control plate.
        polygon([(-.83,-.66),(-.98,-.56),(-1.03,-.14),(-1.02,.23),(-.94,.55),
                 (-.79,.75),(-.45,.84),(0,.86),(.45,.84),(.79,.75),(.94,.55),
                 (1.02,.23),(1.03,-.14),(.98,-.56),(.83,-.66),(.38,-.42),
                 (0,-.40),(-.38,-.42)],'#0a1018','#657386',True)
        for sign in (-1,1):
            polygon([(sign*x,y) for x,y in ((.92,-.45),(1.02,-.15),(1,.25),
                     (.91,.51),(.78,.44),(.80,.10),(.76,-.19),(.80,-.43))],
                    '#252e3a','#465362',True)
            # Transparent-looking hand openings use the control card's solid tint.
            polygon([(sign*x,y) for x,y in ((.76,-.44),(.56,-.34),(.52,-.07),
                     (.69,-.04),(.82,-.13),(.84,-.31))],background,'',True)
            polygon([(sign*x,y) for x,y in ((.81,.11),(.64,.11),(.56,.37),
                     (.59,.52),(.73,.52),(.84,.33))],background,'',True)
            line([(sign*.97,-.17),(sign*.94,.18),(sign*.87,.36)],'#566271')
        polygon([(-.56,-.35),(-.36,-.40),(.36,-.40),(.56,-.35),(.55,.40),
                 (.43,.49),(0,.53),(-.43,.49),(-.55,.40)],'#17212e','#435164',True)
        polygon([(-.65,.61),(-.35,.55),(0,.59),(.35,.55),(.65,.61),
                 (.65,.70),(.35,.74),(0,.75),(-.35,.74),(-.65,.70)],background,'',True)
        # Twelve small backlit buttons, matching the reference's wing arrangement.
        for sign in (-1,1):
            for x,y,color in ((.76,-.53,'#4bb8ff'),(.61,-.46,'#4bb8ff'),
                              (.49,-.32,'#eed94c'),(.46,-.08,'#eed94c'),
                              (.48,.10,'#ff5677'),(.50,.27,'#ff5677')):
                circle(sign*x,y,.037,'#0c1725',color)
        for x,y,color in ((-.23,-.19,'#ff596b'),(.23,-.19,'#52b5ff'),(0,.34,'#34e59a')):
            circle(x,y,.135,'#0a121e',color,1.3)
            line([(x,y+.035),(x+.015,y-.095)],color,1.6)
        # Round central badge and tiny blue/white quadrants keep the front view legible.
        circle(0,.03,.115,'#d4dce7','#070d15')
        polygon([(0,.03),(0,-.05),(.08,-.05),(.08,.03)],'#3aa7e8')
        polygon([(0,.03),(0,.11),(-.08,.11),(-.08,.03)],'#3aa7e8')
        self.set_angle(0)

    def set_angle(self, angle):
        if angle == self.angle:
            return
        self.angle = angle
        radians = math.radians(angle)
        cosine,sine = math.cos(radians),math.sin(radians)
        updates = []
        for kind,item,points in self.parts:
            if kind == 'circle':
                x,y,r = points
                x,y = (self.cx+self.scale*(x*cosine-y*sine),
                       self.cy+self.scale*(x*sine+y*cosine))
                radius = r*self.scale
                coords = (x-radius,y-radius,x+radius,y+radius)
            else:
                coords = [coordinate for x,y in points for coordinate in
                          (self.cx+self.scale*(x*cosine-y*sine),
                           self.cy+self.scale*(x*sine+y*cosine))]
            updates.append((item,*coords))
        # One Tk bridge call per wheel, rather than releasing/reacquiring the GIL
        # for every button and grip at high telemetry rates.
        self.canvas.tk.call('::inputscope::wheel_coords',self.canvas._w,tuple(updates))


def reduce_trace(coords, tolerance=0.35):
    """Linear-time monotonic simplification, with a bounded vertical pixel error.

    Keep actual endpoints and vertical pedal edges. A recursive whole-line RDP
    search can become quadratic on high-rate flat/vertical input traces.
    """
    count = len(coords) // 2
    if count < 3:
        return coords
    output = list(coords[:2])
    ax, ay = px, py = coords[:2]
    low, high = -math.inf, math.inf
    def emit(x,y):
        if output[-2:] != [x,y]:
            output.extend((x,y))
    for index in range(1,count):
        x,y = coords[2*index:2*index+2]
        if x < px:
            return coords
        dx = x-ax
        if dx > 0 and not low <= (y-ay)/dx <= high:
            emit(px,py)
            ax,ay = px,py
            low,high = -math.inf,math.inf
            dx = x-ax
        if dx == 0:
            if y != ay:
                emit(px,py)
                emit(x,y)
                ax,ay = x,y
                low,high = -math.inf,math.inf
        else:
            low = max(low,(y-ay-tolerance)/dx)
            high = min(high,(y-ay+tolerance)/dx)
        px,py = x,y
    emit(px,py)
    return output
