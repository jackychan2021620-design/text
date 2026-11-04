# 当前验证记录

验证日期：2026-11-04。平台：Linux，Python 3.12.14，PySide6 6.10.1，Qt offscreen。

- `python -m pytest -q`：**25 passed**。覆盖范围见 ACCEPTANCE.md 与 tests/。
- `python -m compileall -q zaowu launch.py`：通过。
- `python -m pip check`：通过，无依赖冲突。
- 完整安装脚本已重复执行：已有依赖复用，安装与测试通过。
- 程序入口自动启动 / 退出两次、数据重开保留、自动备份及报告生成：通过自动集成测试。
- 全部导航模块及 1000×640、1500×940、1920×1080 尺寸：通过 Qt 测试。
- 实际订单表单保存后收入与贡献毛利一致，长 Markdown 与固定输入框、会话切换：通过。
- 空库截图人工检查：灰白导航、三栏布局、无虚构经营数据、可操作业务列表正常。
- `docs/schema.sql`：在独立内存 SQLite 数据库重建全部 19 张预期表，版本和完整性检查通过。

尚未通过的外部验证：

1. **Windows EXE 尚未构建或执行。** 已提供 Windows PowerShell / PyInstaller 脚本及 GitHub Actions 工作流；未推送或触发远程构建。Windows 凭据库、开机启动、托盘、桌面快捷方式和无 Python 机器运行需要实机验收。
2. **真实 DeepSeek 尚未联调。** 当前没有配置应用所需的 Key；官方文档站请求返回 HTTP 403，最新文档未核验。已验证的是模拟协议和异常处理，不能当作真实网络服务测试。
3. 已保存云环境 `install_script`、`start_skill` 及 `api.deepseek.com` / `api-docs.deepseek.com` 域名草稿。保存不代表当前运行环境生效或已经发布；需在环境设置审核保存后发布，再重试联网。
4. **照片 AI 视觉识别未实现。** 可导入、预览本地照片，AI 仅使用手工描述。自动 AI 周报未在后台请求；当前自动周 / 月报告为本地统计快照，联网分析必须确认数据发送。

本记录不等同于 Windows 发行版验收通过，也不表示全部原始需求已最终完成。
