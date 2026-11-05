"""Declarative editor schema. Monetary amounts are decimal yuan, unknowns are NULL."""
STATUSES=['待分析','值得测试','测试中','持续投入','暂缓投入','已放弃']
BOOK_TAGS=['','大爆单','小爆单','稳定出单','普通出单','无效测试','未获得广告消耗','失败商品']
VIDEO_TAGS=['','表现优秀','表现一般','未产生消耗','有消耗无成交','已暂停','继续观察']
# key, label, type, required (choices encoded as lists)
SCHEMA={
'books':('图书档案',[
('name','图书名称','text',True),('author','作者','text',False),('publisher','出版社','text',False),('category','分类','text',False),('cover','封面','image',False),('notes','备注','long',False)]),
'product_links':('商品链接',[
('book_id','所属图书','books',True),('url','商品链接','text',True),('price','售价（元）','number',False),('commission','预估单笔佣金（元）','number',False),('commission_rate','佣金比例（%）','percent',False),('status','状态',STATUSES,True),('history_tag','历史分类',BOOK_TAGS,False),('notes','备注','long',False)]),
'data_snapshots':('90天数据快照',[
('product_id','商品链接','product_links',True),('collected','采集日期','date',True),('period_days','统计周期（天）','integer',True),('creators','带货人数','integer',False),('sellers','出单人数','integer',False),('sales','总销量','integer',False),('curve','销量曲线（每日销量，逗号分隔）','curve',False),('screenshot','原始截图','image',False),('ocr_text','原始识别结果（待人工核对）','long',False),('confirmed','人工核对确认','bool',True),('notes','备注／曲线日期与单位','long',False)]),
'video_tests':('视频管理',[
('product_id','所属商品链接','product_links',True),('account','账号','text',True),('code','视频编号','text',True),('name','视频名称','text',True),('url','视频链接','text',False),('opening','开头类型','text',False),('direction','内容方向','text',False),('format','拍摄形式','text',False),('published','发布日期','date',True),('submitted','广告提交日期','date',False),('ad_started','广告实际开始日期','date',False),('review_override','手动复盘日期','date',False),('status','当前状态',['待提交','已提交','投放中','已暂停','已结束'],True),('history_tag','历史分类',VIDEO_TAGS,False),('media','素材／封面','file',False),('notes','备注','long',False)]),
'advertising_records':('广告数据（累计快照，禁止重复相加）',[
('video_id','所属视频','video_tests',True),('collected','数据采集日期','date',True),('period','统计范围／投放环境','text',False),('spend','广告消耗（元）','number',False),('impressions','曝光量','integer',False),('clicks','点击量','integer',False),('orders','成交订单','integer',False),('actual_gmv','截图左上角实际成交GMV','number',False),('backend_gmv','后台广告GMV（独立）','number',False),('backend_roi','后台ROI（独立）','number',False),('estimated_commission','预估佣金','number',False),('settled_commission','最终结算佣金','number',False),('screenshot','原始截图','image',False),('ocr_text','原始识别结果（待核对）','long',False),('confirmed','人工核对确认','bool',False),('other_metrics','其他可见指标／备注','long',False)])}
