# TradeScout · Windows 本机 Codex 外贸智能体

通过本机 Codex CLI 搜索海外采购商、背调官网、按公开证据评分、保存客户和生成英文邮件草稿。默认无需填写 OpenAI API Key；复用运行本应用的电脑上 Codex CLI 的登录状态。模型仍通过网络运行，受该账户的权限和使用额度限制。

## Windows 首次使用

1. 安装 Python 3.10 或更新版本，安装时启用 Python Launcher（`py`）和 PATH。建议 Python 3.12。
2. 安装 Node.js LTS。打开新的 PowerShell，执行：

   ```powershell
   npm install -g @openai/codex
   codex login
   ```

   按 Codex 提示登录你的账户。若 PowerShell 阻止脚本，可执行 `npm.cmd`、`codex.cmd`，或改用命令提示符。
3. 将本项目完整解压到普通文件夹，例如 `C:\TradeScout`，双击 **start.bat**。首次启动自动安装 Python 依赖，需要网络；保留终端窗口。
4. 在打开的网页侧栏点击 **检测 Codex 安装与登录**，再点 **测试 AI 实际连接**。若浏览器未自动打开，在浏览器地址栏输入 `http://127.0.0.1:8501`。
5. 按“智能寻找买家 → 网站背调与评分 → 客户库与开发信”使用。先搜索 1–3 家测试。

关闭终端会停止应用；下次双击 `start.bat`。客户数据保存在 `data/leads.sqlite3`，重新启动仍保留。备份时先关闭应用，再复制 `data` 文件夹。

只有 Codex 桌面应用或 VS Code 扩展时，仍需安装 CLI 并执行 `codex login`。网页调用的是同机 CLI，不连接桌面聊天窗口或 IDE 会话。无需从 Codex 中提取密钥。

## 功能

- 按国家、品类发现候选客户，保留公开来源。
- 公司背调和 100 分证据评分；缺乏来源的条目不加分。
- 本地 SQLite 客户库、联系状态、CSV 导出。
- 英文首封与两次跟进草稿，主题最多 6 词、正文最多 50 词；保存前再次验证。
- 可选 OpenAI API 模式；此模式需要单独的 API Key 和 API 额度。

研究结果和来源由模型生成，未经独立验证，使用前应打开原始来源核实。评分是证据匹配度，不是成交概率。程序只保存草稿，不发送邮件。

## 配置与故障处理

默认不需要 `.env`。可复制 `.env.example` 为 `.env`，设置 `CODEX_MODEL`（留空使用 CLI 默认）、`CODEX_TIMEOUT_SECONDS`（默认 240 秒）或 `CODEX_BIN`（Codex 可执行文件完整路径）。`.env` 和数据库不会被 Git 跟踪。

- **找不到 Codex**：安装后关闭旧终端并重启 `start.bat`，检查 `codex --version`。
- **未登录或调用失败**：在同一电脑终端运行 `codex login status`，然后运行 `codex`，确认账户、网络、额度与模型权限。
- **Windows 沙箱错误**：先更新 Codex CLI；仍不支持时，在 WSL 中安装 Python、Node.js 和 Codex，再使用 `bash start.sh`。应用始终使用只读沙箱，不自动绕过。
- **查询超时**：降低公司数量，或提高 `.env` 中的超时；避免重复提交同一查询。
- **模型无法联网搜索**：检查 Codex 账户及网络策略是否允许 web search。不能将无来源的模型回答视为已核实客户。
- **端口占用**：关闭已运行的应用，或手动以 `--server.port 8502` 启动。

Codex 每次请求在临时目录运行，提示通过标准输入传递，启用只读沙箱并关闭 shell 工具；不把整个客户数据库作为上下文。研究条件和选中客户资料会发送到所选模型服务。请只在可信的个人电脑使用，应用默认仅监听本机。

## 开发与验证

```bash
python -m venv .venv
# Windows: .venv\Scripts\python.exe；macOS/Linux: .venv/bin/python
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

上面的 `python` 应为已激活虚拟环境中的解释器。macOS/Linux 可直接执行 `bash start.sh`。

结构：`app.py` 网页；`engine.py` 搜索/评分/草稿；`codex_backend.py` CLI 接入；`storage.py` 数据库；`tests/` 自动化验证。

云端已验证 Python 测试和网页启动。当前云容器的 Codex 运行目录为只读，真实模型调用被容器限制阻止；尚未在你的 Windows 机器验证。安装与登录检测不代表模型调用成功，首次使用请执行网页中的“测试 AI 实际连接”，随后做一次真实公司搜索。
