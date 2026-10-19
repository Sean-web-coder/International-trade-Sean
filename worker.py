"""Run on the user's PC; outbound HTTPS only, no inbound ports."""
import getpass
import os
import threading
import time
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from codex_backend import connection_status
from engine import discover_companies, research_company, draft_email, invoke_model


def execute(job, model):
    p = job['payload']
    kind = job['kind']
    if kind == 'discover':
        return discover_companies('', model, p['country'], p['niche'], p['limit'])
    if kind == 'research':
        return research_company('', model, p['website'], p['context'])
    if kind == 'draft':
        return draft_email('', model, p['prospect'], p['stage'])
    if kind == 'test':
        result = invoke_model('', model, 'Return JSON only: {"ok":true}', 'Connection test', use_search=False)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('模型响应格式异常')
        return result
    raise ValueError('未知任务类型')


def main():
    load_dotenv()
    url = (os.getenv('TRADESCOUT_URL') or input('网页地址 (https://...): ')).strip().rstrip('/')
    parsed = urlparse(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise SystemExit('请输入网站根地址，不含用户名、密码、路径或参数。')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}):
        raise SystemExit('公网连接必须使用 HTTPS。')
    token = os.getenv('TRADESCOUT_ACCESS_TOKEN') or getpass.getpass('网页连接码（输入不显示）: ')
    print(connection_status())
    model = os.getenv('CODEX_MODEL', '')
    headers = {'Authorization': 'Bearer ' + token}

    def post(path, payload=None):
        response = requests.post(url + path, json=payload, headers=headers, timeout=25, allow_redirects=False)
        if response.status_code in (401, 403):
            raise PermissionError('连接码错误，请重新启动并输入正确连接码。')
        if response.status_code >= 300:
            raise RuntimeError('服务器返回错误 ' + str(response.status_code))
        return response.json()

    print('连接器运行中。请保持窗口打开，在网页提交任务。按 Ctrl+C 退出。')
    while True:
        try:
            job = post('/api/worker/claim')['job']
            if not job:
                time.sleep(3)
                continue
            stop = threading.Event()
            def pulse():
                while not stop.wait(10):
                    try:
                        post('/api/worker/heartbeat')
                    except Exception:
                        pass
            thread = threading.Thread(target=pulse, daemon=True)
            thread.start()
            print('正在处理：', job['kind'])
            try:
                payload = {'lease_token': job['lease_token'], 'result': execute(job, model)}
            except Exception:
                payload = {'lease_token': job['lease_token'], 'error': '本机 Codex 执行失败。请检查本机 codex 登录、网络、模型权限与额度后重试。'}
            finally:
                stop.set()
                thread.join(timeout=1)
            # Retry delivery rather than immediately running the model again.
            for attempt in range(3):
                try:
                    post('/api/worker/' + job['id'] + '/complete', payload)
                    print('结果已返回网页。')
                    break
                except PermissionError:
                    raise
                except Exception:
                    if attempt == 2:
                        print('结果暂未送达，任务可能稍后被重新领取。')
                    else:
                        time.sleep(3)
        except PermissionError as exc:
            raise SystemExit(str(exc))
        except KeyboardInterrupt:
            print('\n连接器已关闭。')
            return
        except Exception:
            print('服务器暂不可用，5 秒后重连。')
            time.sleep(5)


if __name__ == '__main__':
    main()
