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
</style>
""", unsafe_allow_html=True)


def render_sidebar():
    st.sidebar.title("🕸️ 知识图谱平台")
    st.sidebar.markdown("---")

    api_health = client.health_check()
    if api_health:
        st.sidebar.success("✅ API服务正常")
    else:
        st.sidebar.error("❌ API服务不可用")
        st.sidebar.warning(f"API地址: {os.environ.get('API_BASE_URL', 'http://localhost:8000')}")

    st.sidebar.markdown("---")
    page = st.sidebar.radio(
        "导航菜单",
        [
            "📊 图谱总览",
            "🕸️ 图谱可视化",
            "🔍 实体搜索与路径",
            "📋 Pipeline任务",
            "📝 文档输入",
            "✅ 质量评估",
        ],
        index=0,
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        <div style='text-align: center; color: #888; font-size: 0.8rem;'>
        KG Pipeline v1.0<br>
        Powered by FastAPI + Neo4j + Streamlit
        </div>
        """,
        unsafe_allow_html=True,
    )
    return page


def page_overview():
    st.title("📊 知识图谱总览")
    st.markdown("---")

    stats = client.get_graph_stats()

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
            st.info("暂无实体数据")

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

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])

    with col_ctrl1:
        focus_entity = st.text_input(
            "🔍 聚焦实体（留空显示全图）",
            placeholder="输入实体名称查看其周围子图...",
        )
    with col_ctrl2:
        if focus_entity:
            hops = st.slider("跳数", min_value=1, max_value=4, value=2, step=1)
        else:
            hops = 2
    with col_ctrl3:
        min_conf = st.slider("最小置信度", min_value=0.0, max_value=1.0, value=0.0, step=0.05)

    physics = st.toggle("启用物理模拟（力导向布局）", value=True)

    if focus_entity:
        graph_data = client.get_subgraph(focus_entity, hops=hops, min_confidence=min_conf)
    else:
        max_nodes = st.slider("最大节点数", min_value=50, max_value=2000, value=500, step=50)
        graph_data = client.get_all_graph_data(min_confidence=min_conf, max_nodes=max_nodes)

    if not graph_data or (not graph_data.get("nodes") and not graph_data.get("edges")):
        st.info("暂无图谱数据，请先处理文档构建知识图谱。")
        return

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    st.info(f"📊 显示节点: {len(nodes)} 个, 关系边: {len(edges)} 条")

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

    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        st.components.v1.html(html_content, height=720, scrolling=False)
    finally:
        try:
            os.unlink(html_path)
        except:
            pass


