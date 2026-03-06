import streamlit as st
import pandas as pd
import json
import re
import networkx as nx
from pyvis.network import Network
import streamlit.components.v1 as components
import tempfile

# ==========================================
# 1. PAGE CONFIG
# ==========================================
st.set_page_config(page_title="VTuber Network Explorer", layout="wide")
st.title("🔭 VTuber Network Explorer")

# The name of your data file hosted on GitHub
DATA_FILE = "vtuber_data.jsonl"
SELF_REFS = ['herself', 'himself', 'themself', 'themselves', 'self', 'self-made', 'self designed', 'self rigged', 'theirself', 'Theirself', 'self-designed', 'self-rigged', "self made", "self drawn", "self-drawn"]

# ==========================================
# 2. CACHED DATA LOADING & SANITIZATION
# ==========================================
@st.cache_data
def load_and_clean_data(filepath):
    data = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    continue
    except FileNotFoundError:
        return None

    df = pd.json_normalize(data)
    name_map = {}

    def get_normalized_name(raw_name):
        low = str(raw_name).strip().lower()
        if not low: return None
        if low not in name_map:
            name_map[low] = raw_name.strip()
        return name_map[low]

    def extract_creators_strict(text, vtuber_name):
        if pd.isna(text) or not str(text).strip():
            return []
        
        # Initial cleaning of formatting marks
        clean_text = str(text).replace("'''", "").replace("```", "").replace("\n", " ")
        
        # Split by comma first to handle lists of creators
        chunks = clean_text.split(',')
        extracted_names = set()

        for chunk in chunks:
            # 1. RECURSIVE COLON PROCESSING
            # Keep taking the right side of the colon until none remain
            while ':' in chunk:
                parts = chunk.split(':', 1)
                chunk = parts[1] if len(parts) > 1 else parts[0]
            
            # 2. PARENTHESES REMOVAL
            # Remove everything inside () including the parentheses themselves
            chunk = re.sub(r'\(.*?\)', '', chunk).strip()

            # 3. SUB-SPLITTING ('and', '&')
            # Handle cases like "ArtistA & ArtistB" or "ArtistA and ArtistB"
            sub_chunks = re.split(r'\s+and\s+|&', chunk, flags=re.IGNORECASE)
            
            for name in sub_chunks:
                name = name.strip()
                if not name:
                    continue

                # 4. SELF-REFERENCE CHECK
                if name.lower() in SELF_REFS or any((ref in name.lower() and name.lower() != "self") for ref in SELF_REFS):
                    name = vtuber_name

                # 5. Account for "By" like "Designed by KOSMiYU"
                if "by" in name.lower():
                    name = name.split("by")[-1].strip()

                # 6. Account for starting char of "*" or "* "
                if name.startswith("*") or name.startswith("* "):
                    name = name[1:].strip()


                # 7. Account for multiple " *"
                if " *" in name:
                    for name_part in name.split(" *"):
                        normed = get_normalized_name(name_part)
                        if normed:
                            extracted_names.add(normed)
                else:

                    # remove faulty "(text"
                    if "(" in name:
                        name = name.split("(")[0].strip()

                    if name.startswith("@"):
                        name = name[1:].strip()

                    normed = get_normalized_name(name)
                    if normed:
                        extracted_names.add(normed)

        return list(extracted_names)

    # Apply the streamlined logic
    df['all_creators'] = df.apply(
        lambda row: list(set(
            extract_creators_strict(row.get('illustrator', ''), row.get('name', 'Unknown')) +
            extract_creators_strict(row.get('rigger', ''), row.get('name', 'Unknown'))
        )), axis=1
    )
    
    return df

# ==========================================
# 3. CACHED GRAPH GENERATION
# ==========================================
@st.cache_data
def build_network(_df, min_conn, render_img):
    creator_counts = {}
    for creators in _df['all_creators']:
        for c in creators:
            creator_counts[c] = creator_counts.get(c, 0) + 1
    
    valid_creators = {c for c, count in creator_counts.items() if count >= min_conn}
    
    G = nx.Graph()
    vtuber_nodes = set()
    creator_nodes = set()

    for _, row in _df.iterrows():
        v_name = row.get('name', 'Unknown')
        img = row.get('img', None)
        creators = [c for c in row['all_creators'] if c in valid_creators]

        if creators:
            # Add VTuber Node
            if render_img and pd.notna(img) and str(img).startswith("http"):
                G.add_node(v_name, shape='image', image=img, size=20, title=f"VTuber: {v_name}", label=v_name, group="VTuber")
            else:
                G.add_node(v_name, color='#1DA1F2', size=15, title=f"VTuber: {v_name}", label=v_name, group="VTuber")
            vtuber_nodes.add(v_name)
            
            # Add Creator Nodes & Edges
            for c in creators:
                if c not in creator_nodes:
                    G.add_node(c, color='#FF5733', size=25, shape='dot', title=f"Creator: {c}", label=c, group="Creator")
                    creator_nodes.add(c)
                G.add_edge(v_name, c)
                
    return G, creator_counts


