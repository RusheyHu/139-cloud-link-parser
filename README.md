# 中国移动云盘直链解析器（Windows）

## 功能
- 识别中国移动云盘 PC 分享链接及分享 ID
- 可填写提取码
- 使用本机 Edge/Chrome 打开中国移动云盘网页，用户自行扫码登录
- 从本机浏览器上下文读取登录 Cookie 并保存在 `%USERPROFILE%\.139_link_parser\cookies.json`
- 调用分享信息及下载地址接口，显示并复制 CDN 直链
- 不执行文件下载，不上传 Cookie

## 构建 EXE
1. 在 Windows 10/11 安装 Python 3.10 或更高版本，并确保 `py` 命令可用。
2. 安装 Microsoft Edge 或 Google Chrome。
3. 双击 `build_windows.bat`。
4. 构建完成后运行 `dist\139CloudLinkParser\139CloudLinkParser.exe`。

当前使用 PyInstaller onedir 方式，整个 `dist\139CloudLinkParser` 文件夹需要一起分发，不能只拿 exe 单文件。

## 使用
1. 启动程序，点击“扫码登录”。
2. 在弹出的 Edge/Chrome 中打开的移动云盘页面使用移动云盘 App 扫码。
3. 登录成功后关闭浏览器窗口（程序会自动检测并保存 Cookie）。
4. 粘贴分享链接，填写提取码（如有），点击“解析下载直链”。
5. 成功后点击“复制下载地址”。

## 重要说明
- 中国移动云盘网页接口属于非公开接口，平台可能随时调整参数、签名或鉴权方式。当前实现依据公开技术复盘资料整理，尚未在用户提供的分享链接上完成端到端验证。
- 登录态仅保存在本机用户目录。请勿公开或发送 `cookies.json`，其等同于账号临时凭证。
- 直链一般有时效性，公开技术资料记载约 900 秒；请尽快使用。
- 目前第一版只对分享根目录中恰好一个文件的情况自动提取直链。多文件分享会列出文件并提示，不会擅自选择。子目录递归、文件选择将在后续版本补齐。
- 若接口返回鉴权失败、提取码错误、分享失效或接口结构变化，程序会显示错误，不伪造下载地址。
- 请仅解析你有权访问的分享内容，并遵守平台条款及分享者授权。

## 在 GitHub 的 Windows 环境自动打包（无需本机安装 Python）
1. 将压缩包内的 `139_cloud_link_parser` 文件夹和 `.github` 文件夹一起上传到你自己的 GitHub 仓库根目录。
2. 打开仓库的 **Actions** 页面。
3. 选择 **Build Windows EXE** 工作流，点击 **Run workflow**。
4. 等待 Windows Runner 构建完成。
5. 在本次运行页面底部的 **Artifacts** 下载 `139CloudLinkParser-Windows-x64`。
6. 解压后运行 `139CloudLinkParser/139CloudLinkParser.exe`。请保留同目录下的所有文件，不要只复制 EXE。

说明：此工作流会在 GitHub 提供的 `windows-latest` 环境中实际构建 Windows x64 程序。当前对话环境无法直接启动 Windows Runner，因此这里提供的是可执行的 Windows 自动构建配置，不会把未构建的文件冒充为 EXE。
