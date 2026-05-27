# Codex Quota Widget

一个适用于 Windows 的轻量桌面小组件，用于显示 Codex 的 `5小时` 与 `1周` 剩余用量、重置时间和进度条。窗口默认保持低对比度、无标题栏并隐藏任务栏图标，适合常驻桌面。

## 功能

- 自动读取本机 Codex 登录状态并刷新剩余用量
- 两行紧凑显示：`5小时` / `1周`
- 置顶、锁定、手动刷新、拖动与缩放
- 颜色、字体、透明度和刷新频率设置
- Codex 关闭时自动隐藏或退出
- 可选开机启动脚本
- 实时请求不可用时支持 `quota_status.json` 本地数据兜底

## 下载使用

1. 在仓库的 [Releases](https://github.com/thebsf/codex-quota-widget/releases) 页面下载 `CodexQuotaWidget.exe`。
2. 确保 Codex 桌面应用已登录并运行。
3. 双击 exe。小组件会随 Codex 的运行状态自动显示或隐藏。
4. 右键小组件进入设置；顶部按钮可锁定、置顶、刷新和关闭。

Windows 可能对未签名的个人发布程序显示 SmartScreen 提示。本项目不包含代码签名证书。

## 实时数据说明

程序读取当前用户目录中的 `%USERPROFILE%\.codex\auth.json`，仅在本机内存中使用登录令牌向 Codex/ChatGPT 用量接口发起请求；令牌不会写入仓库，也不会包含在 Release 文件中。

此路径已在 **2026-05-27** 的当前 Codex 登录环境中验证可返回 `5小时` 与 `1周` 数据。由于接口与认证机制可能随客户端或服务端更新而变化，后续如果实时读取不可用，可在 exe 同目录放置 `quota_status.json` 作为兜底数据来源。

不要共享 `.codex\auth.json`、`settings.json` 或任何包含登录信息的文件。

## 本地数据兜底

复制 [`quota_status.example.json`](./quota_status.example.json) 为 exe 同目录下的 `quota_status.json`，按需修改：

```json
{
  "updated_at": "2026-05-27 18:00:00",
  "source": "manual-example",
  "items": [
    { "name": "5小时", "remaining_percent": 73, "reset": "20:10" },
    { "name": "1周", "remaining_percent": 96, "reset": "5月31日" }
  ]
}
```

没有获取到实时数据且没有本地兜底文件时，小组件显示 `-- / 未获取`，不会显示示例额度。

## 从源码运行

环境要求：Windows 10/11 与 Python 3.10+。

```powershell
python .\codex_quota_popup.py
```

程序只使用 Python 标准库，运行源码不需要安装额外依赖。

## 构建 EXE

```powershell
.\build-windows.ps1
```

脚本会在缺少 PyInstaller 时安装它，并输出：

```text
dist\Codex剩余额度弹窗.exe
```

## 开机启动

先完成 EXE 构建，再运行：

```powershell
.\install-startup.ps1
```

移除开机启动：

```powershell
.\uninstall-startup.ps1
```

## 隐私与发布范围

- 仓库包含小组件源码、构建/启动脚本和示例配置。
- `dist\`、`build\`、`settings.json`、`quota_status.json` 与调研用拆包目录均被 `.gitignore` 排除。
- Release 仅附带可执行程序，不附带本机设置或登录文件。
