"""Visual tokens for the official public engineering workbench."""

PUBLIC_CSS = """
<style>
:root {
  --paper:#ffffff; --canvas:#f4f5f6; --ink:#171b20; --body:#303841;
  --muted:#52606d; --line:#cbd2d8; --line-strong:#687581;
  --blue:#294c67; --amber:#9b6000;
  --amber-soft:#fff5df; --red:#a63f42; --green:#176a49;
}
.stApp {background:var(--canvas);color:var(--ink);font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;}
[data-testid="stHeader"] {background:var(--paper);}
#MainMenu,footer {visibility:hidden;}
[data-testid="stAppDeployButton"] {display:none;}
.block-container {background:var(--paper);max-width:none!important;width:100%!important;margin:0!important;box-sizing:border-box;
  min-height:100vh;padding:3rem 1.65rem 1.5rem;overflow:visible;}
[data-testid="stSidebar"] {width:clamp(240px,16vw,280px)!important;min-width:clamp(240px,16vw,280px)!important;
  max-width:280px!important;flex:0 0 clamp(240px,16vw,280px)!important;
  background:var(--paper);border-right:1px solid var(--line-strong);}
[data-testid="stSidebar"] [data-testid="stButton"] button {
  min-height:2.15rem;padding:.35rem .72rem;text-align:left;justify-content:flex-start;
  border-radius:4px;border:1px solid transparent;background:transparent;color:var(--body);
  font-size:1.06rem;font-weight:560;box-shadow:none;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {background:#edf1f4;color:var(--ink);}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
  background:var(--ink);color:#fff;border-color:var(--ink);font-weight:680;
}
h1 {font-size:2.4rem!important;line-height:1.22!important;letter-spacing:-.035em!important;
  color:var(--ink)!important;margin-bottom:.35rem!important;font-weight:760!important;}
h2 {font-size:1.65rem!important;letter-spacing:-.025em!important;color:var(--ink)!important;}
h3 {font-size:1.3rem!important;color:var(--ink)!important;}
p,li {font-size:1.14rem;line-height:1.62;color:var(--body);}
[data-testid="stCaptionContainer"] {color:var(--muted)!important;font-size:1rem;}
[data-testid="stVerticalBlockBorderWrapper"] {
  background:var(--paper);border:1px solid var(--line);border-radius:5px;box-shadow:none;
}
[data-testid="stExpander"] {background:var(--paper);border:1px solid var(--line);border-radius:4px;}
[data-testid="stAlert"] {
  background:var(--paper)!important;border:1px solid var(--line)!important;
  border-left:3px solid var(--line-strong)!important;border-radius:5px;box-shadow:none;
}
[data-testid="stAlert"] [data-baseweb="notification"],
[data-testid="stAlert"] [data-testid="stAlertContent"] {
  background:var(--paper)!important;color:var(--body)!important;border-radius:4px;
}
[data-testid="stAlert"] svg {color:var(--muted)!important;}
[data-testid="stButton"] button {min-height:2.8rem;border-radius:4px;font-size:1.12rem;font-weight:640;box-shadow:none;}
[data-testid="stButton"] button p {color:inherit!important;}
[data-testid="stButton"] button[kind="primary"] {background:var(--ink);border-color:var(--ink);color:#fff;}
[data-testid="stButton"] button[kind="primary"]:hover {background:#354554;border-color:#354554;}
[data-testid="stTextArea"] textarea,[data-testid="stTextInput"] input,[data-baseweb="select"]>div {
  background:#fff!important;border:1px solid var(--line-strong)!important;border-radius:4px!important;
  font-size:1.12rem!important;
}
button:focus-visible,a:focus-visible,textarea:focus-visible,input:focus-visible {
  outline:2px solid var(--blue)!important;outline-offset:2px!important;
}
.masthead {border-top:3px solid var(--ink);padding-top:.7rem;margin-bottom:.4rem;}
.masthead .kicker {color:var(--blue);font-size:.83rem;font-weight:720;}
.public-note {color:var(--muted);font-size:.98rem;line-height:1.55;}
.status-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:1.35rem 0;
  border-top:1px solid var(--line-strong);border-bottom:1px solid var(--line-strong);background:#fff;}
.status-cell {padding:.7rem .85rem;border-right:1px solid var(--line);}
.status-cell:last-child {border-right:0;}
.status-label {display:block;font-size:.9rem;color:var(--muted);margin-bottom:.22rem;}
.status-value {display:block;font-size:1rem;font-weight:700;color:var(--ink);line-height:1.36;}
.module-label {display:inline-block;font-family:Consolas,"SFMono-Regular",monospace;
  font-size:.96rem;letter-spacing:.035em;color:var(--blue);margin-bottom:.55rem;}
.st-key-public_rag_module,.st-key-public_agent_module {
  min-height:17.5rem;background:var(--paper)!important;color:var(--ink);
  border:1px solid var(--line-strong)!important;border-radius:5px!important;box-shadow:none!important;
}
.module-detail {font-size:.98rem;line-height:1.5;min-height:2.7rem;}
.flow-track,.review-steps {display:flex;gap:0;align-items:stretch;flex-wrap:wrap;margin:1rem 0;}
.flow-track span,.review-steps span {
  padding:.55rem .75rem;border:1px solid var(--line);margin-right:-1px;background:#fff;
  color:var(--body);font-size:.95rem;font-weight:600;
}
.flow-track span:first-child,.review-steps span:first-child {border-radius:4px 0 0 4px;}
.flow-track span:last-child,.review-steps span:last-child {border-radius:0 4px 4px 0;}
.review-steps .done {background:#eaf4ef;color:var(--green);}
.review-steps .current {background:var(--ink);color:#fff;border-color:var(--ink);}
.section-rule {border-top:1px solid var(--line-strong);padding-top:.72rem;margin:1.25rem 0 .6rem;
  color:var(--blue);font-size:.92rem;font-weight:740;}
.context-strip {display:flex;gap:.5rem;flex-wrap:wrap;margin:.55rem 0 1.05rem;}
.context-strip span {background:#fff;border:1px solid var(--line);padding:.34rem .6rem;
  color:var(--body);font-size:.95rem;}
.context-strip strong {color:var(--ink);}
.notice-title {font-weight:750;color:var(--amber);font-size:1rem;}
.relation-confirmed {color:var(--green);font-weight:730;}
.relation-suggested {color:var(--amber);font-weight:730;}
.mono {font-family:Consolas,"SFMono-Regular",monospace;font-size:.92rem;}
.sidebar-mark {font-weight:770;font-size:1.05rem;color:var(--ink);border-bottom:2px solid var(--ink);
  padding-bottom:.65rem;margin-bottom:.55rem;}
.nav-heading {font-size:.9rem;font-weight:740;color:var(--muted);padding:.7rem .3rem .2rem;
  border-top:1px solid var(--line);margin-top:.45rem;}
[class*="st-key-page_header_"] {overflow:visible;min-height:3rem;margin-bottom:.25rem;}
[class*="st-key-page_header_"] [data-testid="stHorizontalBlock"] {
  align-items:center;overflow:visible;gap:.35rem!important;width:max-content;max-width:100%;flex-wrap:wrap;
}
[class*="st-key-page_header_"] [data-testid="stColumn"] {
  flex:0 0 auto!important;width:auto!important;min-width:0!important;
}
[class*="st-key-page_header_"] [data-testid="stMarkdownContainer"] {overflow:visible;}
.breadcrumbs {font-size:1.05rem;line-height:1.45;color:var(--body);white-space:normal;overflow-wrap:anywhere;}
.breadcrumbs-current {min-height:2.35rem;display:flex;align-items:center;padding:.2rem .35rem;
  color:var(--ink);font-size:1.05rem;font-weight:740;line-height:1.35;overflow-wrap:anywhere;}
[class*="st-key-page_header_"] [class*="st-key-nav_back_"] button {
  width:auto!important;min-width:1.65rem!important;min-height:2.35rem!important;padding:0 .12rem!important;
  font-size:1.5rem!important;line-height:1!important;font-weight:700;
  background:transparent!important;color:var(--ink)!important;border:0!important;box-shadow:none!important;
}
[class*="st-key-page_header_"] [class*="st-key-nav_back_"] button:hover {
  background:transparent!important;color:var(--blue)!important;border:0!important;box-shadow:none!important;
}
[class*="st-key-page_header_"] [class*="st-key-breadcrumb_home_"] button,
[class*="st-key-page_header_"] [class*="st-key-breadcrumb_section_"] button {
  min-height:2.35rem;padding:.2rem .35rem;background:transparent!important;
  color:var(--body)!important;border:1px solid transparent!important;font-size:1.05rem;font-weight:620;
}
[class*="st-key-page_header_"] [class*="st-key-breadcrumb_home_"] button:hover,
[class*="st-key-page_header_"] [class*="st-key-breadcrumb_section_"] button:hover {
  background:transparent!important;color:var(--ink)!important;border-color:var(--line)!important;
}
.breadcrumb-separator {padding:.48rem 0;color:var(--muted);font-size:1.1rem;text-align:center;}
[data-testid="stExpandSidebarButton"] {
  display:flex!important;visibility:visible!important;opacity:1!important;
  width:2.65rem!important;height:2.65rem!important;align-items:center;justify-content:center;
  background:var(--paper)!important;border:1px solid var(--line-strong)!important;
  border-radius:4px!important;color:var(--ink)!important;box-shadow:0 1px 3px rgba(0,0,0,.14)!important;
}
[data-testid="stSidebarCollapseButton"] {visibility:visible!important;opacity:1!important;}
[data-testid="stSidebarCollapseButton"] button {
  display:flex!important;visibility:visible!important;opacity:1!important;
  width:2.65rem!important;height:2.65rem!important;align-items:center;justify-content:center;
  background:var(--paper)!important;border:1px solid var(--line-strong)!important;
  border-radius:4px!important;color:var(--ink)!important;box-shadow:0 1px 3px rgba(0,0,0,.14)!important;
}
[data-testid="stExpandSidebarButton"] svg,[data-testid="stSidebarCollapseButton"] svg {
  width:1.3rem!important;height:1.3rem!important;color:var(--ink)!important;
}
.st-key-generated_answer {
  background:#fff!important;border:1px solid var(--line-strong)!important;
  border-left:3px solid var(--ink)!important;border-radius:5px!important;
}
.st-key-knowledge_generate button,.st-key-knowledge_search button {
  background:var(--paper)!important;color:var(--ink)!important;
  border:1px solid var(--line-strong)!important;
}
.st-key-knowledge_generate button {font-weight:720;border-width:2px!important;}
.st-key-knowledge_search button {font-weight:620;color:var(--body)!important;}
.st-key-knowledge_generate button:hover,.st-key-knowledge_search button:hover {
  background:var(--paper)!important;color:var(--ink)!important;border-color:var(--ink)!important;
}
.citation-index {font-size:.98rem;color:var(--blue);font-weight:720;}
@media (max-width:900px) {.status-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .status-cell:nth-child(2n) {border-right:0;}}
@media (max-width:760px) {.block-container {padding:1rem .85rem 2rem;}
  h1 {font-size:1.9rem!important;}.flow-track span,.review-steps span {flex:1 1 42%;margin-top:-1px;}}
</style>
"""
