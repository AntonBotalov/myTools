"""Понятные объяснения ошибок libxml2 (валидация по XSD и синтаксис XML): что не так и как исправить."""
import difflib
import re

XS_NS = "http://www.w3.org/2001/XMLSchema"
CLARK = re.compile(r"\{([^}]*)\}(.+)")
HEAD = re.compile(r"^Element '(?P<el>[^']+)'(?:, attribute '(?P<attr>[^']+)')?: (?P<rest>.*)$", re.S)
EXPECTED = re.compile(r"Expected is (?P<one>one of )?\( (?P<items>.*?) \)")

TYPE_HINTS = {
    "xs:date": "дата в формате ГГГГ-ММ-ДД, например 2025-07-22",
    "xs:dateTime": "дата и время в формате ГГГГ-ММ-ДДTчч:мм:сс, например 2025-07-22T10:30:00",
    "xs:time": "время в формате чч:мм:сс, например 10:30:00",
    "xs:gYear": "год из четырёх цифр, например 2025",
    "xs:boolean": "true или false (допускаются также 1 и 0)",
    "xs:decimal": "число с точкой в качестве разделителя, например 4550000.00",
    "xs:double": "число с точкой в качестве разделителя, например 5.7",
    "xs:float": "число с точкой в качестве разделителя, например 5.7",
    "xs:anyURI": "ссылка (URI) без пробелов",
    "xs:base64Binary": "данные в кодировке Base64",
}
for _t in ("int", "integer", "long", "short", "byte", "nonNegativeInteger", "positiveInteger",
           "unsignedInt", "unsignedLong", "unsignedShort", "negativeInteger", "nonPositiveInteger"):
    TYPE_HINTS[f"xs:{_t}"] = "целое число без пробелов и разделителей"
NUMERIC_TYPES = {k for k, v in TYPE_HINTS.items() if "число" in v}


def _short(ns):
    """Короткое имя пространства: последняя часть адреса"""
    return ns.rstrip("/").rsplit("/", 1)[-1] if ns else "без пространства имён"


def _split(clark):
    m = CLARK.fullmatch(clark)
    return (m.group(1), m.group(2)) if m else ("", clark)


