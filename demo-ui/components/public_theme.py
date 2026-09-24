"""Visual tokens for the official public engineering workbench."""

PUBLIC_CSS = """
<style>
:root {
  --paper:#ffffff; --canvas:#f4f5f6; --ink:#171b20; --body:#303841;
  --muted:#52606d; --line:#cbd2d8; --line-strong:#687581;
  --blue:#294c67; --blue-soft:#eaf0f4; --amber:#9b6000;
  --amber-soft:#fff5df; --red:#a63f42; --green:#176a49;
}
.stApp {background:var(--canvas);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;}
[data-testid="stHeader"] {background:var(--canvas);}
#MainMenu,footer,[data-testid="stToolbar"] {visibility:hidden;}
.block-container {max-width:1240px;padding:1.5rem 2rem 3.5rem;}
[data-testid="stSidebar"] {background:var(--paper);border-right:1px solid var(--line-strong);}
[data-testid="stSidebar"] [data-testid="stButton"] button {
  min-height:2.15rem;padding:.35rem .72rem;text-align:left;justify-content:flex-start;
  border-radius:4px;border:1px solid transparent;background:transparent;color:var(--body);
  font-size:.89rem;font-weight:560;box-shadow:none;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {background:#edf1f4;color:var(--ink);}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
  background:var(--ink);color:#fff;border-color:var(--ink);font-weight:680;
}
h1 {font-size:2.05rem!important;line-height:1.22!important;letter-spacing:-.035em!important;
  color:var(--ink)!important;margin-bottom:.3rem!important;font-weight:760!important;}
h2 {font-size:1.38rem!important;letter-spacing:-.025em!important;color:var(--ink)!important;}
h3 {font-size:1.06rem!important;color:var(--ink)!important;}
p,li {line-height:1.58;color:var(--body);}
[data-testid="stCaptionContainer"] {color:var(--muted)!important;}
[data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--paper);border:1px solid var(--line);border-radius:5px;box-shadow:none;
}
[data-testid="stExpander"] {background:var(--paper);border:1px solid var(--line);border-radius:4px;}
[data-testid="stAlert"] {border-radius:4px;border-width:1px;}
[data-testid="stButton"] button {border-radius:4px;font-weight:640;box-shadow:none;}
[data-testid="stButton"] button p {color:inherit!important;}
[data-testid="stButton"] button[kind="primary"] {background:var(--ink);border-color:var(--ink);color:#fff;}
[data-testid="stButton"] button[kind="primary"]:hover {background:#354554;border-color:#354554;}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input,[data-baseweb="select"]>div {
  background:#fff!important;border:1px solid var(--line-strong)!important;border-radius:4px!important;
}
button:focus-visible,a:focus-visible,textarea:focus-visible,input:focus-visible {
  outline:2px solid var(--blue)!important;outline-offset:2px!important;
}
.masthead {border-top:3px solid var(--ink);padding-top:.7rem;margin-bottom:.4rem;}
.masthead .kicker {color:var(--blue);font-size:.83rem;font-weight:720;}
.public-note {color:var(--muted);font-size:.83rem;line-height:1.5;}
.status-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:1.35rem 0;
  border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line-strong);background:#fff;}
.status-cell {padding:.7rem .85rem;border-right:1px solid var(--line);}
.status-cell:last-child {border-right:0;}
.status-label {display:block;font-size:.74rem;color:var(--muted);margin-bottom:.22rem;}
.status-value {display:block;font-size:.86rem;font-weight:700;color:var(--ink);line-height:1.36;}
.module-label {display:inline-block;font-family:Consolas,"SFMono-Regular",monospace;
  font-size:.75rem;letter-spacing:.04em;color:var(--blue);margin-bottom:.55rem;}
[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-public_rag_module) {
  background:var(--ink)!important;border-color:var(--ink)!important;
}
.st-key-public_rag_module {background:var(--ink)!important;color:#fff;border-radius:4px;}
.st-key-public_rag_module h3,.st-key-public_rag_module p,
.st-key-public_rag_module [data-testid="stCaptionContainer"],
.st-key-public_rag_module .module-label {color:#fff!important;}
.st-key-public_rag_module [data-testid="stButton"] button {
  background:#fff;color:var(--ink);border-color:#fff;
}
.st-key-public_rag_module [data-testid="stButton"] button:hover {
  background:#e9eff3;color:var(--ink);
}
.st-key-public_agent_module [data-testid="stVerticalBlockBorderWrapper"] {border-color:var(--line-strong);}
.module-detail {font-size:.88rem;line-height:1.5;min-height:2.7rem;}
.flow-track,.review-steps {display:flex;gap:0;align-items:stretch;flex-wrap:wrap;margin:1rem 0;}
.flow-track span,.review-steps span {
  padding:.55rem .75rem;border:1px solid var(--line);margin-right:-1px;background:#fff;
  color:var(--body);font-size:.81rem;font-weight:600;
}
.flow-track span:first-child,.review-steps span:first-child {border-radius:4px 0 0 4px;}
.flow-track span:last-child,.review-steps span:last-child {border-radius:0 4px 4px 0;}
.review-steps .done {background:#eaf4ef;color:var(--green);}
.review-steps .current {background:var(--ink);color:#fff;border-color:var(--ink);}
.section-rule {border-top:1px solid var(--line-strong);padding-top:.72rem;margin:1.25rem 0 .6rem;
  color:var(--blue);font-size:.77rem;font-weight:740;}
.context-strip {display:flex;gap:.5rem;flex-wrap:wrap;margin:.55rem 0 1.05rem;}
.context-strip span {background:#fff;border:1px solid var(--line);padding:.34rem .6rem;
  color:var(--body);font-size:.8rem;}
.context-strip strong {color:var(--ink);}
.notice-title {font-weight:750;color:var(--amber);font-size:.93rem;}
.relation-confirmed {color:var(--green);font-weight:730;}
.relation-suggested {color:var(--amber);font-weight:730;}
.mono {font-family:Consolas,"SFMono-Regular",monospace;font-size:.8rem;}
.sidebar-mark {font-weight:770;font-size:1.02rem;color:var(--ink);border-bottom:2px solid var(--ink);
  padding-bottom:.65rem;margin-bottom:.55rem;}
.nav-heading {font-size:.72rem;font-weight:740;color:var(--muted);padding:.7rem .3rem .2rem;
  border-top:1px solid var(--line);margin-top:.45rem;}
@media (max-width:900px) {.status-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .status-cell:nth-child(2n) {border-right:0;}}
@media (max-width:760px) {.block-container {padding:1rem .85rem 2rem;}
  h1 {font-size:1.55rem!important;}.flow-track span,.review-steps span {flex:1 1 42%;margin-top:-1px;}}
</style>
"""
