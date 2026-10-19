"""Yiwu trade prospecting assistant. Run: streamlit run app.py"""
from __future__ import annotations

import csv
import io
import json
import os

import streamlit as st

from engine import COUNTRIES, SCORING, discover_companies, draft_email, normalize_url, research_company, validate_draft, word_count
from storage import connect, get_prospect, list_drafts, list_prospects, save_draft, update_details, upsert_prospect

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="TradeScout | 外贸开发智能体", page_icon="📦", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 2rem; max-width: 1260px;}
h1 {font-size:2.2rem !important;}
[data-testid="stMetricValue"] {font-size:1.7rem;}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.title("📦 TradeScout")
    st.caption("多品类采购商开发智能体 · 本地版")
    provider_label = st.radio("AI 连接方式", ["本机 Codex（默认）", "OpenAI API"])
    provider = "codex" if provider_label.startswith("本机") else "openai"
    api_key = ""
    if provider == "codex":
        model = st.text_input("Codex 模型（留空使用 CLI 默认）", value=os.getenv("CODEX_MODEL", ""))
        st.caption("复用此电脑上 Codex CLI 的登录状态，无需在此输入 API Key。请求使用登录账户的模型服务和额度，并非离线模型。")
        if st.button("检测 Codex 安装与登录"):
            try:
                from codex_backend import connection_status
                st.success(connection_status())
            except Exception as exc:
                st.error(str(exc))
        if st.button("测试 AI 实际连接"):
            try:
                from engine import invoke_model
                with st.spinner("正在连接 Codex……"):
                    result = invoke_model("", model, 'Return JSON only: {"ok": true}', "Connection test", use_search=False)
                if not isinstance(result, dict) or result.get("ok") is not True:
                    raise RuntimeError("模型已响应，但测试结果格式不正确。")
                st.success("Codex 模型连接成功。")
            except Exception as exc:
                st.error(str(exc))
    else:
        api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
        model = st.text_input("API 模型", value="gpt-5-mini")
        st.caption("API 模式使用单独的 API 额度。")
    st.caption("所有客户资料、评分、邮件草稿存储在本机 data/leads.sqlite3。不会自动发信。")
    st.divider()
    st.markdown("**操作顺序**")
    st.caption("① 按国家找公司 → ② 单家公司背调 → ③ 评分入库 → ④ 生成开发信 → ⑤ 人工审核和跟进")

st.title("海外多品类采购商开发智能体")
st.caption("寻找真正适合义乌贸易公司的一站式采购客户，而非单一商品比价买家")
conn = connect()
records = list_prospects(conn)
a, b, c = st.columns(3)
a.metric("已背调客户", len(records))
b.metric("A级客户", sum(x["score"] >= 80 for x in records))
c.metric("待联系", sum(x["status"] == "未联系" for x in records))

discover_tab, research_tab, crm_tab, help_tab = st.tabs(["🔎 智能寻找买家", "🧭 网站背调与评分", "✉️ 客户库与开发信", "⚙️ 操作指南"])

with discover_tab:
    st.subheader("按国家和商业模式搜索潜在进口商")
    with st.form("discovery"):
        col1, col2, col3 = st.columns([1.1, 2.4, .8])
        country = col1.selectbox("目标国家", COUNTRIES, index=0)
        niche = col2.text_input("重点客户类型 / 产品范围", value="general merchandise wholesalers, household goods, kitchenware, storage, gifts and variety store suppliers")
        limit = col3.number_input("最多返回", min_value=1, max_value=10, value=5)
        discover_click = st.form_submit_button("🌐 联网寻找真实公司", type="primary", use_container_width=True)
    if discover_click:
        if provider == "openai" and not api_key:
            st.error("请先在左侧输入 OpenAI API Key")
        else:
            try:
                with st.spinner("正在搜索公开信息并筛选官网……"):
                    st.session_state["candidates"] = discover_companies(api_key, model, country, niche, limit, provider=provider)
            except Exception as e:
                st.error(str(e))
    if "candidates" in st.session_state:
        candidates = st.session_state["candidates"]
        if not candidates:
            st.warning("暂时没有足够依据确认的候选公司。可调整产品词或国家。")
        for i, row in enumerate(candidates):
            with st.container(border=True):
                left, right = st.columns([4, 1])
                left.markdown(f"**{row['name']}** · {row['country']}")
                left.markdown(f"官网：[{row['website']}]({row['website']})")
                left.write(row["why_match_zh"])
                left.caption(f"查询线索：[公开来源]({row['source_url']}) · 仍需第二步详细核实")
                if right.button("背调这家公司", key=f"research_candidate_{i}", use_container_width=True):
                    st.session_state["research_url"] = row["website"]
                    st.info("已将网址填入第二个标签页，请切换至「网站背调与评分」。")

