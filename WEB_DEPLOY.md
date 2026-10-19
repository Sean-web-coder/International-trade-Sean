# 网页直接使用 Codex 订阅

默认部署模式现在是 **服务器 Codex CLI**。无需下载项目、安装 Windows 连接器或填写 API Key。你仍需亲自在 OpenAI 官方页面完成账号授权。

## 已部署的 Render 网站如何更新

1. Render 服务使用 GitHub 仓库 `Sean-web-coder/International-trade-Sean` 的 **tradescout-windows** 分支。
2. 如果自动部署开启，GitHub 更新后等待部署变成 Live。否则在 Render 点击 **Manual Deploy → Deploy latest commit**。
3. Docker 镜像已默认设置 `TRADESCOUT_CODEX_MODE=server`。若你以前手动配置了同名变量为 `local`，请改为 `server`。
4. 打开网站，使用原来的工作台连接码登录，进入 **连接 Codex**。
5. 点击 **登录我的 Codex**。出现设备码后，点击 **打开 OpenAI 官方授权页面**。
6. 在 OpenAI 页面登录拥有 Codex 订阅额度的 ChatGPT 账号，输入刚刚生成的设备码并授权。若账号要求启用设备码登录，请按官方账号设置提示启用。
7. 返回网站，等待显示“服务器 Codex 已登录”，然后点击 **测试 Codex 实际连接**。成功后即可找客户、背调和生成邮件。

设备码由你自己的 Render 服务器上的官方 `codex login --device-auth` 命令生成。不要授权别人发来的设备码。密码仅在 OpenAI 官方页面输入；不要向聊天、GitHub 或工作台输入 ChatGPT 密码、cookie 或 OAuth 令牌。

## 账号、额度与数据

- 网页调用部署在你服务器上的 Codex CLI，不是远程操控你 Windows 上的 Codex 窗口。
- CLI 强制使用 ChatGPT 登录，并移除 API Key 环境变量，不自动切换到 API 计费。实际可用模型和额度受你的订阅、账号策略及 OpenAI 当前规则限制。
- Codex 自行保存登录凭据在服务器的 `data/.codex`。后端不向网页返回 OAuth 凭据。退出网站只清除工作台会话；要撤销服务器登录，请点“退出 Codex 登录”。
- 此版本是**私人单用户应用**。不要向其他人分享工作台连接码；持有该码的人可以访问客户资料、发起任务并使用你的 Codex 额度。
- Render 免费文件系统是临时的：部署/重启可能清空客户资料和登录状态，需要重新授权。网页支持 CSV 和完整 JSON 导出；当前没有备份导入界面。长期保存可自行选择支持磁盘的付费方案，把 `TRADESCOUT_DATA_DIR` 指向持久化挂载目录。当前配置不会自动购买付费资源。
- Codex 保留只读沙箱，不自动绕过安全限制。若 Render 不支持 Codex 所需的运行环境，或 OpenAI 不接受该服务器的登录/网络，网页会报告失败。这时需要选择兼容的私有服务器；单靠网页按钮无法消除平台限制。

## 首次部署到 Render

在 https://dashboard.render.com/ 选择 **New → Blueprint**，连接仓库，分支选 `tradescout-windows`，应用根目录的 `render.yaml`。配置使用免费实例并自动生成 `TRADESCOUT_ACCESS_TOKEN`。部署后在服务 Environment 中查看该值，用作工作台连接码，勿分享。

也可手动 New → Web Service：选择上述仓库和分支、Docker runtime、Free 实例；设置至少 24 字符的随机 `TRADESCOUT_ACCESS_TOKEN`。使用 Render 实际给出的 `https://…onrender.com` 地址。

## 本地连接器兼容模式（可选）

需要继续使用电脑上已登录的 Codex 时，将服务器变量 `TRADESCOUT_CODEX_MODE=local`。电脑双击 `connect-codex.bat`，输入网页地址和工作台连接码。默认服务器模式无需此操作。

## 验证情况与开发

18 项自动测试已通过，包含登录设备码解析、只接受 ChatGPT 登录、子进程不继承 API Key、服务器任务循环、访问保护、任务租约/取消、客户入库与邮件校验。Chromium 浏览器验证了设备登录界面、授权后状态切换及原有业务流程；设备码与模型返回均使用测试数据。

尚未替你完成真实 OpenAI 登录或订阅模型请求；必须由你本人授权后在部署的网站测试。当前云环境的 Docker 构建因容器 DNS 无法下载依赖而受阻，完整镜像构建需由 Render 验证。

```bash
python -m pip install -r requirements.txt -r requirements-web.txt -r requirements-worker.txt pytest
python -m pytest -q
```

开发使用 `python -m uvicorn web_server:app --host 127.0.0.1 --port 8000`，通过环境变量配置工作台连接码。服务器 Codex 模式还需要安装官方 CLI 0.159.2、设置 `TRADESCOUT_CODEX_MODE=server`。只启动一个 Uvicorn 进程，避免多个登录管理器互相冲突。

认证参考：官方 [Codex authentication](https://developers.openai.com/codex/auth) 和 [设备码登录实现](https://github.com/openai/codex/blob/main/codex-rs/login/src/device_code_auth.rs)。
