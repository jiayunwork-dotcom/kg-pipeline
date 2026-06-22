import os
import sys
import tempfile
import logging
from typing import Dict, Any, List, Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frontend.api_client import client
from frontend.graph_viz import build_graph_visualization, get_entity_legend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PAGES = [
    ("📊 图谱总览", "overview"),
    ("🕸️ 图谱可视化", "graph"),
    ("🔍 实体搜索与路径", "search"),
    ("💬 知识问答", "qa"),
    ("📋 Pipeline任务", "tasks"),
    ("📝 文档输入", "input"),
    ("✅ 质量评估", "quality"),
]

PAGE_LABEL_TO_KEY = {label: key for label, key in PAGES}
PAGE_KEY_TO_LABEL = {key: label for label, key in PAGES}

st.set_page_config(
    page_title="知识图谱构建与可视化平台",
    page_icon="🕸️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; }
    .stMetric { background-color: #f0f2f6; padding: 1rem; border-radius: 0.5rem; }
    .entity-legend { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 0.25rem; margin: 0.1rem; color: white; font-size: 0.8rem; font-weight: 500; }
    div[data-testid="stVerticalBlock"] > div:has(.stButton button.page-nav-btn) {
        margin-top: -1rem;
    }
    .page-nav-btn {
        background-color: transparent !important;
        color: #0068c9 !important;
        border: none !important;
        padding: 0 !important;
        text-decoration: underline;
        font-weight: normal !important;
    }
</style>
""", unsafe_allow_html=True)


def init_state():
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "overview"
    if "submitted_task_id" not in st.session_state:
        st.session_state["submitted_task_id"] = None
    if "qa_history" not in st.session_state:
        st.session_state["qa_history"] = []


def switch_page(page_key: str):
    if page_key in PAGE_KEY_TO_LABEL:
        st.session_state["current_page"] = page_key
        st.rerun()


def render_sidebar():
    st.sidebar.title("🕸️ 知识图谱平台")
    st.sidebar.markdown("---")

    try:
        api_health = client.health_check()
    except Exception:
        api_health = False

    if api_health:
        st.sidebar.success("✅ API服务正常")
    else:
        st.sidebar.error("❌ API服务不可用")
        st.sidebar.caption(f"API地址: {os.environ.get('API_BASE_URL', 'http://localhost:8000')}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("导航菜单")

    current = st.session_state.get("current_page", "overview")

    for label, key in PAGES:
        is_active = (key == current)
        if st.sidebar.button(
            label,
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            switch_page(key)

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        <div style='text-align: center; color: #888; font-size: 0.8rem;'>
        KG Pipeline v1.0<br>
        FastAPI + Neo4j + Streamlit
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_overview():
    st.title("📊 知识图谱总览")
    st.markdown("---")

    try:
        stats = client.get_graph_stats()
    except Exception as e:
        st.error(f"获取图谱统计失败: {e}")
        return

    if not stats:
        st.warning("无法获取图谱统计数据，请检查API服务连接。")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总实体数", stats.get("total_entities", 0))
    with col2:
        st.metric("总关系数", stats.get("total_relations", 0))
    with col3:
        entity_types = stats.get("entity_type_distribution", {})
        st.metric("实体类型数", len(entity_types))
    with col4:
        rel_types = stats.get("relation_type_distribution", {})
        st.metric("关系类型数", len(rel_types))

    st.markdown("---")

    col_pie, col_bar = st.columns(2)

    with col_pie:
        st.subheader("📈 实体类型分布")
        entity_dist = stats.get("entity_type_distribution", {})
        if entity_dist:
            df_entity = pd.DataFrame(
                [(k, v) for k, v in entity_dist.items()],
                columns=["实体类型", "数量"],
            )
            fig_pie = px.pie(
                df_entity,
                values="数量",
                names="实体类型",
                color_discrete_map=get_entity_legend(),
                hole=0.4,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("暂无实体数据，可在「📝 文档输入」页面提交文本开始构建。")

    with col_bar:
        st.subheader("📊 关系类型分布")
        rel_dist = stats.get("relation_type_distribution", {})
        if rel_dist:
            df_rel = pd.DataFrame(
                [(k, v) for k, v in rel_dist.items()],
                columns=["关系类型", "数量"],
            )
            fig_bar = px.bar(
                df_rel,
                x="关系类型",
                y="数量",
                color="关系类型",
                text="数量",
            )
            fig_bar.update_layout(showlegend=False)
            fig_bar.update_traces(textposition="outside")
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("暂无关系数据")

    st.markdown("---")

    st.subheader("🏷️ 实体类型图例")
    legend = get_entity_legend()
    legend_html = ""
    for etype, color in legend.items():
        legend_html += f'<span class="entity-legend" style="background-color: {color};">{etype}</span>'
    st.markdown(legend_html, unsafe_allow_html=True)


def page_graph_viz():
    st.title("🕸️ 图谱可视化")
    st.markdown("---")

    initial_focus = st.session_state.pop("_focus_entity", "")

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])

    with col_ctrl1:
        focus_entity = st.text_input(
            "🔍 聚焦实体（留空显示全图）",
            placeholder="输入实体名称查看其周围子图...",
            value=initial_focus,
        )
    with col_ctrl2:
        hops = st.slider("跳数", min_value=1, max_value=4, value=2, step=1, disabled=not focus_entity)
    with col_ctrl3:
        min_conf = st.slider("最小置信度", min_value=0.0, max_value=1.0, value=0.0, step=0.05)

    physics = st.toggle("启用物理模拟（力导向布局）", value=True)

    graph_data = None
    try:
        if focus_entity:
            graph_data = client.get_subgraph(focus_entity, hops=hops, min_confidence=min_conf)
        else:
            max_nodes = st.slider("最大节点数", min_value=50, max_value=2000, value=500, step=50)
            graph_data = client.get_all_graph_data(min_confidence=min_conf, max_nodes=max_nodes)
    except Exception as e:
        st.error(f"获取图谱数据失败: {e}")
        return

    if not graph_data or (not graph_data.get("nodes") and not graph_data.get("edges")):
        st.info("暂无图谱数据，请先在「📝 文档输入」页面处理文档构建知识图谱。")
        return

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    st.info(f"📊 显示节点: {len(nodes)} 个, 关系边: {len(edges)} 条")

    try:
        net = build_graph_visualization(
            nodes,
            edges,
            highlight_node=focus_entity if focus_entity else None,
            height="700px",
            physics_enabled=physics,
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            net.write_html(f.name, notebook=False)
            html_path = f.name

        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        st.components.v1.html(html_content, height=720, scrolling=False)

        try:
            os.unlink(html_path)
        except Exception:
            pass
    except Exception as e:
        st.error(f"图谱渲染失败: {e}")


def page_search():
    st.title("🔍 实体搜索与路径查询")
    st.markdown("---")

    tab1, tab2 = st.tabs(["🔎 实体搜索", "🛤️ 路径查询"])

    with tab1:
        search_name = st.text_input("输入实体名称搜索", placeholder="例如：阿里巴巴")
        if search_name:
            try:
                results = client.search_entities(search_name, limit=50)
            except Exception as e:
                st.error(f"搜索失败: {e}")
                results = []

            if not results:
                st.info("未找到匹配的实体")
            else:
                st.success(f"找到 {len(results)} 个匹配实体")
                for node in results:
                    name = node.get('canonical_name', '')
                    etype = node.get('type', 'UNKNOWN')
                    with st.expander(f"📌 {name}  ({etype})"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write(f"**规范名称:** {name}")
                            st.write(f"**类型:** {etype}")
                            st.write(f"**出现频次:** {node.get('frequency', 0)}")
                            st.write(f"**首次来源:** {node.get('first_source', '')}")
                        with col_b:
                            aliases = node.get('aliases', [])
                            if aliases:
                                st.write("**别名:**")
                                for a in aliases:
                                    st.write(f"  - {a}")

                        c1, c2, _ = st.columns([1, 1, 3])
                        with c1:
                            if st.button(f"🔍 查看关系", key=f"detail_{name}"):
                                try:
                                    details = client.get_entity_details(name)
                                    if details and "relations" in details:
                                        st.markdown("**相关关系:**")
                                        rels = details["relations"]
                                        if rels:
                                            for rel in rels[:30]:
                                                direction = "→" if rel["direction"] == "out" else "←"
                                                st.write(
                                                    f"  {direction} **[{rel['relation']}]** → {rel['other_name']} "
                                                    f"({rel['other_type']}) - 置信度: {rel['confidence']:.4f}"
                                                )
                                        else:
                                            st.info("该实体暂无关系")
                                except Exception as e:
                                    st.error(f"获取详情失败: {e}")
                        with c2:
                            if st.button(f"🕸️ 查看子图", key=f"viz_{name}"):
                                st.session_state["_focus_entity"] = name
                                switch_page("graph")

    with tab2:
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            entity1 = st.text_input("起始实体", placeholder="实体A")
        with col_e2:
            entity2 = st.text_input("目标实体", placeholder="实体B")

        max_hops = st.slider("最大跳数", min_value=1, max_value=10, value=5, step=1)

        if st.button("🔍 查找最短路径"):
            if not entity1 or not entity2:
                st.warning("请输入两个实体名称")
            else:
                try:
                    paths = client.find_path(entity1, entity2, max_hops=max_hops)
                except Exception as e:
                    st.error(f"路径查询失败: {e}")
                    paths = []

                if not paths:
                    st.info(f"未找到 {entity1} 到 {entity2} 之间的路径（{max_hops}跳内）")
                else:
                    st.success(f"找到 {len(paths)} 条路径")
                    for i, path in enumerate(paths, 1):
                        with st.expander(f"🛤️ 路径 {i}  ({path.get('path_length', 0)} 跳)"):
                            node_names = path.get("node_names", [])
                            node_types = path.get("node_types", [])
                            rel_types = path.get("relation_types", [])

                            if node_names:
                                path_display = ""
                                for j, name in enumerate(node_names):
                                    color = get_entity_legend().get(
                                        node_types[j] if j < len(node_types) else "UNKNOWN",
                                        "#888",
                                    )
                                    path_display += f' <span style="background-color:{color};color:white;padding:2px 8px;border-radius:4px;">{name}</span>'
                                    if j < len(rel_types):
                                        path_display += f" --[{rel_types[j]}]-->"
                                st.markdown(path_display, unsafe_allow_html=True)

                                confidences = path.get("confidences", [])
                                if confidences:
                                    avg_conf = sum(confidences) / len(confidences)
                                    st.write(f"**平均置信度:** {avg_conf:.4f}")


def page_tasks():
    st.title("📋 Pipeline任务管理")
    st.markdown("---")

    if st.button("🔄 刷新任务列表", use_container_width=True):
        st.rerun()

    st.markdown("")

    try:
        tasks = client.list_tasks(limit=100)
    except Exception as e:
        st.error(f"获取任务列表失败: {e}")
        tasks = []

    if not tasks:
        st.info("暂无任务记录，请先到「📝 文档输入」页面提交文档处理任务")
        return

    for task in tasks:
        status = task.get("status", "")
        task_id = task.get("task_id", "")

        status_emoji = {
            "排队中": "⏳",
            "预处理中": "⚙️",
            "实体识别中": "🏷️",
            "关系抽取中": "🔗",
            "融合入图中": "🕸️",
            "完成": "✅",
            "失败": "❌",
        }.get(status, "❓")

        with st.expander(f"{status_emoji} [{status}] {task_id}  -  {task.get('created_at', '')}", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**任务ID:** `{task_id}`")
                st.write(f"**状态:** {status}")
                st.write(f"**创建时间:** {task.get('created_at', '')}")
            with col2:
                st.write(f"**文档总数:** {task.get('total_documents', 0)}")
                st.write(f"**已处理:** {task.get('processed_documents', 0)}")
                st.write(f"**抽取实体:** {task.get('entities_extracted', 0)}")
            with col3:
                st.write(f"**抽取关系:** {task.get('relations_extracted', 0)}")
                if task.get("failed_step"):
                    st.error(f"**失败步骤:** {task.get('failed_step', '')}")
                if task.get("error_message"):
                    st.error(f"**错误信息:** {task.get('error_message', '')}")

            if status == "失败":
                if st.button(f"🔄 重试任务 {task_id}", key=f"retry_{task_id}", type="primary"):
                    try:
                        result = client.retry_task(task_id)
                        if result:
                            st.success("任务已重新提交！")
                            st.rerun()
                        else:
                            st.error("重试失败")
                    except Exception as e:
                        st.error(f"重试异常: {e}")


def page_input():
    st.title("📝 文档输入与处理")
    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs(["✏️ 直接输入文本", "📂 批量上传文件", "🌐 URL列表", "📚 自定义实体词典"])

    with tab1:
        input_text = st.text_area(
            "输入待处理的文本内容",
            height=250,
            placeholder="请输入要抽取实体和关系的文本内容...\n\n例如：\n阿里巴巴集团由马云于1999年在杭州创立，是中国最大的电子商务公司。阿里巴巴与腾讯在多个领域存在竞争关系，同时与百度也有合作项目。",
        )

        if st.button("🚀 提交处理", key="submit_text", type="primary"):
            if not input_text.strip():
                st.warning("请输入文本内容")
            else:
                with st.spinner("正在提交任务..."):
                    try:
                        result = client.create_task_text(input_text)
                        if result:
                            task_id = result.get('task_id', '')
                            st.success(f"✅ 任务已提交！任务ID: `{task_id}`")
                            st.info(f"当前状态: {result.get('status', '')}")
                            st.session_state["submitted_task_id"] = task_id

                            c1, c2, _ = st.columns([1, 1, 2])
                            with c1:
                                if st.button("📋 立即跳转到任务管理", type="secondary"):
                                    switch_page("tasks")
                            with c2:
                                if st.button("🔄 再提交一个文本", key="resubmit_text"):
                                    st.session_state["submitted_task_id"] = None
                                    st.rerun()
                        else:
                            st.error("❌ 任务提交失败，请检查API服务是否正常运行")
                    except Exception as e:
                        st.error(f"❌ 任务提交异常: {e}")

    with tab2:
        st.markdown("""
        **支持批量上传多个 `.txt` 或 `.md` (Markdown) 文件**

        💡 每个文件会作为独立文档进行实体关系抽取，自动检测文件编码（UTF-8/GBK等）
        """)

        uploaded_files = st.file_uploader(
            "📤 选择文件（可多选）",
            type=["txt", "md", "markdown"],
            accept_multiple_files=True,
            help="支持 .txt 和 .md/.markdown 文件，可一次选择多个",
        )

        if uploaded_files:
            st.info(f"已选择 {len(uploaded_files)} 个文件:")
            for f in uploaded_files:
                try:
                    raw_size = len(f.getvalue())
                    size_kb = raw_size / 1024
                    st.caption(f"  • {f.name} — {size_kb:.1f} KB")
                except Exception as e:
                    st.warning(f"  • {f.name} — 无法读取: {e}")

        if st.button("🚀 上传并处理文件", key="submit_files", type="primary"):
            if not uploaded_files:
                st.warning("请先选择至少一个 .txt 或 .md 文件")
            else:
                with st.spinner(f"正在上传并处理 {len(uploaded_files)} 个文件..."):
                    try:
                        file_tuples = []
                        for f in uploaded_files:
                            f.seek(0)
                            content_bytes = f.getvalue()
                            mime = "text/markdown" if f.name.lower().endswith((".md", ".markdown")) else "text/plain"
                            file_tuples.append((f.name, content_bytes, mime))

                        result = client.create_task_files(file_tuples)
                        if result:
                            task_id = result.get('task_id', '')
                            total_docs = result.get('total_documents', 0)
                            st.success(f"✅ 任务已提交！任务ID: `{task_id}`")
                            st.info(f"文件数量: {len(uploaded_files)}, 当前状态: {result.get('status', '')}")
                            st.caption("💡 每个文件作为独立文档处理，前往任务管理页面查看进度")
                            st.session_state["submitted_task_id"] = task_id

                            if st.button("📋 跳转到任务管理查看进度", key="goto_tasks_from_file", type="secondary"):
                                switch_page("tasks")
                        else:
                            st.error("❌ 文件上传失败，请检查文件格式和API服务状态")
                    except Exception as e:
                        st.error(f"❌ 文件上传异常: {e}")

    with tab3:
        urls_text = st.text_area(
            "输入URL列表（每行一个）",
            height=200,
            placeholder="https://example.com/article1\nhttps://example.com/article2\nhttps://example.com/news",
        )

        if st.button("🚀 抓取并处理", key="submit_urls", type="primary"):
            urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
            if not urls:
                st.warning("请输入至少一个URL")
            else:
                with st.spinner(f"正在提交 {len(urls)} 个URL处理任务..."):
                    try:
                        result = client.create_task_urls(urls)
                        if result:
                            task_id = result.get('task_id', '')
                            st.success(f"✅ 任务已提交！任务ID: `{task_id}`")
                            st.info(f"URL数量: {len(urls)}, 当前状态: {result.get('status', '')}")
                            st.caption("💡 URL抓取和解析需要一些时间，请前往任务管理页面查看进度")
                            st.session_state["submitted_task_id"] = task_id

                            if st.button("📋 跳转到任务管理查看进度", key="goto_tasks_from_url", type="secondary"):
                                switch_page("tasks")
                        else:
                            st.error("❌ 任务提交失败，请检查URL格式和网络连接")
                    except Exception as e:
                        st.error(f"❌ 任务提交异常: {e}")

    with tab4:
        st.markdown("""
        上传自定义实体词典可以增强实体识别效果。

        **CSV格式:** `实体名,实体类型`（每行一条）

        **支持的实体类型:**
        - `PER` 人名
        - `ORG` 组织机构
        - `LOC` 地点
        - `TIME` 时间
        - `EVENT` 事件
        - `WORK` 作品
        - `TECH` 技术术语
        """)

        with st.expander("📋 查看示例CSV", expanded=False):
            st.code("""
阿里巴巴,ORG
马云,PER
杭州,LOC
人工智能,TECH
深度学习,TECH
云栖大会,EVENT
通义千问,WORK
""".strip())

        dict_file = st.file_uploader("📤 上传实体词典CSV文件", type=["csv"])
        if dict_file is not None:
            content = dict_file.getvalue().decode("utf-8")
            lines = [l for l in content.splitlines() if l.strip()]
            valid_count = 0
            for l in lines:
                parts = l.split(",")
                if len(parts) >= 2 and parts[1].strip().upper() in ["PER", "ORG", "LOC", "TIME", "EVENT", "WORK", "TECH"]:
                    valid_count += 1

            st.text_area("词典内容预览", content, height=150)
            st.success(f"✅ 词典已加载，共 {len(lines)} 行，有效条目 {valid_count} 条")

    st.markdown("---")
    st.subheader("💡 使用示例")
    st.code(
        """# 示例文本 - 复制粘贴到上方测试
阿里巴巴集团由马云于1999年在杭州创立，是中国最大的电子商务公司。
马云毕业于杭州师范学院，曾任阿里巴巴的首席执行官。
阿里巴巴与腾讯在多个领域存在竞争关系，同时与百度在云计算领域有合作项目。
2023年，阿里巴巴在云栖大会上发布了新一代人工智能模型通义千问。
通义千问基于深度学习和机器学习技术构建，是一款大语言模型作品。
""".strip(),
        language="text",
    )


def _collect_qa_entities(qa_data: Dict[str, Any]) -> Dict[str, str]:
    entity_map: Dict[str, str] = {}
    legend = get_entity_legend()

    for e in qa_data.get("entities", []):
        name = e.get("name", "")
        etype = e.get("type", "UNKNOWN")
        if name and name not in entity_map:
            entity_map[name] = etype

    for r in qa_data.get("relations", []):
        head = r.get("head", "")
        tail = r.get("tail", "")
        htype = r.get("head_type", "") or "UNKNOWN"
        ttype = r.get("tail_type", "") or "UNKNOWN"
        if head and head not in entity_map:
            entity_map[head] = htype if htype in legend else "UNKNOWN"
        if tail and tail not in entity_map:
            entity_map[tail] = ttype if ttype in legend else "UNKNOWN"

    for p in qa_data.get("paths", []):
        names = p.get("node_names", [])
        types = p.get("node_types", [])
        for i, name in enumerate(names):
            if name and name not in entity_map:
                etype = types[i] if i < len(types) else "UNKNOWN"
                entity_map[name] = etype if etype in legend else "UNKNOWN"

    return entity_map


def _highlight_entities_in_text(text: str, entity_map: Dict[str, str]) -> str:
    legend = get_entity_legend()
    if not entity_map:
        return text.replace("\n", "<br>")

    sorted_entities = sorted(entity_map.keys(), key=len, reverse=True)

    result = text
    for entity_name in sorted_entities:
        if entity_name and entity_name in result:
            etype = entity_map.get(entity_name, "UNKNOWN")
            color = legend.get(etype, "#888")
            span = (
                f'<span style="background-color:{color};color:white;padding:1px 6px;'
                f'border-radius:3px;font-size:0.92em;font-weight:500;'
                f'margin:0 1px;">{entity_name}</span>'
            )
            result = result.replace(entity_name, span)

    return result.replace("\n", "<br>")


def _render_entity_buttons(entity_map: Dict[str, str], key_prefix: str):
    legend = get_entity_legend()
    if not entity_map:
        return

    entities_list = list(entity_map.items())
    cols_per_row = 4
    total_rows = (len(entities_list) + cols_per_row - 1) // cols_per_row

    for row in range(total_rows):
        row_items = entities_list[row * cols_per_row : (row + 1) * cols_per_row]
        cols = st.columns(cols_per_row)
        for i, (ename, etype) in enumerate(row_items):
            color = legend.get(etype, "#888")
            with cols[i]:
                st.markdown(
                    f'<div style="font-size:0.7rem;color:#666;margin-bottom:2px;">{etype}</div>'
                    f'<div style="background-color:{color};color:white;padding:6px 8px;'
                    f'border-radius:5px;font-size:0.85rem;text-align:center;'
                    f'margin-bottom:4px;">{ename}</div>',
                    unsafe_allow_html=True,
                )
                btn_key = f"{key_prefix}_{ename}"
                if st.button(
                    "🔍 聚焦图谱",
                    key=btn_key,
                    use_container_width=True,
                    disabled=False,
                ):
                    st.session_state["_focus_entity"] = ename
                    switch_page("graph")


def _render_qa_history_item(idx: int, history_item: Dict[str, Any]):
    question = history_item.get("question", "")
    answer = history_item.get("answer", "")
    timestamp = history_item.get("timestamp", "")

    entity_map = _collect_qa_entities(history_item)

    with st.container():
        st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 12px; border-radius: 8px; margin-bottom: 10px;">
            <div style="color: #666; font-size: 0.8rem; margin-bottom: 4px;">
                🕐 {timestamp}
            </div>
            <div style="font-weight: 600; margin-bottom: 6px;">
                ❓ {question}
            </div>
            <div style="white-space: normal; color: #333; line-height: 1.7;">
                💡 {_highlight_entities_in_text(answer, entity_map)}
            </div>
        </div>
        """, unsafe_allow_html=True)

        if entity_map:
            st.caption("🏷️ 点击下方按钮跳转到图谱可视化页面，聚焦对应实体：")
            _render_entity_buttons(entity_map, key_prefix=f"qa_hist_{idx}")

        st.markdown("---")


def page_qa():
    st.title("💬 知识问答")
    st.markdown("---")

    col_question, col_examples = st.columns([3, 2])

    with col_question:
        st.subheader("🔎 提问")
        question_input = st.text_input(
            "输入您的问题",
            placeholder="例如：阿里巴巴是什么类型的实体？马云和阿里巴巴是什么关系？",
            key="qa_question_input",
        )

        col_submit, col_clear = st.columns([1, 1])
        with col_submit:
            submit_clicked = st.button("🚀 提交问题", type="primary", use_container_width=True)
        with col_clear:
            if st.button("🗑️ 清空历史", use_container_width=True):
                st.session_state["qa_history"] = []
                st.rerun()

        if submit_clicked and question_input.strip():
            with st.spinner("正在分析问题并检索答案..."):
                try:
                    response = client.ask_question(question_input.strip())
                    if response and response.get("success"):
                        result = response.get("result", {})
                        parsed = response.get("parsed_question", {})
                        answer_text = result.get("answer_text", "抱歉，未能获取到答案。")
                        entities = result.get("entities", [])
                        relations = result.get("relations", [])
                        paths = result.get("paths", [])

                        history_item = {
                            "question": question_input.strip(),
                            "answer": answer_text,
                            "entities": entities,
                            "relations": relations,
                            "paths": paths,
                            "parsed": parsed,
                            "timestamp": response.get("timestamp", ""),
                        }

                        st.session_state["qa_history"].insert(0, history_item)
                        if len(st.session_state["qa_history"]) > 20:
                            st.session_state["qa_history"] = st.session_state["qa_history"][:20]

                    else:
                        error_msg = response.get("error_message", "未知错误") if response else "未能连接到问答服务"
                        st.error(f"❌ {error_msg}")
                except Exception as e:
                    st.error(f"❌ 提问失败：{e}")

        st.markdown("### 📝 当前答案")
        if st.session_state["qa_history"]:
            latest = st.session_state["qa_history"][0]
            answer = latest.get("answer", "")
            parsed = latest.get("parsed", {})
            intent = parsed.get("intent", "")
            parsed_entities = parsed.get("entities", [])

            entity_map = _collect_qa_entities(latest)

            intent_map = {
                "attribute": "属性查询",
                "relation": "关系查询",
                "path": "路径查询",
                "list": "列举查询",
            }

            with st.expander("🔧 问题解析详情", expanded=False):
                st.write(f"**识别意图：** {intent_map.get(intent, intent)}")
                st.write(f"**提取实体：** {', '.join(parsed_entities) if parsed_entities else '无'}")
                if entity_map:
                    st.write("**答案涉及实体：**")
                    for ename, etype in entity_map.items():
                        st.write(f"  - {ename} ({etype})")

            st.markdown(f"""
            <div style="background-color: #e8f4fd; padding: 16px; border-radius: 8px; border-left: 4px solid #4ECDC4;">
                <div style="font-weight: 600; margin-bottom: 8px;">❓ {latest.get('question', '')}</div>
                <div style="white-space: normal; line-height: 1.8;">💡 {_highlight_entities_in_text(answer, entity_map)}</div>
            </div>
            """, unsafe_allow_html=True)

            if entity_map:
                st.markdown("#### 🏷️ 涉及实体（点击按钮跳转到图谱可视化）")
                _render_entity_buttons(entity_map, key_prefix="qa_current")
        else:
            st.info("👆 请在上方输入问题并提交，答案将在这里显示。")

    with col_examples:
        st.subheader("💡 提问示例")

        try:
            intents_data = client._get("/api/qa/intents")
            if intents_data and "intents" in intents_data:
                for intent_info in intents_data["intents"]:
                    with st.expander(f"📌 {intent_info.get('name', '')}", expanded=False):
                        st.markdown(f"**说明：** {intent_info.get('description', '')}")
                        st.markdown("**示例问题：**")
                        for example in intent_info.get("examples", []):
                            if st.button(
                                f"❓ {example}",
                                key=f"qa_example_{example}",
                                use_container_width=True,
                            ):
                                st.session_state["qa_question_input"] = example
                                st.rerun()
        except Exception as e:
            st.info("""
            **可以尝试以下类型的问题：**

            🏷️ **属性查询**
            - 阿里巴巴是什么类型的实体？
            - 马云的别名有哪些？

            🔗 **关系查询**
            - 马云和阿里巴巴是什么关系？
            - 阿里巴巴和腾讯有什么关系？

            🛤️ **路径查询**
            - 马云和杭州是怎么关联的？
            - 从阿里巴巴到百度的路径？

            📋 **列举查询**
            - 阿里巴巴有哪些关联的实体？
            - 和杭州相关的实体有哪些？
            """)

    st.markdown("---")
    st.subheader("📜 问答历史（最近20条）")

    history = st.session_state.get("qa_history", [])
    if not history:
        st.info("暂无问答历史记录")
    else:
        for idx, item in enumerate(history):
            _render_qa_history_item(idx, item)


def page_quality():
    st.title("✅ 质量评估")
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📊 精确率趋势", "🎯 采样评估", "📜 评估历史"])

    with tab1:
        try:
            trend = client.get_quality_trend(limit=10)
        except Exception as e:
            st.error(f"获取趋势数据失败: {e}")
            trend = None

        if not trend or not trend.get("precisions"):
            st.info("暂无评估历史数据，请先到「🎯 采样评估」标签页进行质量评估")
        else:
            dates = trend.get("dates", [])
            precisions = [p * 100 for p in trend.get("precisions", [])]
            totals = trend.get("totals", [])

            df_trend = pd.DataFrame(
                {
                    "评估时间": dates,
                    "精确率 (%)": precisions,
                    "样本数": totals,
                }
            )

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=df_trend["评估时间"],
                    y=df_trend["精确率 (%)"],
                    mode="lines+markers",
                    name="精确率",
                    line=dict(width=3, color="#4ECDC4"),
                    marker=dict(size=10),
                )
            )
            fig.add_hline(
                y=80,
                line_dash="dash",
                line_color="red",
                annotation_text="目标阈值 80%",
            )
            fig.update_layout(
                title="📈 最近评估精确率趋势",
                yaxis_title="精确率 (%)",
                yaxis_range=[0, 105],
            )
            st.plotly_chart(fig, use_container_width=True)

            col1, col2, col3 = st.columns(3)
            with col1:
                avg_p = sum(precisions) / len(precisions) if precisions else 0
                st.metric("平均精确率", f"{avg_p:.1f}%")
            with col2:
                st.metric("最高精确率", f"{max(precisions):.1f}%" if precisions else "N/A")
            with col3:
                st.metric("评估次数", len(precisions))

    with tab2:
        if st.button("🎲 生成100条随机三元组样本", type="primary"):
            with st.spinner("正在生成样本..."):
                try:
                    sample = client.generate_quality_sample(100)
                    st.session_state["quality_sample"] = sample
                    st.session_state["quality_labels"] = {}
                except Exception as e:
                    st.error(f"生成样本失败: {e}")
                    sample = []

        if "quality_sample" not in st.session_state or not st.session_state["quality_sample"]:
            st.info("👆 点击上方按钮生成评估样本")
        else:
            sample = st.session_state["quality_sample"]
            labels = st.session_state.get("quality_labels", {})
            st.success(f"已生成 {len(sample)} 条样本，请逐条标注正确/错误")

            labeled_count = len(labels)
            st.progress(labeled_count / max(len(sample), 1), text=f"标注进度: {labeled_count}/{len(sample)}")

            batch_size = 10
            total_pages = (len(sample) + batch_size - 1) // batch_size
            page_num = st.number_input(
                "页码",
                min_value=1,
                max_value=total_pages,
                value=1,
            )
            start = (page_num - 1) * batch_size
            end = min(start + batch_size, len(sample))

            st.markdown(f"**显示第 {start + 1} - {end} 条**")

            batch_labels_changed = False
            for i in range(start, end):
                triple = sample[i]
                tid = triple.get("id", f"triple_{i}")
                st.markdown("---")
                col_info, col_label = st.columns([4, 1])
                with col_info:
                    st.markdown(
                        f"""
                        **{i + 1}.**
                        <span style="background-color:#4ECDC4;color:white;padding:2px 6px;border-radius:3px;">{triple.get('head', '')}</span>
                        <b> → [{triple.get('relation', '')}] → </b>
                        <span style="background-color:#45B7D1;color:white;padding:2px 6px;border-radius:3px;">{triple.get('tail', '')}</span>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"置信度: {triple.get('confidence', 0):.4f} | "
                        f"头: {triple.get('head_type', '')} | 尾: {triple.get('tail_type', '')}"
                    )
                    sentences = triple.get("sentences", [])
                    if sentences:
                        s = sentences[0]
                        st.caption(f"来源句子: {s[:200]}{'...' if len(s) > 200 else ''}")

                with col_label:
                    current_label = labels.get(tid)
                    choice = st.radio(
                        "标注",
                        options=["正确", "错误"],
                        index=0 if current_label is True else (1 if current_label is False else 0),
                        key=f"radio_{tid}",
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                    new_val = (choice == "正确")
                    if current_label is None or current_label != new_val:
                        labels[tid] = new_val
                        batch_labels_changed = True

            if batch_labels_changed:
                st.session_state["quality_labels"] = labels

            col_submit, col_clear = st.columns(2)
            with col_submit:
                if st.button("✅ 提交评估结果", type="primary", disabled=(labeled_count == 0)):
                    with st.spinner("正在提交..."):
                        try:
                            result = client.submit_evaluation(labels)
                            if result:
                                precision = result.get('precision', 0) * 100
                                correct = result.get('correct', 0)
                                total = result.get('total', 0)
                                st.success(f"🎉 评估完成！精确率: **{precision:.1f}%** ({correct}/{total})")
                                st.session_state.pop("quality_sample", None)
                                st.session_state.pop("quality_labels", None)
                                st.rerun()
                        except Exception as e:
                            st.error(f"提交评估失败: {e}")
            with col_clear:
                if st.button("🔄 重新生成样本"):
                    st.session_state.pop("quality_sample", None)
                    st.session_state.pop("quality_labels", None)
                    st.rerun()

    with tab3:
        try:
            history = client.get_quality_history(limit=20)
        except Exception as e:
            st.error(f"获取历史失败: {e}")
            history = []

        if not history:
            st.info("暂无评估历史记录")
        else:
            df_history = pd.DataFrame(history)
            df_history["precision"] = df_history["precision"].apply(lambda x: f"{x * 100:.1f}%")
            df_history.columns = ["精确率", "样本总数", "正确数", "评估时间"]
            df_history = df_history[["评估时间", "精确率", "正确数", "样本总数"]]
            st.dataframe(df_history, use_container_width=True, hide_index=True)


def main():
    init_state()
    render_sidebar()

    current_page = st.session_state.get("current_page", "overview")

    handlers = {
        "overview": page_overview,
        "graph": page_graph_viz,
        "search": page_search,
        "qa": page_qa,
        "tasks": page_tasks,
        "input": page_input,
        "quality": page_quality,
    }

    handler = handlers.get(current_page, page_overview)
    try:
        handler()
    except Exception as e:
        st.error(f"页面渲染出错: {e}")
        import traceback
        with st.expander("🔧 详细错误信息"):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
