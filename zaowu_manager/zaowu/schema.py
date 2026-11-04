"""Shared, validated field definitions used by SQLite, forms and interchange.

Money is stored as integer fen; files and forms use yuan. No demo records.
"""
from dataclasses import dataclass

BUSINESSES = ('DIY散客', '花束业务', '活动沙龙')
FLOWERS = ('待沟通', '待报价', '待确认', '已付款', '制作中', '已完成', '已取消')
SALON = ('潜在客户', '初步沟通', '需求确认', '报价', '商务确认', '成交', '活动执行', '完成结算', '已取消')
REALIZED = ('已付款', '制作中', '已完成', '成交', '活动执行', '完成结算')

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = 'text'
    options: tuple = ()
    required: bool = False

def f(key, label, kind='text', options=(), required=False):
    return Field(key, label, kind, options, required)

B = f('business', '业务', 'choice', BUSINESSES, True)
D = f('date', '日期', 'date', required=True)
SCHEMAS = {
 'products': ('产品档案', [B, f('name','项目 / 产品名称',required=True), f('price','单价','money'), f('material','单件材料成本','money'), f('active','上架','bool'), f('features','款式 / 特色','long')]),
 'customers': ('客户档案', [f('code','匿名客户编号',required=True), B, f('category','客户类型','choice',('新客户','老客户','高复购客户','转介绍客户','企业客户')), f('source','首次获客来源'), f('preferences','兴趣偏好','long'), f('consent','同意接收推广','bool'), f('notes','本地沟通备注（不发送 AI）','long')]),
 'orders': ('订单管理', [D, B, f('product_id','产品','product'), f('customer_id','客户','customer'), f('quantity','件数 / 组数','int'), f('people','顾客 / 参与人数','int'), f('customer_kind','客群','choice',('新客','复购','转介绍')), f('source','首次获客来源'), f('channel','最终下单渠道'), f('status','订单 / 销售阶段','choice',tuple(dict.fromkeys(FLOWERS + SALON))), f('expected','报价 / 预计收入','money'), f('revenue','实际收入（整单）','money'), f('material','材料成本（整单）','money'), f('labor','直接人工成本','money'), f('other','交通及其他直接成本','money'), f('delivery','交付 / 活动日期','optional_date'), f('fulfillment','交付方式','choice',('自提','配送','到店体验','到场活动')), f('festival','节日标签'), f('location','活动地点'), f('activity','活动类型 / 项目'), f('notes','跟进 / 后续合作机会','long')]),
 'inventory': ('鲜花采购与库存流水', [D, f('item','鲜花 / 材料名称',required=True), f('movement','流水类型','choice',('采购入库','制作领用','损耗','盘盈')), f('quantity','数量','int'), f('unit','单位'), f('amount','采购 / 损耗金额','money'), f('notes','说明','long')]),
 'expenses': ('固定费用', [D, f('category','费用类型','choice',('房租','固定工资','水电','折旧','其他固定费用')), f('amount','金额','money'), f('notes','说明','long')]),
 'goals': ('经营目标', [D, B, f('title','目标名称',required=True), f('metric','衡量指标'), f('target','目标值','number'), f('actual','实际值','number'), f('deadline','截止日期','date',required=True), f('notes','目标说明','long')]),
 'campaigns': ('营销实验', [D, B, f('title','实验名称',required=True), f('platform','平台'), f('hypothesis','问题诊断 / 假设','long'), f('audience','目标人群'), f('budget','预算','money'), f('spent','实际花费','money'), f('criterion','成功指标（必填）',required=True), f('exposures','曝光','int'), f('visits','访问','int'), f('inquiries','有效咨询','int'), f('conversions','获客订单','int'), f('result','结果 / 调整结论','long'), f('status','执行状态','choice',('计划中','执行中','已完成','已停止'))]),
 'tasks': ('任务管理', [D, B, f('title','任务名称',required=True), f('deadline','截止日期','date',required=True), f('status','任务状态','choice',('待确认','待执行','进行中','已完成','已取消')), f('result','执行结果 / 效果','long')]),
 'contents': ('内容与发布日历', [f('date','计划发布日期','date',required=True), B, f('platform','平台','choice',('小红书','抖音','微信朋友圈','其他')), f('title','选题 / 标题',required=True), f('format','内容类型','choice',('种草文案','视频脚本','拍摄分镜','封面文字','图片排序','账号规划')), f('body','文案 / 脚本','long'), f('status','发布状态','choice',('未发布','已发布')), f('url','公开内容链接'), f('views','曝光','int'), f('inquiries','有效咨询','int'), f('orders','获客订单','int')]),
 'assets': ('照片素材库', [D, B, f('title','素材名称',required=True), f('path','本地文件（由导入照片功能管理）',required=True), f('description','照片描述 / 创作提示（AI 使用文字描述）','long')]),
 'competitors': ('竞争对手资料', [D, f('name','门店名称',required=True), f('product','产品类型'), f('price','观察售价','money'), f('features','特色 / 差异','long'), f('marketing','营销 / 促销 / 平台表现','long'), f('url','公开来源链接'), f('learnings','市场变化 / 可测试机会','long')]),
 'reviews': ('经营复盘', [D, f('period','周期','choice',('每日','每周','每月')), f('title','复盘标题',required=True), f('facts','经营事实 / 营销动作','long'), f('findings','问题 / 有效与无效方法','long'), f('actions','下期重点 / 追踪结论','long')]),
 'memories': ('经营背景与长期记忆', [D, f('category','分类','choice',('门店背景','主推项目','重要决策','有效方法','失败方案','历史结论')), f('title','标题',required=True), f('body','内容（仅在勾选授权后发送 AI）','long'), f('share_ai','允许发送给 DeepSeek（勿含个人信息）','bool')]),
 'followups': ('客户跟进记录', [D, f('customer_id','客户','customer'), f('stage','跟进阶段'), f('body','沟通记录（仅本地）','long'), f('next_date','下次跟进日期','optional_date')]),
}
