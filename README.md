# 图书带货智能选品工作台

新增独立应用位于 [book_workbench](book_workbench/README.md)，包含图书与商品快照、选品分析、视频投放及双提醒系统。当前为 Linux 已测试源码，Windows 打包与实机验收状态见应用文档。

---

# 造物手作 AI 经营管理系统

新的 **[AI 获客与内容运营工作台](zaowu_studio/README.md)** 位于 `zaowu_studio`，采用四入口与逐条内容工作流。Windows 安装包在构建成功后发布到 [Releases](https://github.com/jackychan2021620-design/text/releases)。

新工作台使用独立数据库，旧版经营系统源码与数据保留。

独立 Windows 桌面经营工作台源代码位于 [zaowu_manager](zaowu_manager/README.md)。

包含三项业务管理、经营分析、营销与复盘、SQLite 持久化、DeepSeek 流式助手，以及 Windows 启动和打包脚本。

目前已验证 Linux 下的业务逻辑与 Qt 桌面流程；Windows EXE 构建和真实 DeepSeek 账户联调仍待执行，详见项目文档。
