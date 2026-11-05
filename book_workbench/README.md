# 图书带货智能选品工作台 V1.1

独立的 Python / PySide6 / SQLite 桌面应用。与仓库内的造物系统不共享数据库、设置或凭据。本地基础功能离线可用，无演示订单或预填经营数字。

## Windows用户：直接运行

**[下载Windows安装版与便携版](https://github.com/jackychan2021620-design/text/actions/runs/41995501042/artifacts/13400790050)**（外层ZIP约235MB，需要登录GitHub）。

Windows构建由 [Book Workbench Windows App](https://github.com/jackychan2021620-design/text/actions/workflows/book-workbench-windows.yml) 工作流生成。选择成功的构建，在 Artifacts 下载 `BookWorkbench-Windows-x64`（需要登录GitHub）。只有构建成功并上传了附件，才能视为已有Windows程序包。

下载解压后有两种选择：

- **安装版**：双击 `BookWorkbench-Setup-1.1.0-Windows-x64.exe`，按提示安装，默认创建桌面快捷方式。
- **便携版**：完整解压 `BookWorkbench-1.1.0-Windows-x64-portable.zip`，再双击其中的 `BookWorkbench.exe`。不能只复制EXE，也不要在压缩包内直接运行。

发行包内置 Python、Qt、Tesseract 与中文／英文识别模型，**用户不需要安装Python或OCR**。基础功能离线可用，只有AI功能需要自己的DeepSeek Key。

当前为未签名试用包；请核对仓库来源及包内 `SHA256SUMS.txt`。程序数据与安装文件分开保存，升级安装保留经营资料。

## 源码开发：安装与启动

推荐 Windows 10/11 x64、Python 3.12。源码兼容 Python 3.11+；当前验证使用 Python 3.12。

1. 安装 Python 3.12（包含 Python Launcher）。
2. 安装 Tesseract 5，包含英文模型。Windows 安装来源见 [Tesseract官方安装说明](https://tesseract-ocr.github.io/tessdoc/Installation.html)；默认检测 PATH 或 `C:\Program Files\Tesseract-OCR\tesseract.exe`，也可以设置 `BOOK_WORKBENCH_TESSERACT` 指向程序。
3. 本目录运行 `powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1`。脚本安装依赖、从官方仓库获取并校验中文和英文 OCR 模型、运行测试。缺少引擎会导致实际 OCR 测试失败，请补齐后重跑。
4. 双击 `start-windows.bat`。开发时也可运行 `.venv\Scripts\python.exe launch.py` 查看诊断输出。

Linux 开发：

```sh
cd book_workbench
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
# 系统需另装 tesseract-ocr 及中文字体（如 Noto Sans CJK）
.venv/bin/python scripts/setup_ocr.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python launch.py
```

当前云环境可用解释器是 `/workspace/text/zaowu_studio/.venv/bin/python`，已包含本应用相同的固定版本依赖。不需要修改原应用文件。`--smoke-test` 会自动结束，可配合 `BOOK_WORKBENCH_DATA_DIR` 指向临时目录进行隔离验证。无显示器时设置 `QT_QPA_PLATFORM=offscreen`；真实窗口启动应移除该变量。

## 使用顺序与七个模块

1. **图书数据库**：先新增图书，再点击“管理商品链接”。同书可保存多个链接。支持编辑、搜索、分类过滤和修改历史；下游记录存在时阻止删除，以保留证据。档案保存封面及本地附件。
2. **数据采集中心**：新增90天数据快照，选择商品链接，填写采集日期、统计天数、带货人数、出单人数、总销量、每日销量曲线。曲线用逗号分隔每日销量，备注写清起止日期与单位。截图“选择附件 → 识别 → 核对数值 → 勾选确认 → 保存”。OCR展示原文，不自动替用户确认金额或从图像猜测曲线数据。未知字段留空，明确零才录0。原图、原识别文字与确认数据共同保留。
3. **选品分析引擎**：查看三个计算指标、趋势分类、解释与曲线图。同类别至少5个有效90天商品才显示销量百分位和历史覆盖比较。启发式阈值见 `workbench/analysis.py`，它们不是统计模型，也不是个人爆单概率。
4. **多商品对比**：选择2～10个商品，按稳定出单、爆单容量或进入机会代理指标排序；比较窗展示明细、理由和限制。跨类别或不同时间口径的排名不能直接用于确定性决策。
5. **AI选品顾问**：右侧选择任务、全部历史或单本书范围，输入问题，核对完整发送文字后确认。上下文包括快照、计算结果、视频、广告和复盘历史，图片像素不发送。历史很大时选择单本书，超过大小上限明确拒绝，不静默截断。回复只作为建议保存在历史，不修改状态或自动投放。
6. **视频投放与复盘**：为每条视频填写账号、所属链接、编号、内容特征、发布日期、广告提交日期和实际开始日期。广告记录通过“广告数据”进入，可多次追加累计快照。预览五日复盘，补充人工备注后确认，形成不可覆盖的报告历史。允许提前复盘、手动改日期、延后2或3天、重复复盘；同书视频比较提供消耗、订单、GMV和独立ROI等横向数据及极值摘要。
7. **历史复盘**：保留商品分析、视频复盘、延后事件、AI回复、档案修改历史。商品和视频历史标签由经营者核定；分组统计按品类、账号、开头、方向、形式、历史标签和统计范围展示。可结合AI提出待验证规则，不能据此断言因果。

表单编辑每隔500ms保存草稿；重新进入相同表单可继续。点击“保存”才提交正式记录（校验及写入在事务中）。取消保留草稿，防止误关丢失；清空草稿字段再保存可替换。快照只能新增，发现错误以新快照及备注纠正，不改写原证据。

## 两种独立提醒

- 商品链接：按**最新采集日期**加15天。补录旧快照不会把提醒倒退。同书不同链接独立。
- 视频：优先实际广告开始日，否则发布日期，加5天；允许手动覆盖。广告提交日仅保存，不作为默认起点。同书各条视频拥有独立任务。
- 首页分别展示今日、未来3天即将到期、逾期；最近完成更新和复盘另有入口。视频页显示所有当前日期、原日期、完成状态及剩余天数。
- 软件启动和每分钟检查提醒，每天同任务同到期日通知一次；不能显示系统通知时不记为已发送，首页仍保留待办。开启“关闭后留在托盘”并允许Windows通知，可在后台提醒；托盘菜单“退出”彻底关闭。设置支持Windows登录启动（当前用户注册表Run项）。
- **完全退出或电脑关机时不会执行提醒**；下次启动从持久化待办中恢复。不是Windows后台服务。

## 计算口径

- 达人出单率 = 出单人数 / 带货人数；两个达人人均销量分别用出单人数和带货人数作分母。分母无效或数据缺失返回未知，不返回0。
- 两次滚动90天快照的差值只是窗口指标变化，不是两次采集之间真实销量。
- 广告记录按采集日期、ID取最新累计快照，绝不相加；录入备注说明统计范围与投放环境。
- `actual_gmv`：人工核对的广告截图左上角实际成交金额；`backend_gmv`：后台广告GMV；`backend_roi`：后台ROI，三个字段各自保存。
- 实际GMV/广告消耗独立计算；未知或零消耗时显示“无有效消耗数据”，不是ROI=0。GMV比率不是佣金收益率或利润率。
- 默认复盘经营门槛：消耗100元、订单5单、目标GMV/消耗1，均在设置中可改。它们仅用于形成可解释的五类建议，不代表盈利标准、显著性或保证。
- 本条视频建议与同书新素材建议分开。参考同书其他视频、同账号同类记录、商品趋势与样本量；不凭单条视频否定整本书。

## DeepSeek设置

设置页输入官方 HTTPS 地址（支持 `/v1`），输入自己的 Key，点击“获取模型”后选择并保存。仅支持 `api.deepseek.com`，模型由接口获取，不写死模型名。

Windows默认使用系统凭据库条目 `BookWorkbench.DeepSeek`。不能安全持久保存时可取消勾选，只保留本次运行；也支持进程变量 `BOOK_WORKBENCH_API_KEY`。Key不写进SQLite、备份或源码。删除持久凭据请用Windows凭据管理器。网络需允许 `api.deepseek.com`，云环境可在环境设置中安全配置访问。不要在聊天或Git中提交Key。

每次生成前预览完整请求。事实、计算、推测、不确定因素、下一步建议由系统提示词约束，但仍需经营者核查模型输出。调用失败、退出中断均单独记录，不当作成功。当前仅验证模拟API协议，未验证真实账户、计费与生成质量。

## 数据、安全与迁移

Windows默认 `%LOCALAPPDATA%\BookWorkbench\`；Linux默认 `~/.local/share/BookWorkbench/`。数据库 `books.sqlite3`，附件 `assets/` 按内容哈希存储。可通过 `BOOK_WORKBENCH_DATA_DIR` 指定隔离数据目录。同一数据目录用锁防止重复启动。

SQLite使用外键、WAL、完整同步及事务。首次启动自动在原子迁移中建立版本1；`python scripts/database.py [数据目录]` 可显式初始化／执行迁移入口。高于支持版本的数据库拒绝打开，不降级覆盖。后续schema升级需要追加迁移，不能把新数据库覆盖旧库。

每天自动备份含数据库和附件的ZIP，保留最近30个每日备份；每分钟维护检查，重启不丢待办。“设置与备份”可手动导出完整资料包。恢复校验清单、SHA256、路径、大小、SQLite完整性、字段和引用附件，先备份当前数据，再替换数据库。恢复保留已有附件，避免误删其他资料；新数据库引用包内附件。备份不含凭据、未加密，应妥善保存。

## Windows EXE

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

脚本先设置和测试，再用PyInstaller生成 `dist\BookWorkbench\BookWorkbench.exe`，最后运行打包程序隔离启动检查。需要分发**整个目录**。产物内置Tesseract及中英文模型，用户无需另装运行环境。构建会运行Windows测试、原生窗口启动、内置OCR识别、安装与安装后再次启动检查。自动检查不替代真人的通知、托盘、开机启动及真实DeepSeek联调；结果见 [验收与测试记录](docs/VALIDATION.md)。
