import os
import sqlite3

import matplotlib.pyplot as plt
import networkx as nx
import streamlit as st

st.set_page_config(page_title="Knowledge Graph", layout="wide")
st.title("Семантический Граф Знаний R&D")


@st.cache_resource
def generate_cached_graph_figure():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../.."))
    db_path = os.path.join(project_root, "knowledge_base.db")

    if not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT material, process, source_file FROM facts LIMIT 25;")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    G = nx.Graph()
    for material, process, source in rows:
        if material and process:
            mat_node = f"Материал:\n{material[:20]}..." if len(material) > 20 else f"Материал:\n{material}"
            proc_node = f"Процесс:\n{process[:20]}..." if len(process) > 20 else f"Процесс:\n{process}"
            src_node = f"Документ:\n{source[:15]}..." if len(source) > 15 else f"Документ:\n{source}"

            G.add_node(mat_node, color="#1f77b4", type="Material")
            G.add_node(proc_node, color="#ff7f0e", type="Process")
            G.add_node(src_node, color="#2ca02c", type="Document")

            G.add_edge(mat_node, proc_node)
            G.add_edge(proc_node, src_node)

    fig, ax = plt.subplots(figsize=(14, 9), facecolor="#0e1117")
    ax.set_facecolor("#0e1117")

    pos = nx.kamada_kawai_layout(G)
    node_colors = [G.nodes[node]["color"] for node in G.nodes()]

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=1200, alpha=0.9, ax=ax)
    nx.draw_networkx_edges(G, pos, width=1.5, edge_color="#4a4a4a", alpha=0.6, ax=ax)

    labels_pos = {k: [v[0], v[1] - 0.05] for k, v in pos.items()}
    nx.draw_networkx_labels(G, labels_pos, font_size=8, font_color="#ffffff", font_family="sans-serif", ax=ax)
    ax.axis("off")
    return fig


fig = generate_cached_graph_figure()

if fig is None:
    st.warning("База данных пуста или еще не заполнена.")
else:
    st.pyplot(fig)
    st.markdown(
        """
    **Легенда графа:**
    *   🔵 **Синие узлы** — Материалы и вещества
    *   🟠 **Оранжевые узлы** — Технологические процессы / Эксперименты
    *   🟢 **Зеленые узлы** — Исходные документы (файлы верификации)
    """
    )
