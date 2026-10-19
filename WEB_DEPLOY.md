# Render 网页版 + 本机 Codex

这是私人单用户工作台。网页托管在 Render，Windows 连接器主动通过 HTTPS 领取任务，再调用本机已登录的 Codex。无需在电脑上开放端口，也无需上传 Codex 登录文件。网页支持找客户、背调评分、客户状态、邮件草稿和导出备份。

## 1. 在 Render 创建网站（首次一次）

1. 登录 https://dashboard.render.com/ ，选择 **New → Web Service**。
2. 连接 GitHub 并选择 `Sean-web-coder/International-trade-Sean`。私有仓库需授权 Render 读取。
3. **Branch 选 `tradescout-windows`**；Language / Runtime 选 **Docker**，Dockerfile 使用根目录 `Dockerfile`。
4. Instance Type 选 **Free**。
5. 添加环境变量 `TRADESCOUT_ACCESS_TOKEN`。用密码管理器生成至少 24 字符的随机密码，在 Render 中保存。它也是网页登录和连接器使用的连接码；不要发到聊天或写进 GitHub。
6. 点击 **Deploy Web Service**。成功后打开 Render 显示的 `https://…onrender.com` 地址。这才是实际网页网址。
7. 在网页输入连接码，进入工作台。

项目也带 `render.yaml`，可通过 Render 的 Blueprint 功能选择本分支部署；Blueprint 会自动生成连接码，可在服务的 Environment 中查看。**无需同时创建两种服务，任选一种。**

免费服务可能休眠，首次打开需要等待唤醒。免费文件系统是临时的，重启/重新部署可能丢失 SQLite 客户和任务数据。网页提供 CSV 和包含草稿的完整 JSON 导出。JSON 是备份文件，当前没有界面导入功能。需要长期持久化时，在 Render 选择支持磁盘的付费方案，添加持久化磁盘并把 `TRADESCOUT_DATA_DIR` 指向挂载路径；在选择前查看 Render 当前费用。当前配置不会自动购买付费资源。

## 2. Windows 接入 Codex

1. 电脑安装 Python 3.10+（推荐 3.12）、Node.js LTS。
2. 终端执行 `npm install -g @openai/codex`，再执行 `codex login`。
3. 从 GitHub 本分支 **Code → Download ZIP** 下载、解压。双击 **connect-codex.bat**。
4. 按提示输入 Render 网站根地址（`https://…onrender.com`）及同一个连接码。连接码输入时不会显示。
5. 保持窗口打开，在网页的“连接 Codex”页点击“测试 Codex 实际连接”。成功后即可搜索。

连接器只需首次安装 Python 依赖。它不会接收任意命令，只执行搜索、背调、草稿和连接测试四种任务。模型调用使用本机 Codex 账户的服务与额度；电脑关机或关闭连接器后无法执行新任务。

可在本机 `.env` 配置 `TRADESCOUT_URL`、`TRADESCOUT_ACCESS_TOKEN` 和可选的 `CODEX_MODEL`，避免每次输入。这些内容只保存在本机，不要提交。

## 验证与限制

云端 12 项自动测试通过，并用真实 Chromium 验证了登录、背调任务返回、客户编辑、草稿保存、备份下载和手机布局。模型结果使用测试数据；不代表真实 Codex 已连通。Docker 构建在当前云环境中因容器无法解析依赖仓库/代理域名而受阻，Render 上的镜像构建尚待验证。实际 Windows Codex 连接需要在你的电脑测试；本云容器的 Codex 运行目录只读，不能完成真实模型调用。网页上“连接器在线”和“AI 连接成功”是不同状态。

Render 部署必须由有权限的账号创建。本项目文件和部署配置本身不意味着网站已经上线。使用 Render 实际显示的域名，不要猜测网站地址。

开发启动：

```bash
python -m pip install -r requirements.txt -r requirements-web.txt -r requirements-worker.txt pytest
# 通过环境变量设置本地测试连接码，不要将真实值写进代码
python -m uvicorn web_server:app --host 127.0.0.1 --port 8000
python -m pytest -q
```

本机测试连接器允许 `http://127.0.0.1:8000`；公网必须 HTTPS。生产运行使用一个 Uvicorn 进程和一个本机连接器。此版本用于一个拥有者，不支持多用户数据隔离。
