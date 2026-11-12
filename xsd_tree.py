"""Разбор XSD-схемы в дерево, отрисовка в стиле XMLSpy и сопоставление с XML-документом."""
import html
from collections import Counter

from lxml import etree

XS_NS = "http://www.w3.org/2001/XMLSchema"
XS = "{%s}" % XS_NS
MAX_DEPTH = 40        # защита от слишком глубокой вложенности
MAX_NODES = 20000     # защита от гигантских схем
COMPOSITORS = ("sequence", "choice", "all")


# --- Мелкие помощники ---

def _tag(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None


def _local(qname):
    return qname.split(":")[-1] if qname else None


def _is_builtin(el, qname):
    """Тип из пространства имён XMLSchema (xs:string, xs:date и т.п.)"""
    prefix = qname.split(":")[0] if ":" in qname else None
    return el.nsmap.get(prefix) == XS_NS


def _type_label(el, qname):
    name = _local(qname)
    return f"xs:{name}" if _is_builtin(el, qname) else name


def _doc(el):
    """Текст из xs:annotation/xs:documentation"""
    if el is None:
        return ""
    texts = []
    for d in el.findall(f"{XS}annotation/{XS}documentation"):
        t = " ".join("".join(d.itertext()).split())
        if t:
            texts.append(t)
    return " ".join(texts)


def _max(value):
    return "∞" if value == "unbounded" else value


# --- Построение дерева по схеме ---

class XsdTree:
    def __init__(self, xsd_root):
        self.index = {k: {} for k in ("element", "complexType", "simpleType",
                                      "group", "attributeGroup", "attribute")}
        for child in xsd_root:
            tag = _tag(child)
            if tag in self.index and child.get("name"):
                self.index[tag][child.get("name")] = child
        self.count = 0
        self.truncated = False

    @property
    def global_elements(self):
        return list(self.index["element"])

    def build(self, root_name):
        self.count = 0
        self.truncated = False
        return self._element(self.index["element"][root_name], "", 0, (), False)

    # Элемент
    def _element(self, el, parent_path, depth, type_stack, optional_ctx):
        self.count += 1
        ref = el.get("ref")
        target = self.index["element"].get(_local(ref)) if ref else el
        name = _local(ref) if ref else el.get("name", "?")
        min_o = el.get("minOccurs", "1")
        max_o = el.get("maxOccurs", "1")
        path = f"{parent_path}/{name}" if parent_path else name

        node = dict(kind="element", name=name, min=min_o, max=_max(max_o), path=path,
                    required=(min_o != "0" and not optional_ctx),
                    doc=_doc(el) or _doc(target), type="", named_complex=False,
                    facets="", note="", attrs=[], children=[])

        if target is None:
            node["note"] = "элемент описан во внешней схеме"
            return node
        if self.count > MAX_NODES:
            self.truncated = True
            node["note"] = "дерево обрезано: слишком большая схема"
            return node

        inline_ct = target.find(f"{XS}complexType")
        inline_st = target.find(f"{XS}simpleType")
        type_q = target.get("type")

        if inline_ct is not None:
            self._content(inline_ct, node, path, depth, type_stack)
        elif inline_st is not None:
            node["facets"] = self._simple(inline_st)
        elif type_q:
            lname = _local(type_q)
            node["type"] = _type_label(target, type_q)
            if _is_builtin(target, type_q):
                pass
            elif lname in self.index["complexType"]:
                node["named_complex"] = True
                if lname in type_stack:
                    node["note"] = "рекурсивный тип — содержимое показано выше по дереву"
                elif depth >= MAX_DEPTH:
                    node["note"] = "слишком глубокая вложенность"
                else:
                    self._content(self.index["complexType"][lname], node, path, depth,
                                  type_stack + (lname,))
            elif lname in self.index["simpleType"]:
                node["facets"] = self._simple(self.index["simpleType"][lname])
            else:
                node["note"] = "тип описан во внешней схеме (xs:import / xs:include)"
        return node

    # Содержимое комплексного типа
    def _content(self, container, node, path, depth, type_stack):
        for ch in container:
            tag = _tag(ch)
            if tag in COMPOSITORS:
                comp = self._compositor(ch, path, depth, type_stack, False)
                if comp["children"]:
                    node["children"].append(comp)
            elif tag == "group":
                comp = self._group(ch, path, depth, type_stack, False)
                if comp:
                    node["children"].append(comp)
            elif tag in ("complexContent", "simpleContent"):
                for der in ch:
                    dtag = _tag(der)
                    if dtag not in ("extension", "restriction"):
                        continue
                    base = der.get("base")
                    if base:
                        bl = _local(base)
                        if tag == "complexContent":
                            if (dtag == "extension" and bl in self.index["complexType"]
                                    and bl not in type_stack):
                                self._content(self.index["complexType"][bl], node, path, depth,
                                              type_stack + (bl,))
                        else:
                            if not node["type"]:
                                node["type"] = _type_label(der, base)
                            parts = []
                            if bl in self.index["simpleType"]:
                                parts.append(self._simple(self.index["simpleType"][bl]))
                            if dtag == "restriction":
                                parts.append(self._facets(der))
                            node["facets"] = " · ".join(p for p in parts if p)
                    self._content(der, node, path, depth, type_stack)
            elif tag == "attribute":
                node["attrs"].append(self._attr(ch, path))
            elif tag == "attributeGroup":
                self._attr_group(ch, node, path, set())
            elif tag == "anyAttribute":
                node["attrs"].append(dict(name="*", required=False, type="любой атрибут",
                                          facets="", doc="", path=f"{path}/@*"))

    def _compositor(self, c, path, depth, type_stack, optional_ctx, min_o=None, max_o=None):
        kind = _tag(c)
        mn = min_o or c.get("minOccurs", "1")
        mx = max_o or c.get("maxOccurs", "1")
        # Внутри choice или необязательной группы элементы по отдельности не обязательны
        opt = optional_ctx or mn == "0" or kind == "choice"
        node = dict(kind=kind, min=mn, max=_max(mx), children=[])
        for ch in c:
            tag = _tag(ch)
            if tag == "element":
                node["children"].append(self._element(ch, path, depth + 1, type_stack, opt))
            elif tag in COMPOSITORS:
                sub = self._compositor(ch, path, depth, type_stack, opt)
                if sub["children"]:
                    node["children"].append(sub)
            elif tag == "group":
                sub = self._group(ch, path, depth, type_stack, opt)
                if sub:
                    node["children"].append(sub)
            elif tag == "any":
                node["children"].append(dict(kind="any", min=ch.get("minOccurs", "1"),
                                             max=_max(ch.get("maxOccurs", "1")), doc=_doc(ch)))
        return node

    def _group(self, ref_el, path, depth, type_stack, optional_ctx):
        gname = _local(ref_el.get("ref"))
        gdef = self.index["group"].get(gname)
        if gdef is None or gname in type_stack:
            return None
        for ch in gdef:
            if _tag(ch) in COMPOSITORS:
                return self._compositor(ch, path, depth, type_stack + (gname,), optional_ctx,
                                        ref_el.get("minOccurs"), ref_el.get("maxOccurs"))
        return None

    # Атрибуты
    def _attr(self, a, path):
        ref = a.get("ref")
        target = self.index["attribute"].get(_local(ref)) if ref else a
        name = _local(ref) if ref else a.get("name", "?")
        info = dict(name=name, required=a.get("use") == "required", type="", facets="",
                    doc=_doc(a) or _doc(target), path=f"{path}/@{name}")
        if target is not None:
            st = target.find(f"{XS}simpleType")
            t = target.get("type")
            if st is not None:
                info["facets"] = self._simple(st)
            elif t:
                info["type"] = _type_label(target, t)
                if _local(t) in self.index["simpleType"]:
                    info["facets"] = self._simple(self.index["simpleType"][_local(t)])
        return info

    def _attr_group(self, ref_el, node, path, seen):
        gname = _local(ref_el.get("ref"))
        gdef = self.index["attributeGroup"].get(gname)
        if gdef is None or gname in seen:
            return
        seen.add(gname)
        for ch in gdef:
            tag = _tag(ch)
            if tag == "attribute":
                node["attrs"].append(self._attr(ch, path))
            elif tag == "attributeGroup":
                self._attr_group(ch, node, path, seen)

    # Простые типы
    def _simple(self, st, seen=()):
        r = st.find(f"{XS}restriction")
        if r is not None:
            parts = []
            base = r.get("base")
            if base:
                bl = _local(base)
                if _is_builtin(r, base):
                    parts.append(f"xs:{bl}")
                elif bl in self.index["simpleType"] and bl not in seen:
                    inherited = self._simple(self.index["simpleType"][bl], seen + (bl,))
                    parts.append(f"{bl} ({inherited})" if inherited else bl)
                else:
                    parts.append(bl)
            facets = self._facets(r)
            if facets:
                parts.append(facets)
            return " · ".join(parts)
        if st.find(f"{XS}list") is not None:
            return "список значений через пробел"
        if st.find(f"{XS}union") is not None:
            return "объединение нескольких типов"
        return ""

    @staticmethod
    def _facets(r):
        def vals(t):
            return [f.get("value") for f in r.findall(f"{XS}{t}")]

        parts = []
        enum = vals("enumeration")
        if enum:
            shown = ", ".join(enum[:8])
            more = f" … (+{len(enum) - 8})" if len(enum) > 8 else ""
            parts.append(f"значения: {shown}{more}")
        length, min_l, max_l = vals("length"), vals("minLength"), vals("maxLength")
        if length:
            parts.append(f"длина {length[0]}")
        elif min_l or max_l:
            parts.append(f"длина {min_l[0] if min_l else 0}–{max_l[0] if max_l else '∞'}")
        for p in vals("pattern"):
            parts.append(f"шаблон {p}")
        for t, sign in (("minInclusive", "≥"), ("minExclusive", ">"),
                        ("maxInclusive", "≤"), ("maxExclusive", "<")):
            for v in vals(t):
                parts.append(f"{sign} {v}")
        total, frac = vals("totalDigits"), vals("fractionDigits")
        if total:
            parts.append(f"цифр не более {total[0]}")
        if frac:
            parts.append(f"знаков после запятой {frac[0]}")
        return " · ".join(parts)


# --- Анализ XML ---

def local_path(el):
    """Путь элемента из локальных имён без префиксов: root/child/sub"""
    names = []
    while el is not None:
        names.append(etree.QName(el).localname)
        el = el.getparent()
    return "/".join(reversed(names))


def xml_presence(xml_root):
    """Сколько раз каждый путь (элементы и атрибуты) встречается в XML"""
    counter = Counter()
    for el in xml_root.iter():
        if not isinstance(el.tag, str):
            continue
        p = local_path(el)
        counter[p] += 1
        for a in el.attrib:
            counter[f"{p}/@{etree.QName(a).localname}"] += 1
    return dict(counter)


def collect_namespaces(xml_root):
    ns = {}
    for el in xml_root.iter():
        if isinstance(el.tag, str):
            for k, v in el.nsmap.items():
                if k:
                    ns.setdefault(k, v)
    return ns


def error_element_path(entry, xml_root, ns):
    """Определяет, к какому элементу XML относится ошибка валидации"""
    target = None
    if getattr(entry, "path", None):
        try:
            found = xml_root.getroottree().xpath(entry.path, namespaces=ns)
            if found and isinstance(found[0], etree._Element):
                target = found[0]
        except Exception:
            target = None
    if target is None and entry.line:
        for el in xml_root.iter():
            if isinstance(el.tag, str) and el.sourceline == entry.line:
                target = el
                break
    return local_path(target) if target is not None else ""


# --- Отрисовка ---

def _card(mn, mx):
    if (mn, mx) in (("1", "1"), ("0", "1")):
        return ""
    return f'<span class="card">{html.escape(mn)}..{html.escape(mx)}</span>'


def _r_node(n, ctx, depth):
    if n["kind"] == "element":
        return _r_element(n, ctx, depth)
    if n["kind"] == "any":
        return (f'<div class="el opt leaf" data-s="any"><div class="head">'
                f'<span class="box">любой элемент</span>{_card(n["min"], n["max"])}'
                f'<span class="type">xs:any</span></div></div>')
    icon, label = {"sequence": ("•••", "последовательно"),
                   "choice": ("⑂", "одно из"),
                   "all": ("≡", "все, в любом порядке")}[n["kind"]]
    kids = "".join(_r_node(k, ctx, depth) for k in n["children"])
    optc = " optc" if n["min"] == "0" else ""
    return (f'<div class="comp {n["kind"]}{optc}"><div class="comp-h"><span class="comp-ic">{icon}</span>'
            f'{label}{_card(n["min"], n["max"])}</div><div class="comp-b">{kids}</div></div>')


def _r_attrs(attrs, ctx, el_present):
    e = html.escape
    rows = []
    for a in attrs:
        cls = "attr " + ("req" if a["required"] else "opt")
        badge = ""
        if ctx["xml"] and el_present:
            if ctx["presence"].get(a["path"], 0):
                badge = '<span class="b ok">✓</span>'
            elif a["required"]:
                badge = '<span class="b miss">нет в XML</span>'
                cls += " miss"
        meta = " · ".join(x for x in (a["type"], a["facets"]) if x)
        search = e(f'{a["name"]} {a["doc"]}'.lower(), quote=True)
        rows.append(
            f'<div class="{cls}" data-s="{search}"><span class="aname">@{e(a["name"])}</span>'
            + (f'<span class="type">{e(meta)}</span>' if meta else "")
            + badge
            + (f'<span class="adoc">{e(a["doc"])}</span>' if a["doc"] else "")
            + "</div>")
    return '<div class="attrs">' + "".join(rows) + "</div>"


def _r_element(n, ctx, depth):
    e = html.escape
    path = n["path"]
    classes = ["el", "req" if n["required"] else "opt"]
    badges = []
    count = 0
    if ctx["xml"]:
        count = ctx["presence"].get(path, 0)
        parent = path.rsplit("/", 1)[0] if "/" in path else None
        parent_present = parent is None or ctx["presence"].get(parent, 0) > 0
        if count:
            classes.append("ok")
            badges.append(f'<span class="b ok">✓{" ×%d" % count if count > 1 else ""}</span>')
        elif n["required"] and parent_present:
            classes.append("miss")
            badges.append('<span class="b miss">нет в XML</span>')
        else:
            classes.append("absent")
    errs = ctx["errors"].get(path, [])
    if errs:
        classes.append("has-err")
        badges.append(f'<span class="b err">⚠ {len(errs)}</span>')

    head = (f'<span class="box">{e(n["name"])}</span>{_card(n["min"], n["max"])}'
            + (f'<span class="type">{e(n["type"])}</span>' if n["type"] else "")
            + "".join(badges))
    sub = ""
    if n["doc"]:
        sub += f'<div class="doc">{e(n["doc"])}</div>'
    if n["facets"]:
        sub += f'<div class="facets">{e(n["facets"])}</div>'
    if n["note"]:
        sub += f'<div class="note">{e(n["note"])}</div>'

    inner = ""
    if n["attrs"]:
        inner += _r_attrs(n["attrs"], ctx, count > 0)
    kids = "".join(_r_node(c, ctx, depth + 1) for c in n["children"])
    if kids:
        inner += f'<div class="kids">{kids}</div>'
    if inner and n["named_complex"]:
        inner = f'<div class="typebox"><div class="typebox-h">{e(n["type"])}</div>{inner}</div>'

    body = ""
    if errs:
        body += '<ul class="errs">' + "".join(f"<li>{e(m)}</li>" for m in errs) + "</ul>"
    body += inner

    search = e(f'{n["name"]} {n["doc"]}'.lower(), quote=True)
    cls = " ".join(classes)
    if body:
        is_open = " open" if depth < 3 else ""
        return (f'<details class="{cls}" data-s="{search}"{is_open}><summary>'
                f'<div class="head">{head}</div>{sub}</summary>{body}</details>')
    return f'<div class="{cls} leaf" data-s="{search}"><div class="head">{head}</div>{sub}</div>'


def render_tree(root_node, presence=None, errors=None):
    """Возвращает самостоятельную HTML-страницу с деревом схемы"""
    ctx = {"xml": presence is not None, "presence": presence or {}, "errors": errors or {}}
    tree_html = _r_element(root_node, ctx, 0)

    legend = ('<span><span class="box">обязательный</span></span>'
              '<span><span class="box dashed">необязательный</span></span>'
              '<span><span class="comp-ic">•••</span> последовательно</span>'
              '<span><span class="comp-ic">⑂</span> одно из</span>')
    err_btn = ""
    if ctx["xml"]:
        legend += ('<span><span class="b ok">✓</span> есть в XML</span>'
                   '<span><span class="b miss">нет в XML</span> обязательный отсутствует</span>'
                   '<span><span class="b err">⚠</span> ошибки валидации</span>'
                   '<span style="opacity:.6">бледный — необязательный, в XML нет</span>')
        err_btn = '<button onclick="showProblems()">Показать проблемы</button>'

    return (TEMPLATE.replace("%%TREE%%", tree_html)
            .replace("%%LEGEND%%", legend)
            .replace("%%ERRBTN%%", err_btn))


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><style>
:root{--ink:#1f2328;--muted:#5a6b7a;--line:#9aa4ae;--type-bg:#fffbe6;--type-bd:#c9b458;--type-ink:#7a6a12;
--ok:#1a7f37;--ok-bg:#e9f7ec;--bad:#c62828;--bad-bg:#fdecec;--hit:#2563eb}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:13px/1.4 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.bar{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #e5e7eb;padding:8px 10px;
display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.bar input{flex:1 1 220px;min-width:160px;padding:5px 8px;border:1px solid #cbd5e1;border-radius:6px;font:inherit}
.bar button{padding:5px 10px;border:1px solid #cbd5e1;background:#f8fafc;border-radius:6px;cursor:pointer;font:inherit}
.bar button:hover{background:#eef2f7}
#cnt{color:var(--muted);font-size:12px}
.legend{padding:6px 10px;color:var(--muted);font-size:12px;display:flex;flex-wrap:wrap;gap:6px 14px;
align-items:center;border-bottom:1px solid #f1f5f9}
.tree{padding:10px 10px 40px}
summary{list-style:none;cursor:pointer;display:block}
summary::-webkit-details-marker{display:none}
.head{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:3px 0}
details>summary .head::before{content:"▸";display:inline-block;width:12px;color:var(--muted);transition:transform .15s}
details[open]>summary .head::before{transform:rotate(90deg)}
.leaf .head::before{content:"";display:inline-block;width:12px}
.box{display:inline-block;border:1.5px solid #444;background:#fff;padding:1px 8px;font-weight:600;border-radius:2px}
.opt>summary .box,.opt.leaf .box,.box.dashed{border-style:dashed;border-color:#777}
.card{font-size:11px;color:var(--muted)}
.type{font-size:11.5px;color:var(--type-ink);background:var(--type-bg);border:1px solid #efe3a8;padding:0 6px;border-radius:3px}
.doc{color:var(--muted);font-size:12px;margin-left:18px}
.facets{font:11.5px/1.4 ui-monospace,Consolas,monospace;color:#6b5d00;margin-left:18px;word-break:break-word}
.note{font-size:11.5px;color:#b45309;margin-left:18px}
.kids{margin-left:6px;padding-left:12px;border-left:1px dotted var(--line)}
.typebox{border:1px dashed var(--type-bd);background:var(--type-bg);border-radius:3px;padding:4px 8px 6px;margin:4px 0 6px 18px}
.typebox-h{color:var(--type-ink);font-weight:600;font-size:12px;margin-bottom:2px}
.comp{margin:4px 0}
.comp-h{display:inline-flex;gap:6px;align-items:center;font-size:11.5px;color:var(--muted);border:1px solid #c8ced6;
border-radius:10px;padding:0 8px;background:#f6f8fa}
.comp.optc>.comp-h{border-style:dashed}
.comp-ic{font-weight:700;color:#444;letter-spacing:1px}
.comp-b{margin-left:10px;padding-left:12px;border-left:1px solid var(--line)}
.attrs{margin:2px 0 4px 18px}
.attr{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:1px 0}
.aname{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.attr.req .aname{font-weight:700}
.adoc{color:var(--muted);font-size:12px}
.b{font-size:11px;padding:0 6px;border-radius:9px;font-weight:600}
.b.ok{color:var(--ok);background:var(--ok-bg)}
.b.miss,.b.err{color:var(--bad);background:var(--bad-bg)}
.ok>summary .box,.ok.leaf .box{background:var(--ok-bg)}
.has-err>summary .box,.has-err.leaf .box,.miss>summary .box,.miss.leaf .box{border-color:var(--bad);background:var(--bad-bg)}
.absent>summary .box,.absent.leaf .box{opacity:.55}
.errs{margin:2px 0 4px 18px;padding-left:16px;color:var(--bad);font-size:12px}
.hit>summary .box,.hit.leaf .box,.attr.hit .aname{outline:2px solid var(--hit);outline-offset:1px}
</style></head><body>
<div class="bar"><input id="q" placeholder="Поиск по имени или описанию…"><span id="cnt"></span>
<button onclick="setAll(true)">Развернуть всё</button><button onclick="setAll(false)">Свернуть всё</button>%%ERRBTN%%</div>
<div class="legend">%%LEGEND%%</div>
<div class="tree">%%TREE%%</div>
<script>
function setAll(v){document.querySelectorAll('details').forEach(function(d){d.open=v})}
function reveal(n){var p=n.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement}}
function showProblems(){setAll(false);var ns=document.querySelectorAll('.has-err,.miss');
ns.forEach(function(n){reveal(n);if(n.tagName==='DETAILS')n.open=true});
if(ns[0])ns[0].scrollIntoView({block:'center'})}
var timer;document.getElementById('q').addEventListener('input',function(e){clearTimeout(timer);
timer=setTimeout(function(){search(e.target.value)},200)});
function search(q){document.querySelectorAll('.hit').forEach(function(n){n.classList.remove('hit')});
var c=document.getElementById('cnt');q=q.trim().toLowerCase();if(q.length<2){c.textContent='';return}
var ns=Array.prototype.filter.call(document.querySelectorAll('[data-s]'),function(n){return n.dataset.s.indexOf(q)>-1});
ns.forEach(function(n){n.classList.add('hit');reveal(n)});c.textContent='Найдено: '+ns.length;
if(ns[0])ns[0].scrollIntoView({block:'center'})}
</script></body></html>"""