with research_tab:
    st.subheader("输入网址，获得证据驱动的客户评分")
    with st.form("research"):
        url = st.text_input("企业官网", value=st.session_state.get("research_url", ""), placeholder="https://www.example.com")
        context = st.text_area("补充信息（可选）", placeholder="例如：客户主要经营厨房用品和礼品；不要将猜测记为事实", height=75)
        research_click = st.form_submit_button("🔬 联网背调并评分", type="primary")
    if research_click:
        if provider == "openai" and not api_key:
            st.error("请在左侧输入 OpenAI API Key")
        else:
            try:
                normalized = normalize_url(url)
                with st.spinner("查询官网、业务模式、采购证据与扩张信号……"):
                    data = research_company(api_key, model, normalized, context, provider=provider)
                st.session_state["research_result"] = data
                upsert_prospect(conn, data)
                st.success("背调已保存至本地客户库。")
            except Exception as e:
                st.error(str(e))
    if "research_result" in st.session_state:
        p = st.session_state["research_result"]
        st.divider()
        ca, cb = st.columns([3, 1])
        ca.subheader(p.get("company_name") or p.get("input_website"))
        ca.write(p.get("summary_zh", ""))
        ca.caption(f"经营模式：{p.get('business_model') or '尚未核实'}")
        cb.metric("匹配评分", f"{p.get('score', 0)}/100")
        cb.write(p.get("priority", ""))
        st.markdown("**产品大类：** " + "、".join(map(str, p.get("product_categories", []))))
        st.markdown("**切入价值：** " + str(p.get("customer_fit") or "待核实"))
        st.markdown("**近期动态：** " + str(p.get("recent_signal") or "未找到明确证据"))
        for criterion, (points, label) in SCORING.items():
            ev = p.get("evidence", {}).get(criterion, {})
            confirmed = bool(isinstance(ev, dict) and ev.get("confirmed") is True and ev.get("sources") and ev.get("explanation"))
            with st.expander(f"{'✅' if confirmed else '◻️'} {label} · +{points if confirmed else 0}分"):
                st.write(ev.get("explanation") or "没有充分证据，不加分")
                for source in ev.get("sources", []):
                    st.write(f"来源：{source}")
        if p.get("risks"):
            st.warning("待核实风险：" + "；".join(map(str, p["risks"])))
        with st.expander("所有公开来源和研究原始JSON"):
            for src in p.get("sources", []):
                if isinstance(src, dict):
                    st.write(f"- {src.get('what_it_supports', '')}: {src.get('url', '')}")
            st.json(p)
        st.caption("评分代表公开证据充分度和业务匹配度，并不代表真实成交概率。请点击原始来源复核。")

