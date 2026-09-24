"""Visual tokens for the official public engineering workbench."""

PUBLIC_CSS = """
<style>
:root {
  --paper:#ffffff; --canvas:#f3f7fb; --ink:#172b3f; --body:#35485b;
  --muted:#60758a; --line:#d8e2ec; --line-strong:#b9c8d8;
  --blue:#2868a8; --blue-dark:#1c527f; --blue-soft:#edf5fc; --amber:#855500;
  --amber-soft:#fff5df; --red:#a63f42; --green:#176a49;
  --radius-card:14px; --radius-control:10px;
}
.stApp {background:var(--canvas);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;}
[data-testid="stHeader"] {background:var(--canvas);}
#MainMenu,footer,[data-testid="stToolbar"] {visibility:hidden;}
.block-container {max-width:1240px;padding:1.5rem 2rem 3.5rem;}
[data-testid="stSidebar"] {background:#f8fbfe;border-right:1px solid var(--line);}
[data-testid="stSidebar"] [data-testid="stButton"] button {
  min-height:2.15rem;padding:.35rem .72rem;text-align:left;justify-content:flex-start;
  border-radius:var(--radius-control);border:1px solid transparent;background:transparent;color:var(--body);
  font-size:.89rem;font-weight:560;box-shadow:none;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {background:#edf3f8;color:var(--ink);}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
  background:var(--blue-soft);color:var(--blue-dark);border-color:#c9def1;font-weight:700;
}
h1 {font-size:2.05rem!important;line-height:1.22!important;letter-spacing:-.035em!important;
  color:var(--ink)!important;margin-bottom:.3rem!important;font-weight:760!important;}
h2 {font-size:1.38rem!important;letter-spacing:-.025em!important;color:var(--ink)!important;}
h3 {font-size:1.06rem!important;color:var(--ink)!important;}
p,li {line-height:1.58;color:var(--body);}
[data-testid="stCaptionContainer"] {color:var(--muted)!important;}
[data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--paper);border:1px solid var(--line);border-radius:var(--radius-card);box-shadow:none;
}
[data-testid="stExpander"] {background:var(--paper);border:1px solid var(--line);border-radius:var(--radius-control);}
[data-testid="stAlert"] {border-radius:var(--radius-control);border-width:1px;}
[data-testid="stButton"] button {min-height:2.55rem;border-radius:var(--radius-control);font-weight:640;box-shadow:none;}
[data-testid="stButton"] button p {color:inherit!important;}
[data-testid="stButton"] button[kind="primary"] {background:var(--blue);border-color:var(--blue);color:#fff;}
[data-testid="stButton"] button[kind="primary"]:hover {background:var(--blue-dark);border-color:var(--blue-dark);}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input,[data-baseweb="select"]>div {
  background:#fff!important;border:1px solid var(--line-strong)!important;border-radius:var(--radius-control)!important;
}
button:focus-visible,a:focus-visible,textarea:focus-visible,input:focus-visible {
  outline:2px solid var(--blue)!important;outline-offset:2px!important;
}
.masthead {border-top:3px solid var(--ink);padding-top:.7rem;margin-bottom:.4rem;}
.masthead .kicker {color:var(--blue);font-size:.83rem;font-weight:720;}
.public-note {color:var(--muted);font-size:.83rem;line-height:1.5;}
.page-nav-row {display:flex;align-items:center;min-height:2.7rem;margin:.1rem 0 .65rem;}
.breadcrumbs {color:var(--muted);font-size:.88rem;line-height:2.5rem;}
.breadcrumbs strong {color:var(--ink);font-weight:680;}
.page-nav-row [data-testid="stButton"] button {min-height:2.35rem;padding:.25rem .75rem;}
.status-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:1.35rem 0;
  border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line-strong);background:#fff;}
.status-cell {padding:.7rem .85rem;border-right:1px solid var(--line);}
.status-cell:last-child {border-right:0;}
.status-label {display:block;font-size:.74rem;color:var(--muted);margin-bottom:.22rem;}
.status-value {display:block;font-size:.86rem;font-weight:700;color:var(--ink);line-height:1.36;}
.module-label {display:inline-block;font-size:.78rem;font-weight:680;color:var(--blue-dark);margin-bottom:.55rem;}
.st-key-public_rag_module,.st-key-public_agent_module {min-height:100%;}
.st-key-public_rag_module [data-testid="stVerticalBlockBorderWrapper"],
.st-key-public_agent_module [data-testid="stVerticalBlockBorderWrapper"] {
  height:100%;background:var(--paper);border-color:var(--line);border-radius:var(--radius-card);
}
.module-detail {font-size:.88rem;line-height:1.5;min-height:2.7rem;}
.flow-track,.review-steps {display:flex;gap:0;align-items:stretch;flex-wrap:wrap;margin:1rem 0;}
.flow-track span,.review-steps span {
  padding:.55rem .75rem;border:1px solid var(--line);margin-right:-1px;background:#fff;
  color:var(--body);font-size:.81rem;font-weight:600;
}
.flow-track span:first-child,.review-steps span:first-child {border-radius:var(--radius-control) 0 0 var(--radius-control);}
.flow-track span:last-child,.review-steps span:last-child {border-radius:0 var(--radius-control) var(--radius-control) 0;}
.review-steps .done {background:#eaf4ef;color:var(--green);}
.review-steps .current {background:var(--blue-soft);color:var(--blue-dark);border-color:#c9def1;}
.section-rule {border-top:1px solid var(--line-strong);padding-top:.72rem;margin:1.25rem 0 .6rem;
  color:var(--blue-dark);font-size:.77rem;font-weight:740;}
.context-strip {display:flex;gap:.5rem;flex-wrap:wrap;margin:.55rem 0 1.05rem;}
.context-strip span {background:#fff;border:1px solid var(--line);border-radius:8px;padding:.34rem .6rem;
  color:var(--body);font-size:.8rem;}
.context-strip strong {color:var(--ink);}
.notice-title {font-weight:750;color:var(--amber);font-size:.93rem;}
.relation-confirmed {color:var(--green);font-weight:730;}
.relation-suggested {color:var(--amber);font-weight:730;}
.mono {font-family:Consolas,"SFMono-Regular",monospace;font-size:.8rem;}
.sidebar-mark {font-weight:770;font-size:1.02rem;color:var(--ink);border-bottom:2px solid var(--blue);
  padding-bottom:.65rem;margin-bottom:.55rem;}
.nav-heading {font-size:.72rem;font-weight:740;color:var(--muted);padding:.7rem .3rem .2rem;
  border-top:1px solid var(--line);margin-top:.45rem;}
.result-answer {padding:.95rem 1.1rem;background:#fff;border:1px solid var(--line);border-left:3px solid var(--blue);
  border-radius:var(--radius-card);}
.citation-index {color:var(--blue-dark);font-weight:720;}
@media (max-width:900px) {.status-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .status-cell:nth-child(2n) {border-right:0;}}
@media (max-width:760px) {.block-container {padding:1rem .85rem 2rem;}
  h1 {font-size:1.55rem!important;}.flow-track span,.review-steps span {flex:1 1 42%;margin-top:-1px;}
  .breadcrumbs {font-size:.82rem;}.page-nav-row [data-testid="stButton"] button {padding:.2rem .45rem;font-size:.82rem;}}
</style>
"""
