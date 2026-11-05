"""Conservative OCR field proposals. Every proposal remains subject to user confirmation."""
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal,InvalidOperation

LABELS={
    'data_snapshots':{
        'creators':('带货人数','带货达人总数','带货达人数量','带货达人数','带货达人','参与达人数'),
        'sellers':('出单人数','出单达人数','出单达人','成交达人数','成交达人','动销达人数','动销达人'),
        'sales':('90天总销量','近90天销量','90天销量','总销量','累计销量','销量'),
    },
    'advertising_records':{
        'spend':('广告消耗金额','广告消耗','消耗金额','投放消耗'),
        'impressions':('广告曝光量','曝光量','展示量'),
        'clicks':('点击量','点击次数'),
        'orders':('成交订单数','成交订单','成交单数'),
        # Generic GMV/成交金额 cannot establish the screenshot's upper-left actual GMV.
        'actual_gmv':('左上角实际成交GMV','左上角成交金额','实际成交GMV'),
        'backend_gmv':('后台广告GMV','广告GMV'),
        'backend_roi':('后台显示ROI','后台ROI'),
        'estimated_commission':('预估佣金',),'settled_commission':('最终结算佣金',),
    },
}
INTEGER_FIELDS={'creators','sellers','sales','impressions','clicks','orders'}
NUMBER=r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:万|亿|千|[wWkK])?'

def normalized(text):
    text=unicodedata.normalize('NFKC',text)
    text=re.sub(r'(?<=\d)\s+(?=\d)','\x00',text)
    return re.sub(r'\s+','',text).replace('\x00',' ').replace('gmv','GMV').replace('roi','ROI')

def numeric_value(text,field):
    text=normalized(text).strip(':：=¥￥')
    match=re.fullmatch('('+NUMBER+r')(?:人|件|单|次|元)?',text)
    if not match:return None
    value=match[1];unit=value[-1] if value[-1] in '万亿千wWkK' else ''
    if unit:value=value[:-1]
    try:
        value=Decimal(value.replace(',',''))*{'':1,'万':10000,'亿':100000000,'千':1000,'w':10000,'W':10000,'k':1000,'K':1000}[unit]
        if field in INTEGER_FIELDS:
            return int(value) if value==value.to_integral_value() else None
        return float(value)
    except (InvalidOperation,ValueError,OverflowError):return None

def _labels(text,table):
    # Longest labels win so '后台广告GMV' isn't also a generic GMV match.
    choices=sorted(((label,field) for field,labels in LABELS.get(table,{}).items() for label in labels),key=lambda p:-len(p[0]))
    occupied=[];found=[]
    for label,field in choices:
        for match in re.finditer(re.escape(label),text):
            if any(match.start()<end and match.end()>start for start,end in occupied):continue
            occupied.append(match.span());found.append((match.start(),match.end(),field,label))
    return sorted(found)

def text_proposals(text,table):
    lines=[normalized(line) for line in text.splitlines() if line.strip()];candidates=defaultdict(list)
    for i,line in enumerate(lines):
        labels=_labels(line,table)
        for j,(start,end,field,label) in enumerate(labels):
            right=labels[j+1][0] if j+1<len(labels) else len(line)
            values=[line[end:right].strip(':：=')]
            if len(labels)==1 and not values[0]:
                # Vertical text without coordinates is ambiguous if both neighbors are numbers.
                values=[lines[k] for k in (i-1,i+1) if 0<=k<len(lines)]
            for raw in values:
                value=numeric_value(raw,field)
                if value is not None:candidates[field].append({'value':value,'source':label+' '+raw})
    return {f:items[0] for f,items in candidates.items() if len({x['value'] for x in items})==1}

def _box(words,start,end):
    offset=0;parts=[];previous=''
    for word in words:
        token=normalized(word['text']);length=len(token)
        if previous and token and previous[-1].isdigit() and token[0].isdigit():offset+=1
        lo=max(start,offset);hi=min(end,offset+length)
        if hi>lo and length:
            left=word['left']+word['width']*(lo-offset)/length
            right=word['left']+word['width']*(hi-offset)/length
            parts.append((left,word['top'],right,word['top']+word['height']))
        offset+=length;previous=token
    return (min(p[0] for p in parts),min(p[1] for p in parts),max(p[2] for p in parts),max(p[3] for p in parts))

def geometry_proposals(words,table):
    lines=defaultdict(list)
    for word in words:
        if word.get('text','').strip() and word.get('conf',0)>=25:
            lines[tuple(word.get(k,0) for k in ('page_num','block_num','par_num','line_num'))].append(word)
    labels=[];numbers=[]
    for line_id,line_words in lines.items():
        line_words.sort(key=lambda w:w['left']);text=''
        for word in line_words:
            token=normalized(word['text'])
            if text and token and text[-1].isdigit() and token[0].isdigit():text+=' '
            text+=token
        found=_labels(text,table)
        labels += [(field,label,_box(line_words,start,end),line_id) for start,end,field,label in found]
        for match in re.finditer(NUMBER,text):
            if any(match.start()<end and match.end()>start for start,end,_,_ in found):continue
            before=text[max(0,match.start()-1):match.start()];after=text[match.end():match.end()+1]
            if before in ('-','~','>','<','±') or after in ('%','天','日','月','年','+','-','~','至'):continue
            numbers.append((match[0],_box(line_words,*match.span()),line_id))
    pairs=[]
    for i,(field,label,a,line_id) in enumerate(labels):
        ax=(a[0]+a[2])/2;aw=max(1,a[2]-a[0]);ah=max(1,a[3]-a[1])
        for j,(raw,b,other_line) in enumerate(numbers):
            value=numeric_value(raw,field)
            if value is None:continue
            bx=(b[0]+b[2])/2;bw=max(1,b[2]-b[0]);bh=max(1,b[3]-b[1]);height=max(ah,bh)
            vertical=max(0,a[1]-b[3],b[1]-a[3]);horizontal=max(0,a[0]-b[2],b[0]-a[2])
            if line_id==other_line and horizontal<=height*8:
                score=horizontal/height
            elif abs(ax-bx)<=max(aw,bw)*.6 and vertical<=height*3:
                score=1+vertical/height+abs(ax-bx)/max(aw,bw)
            else:continue
            pairs.append((score,i,j,value))
    # A number is only offered to its nearest label; ties and multiple conflicting
    # appearances of a field are left for manual entry rather than guessed.
    by_number=defaultdict(list)
    for pair in pairs:by_number[pair[2]].append(pair)
    candidates=defaultdict(list)
    for j,items in by_number.items():
        items.sort();best=items[0]
        if len(items)>1 and abs(items[1][0]-best[0])<.15:continue
        score,i,_,value=best;field,label,_,_=labels[i]
        candidates[field].append((score,{'value':value,'source':label+' '+numbers[j][0]}))
    out={}
    for field,items in candidates.items():
        items.sort(key=lambda x:x[0]);best=items[0]
        if any(other['value']!=best[1]['value'] and score<best[0]+.5 for score,other in items[1:]):continue
        out[field]=best[1]
    return out

def propose_fields(document,table):
    if isinstance(document,str):document={'text':document}
    direct=text_proposals(document.get('text',''),table)
    geometric=geometry_proposals(document.get('words',[]),table)
    # Never resolve conflicting evidence by silently preferring one parsing method.
    for key,value in geometric.items():
        if key in direct and direct[key]['value']!=value['value']:direct.pop(key)
        else:direct[key]=value
    return direct
