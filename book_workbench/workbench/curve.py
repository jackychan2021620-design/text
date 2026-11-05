"""Trace blue chart pixels. Results are estimates, never recovered exact daily sales."""
from collections import deque,defaultdict
from statistics import median
import math
from .image_io import read_image
from PySide6.QtGui import QImage


def blue_pixels(image,rect=None):
    image=image.convertToFormat(QImage.Format.Format_RGB888)
    raw=bytes(image.constBits());stride=image.bytesPerLine()
    x,y,w,h=rect or (0,0,image.width(),image.height());points=set()
    for row in range(max(0,int(y)),min(image.height(),int(y+h))):
        for col in range(max(0,int(x)),min(image.width(),int(x+w))):
            i=row*stride+col*3;r,g,b=raw[i:i+3]
            if b>=180 and 100<=g<=230 and r<=130 and b-r>=80 and b-g>=15:
                points.add((col,row))
                if len(points)>500000:raise ValueError('蓝色区域过大，请只框选销量折线绘图区')
    return points


def locate_curve(image,words=()):
    points=blue_pixels(image);candidates=[]
    while points:
        first=points.pop();q=deque([first]);component=[first]
        while q:
            x,y=q.popleft()
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
                point=(x+dx,y+dy)
                if point in points:points.remove(point);q.append(point);component.append(point)
        xs=[p[0] for p in component];ys=[p[1] for p in component]
        left,right=min(xs),max(xs);top,bottom=min(ys),max(ys);width=right-left+1;height=bottom-top+1
        if width<image.width()*.35 or height<15 or width<height*1.3:continue
        if len(set(xs))/width<.7:continue
        # Thin, wide connected components are plausible line charts, not bars/cards.
        density=len(component)/(width*height)
        if density>.28:continue
        candidates.append((width*(1-density),left,top,right,bottom))
    if not candidates:return None
    _,left,top,right,bottom=max(candidates)
    ticks=[]
    for word in words:
        try:value=float(word['text'].replace(',',''))
        except (ValueError,TypeError):continue
        cy=word['top']+word['height']/2
        if word['left']+word['width']<=left-2 and word['left']>=left-80 and top-35<=cy<=bottom+35:
            ticks.append((cy,value))
    ticks.sort();upper=lower=None
    if len(ticks)>=2 and ticks[0][1]>ticks[-1][1] and ticks[-1][0]>ticks[0][0]:
        # Require the intervening ticks to agree with the same vertical scale.
        yt,upper=ticks[0];yb,lower=ticks[-1]
        if all(abs(v-(upper-(y-yt)/(yb-yt)*(upper-lower)))<=max(1,(upper-lower)*.08) for y,v in ticks):top,bottom=round(yt),round(yb)
        else:upper=lower=None
    return {'rect':[left,top,right-left+1,bottom-top+1],'upper':upper,'lower':lower}


def trace_curve(image,rect,upper,lower,count):
    if not all(math.isfinite(float(v)) for v in (upper,lower)) or not upper>lower>=0:raise ValueError('请核对纵轴上下刻度，上刻度必须大于下刻度且均非负')
    if not 7<=count<=366:raise ValueError('趋势采样点数应为7～366；不是自动恢复的精确逐日数据')
    x,y,w,h=map(int,rect)
    if w<30 or h<15 or x<0 or y<0 or x+w>image.width() or y+h>image.height():raise ValueError('请框选完整的销量折线绘图区')
    columns=defaultdict(list)
    for px,py in blue_pixels(image,rect):columns[px].append(py)
    if len(columns)<w*.65:raise ValueError('没有找到覆盖足够宽度的蓝色折线，请调整绘图区，避免选择柱状图或整张截图')
    xs=sorted(columns);ys={px:median(values) for px,values in columns.items()};max_gap=max(5,w*.04);values=[]
    import bisect
    for i in range(count):
        px=x+i*(w-1)/(count-1);j=bisect.bisect_left(xs,px)
        a=xs[max(0,j-1)];b=xs[min(j,len(xs)-1)]
        if min(abs(px-a),abs(px-b))>max_gap or b-a>max_gap:raise ValueError('曲线存在较大缺口，不补造缺失数据；请重新框选或手工录入')
        py=ys[a] if a==b else ys[a]+(ys[b]-ys[a])*(px-a)/(b-a)
        value=lower+(y+h-1-py)/(h-1)*(upper-lower)
        values.append(round(max(lower,min(upper,value)),2))
    note=f'【曲线读图估算】仅用于趋势参考，不是精确逐日销量。等距采样{count}点；纵轴上界{upper}、下界{lower}；绘图区{x},{y},{w},{h}。需人工核对坐标和原图，不能用估算点求和代替90天总销量。'
    return {'values':values,'note':note}