def page_search():
    st.title("🔍 实体搜索与路径查询")
    st.markdown("---")

    tab1, tab2 = st.tabs(["🔎 实体搜索", "🛤️ 路径查询"])

    with tab1:
        search_name = st.text_input("输入实体名称搜索", placeholder="例如：阿里巴巴")
        if search_name:
            results = client.search_entities(search_name, limit=50)
            if not results:
                st.info("未找到匹配的实体")
            else:
                st.success(f"找到 {len(results)} 个匹配实体")
                for node in results:
                    with st.expander(f"📌 {node.get('canonical_name', '')}  ({node.get('type', 'UNKNOWN')})"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write(f"**规范名称:** {node.get('canonical_name', '')}")
                            st.write(f"**类型:** {node.get('type', '')}")
                            st.write(f"**出现频次:** {node.get('frequency', 0)}")
                            st.write(f"**首次来源:** {node.get('first_source', '')}")
                        with col_b:
                            aliases = node.get('aliases', [])
                            if aliases:
                                st.write("**别名:**")
                                for a in aliases:
                                    st.write(f"  - {a}")

                        if st.button(f"查看详情: {node.get('canonical_name', '')}", key=f"detail_{node.get('canonical_name', '')}"):
                            details = client.get_entity_details(node["canonical_name"])
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
                paths = client.find_path(entity1, entity2, max_hops=max_hops)
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

    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 刷新任务列表"):
            st.rerun()

    tasks = client.list_tasks(limit=100)

    if not tasks:
        st.info("暂无任务记录，请先提交文档处理任务")
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
                st.write(f"**任务ID:** {task_id}")
                st.write(f"**状态:** {status}")
                st.write(f"**创建时间:** {task.get('created_at', '')}")
            with col2:
                st.write(f"**文档总数:** {task.get('total_documents', 0)}")
                st.write(f"**已处理:** {task.get('processed_documents', 0)}")
                st.write(f"**抽取实体:** {task.get('entities_extracted', 0)}")
            with col3:
                st.write(f"**抽取关系:** {task.get('relations_extracted', 0)}")
                if task.get("failed_step"):
                    st.write(f"**失败步骤:** :red[{task.get('failed_step', '')}]")
                if task.get("error_message"):
                    st.write(f"**错误信息:** :red[{task.get('error_message', '')}]")

            if status == "失败":
                if st.button(f"🔄 重试任务 {task_id}", key=f"retry_{task_id}"):
                    result = client.retry_task(task_id)
                    if result:
                        st.success("任务已重新提交！")
                        st.rerun()
                    else:
                        st.error("重试失败")


def page_input():
    st.title("📝 文档输入与处理")
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["✏️ 直接输入文本", "🌐 URL列表", "📚 自定义实体词典"])

    with tab1:
        input_text = st.text_area(
            "输入待处理的文本内容",
            height=250,
            placeholder="请输入要抽取实体和关系的文本内容...\n\n例如：\n阿里巴巴集团由马云于1999年在杭州创立，是中国最大的电子商务公司。阿里巴巴与腾讯在多个领域存在竞争关系，同时与百度也有合作项目。",
        )

        if st.button("🚀 提交处理", key="submit_text"):
            if not input_text.strip():
                st.warning("请输入文本内容")
            else:
                with st.spinner("正在提交任务..."):
                    result = client.create_task_text(input_text)
                    if result:
                        st.success(f"✅ 任务已提交！任务ID: {result.get('task_id', '')}")
                        st.info(f"当前状态: {result.get('status', '')}")
                        st.page_link(f"任务管理页面可查看进度")
                    else:
                        st.error("❌ 任务提交失败，请检查API服务")

    with tab2:
        urls_text = st.text_area(
            "输入URL列表（每行一个）",
            height=200,
            placeholder="https://example.com/article1\nhttps://example.com/article2\nhttps://example.com/news",
        )

        if st.button("🚀 抓取并处理", key="submit_urls"):
            urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
            if not urls:
                st.warning("请输入至少一个URL")
            else:
                with st.spinner(f"正在提交 {len(urls)} 个URL处理任务..."):
                    result = client.create_task_urls(urls)
                    if result:
                        st.success(f"✅ 任务已提交！任务ID: {result.get('task_id', '')}")
                        st.info(f"URL数量: {len(urls)}, 当前状态: {result.get('status', '')}")
                    else:
                        st.error("❌ 任务提交失败")

    with tab3:
        st.markdown("""
        上传自定义实体词典可以增强实体识别效果。
        **CSV格式:** `实体名,实体类型`
        - 实体类型: `PER`(人名), `ORG`(组织机构), `LOC`(地点), `TIME`(时间), `EVENT`(事件), `WORK`(作品), `TECH`(技术术语)

        示例:
        ```
        阿里巴巴,ORG
        马云,PER
        杭州,LOC
        人工智能,TECH
        ```
        """)
        dict_file = st.file_uploader("上传实体词典CSV文件", type=["csv"])
        if dict_file is not None:
            content = dict_file.getvalue().decode("utf-8")
            st.text_area("词典内容预览", content, height=150)
            st.success(f"✅ 词典已加载，包含 {len([l for l in content.splitlines() if l.strip()])} 条记录")

    st.markdown("---")
    st.subheader("💡 使用示例")
    st.code(
        """# 示例文本
阿里巴巴集团由马云于1999年在杭州创立，是中国最大的电子商务公司。
马云毕业于杭州师范学院，曾任阿里巴巴的首席执行官。
阿里巴巴与腾讯在多个领域存在竞争关系，同时与百度在云计算领域有合作项目。
2023年，阿里巴巴在云栖大会上发布了新一代人工智能模型通义千问。
"""
    )


