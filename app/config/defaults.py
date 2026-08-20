"""Shared baseline values for generated configs.

The generator starts from these and overrides the parts it can defend from the
site itself. Kept in one place so the defaults are not duplicated across every
generated file.
"""

from __future__ import annotations

BASELINE_PATHS_TO_SKIP = [
    "/admin",
    "/wp-admin",
    "/login",
    "/signin",
    "/register",
    "/signup",
    "/cart",
    "/checkout",
    "/account",
    "/account/login",
    "/search",
    "/404",
    "/error",
    "/privacy-policy",
    "/privacy",
    "/terms",
    "/cookie-policy",
    "/sitemap.xml",
    "/robots.txt",
]

BASELINE_ELEMENTS_TO_REMOVE = [
    "#beyond-chats-widget",
    "nav",
    ".navbar",
    "header",
    "footer",
    "#footer",
    ".pum",
    "#cookie-notice",
    ".cookie-banner",
    ".hidden",
    ".fixed-bottom",
    ".sr-only",
    ".breadcrumb",
    ".sidebar",
    "#sidebar",
]

STRIP_FLAGS = {
    "stripImages": True,
    "stripScripts": True,
    "stripStyles": True,
    "stripLinks": True,
    "stripMeta": True,
    "stripHead": True,
    "stripNoscript": True,
    "stripSvg": True,
}

# Path segments that almost always mark taxonomy/list pages rather than content a
# chatbot can answer from. Kept conservative: only unambiguous taxonomy dirs, not
# real content sections (news, events, resources) a site may legitimately publish.
LIST_PATH_SEGMENTS = (
    "tag",
    "tags",
    "category",
    "categories",
    "author",
    "authors",
    "obituary",
    "obituaries",
)

# Markers that tell us a page is a JavaScript shell rather than server-rendered
# HTML. Kept for callers that want to bet a site is fully static; the generator
# itself defaults puppeteerOnly to true regardless.
SPA_MARKERS = (
    "__NEXT_DATA__",
    "__NUXT__",
    "window.__INITIAL_STATE__",
    "ng-version",
    "data-reactroot",
    'id="root"',
    'id="app"',
    "createRoot(",
    "Vue(",
    '<div id="root">',
)