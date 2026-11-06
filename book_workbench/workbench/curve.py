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
            if b>=105 and b-r>=18 and b-g>=5 and (b-r)/max(1,b)>=.075 and g>=45:
                points.add((col,row))
                if len(points)>500000:raise ValueError('蓝色区域过大，请只框选销量折线绘图区')
    return points


def locate_curve(image,words=()):
    points=blue_pixels(image);components=[]
    while points:
        first=points.pop();q=deque([first]);component=[first]
        while q:
            x,y=q.popleft()
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
                point=(x+dx,y+dy)
                if point in points:points.remove(point);q.append(point);component.append(point)
        if len(component)>=3:components.append(component)
    def bounds(c):
        xs=[p[0] for p in c];ys=[p[1] for p in c];return min(xs),min(ys),max(xs),max(ys)
    # JPEG/antialiasing can break a thin curve into adjacent components.
    gap=max(3,round(image.width()*.018));merged=[]
    for component in sorted(components,key=len,reverse=True):
        box=bounds(component);match=None
        for index,(_,other) in enumerate(merged):
            if box[0]<=other[2]+gap and box[2]>=other[0]-gap and box[1]<=other[3]+gap and box[3]>=other[1]-gap:match=index;break
        if match is None:merged.append((component,box))
        else:
            old,other=merged[match];old.extend(component);merged[match]=(old,bounds(old))
    candidates=[]
    for component,(left,top,right,bottom) in merged:
        width=right-left+1;height=bottom-top+1
        if width<image.width()*.35 or width<height*1.3:continue
        if len({p[0] for p in component})/width<.65:continue
        density=len(component)/(width*max(1,height))
        if height>5 and density>.3:continue
        candidates.append((width*(1-min(.25,density)),left,top,right,bottom))
    if not candidates:return None
    _,left,top,right,bottom=max(candidates)
    ticks=[];margin=max(40,image.width()*.22)
    for word in words:
        raw=str(word.get('text','')).replace(',','').strip()
        if not __import__('re').fullmatch(r'\d+(?:\.\d+)?',raw):continue
        value=float(raw);cy=word['top']+word['height']/2
        if word['left']+word['width']<=left+3 and word['left']>=left-100 and top-margin<=cy<=bottom+margin:ticks.append((cy,value))
    ticks=sorted(set(ticks));best=None
    for i,(yt,upper) in enumerate(ticks):
        for yb,lower in ticks[i+1:]:
            if upper<=lower or yb-yt<max(20,(bottom-top)*.6):continue
            inliers=[(y,v) for y,v in ticks if yt-2<=y<=yb+2 and abs(v-(upper-(y-yt)/(yb-yt)*(upper-lower)))<=max(.6,(upper-lower)*.04)]
            if len(inliers)>=3 and (best is None or (len(inliers),yb-yt)>best[0]):best=((len(inliers),yb-yt),yt,yb,upper,lower)
    upper=lower=None
    if best:_,top,bottom,upper,lower=best;top=round(top);bottom=round(bottom)
    else:
        padding=max(4,round((bottom-top)*.06));top=max(0,top-padding);bottom=min(image.height()-1,bottom+padding)
    return {'rect':[left,top,right-left+1,max(15,bottom-top+1)],'upper':upper,'lower':lower}


def trace_curve(image,rect,upper,lower,count):
    if not all(math.isfinite(float(v)) for v in (upper,lower)) or not upper>lower>=0:raise ValueError('请核对纵轴上下刻度，上刻度必须大于下刻度且均非负')
    if not 7<=count<=366:raise ValueError('趋势采样点数应为7～366；不是自动恢复的精确逐日数据')
    x,y,w,h=map(int,rect)
    if w<30 or h<15 or x<0 or y<0 or x+w>image.width() or y+h>image.height():raise ValueError('请框选完整的销量折线绘图区')
    columns=defaultdict(list)
    for px,py in blue_pixels(image,rect):columns[px].append(py)
    if sum(map(len,columns.values()))>w*h*.32:raise ValueError('选区包含大块蓝色背景或柱形，请只框选折线绘图区，或改用手动描绘')
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


def trace_manual(image,rect,points,upper,lower,count):
    if not math.isfinite(upper) or not math.isfinite(lower) or not upper>lower>=0:raise ValueError('请先填写并核对纵轴上下刻度')
    if not 7<=count<=366:raise ValueError('趋势采样点数应为7～366')
    x,y,w,h=rect
    if w<30 or h<15 or x<0 or y<0 or x+w>image.width() or y+h>image.height():raise ValueError('请先框选完整的绘图区')
    columns=defaultdict(list)
    for px,py in points:
        if x<=px<x+w and y<=py<y+h:columns[int(px)].append(py)
    xs=sorted(columns)
    if len(xs)<2 or xs[-1]-xs[0]<w*.65:raise ValueError('请沿原图折线从左向右描绘，覆盖至少三分之二宽度')
    import bisect
    values=[]
    for i in range(count):
        px=x+i*(w-1)/(count-1);j=bisect.bisect_left(xs,px);a=xs[max(0,j-1)];b=xs[min(j,len(xs)-1)]
        py=median(columns[a]) if a==b else median(columns[a])+(median(columns[b])-median(columns[a]))*(px-a)/(b-a)
        values.append(round(max(lower,min(upper,lower+(y+h-1-py)/(h-1)*(upper-lower))),2))
    return {'values':values,'note':f'【曲线读图估算】手动描绘原图后按坐标估算{count}个趋势点，不是精确逐日销量；不能用估算点求和代替90天总销量。'}
