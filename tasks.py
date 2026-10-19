"""Fixed research task types for local and server Codex runners."""
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

