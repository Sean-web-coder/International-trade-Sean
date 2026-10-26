#!/bin/bash
cd "$(dirname "$0")" || exit 1
if ! command -v node >/dev/null 2>&1; then
  echo '未找到 Node.js。请先安装 Node.js 20 或更新版本，然后重新打开本文件。'
  read -r -p '按回车关闭窗口'
  exit 1
fi
if [ ! -d node_modules ]; then
  echo '首次启动，正在安装依赖。这可能需要几分钟...'
  npm install --no-audit --no-fund || { read -r -p '安装失败，按回车关闭窗口'; exit 1; }
fi
(sleep 2; open 'http://localhost:48173') &
npm start
read -r -p '服务已停止。按回车关闭窗口'
