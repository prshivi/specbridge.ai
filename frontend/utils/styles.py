import streamlit as st


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');
        :root {
            --ink:#eef2ff; --muted:#94a3b8; --panel:#11182b;
            --line:rgba(148,163,184,.16); --violet:#8b5cf6;
            --blue:#3b82f6; --cyan:#06b6d4; --green:#34d399;
        }
        html, body, [class*="css"] {font-family:"Manrope",sans-serif;}
        .stApp {
            background:
              radial-gradient(circle at 8% 2%,rgba(124,58,237,.17),transparent 30rem),
              radial-gradient(circle at 96% 8%,rgba(6,182,212,.12),transparent 28rem),
              #070b14;
        }
        [data-testid="stHeader"] {background:transparent;}
        [data-testid="stSidebar"] {
            background:linear-gradient(180deg,#10162a,#0a0f1d);
            border-right:1px solid var(--line);
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            padding:.45rem .5rem;border-radius:10px;
        }
        .block-container {max-width:1500px;padding-top:1.35rem;padding-bottom:4rem;}
        .product-hero {
            position:relative;overflow:hidden;padding:2rem 2.2rem;margin-bottom:1.4rem;
            border:1px solid rgba(255,255,255,.14);border-radius:24px;
            background:linear-gradient(120deg,#5b21b6 0%,#2563eb 52%,#0891b2 100%);
            box-shadow:0 28px 80px rgba(37,99,235,.20);
        }
        .product-hero:after {
            content:"";position:absolute;width:310px;height:310px;right:-80px;top:-145px;
            border-radius:50%;background:rgba(255,255,255,.11);
        }
        .product-hero h1 {margin:.45rem 0;font-size:clamp(2.2rem,4vw,3.5rem);color:white;}
        .product-hero p {max-width:780px;color:rgba(255,255,255,.82);font-size:1.02rem;}
        .hero-kicker {font-size:.74rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;}
        .page-title {font-size:1.8rem;font-weight:800;color:#f8fafc;margin:.2rem 0;}
        .page-copy {color:#94a3b8;margin-bottom:1.2rem;}
        .metric-tile,.content-card {
            height:100%;padding:1.05rem 1.1rem;border:1px solid var(--line);
            border-radius:17px;background:linear-gradient(145deg,rgba(20,28,49,.96),rgba(12,18,33,.95));
            box-shadow:0 12px 34px rgba(0,0,0,.16);
        }
        .metric-tile {transition:.16s ease;}
        .metric-tile:hover {transform:translateY(-3px);border-color:rgba(99,102,241,.55);}
        .metric-icon {font-size:1.25rem;}
        .metric-number {font-size:2rem;font-weight:800;color:#f8fafc;margin:.15rem 0;}
        .metric-name {font-size:.78rem;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:.05em;}
        .metric-note {font-size:.72rem;color:#64748b;margin-top:.3rem;}
        .severity {
            display:inline-flex;padding:.25rem .58rem;border-radius:999px;
            font-size:.7rem;font-weight:800;text-transform:uppercase;letter-spacing:.04em;
        }
        .critical {color:#fecdd3;background:rgba(244,63,94,.18);}
        .high {color:#fed7aa;background:rgba(249,115,22,.18);}
        .medium {color:#fef08a;background:rgba(234,179,8,.17);}
        .low {color:#bbf7d0;background:rgba(34,197,94,.16);}
        .trace-chain {display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin:.5rem 0;}
        .trace-node {padding:.38rem .62rem;border:1px solid var(--line);border-radius:9px;background:#111a30;color:#dbeafe;font-size:.76rem;}
        .trace-arrow {color:#64748b;}
        .document-chip {padding:.7rem .8rem;border:1px solid rgba(52,211,153,.24);border-radius:12px;background:rgba(52,211,153,.08);}
        .empty-state {padding:2.2rem;text-align:center;border:1px dashed rgba(148,163,184,.28);border-radius:18px;color:#94a3b8;}
        div.stButton > button {
            min-height:2.7rem;border:0;border-radius:11px;
            background:linear-gradient(100deg,#7c3aed,#2563eb,#0891b2);
            color:white;font-weight:750;
        }
        div.stButton > button:hover {color:white;border:0;filter:brightness(1.12);}
        div[data-testid="stExpander"] {border:1px solid var(--line);border-radius:14px;background:rgba(15,23,42,.42);}
        code {font-size:.82rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