# ==========================================
# 4. SIDEBAR CONTROLS
# ==========================================
st.sidebar.header("📁 Graph Filtering")
st.sidebar.markdown("Adjust the settings below to filter the network.")
min_connections = st.sidebar.slider("Minimum VTubers per Creator", 1, 10, 2,
                                    help="Hides creators who only have one 'child'.")

render_images = st.sidebar.checkbox("Render VTuber Images", value=False, 
                                    help="Toggle on to display images for VTubers. May impact performance slightly.")

st.sidebar.markdown("---")
st.sidebar.markdown('Created by <a href="[https://x.com/TheDarkEnjoyer](https://x.com/TheDarkEnjoyer)" target="_blank">TheDarkEnjoyer</a>', unsafe_allow_html=True)

# ==========================================
# 5. MAIN APPLICATION LOGIC
# ==========================================
with st.spinner("Loading VTuber Database..."):
    df = load_and_clean_data(DATA_FILE)

if df is None:
    st.error(f"❌ Could not find `{DATA_FILE}`. Please make sure the file is uploaded to your repository!")
else:
    # --- GRAPH BUILDING ---
    G, creator_counts = build_network(df, min_connections, render_images)

    # ==========================================
    # 6. TABS, SEARCH, AND RENDERING
    # ==========================================
    tab1, tab2 = st.tabs(["🕸️ Network Graph", "🏆 Creator Leaderboard"])

    with tab1:
        # --- SEARCH BAR ---
        all_nodes = sorted(list(G.nodes()))
        search_query = st.selectbox("🔍 Search & Focus on a specific VTuber or Creator:", ["-- View All --"] + all_nodes)
        
        # Filter Graph if Search is used
        if search_query != "-- View All --":
            G_render = nx.ego_graph(G, search_query, radius=1)
            st.info(f"Viewing isolated network for: **{search_query}**")
        else:
            G_render = G

        # --- LIVE METRICS ---
        col1, col2 = st.columns(2)
        v_count = len([n for n, attr in G_render.nodes(data=True) if attr.get('group') == 'VTuber'])
        c_count = len([n for n, attr in G_render.nodes(data=True) if attr.get('group') == 'Creator'])
        
        col1.metric("VTubers in View", v_count)
        col2.metric("Creators in View", c_count)

        # --- PYVIS RENDERING ---
        if len(G_render.nodes) > 0:
            net = Network(height='800px', width='100%', bgcolor='#0E1117', font_color='white')
            net.from_nx(G_render)
            
            # Optimized JSON (Added missing commas and streamlined stabilization)
            net.set_options("""
            {
              "configure": {
                "enabled": true,
                "filter": ["physics"],
                "showButton": true
              },
              "interaction": {
                "navigationButtons": true,
                "hover": true,
                "selectConnectedEdges": true,
                "multiselect": true,
                "tooltipDelay": 200
              },
              "nodes": {
                "font": { "size": 14, "color": "#ffffff" },
                "borderWidth": 2
              },
              "physics": {
                "barnesHut": { 
                    "gravitationalConstant": -15000, 
                    "centralGravity": 0.3, 
                    "springLength": 150,
                    "springConstant": 0.05
                },
                "stabilization": { "enabled": true, "iterations": 600 },
                "minVelocity": 0.75,
                "solver": "barnesHut"
              }
            }
            """)

            with tempfile.NamedTemporaryFile(delete=False, suffix='.html') as tmp:
                net.save_graph(tmp.name)
                with open(tmp.name, 'r', encoding='utf-8') as f:
                    components.html(f.read(), height=1000, scrolling=True)
        else:
            st.warning("No nodes match the current filter criteria.")

    with tab2:
        st.subheader("Creator Productivity Leaderboard")
        st.markdown("Shows every parsed creator and the total number of VTubers they are credited with in this dataset.")

        df_leaderboard = pd.DataFrame(list(creator_counts.items()), columns=["Creator Name", "VTuber Count"])
        df_leaderboard = df_leaderboard.sort_values(by="VTuber Count", ascending=False).reset_index(drop=True)
        df_leaderboard.index = df_leaderboard.index + 1 

        st.dataframe(df_leaderboard, width='stretch')