class Explainer:
    def __init__(self, nsmap=None, element_docs=None, roots=None, type_bases=None):
        """nsmap — префиксы из XML (None — пространство по умолчанию), element_docs — {имя: описание},
        type_bases — {имя простого типа схемы: встроенный базовый тип, например xs:decimal}"""
        self.type_bases = type_bases or {}
        self.rev = {}
        for prefix, uri in (nsmap or {}).items():
            if uri not in self.rev or prefix is None:
                self.rev[uri] = prefix
        self.docs = element_docs or {}
        self.roots = roots or []

    # --- Имена ---
    def name(self, clark):
        """'{ns}signer' → 'ns5:signer' (с префиксом из XML)"""
        ns, local = _split(clark)
        if ns == XS_NS:
            return f"xs:{local}"
        if ns in self.rev:
            prefix = self.rev[ns]
            return f"{prefix}:{local}" if prefix else local
        return local

    def tag(self, clark):
        return f"<{self.name(clark)}>"

    def described(self, clark):
        doc = self.docs.get(_split(clark)[1])
        return f"{self.tag(clark)} «{doc}»" if doc else self.tag(clark)

    @staticmethod
    def _expected(rest):
        m = EXPECTED.search(rest)
        if not m:
            return [], False
        items = [x.strip() for x in m.group("items").split(",")]
        return [x for x in items if x and not x.startswith("##")], bool(m.group("one"))

    # --- Главная функция ---
    def explain(self, message):
        """Возвращает (что не так, как исправить). Пустые строки — если объяснить нечем."""
        msg = " ".join(message.split())
        m = HEAD.match(msg)
        try:
            if m:
                return self._schema(m.group("el"), m.group("attr"), m.group("rest"))
            return self._syntax(msg)
        except Exception:
            return "", ""

    # --- Ошибки валидации по схеме ---
    def _schema(self, el, attr, rest):
        tag = self.tag(el)
        target = f"атрибута {attr} у {tag}" if attr else tag

        if "This element is not expected" in rest:
            return self._not_expected(el, rest)

        if "Missing child element(s)" in rest:
            expected, one_of = self._expected(rest)
            if not expected:
                return f"Внутри {tag} не хватает обязательных элементов.", "Сверьтесь с деревом схемы."
            listed = ", ".join(self.described(x) for x in expected[:6])
            what = "одного из элементов" if one_of else "обязательного элемента"
            fix = (f"Добавьте внутрь {tag} {'один из них' if one_of else self.tag(expected[0])}"
                   " на положенное по схеме место — порядок элементов важен.")
            return f"Внутри {tag} не хватает {what}: {listed}.", fix

        m = re.search(r"The attribute '(.+?)' is required but missing", rest)
        if m:
            return (f"У {tag} нет обязательного атрибута {m.group(1)}.",
                    f'Добавьте атрибут в открывающий тег: <{self.name(el)} … {m.group(1)}="значение">.')

        if re.search(r"The attribute '.+?' is not allowed", rest):
            return (f"У {tag} не может быть атрибута {attr or ''}.".replace("  ", " "),
                    "Удалите атрибут или проверьте его имя — регистр букв важен.")

        m = re.search(r"\[facet '(\w+)'\] (.*)", rest)
        if m:
            return self._facet(m.group(1), m.group(2), target)

        m = re.search(r"'(.*?)' is not a valid value of the (?:local )?(?:atomic|union|list) type(?: '(.+?)')?", rest)
        if m:
            return self._bad_value(m.group(1), m.group(2), target)

        if "Character content other than whitespace is not allowed" in rest:
            return (f"Внутри {tag} должны быть только вложенные элементы, а найден текст.",
                    "Удалите текст или поместите его в нужный вложенный элемент.")
        if "content type is empty" in rest:
            return (f"{tag} по схеме должен быть пустым.", f"Запишите его как <{self.name(el)}/>.")
        if "Element content is not allowed" in rest:
            return (f"{tag} должен содержать просто значение, а внутри вложенные элементы.",
                    "Уберите вложенные теги или проверьте, не перепутан ли элемент.")
        if "No matching global declaration available for the validation root" in rest:
            roots = ", ".join(self.roots[:5]) or "—"
            return (f"Корневой элемент {tag} не описан в этой схеме или указан в другом пространстве имён.",
                    f"Схема допускает корень: {roots}. Проверьте имя корня, xmlns и что выбрана нужная схема.")
        m = re.search(r"Duplicate key-sequence \[(.*?)\]", rest)
        if m:
            return (f"Значение {m.group(1)} должно быть уникальным, но повторяется.",
                    "Сделайте значения разными (часто это идентификаторы вроде _id).")
        if "No match found for key-sequence" in rest:
            return ("Ссылка указывает на значение, которого нет в документе.",
                    "Проверьте, что идентификатор, на который ссылается элемент, существует.")
        return "", ""

    def _not_expected(self, el, rest):
        tag = self.tag(el)
        el_ns, el_local = _split(el)
        expected, one_of = self._expected(rest)
        if not expected:
            return (f"{tag} здесь лишний — схема не допускает на этом месте больше элементов.",
                    "Удалите элемент или проверьте, что он вложен в правильного родителя "
                    "и не повторяется чаще, чем разрешено.")

        # То же имя, но другое пространство имён — самая частая и самая непонятная ошибка
        same = [x for x in expected if _split(x)[1] == el_local]
        if same:
            exp_ns = _split(same[0])[0]
            problem = (f"Элемент {tag} записан не в том пространстве имён: сейчас «{_short(el_ns)}», "
                       f"а схема ждёт «{_short(exp_ns)}» ({exp_ns or 'без пространства имён'}).")
            if exp_ns in self.rev:
                right = self.name(same[0])
                fix = (f"Замените <{self.name(el)}> на <{right}> и закрывающий тег на </{right}>. "
                       "Вложенные элементы не трогайте.")
            else:
                fix = (f'Объявите пространство имён в корне, например xmlns:x="{exp_ns}", '
                       f"и запишите элемент как <x:{el_local}>.")
            return problem, fix

        names = [_split(x)[1] for x in expected]
        listed = ", ".join(self.described(x) for x in expected[:6])
        problem = (f"На этом месте схема не ожидает {tag}. "
                   f"{'Здесь должен быть один из' if one_of else 'Здесь должен быть'}: {listed}.")
        lower = [n for n in names if n.lower() == el_local.lower()]
        close = lower or difflib.get_close_matches(el_local, names, n=1, cutoff=0.7)
        if close:
            fix = f"Похоже на опечатку: возможно, имелось в виду <{close[0]}>. Регистр букв важен."
        else:
            fix = (f"Порядок элементов задан схемой. Либо перед {tag} не хватает {self.tag(expected[0])}, "
                   f"либо {tag} стоит не на своём месте или вложен не в тот элемент.")
        return problem, fix

    def _facet(self, facet, text, target):
        quoted = re.findall(r"'([^']*)'", text)
        value = quoted[0] if quoted else ""

        if facet == "enumeration":
            allowed = re.findall(r"'([^']*)'", text.split("set", 1)[-1])
            shown = ", ".join(allowed[:15]) + (f" … (+{len(allowed) - 15})" if len(allowed) > 15 else "")
            by_case = [a for a in allowed if a.lower() == value.strip().lower()]
            close = by_case or difflib.get_close_matches(value.strip(), allowed, n=1, cutoff=0.6)
            fix = f"Допустимые значения: {shown}."
            if value.strip() in allowed:
                fix = "Уберите пробелы в начале и в конце значения. " + fix
            elif close:
                fix = f"Возможно, имелось в виду «{close[0]}». " + fix
            return f"Значение «{value}» не входит в список допустимых для {target}.", fix

        if facet == "pattern":
            pattern = quoted[-1] if len(quoted) > 1 else ""
            hint = _pattern_hint(pattern)
            fix = (f"Нужен формат: {hint}. " if hint else "") + f"Шаблон из схемы: {pattern}"
            if value != value.strip():
                fix = "В значении есть пробелы в начале или в конце — уберите их. " + fix
            return f"Значение «{value}» не подходит под формат {target}.", fix

        nums = re.findall(r"'(-?[\d.]+)'|\('(-?[\d.]+)'\)", text)
        nums = [a or b for a, b in nums]
        if facet in ("maxLength", "minLength", "length") and len(nums) >= 2:
            have, limit = nums[0], nums[-1]
            if facet == "maxLength":
                return (f"Значение {target} слишком длинное: {have} символов при максимуме {limit}.",
                        f"Сократите значение до {limit} символов.")
            if facet == "minLength":
                if have == "0":
                    return (f"У {target} пустое значение.",
                            "Заполните значение или удалите элемент, если он необязательный.")
                return (f"Значение {target} слишком короткое: {have} символов при минимуме {limit}.",
                        f"Нужно не меньше {limit} символов.")
            return (f"Длина значения {target} — {have} символов, а нужно ровно {limit}.",
                    f"Приведите значение к {limit} символам.")

        if facet in ("minInclusive", "minExclusive", "maxInclusive", "maxExclusive") and len(nums) >= 2:
            rule = {"minInclusive": f"не меньше {nums[-1]}", "minExclusive": f"больше {nums[-1]}",
                    "maxInclusive": f"не больше {nums[-1]}", "maxExclusive": f"меньше {nums[-1]}"}[facet]
            return f"Значение {nums[0]} у {target} вне допустимого диапазона.", f"Значение должно быть {rule}."

        if facet == "totalDigits" and nums:
            return (f"В значении {target} слишком много цифр.", f"Допускается не больше {nums[-1]} цифр всего.")
        if facet == "fractionDigits" and nums:
            return (f"В значении {target} слишком много знаков после точки.",
                    f"Допускается не больше {nums[-1]} знаков после точки.")
        return f"Значение {target} не соответствует ограничению схемы ({facet}).", ""

    def _bad_value(self, value, type_clark, target):
        tname = self.name(type_clark) if type_clark else ""
        base = tname if tname in TYPE_HINTS else self.type_bases.get(_split(type_clark)[1] if type_clark else "")
        hint = TYPE_HINTS.get(base)
        if value == "":
            return (f"У {target} пустое значение.",
                    "Заполните значение" + (f" ({hint})" if hint else "") +
                    " или удалите элемент, если он необязательный.")
        problem = f"Значение «{value}» не подходит по типу для {target}" + (f" ({tname})." if tname else ".")
        if hint:
            fix = f"Нужно: {hint}."
            if base in NUMERIC_TYPES and "," in value:
                fix = "Замените запятую на точку. " + fix
            if value != value.strip():
                fix = "Уберите пробелы в начале и в конце значения. " + fix
        elif tname:
            fix = (f"Значение не проходит проверки типа {tname} — ограничения этого типа видны в дереве "
                   "схемы; конкретное нарушение обычно указано в соседней ошибке.")
        else:
            fix = "Проверьте формат значения по дереву схемы."
        return problem, fix

    # --- Синтаксис XML ---
    def _syntax(self, msg):
        rules = [
            (r"Namespace prefix (\S+) (?:on|for) (\S+) is not defined",
             lambda m: (f"Префикс {m.group(1)} в <{m.group(1)}:{m.group(2)}> нигде не объявлен.",
                        f'Добавьте в корневой элемент xmlns:{m.group(1)}="…". Если таких ошибок много — '
                        "скорее всего, у документа обрезано начало вместе с корневым тегом.")),
            (r"Opening and ending tag mismatch: (\S+) line (\d+) and (\S+)",
             lambda m: (f"Тег <{m.group(1)}> из строки {m.group(2)} закрыт как </{m.group(3)}>.",
                        f"Закрывающий тег должен совпадать с открывающим: </{m.group(1)}>. "
                        "Проверьте, не пропущен ли закрывающий тег где-то между ними.")),
            (r"Premature end of data in tag (\S+) line (\d+)",
             lambda m: (f"Документ оборвался: не закрыт тег <{m.group(1)}> из строки {m.group(2)}.",
                        "Похоже, файл обрезан. Добавьте недостающий конец документа.")),
            (r"EndTag: '</' not found",
             lambda m: ("Документ оборвался: не все теги закрыты.", "Похоже, файл обрезан в конце.")),
            (r"Extra content at the end of the document",
             lambda m: ("После корневого элемента есть ещё что-то.",
                        "В XML должен быть ровно один корневой элемент. Часто это значит, что обрезано "
                        "начало документа или два документа склеены вместе.")),
            (r"Document is empty|Start tag expected, '<' not found",
             lambda m: ("Это не XML: в начале нет ни одного тега.",
                        "Проверьте, что загружен нужный файл и он не пустой.")),
            (r"xmlParseEntityRef: no name|EntityRef: expecting ';'",
             lambda m: ("В тексте есть символ & без экранирования.", "Замените & на &amp;.")),
            (r"Unescaped '<' not allowed in attributes values",
             lambda m: ("В значении атрибута есть символ <.", "Замените < на &lt;.")),
            (r"StartTag: invalid element name",
             lambda m: ("После символа < идёт что-то, что не может быть именем тега.",
                        "Если < — часть текста, замените его на &lt;.")),
            (r"Attribute (\S+) redefined",
             lambda m: (f"Атрибут {m.group(1)} указан дважды в одном теге.", "Оставьте один.")),
            (r"AttValue: \" or ' expected|attributes construct error|Couldn't find end of Start Tag",
             lambda m: ("Тег записан с ошибкой: что-то не так с атрибутами.",
                        "Значения атрибутов должны быть в кавычках: имя=\"значение\".")),
            (r"Input is not proper UTF-8|Char 0x[0-9A-F]+ out of allowed range|invalid character",
             lambda m: ("Файл не в той кодировке, что указана в заголовке, или в нём есть недопустимые символы.",
                        "Пересохраните файл в UTF-8 или укажите правильную кодировку в "
                        '<?xml … encoding="…"?>.')),
            (r"XML declaration allowed only at the start",
             lambda m: ("Строка <?xml …?> стоит не в самом начале файла.",
                        "Уберите всё, что стоит перед ней, включая пробелы и пустые строки.")),
        ]
        for pattern, build in rules:
            m = re.search(pattern, msg)
            if m:
                return build(m)
        return "", ""


def _pattern_hint(pattern):
    """Человеческое описание нескольких типовых шаблонов"""
    if re.fullmatch(r"\[a-fA-F0-9\]\{8\}-.*\{12\}", pattern) or "{8}-" in pattern and "{12}" in pattern:
        return "UUID вида xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (цифры и буквы a–f)"
    m = re.fullmatch(r"(?:\\d|\[0-9\])\{(\d+)\}", pattern)
    if m:
        return f"ровно {m.group(1)} цифр"
    m = re.fullmatch(r"(?:\\d|\[0-9\])\{(\d+),(\d+)\}", pattern)
    if m:
        return f"от {m.group(1)} до {m.group(2)} цифр"
    if re.fullmatch(r"(?:\\d|\[0-9\])\+", pattern):
        return "только цифры"
    return ""
