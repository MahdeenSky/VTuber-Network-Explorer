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
DATA_FILE = "vtuber_data.jsonl" # Note: Update this if reading directly from your new .json map format!

# Sets for aggressive filtering
SELF_REFS = {'herself', 'himself', 'themself', 'themselves', 'self', 'self-made', 'self designed', 'self rigged', 'theirself', 'self-designed', 'self-rigged', 'self made', 'her own', 'their own', 'his own', 'herself!'}
INVALID_CREATORS = {'unknown', '?', '??', '???', 'tba', 'went to get milk', 'left to go get milk', 'none', 'n/a', 'rigger', 'model', 'illustrator', 'art', 'rigging', 'live2d', '3d', '2d'}

# ==========================================
# 2. CACHED DATA LOADING & SANITIZATION
# ==========================================
@st.cache_data
def load_and_clean_data(filepath):
    data = []
    try:
        # Assuming we are now reading the raw JSON dictionary format you provided
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_dict = json.load(f)
            # Convert dictionary format to a list of dicts for pandas
            for vtuber, creators in raw_dict.items():
                data.append({"name": vtuber, "raw_creators": creators})
    except FileNotFoundError:
        return None

    df = pd.DataFrame(data)
    name_map = {}

    def get_normalized_name(raw_name):
        low = str(raw_name).strip().lower()
        if not low: return None
        if low not in name_map:
            name_map[low] = raw_name.strip()
        return name_map[low]

    def clean_creator_string(text):
        # 1. Remove URLs (e.g., https://x.com/... or //x.com/...)
        text = re.sub(r'(?:https?:)?//\S+', '', text)
        
        # 2. Remove role labels/prefixes (e.g., "Live2D:", "Rig:", "3D Model Artist:")
        role_patterns = [
            r'Live2D(?: Max| Model)?\s*[:\-]?\s*',
            r'(?:2D|3D)\s*(?:Model(?:ling|er)?\s*|Art(?:ist)?\s*)?[:\-]?\s*',
            r'Rig(?:ging|ger)?\s*[:\-)]?\s*',
            r'Ill?ustrat(?:ion|or)\s*[:\-]?\s*',
            r'Model(?:ling|er)?\s*[:\-]?\s*',
            r'Art(?:ist)?\s*[:\-]?\s*',
            r'Design(?:er)?\s*[:\-]?\s*',
            r'Current design\s*[:\-]?\s*'
        ]
        for pattern in role_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # 3. Remove unwanted brackets/parentheses and their contents (e.g., [clothes], (Base), (2.0))
        # This keeps Japanese alternate names like "(森倉円)" intact but targets structural notes
        meta_patterns = [
            r'\([^)]*(?:base|redesign|original|current|previous|main|outfit|draft|nsfw|supervisor|rigging|version|model|art|1\.0|2\.0|3\.0|\#\d+)[^)]*\)',
            r'\[(?:face|clothes|expressions?)\]',
            r'expressions?\]' # Catches broken leftover brackets like "expressions]"
        ]
        for pattern in meta_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # 4. Strip stray artifacts at the end of strings
        text = re.sub(r'\(\s*Art$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'Rigging\)$', '', text, flags=re.IGNORECASE)

        return text.strip()

    def extract_creators_strict(creator_list, vtuber_name):
        if not isinstance(creator_list, list):
            creator_list = [creator_list]
            
        extracted_names = set()
        
        for text in creator_list:
            if pd.isna(text) or not str(text).strip():
                continue
            
            clean_text = str(text).replace("'''", "").replace("```", "").replace("\n", " ")
            clean_text = clean_creator_string(clean_text)
            
            # Split by commas, pluses, slashes, ampersands, and 'and' to separate combined creators
            chunks = re.split(r',|\+|\/|&|\s+and\s+', clean_text, flags=re.IGNORECASE)
            
            for name in chunks:
                # Remove leading/trailing garbage characters (*, @, -, _)
                name = re.sub(r'^[@*\-\s\'\"_]+|[@*\-\s\'\"_]+$', '', name)
                
                # If there's still a colon acting as a separator, take the right side
                if ':' in name:
                    name = name.split(':', 1)[-1]
                
                name = name.strip()
                
                # Check for joke entries or empty strings
                if not name or len(name) < 2 or name.lower() in INVALID_CREATORS:
                    continue
                    
                # Convert self-references into the VTuber's own name
                lower_name = name.lower()
                if lower_name in SELF_REFS or "herself" in lower_name or "themselves" in lower_name or "himself" in lower_name:
                    name = vtuber_name
                    
                normed = get_normalized_name(name)
                if normed: 
                    extracted_names.add(normed)
                    
        return list(extracted_names)

    # Apply strict logic based on the raw JSON list
    df['all_creators'] = df.apply(
        lambda row: extract_creators_strict(row.get('raw_creators', []), row.get('name', 'Unknown')), axis=1
    )
    
    return df

# ==========================================
# 3. SIDEBAR CONTROLS
# ==========================================
st.sidebar.header("📁 Graph Filtering")
st.sidebar.markdown("Adjust the settings below to filter the network.")
min_connections = st.sidebar.slider("Minimum VTubers per Creator", 1, 10, 2,
                                    help="Hides creators who only have one 'child'.")

st.sidebar.markdown("---")
st.sidebar.markdown('Created by <a href="[https://x.com/TheDarkEnjoyer](https://x.com/TheDarkEnjoyer)" target="_blank">TheDarkEnjoyer</a>', unsafe_allow_html=True)

# ==========================================
# 4. MAIN APPLICATION LOGIC
# ==========================================
with st.spinner("Loading and Sanitizing VTuber Database..."):
    df = load_and_clean_data(DATA_FILE)

if df is None:
    st.error(f"❌ Could not find `{DATA_FILE}`. Please make sure the file is uploaded to your repository!")
else:
    # --- GRAPH BUILDING ---
    creator_counts = {}
    for creators in df['all_creators']:
        for c in creators:
            creator_counts[c] = creator_counts.get(c, 0) + 1
    
    valid_creators = {c for c, count in creator_counts.items() if count >= min_connections}
    
    G = nx.Graph()
    vtuber_nodes = set()
    creator_nodes = set()

    for _, row in df.iterrows():
        v_name = row.get('name', 'Unknown')
        creators = [c for c in row['all_creators'] if c in valid_creators]

        if creators:
            # Add VTuber Node
            G.add_node(v_name, color='#1DA1F2', size=15, title=f"VTuber: {v_name}", label=v_name, group="VTuber")
            vtuber_nodes.add(v_name)
            
            # Add Creator Nodes & Edges
            for c in creators:
                if c not in creator_nodes:
                    G.add_node(c, color='#FF5733', size=25, shape='dot', title=f"Creator: {c}", label=c, group="Creator")
                    creator_nodes.add(c)
                G.add_edge(v_name, c)

    # ==========================================
    # 5. TABS, SEARCH, AND RENDERING
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