def page_quality():
    st.title("✅ 质量评估")
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📊 精确率趋势", "🎯 采样评估", "📜 评估历史"])

    with tab1:
        trend = client.get_quality_trend(limit=10)
        if not trend or not trend.get("precisions"):
            st.info("暂无评估历史数据，请先进行质量评估")
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
        if st.button("🎲 生成100条随机三元组样本"):
            with st.spinner("正在生成样本..."):
                sample = client.generate_quality_sample(100)
                st.session_state["quality_sample"] = sample
                st.session_state["quality_labels"] = {}

        if "quality_sample" not in st.session_state or not st.session_state["quality_sample"]:
            st.info("点击上方按钮生成评估样本")
        else:
            sample = st.session_state["quality_sample"]
            labels = st.session_state.get("quality_labels", {})
            st.success(f"已生成 {len(sample)} 条样本，请逐条标注正确/错误")

            labeled_count = len(labels)
            st.progress(labeled_count / len(sample), text=f"标注进度: {labeled_count}/{len(sample)}")

            batch_size = 10
            page_num = st.number_input(
                "页码",
                min_value=1,
                max_value=(len(sample) + batch_size - 1) // batch_size,
                value=1,
            )
            start = (page_num - 1) * batch_size
            end = min(start + batch_size, len(sample))

            st.markdown(f"**显示第 {start + 1} - {end} 条**")

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
                        st.caption(f"来源句子: {sentences[0][:200]}{'...' if len(sentences[0]) > 200 else ''}")

                with col_label:
                    current_label = labels.get(tid)
                    choice = st.radio(
                        "标注",
                        options=["正确", "错误"],
                        index=0 if current_label is True else (1 if current_label is False else 0),
                        key=f"radio_{tid}",
                        horizontal=True,
                    )
                    labels[tid] = (choice == "正确")

            st.session_state["quality_labels"] = labels

            col_submit, col_clear = st.columns(2)
            with col_submit:
                if st.button("✅ 提交评估结果", type="primary", disabled=(labeled_count == 0)):
                    with st.spinner("正在提交..."):
                        result = client.submit_evaluation(labels)
                        if result:
                            st.success(f"评估完成！精确率: {result.get('precision', 0) * 100:.1f}% ({result.get('correct', 0)}/{result.get('total', 0)})")
                            st.session_state.pop("quality_sample", None)
                            st.session_state.pop("quality_labels", None)
            with col_clear:
                if st.button("🔄 重新生成样本"):
                    st.session_state.pop("quality_sample", None)
                    st.session_state.pop("quality_labels", None)
                    st.rerun()

    with tab3:
        history = client.get_quality_history(limit=20)
        if not history:
            st.info("暂无评估历史")
        else:
            df_history = pd.DataFrame(history)
            df_history["precision"] = df_history["precision"].apply(lambda x: f"{x * 100:.1f}%")
            df_history.columns = ["精确率", "样本总数", "正确数", "评估时间"]
            df_history = df_history[["评估时间", "精确率", "正确数", "样本总数"]]
            st.dataframe(df_history, use_container_width=True, hide_index=True)


def main():
    page = render_sidebar()

    if page.startswith("📊"):
        page_overview()
    elif page.startswith("🕸️"):
        page_graph_viz()
    elif page.startswith("🔍"):
        page_search()
    elif page.startswith("📋"):
        page_tasks()
    elif page.startswith("📝"):
        page_input()
    elif page.startswith("✅"):
        page_quality()


if __name__ == "__main__":
    main()