with crm_tab:
    st.subheader("客户库、联系状态与邮件草稿")
    records = list_prospects(conn)
    if not records:
        st.info("还没有入库客户，请先在第二个标签页背调一家企业。")
    else:
        trows = [{"公司":r["name"], "国家":r["country"], "匹配分":r["score"], "状态":r["status"], "官网":r["website"]} for r in records]
        st.dataframe(trows, hide_index=True, use_container_width=True)
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["公司", "国家", "匹配分", "状态", "官网"])
        writer.writeheader()
        writer.writerows(trows)
        st.download_button("⬇ 导出客户CSV", out.getvalue().encode("utf-8-sig"), file_name="trade_leads.csv", mime="text/csv")
        selected_id = st.selectbox("选择一家客户", options=[int(x["id"]) for x in records], format_func=lambda pid: next(f"{r['name']} · {r['score']}分" for r in records if r["id"] == pid))
        selected = get_prospect(conn, selected_id)
        p = json.loads(selected["research_json"])
        st.markdown(f"**官网：** {selected['website']} | **评分：** {selected['score']} / 100")
        with st.form("details"):
            l, m, n = st.columns(3)
            status = l.selectbox("跟进状态", ["未联系", "已发首封", "已跟进一次", "已跟进两次", "已回复", "已询盘", "已成交", "暂停"], index=["未联系", "已发首封", "已跟进一次", "已跟进两次", "已回复", "已询盘", "已成交", "暂停"].index(selected["status"]) if selected["status"] in ["未联系", "已发首封", "已跟进一次", "已跟进两次", "已回复", "已询盘", "已成交", "暂停"] else 0)
            contact_name = m.text_input("联系人（仅录入已验证的姓名）", value=selected["contact_name"])
            contact_email = n.text_input("工作邮箱（仅录入已验证的地址）", value=selected["email"])
            if st.form_submit_button("保存跟进信息"):
                update_details(conn, selected_id, status, contact_email, contact_name)
                st.success("已保存")
        st.divider()
        stage = st.radio("邮件阶段", options=[0, 1, 2], format_func=lambda i: ["首封开发信", "第一次跟进", "第二次跟进（最后一次）"][i], horizontal=True)
        if st.button("✨ 生成英文个性化开发信", type="primary"):
            if provider == "openai" and not api_key:
                st.error("请先输入API Key")
            elif not p.get("evidence"):
                st.warning("此公司目前只有候选信息，请先背调核实。")
            else:
                try:
                    with st.spinner("严格按简短冷邮件规则撰写……"):
                        draft = draft_email(api_key, model, p, stage, provider=provider)
                    st.session_state["current_draft"] = {"pid": selected_id, "stage": stage, "draft": draft}
                except Exception as e:
                    st.error(str(e))
        existing = st.session_state.get("current_draft")
        if existing and existing["pid"] == selected_id:
            draft = existing["draft"]
            with st.form("draft_edit"):
                subject = st.text_input("邮件主题（最多6词）", value=draft["subject"])
                body = st.text_area("邮件正文（最多50词）", value=draft["body"], height=200)
                st.caption(f"主题 {word_count(subject)} 词 | 正文 {word_count(body)} 词")
                if draft.get("rationale_zh"):
                    st.caption("写作思路：" + draft["rationale_zh"])
                save_click = st.form_submit_button("✅ 审核完成，保存草稿")
                if save_click:
                    warnings = validate_draft(subject, body)
                    if warnings:
                        st.error("；".join(warnings))
                    else:
                        save_draft(conn, selected_id, existing["stage"], {"subject": subject, "body": body})
                        st.success("草稿已保存。发送邮件需你自行在邮箱中审核操作。")
        drafts = list_drafts(conn, selected_id)
        if drafts:
            st.markdown("**历史草稿**")
            for d in drafts:
                with st.expander(f"{d['created_at'][:10]} · {['首封', '跟进1', '跟进2'][d['stage']]} · {d['subject']}"):
                    st.code(f"Subject: {d['subject']}\n\n{d['body']}", language="text")
                    st.download_button("下载草稿", f"Subject: {d['subject']}\n\n{d['body']}", file_name=f"draft_{selected_id}_{d['id']}.txt", key=f"download_draft_{d['id']}")

with help_tab:
    st.markdown("""### 运行与使用\n
1. 默认选择本机 Codex，先检测登录并测试 AI 连接；也可切换为 OpenAI API。\n2. 「智能寻找买家」根据国家和品类搜索 **真实官网**。这里仅是候选名单，未经背调不能视为合格采购商。\n3. 「网站背调与评分」核实分销业务、多产品类别、中国采购证据等。只有具备对应公开来源的证据才计分。\n4. 「客户库与开发信」逐家生成首封邮件和两封不同角度的跟进邮件，人工复核之后自行发信。\n
**边界：** 不抓取非公开信息、不猜测私人邮箱、不承诺销售结果、不自动批量发信；AI与搜索引擎也会出错，务必点击来源验证。首次使用建议先测试3家企业。\n
**数据安全：** `.env` 和本地 SQLite 数据库已被 `.gitignore` 排除。部署为多人服务前应额外增加账户登录、权限和加密备份。\n""")

conn.close()
