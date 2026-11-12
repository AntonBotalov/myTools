import streamlit as st
import random
import string
from difflib import SequenceMatcher
import html
import streamlit.components.v1 as components
import jwt
import json
from jwt.exceptions import InvalidTokenError
import uuid
import base64
import io
import re
import os
import shutil
import subprocess
import tempfile
import zipfile
import pandas as pd
from lxml import etree  # Для валидации XML по XSD
from xsd_tree import (XsdPackage, XsdTree, render_tree, xml_presence, collect_namespaces,
                      error_element_path)

st.set_page_config(page_title="Утилиты для текста и данных", layout="wide")

cyrillic_letters = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
latin_letters = string.ascii_lowercase
special_chars = string.punctuation + string.digits

AVAILABLE_ALGORITHMS = ["HS256"]

# --- Вспомогательные функции ---

def get_highlighted(text_base, text_compare):
    matcher = SequenceMatcher(None, text_base, text_compare)
    result = []
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        if opcode == 'equal':
            result.append(html.escape(text_compare[b0:b1]))
        elif opcode == 'insert':
            result.append(f"<span style='background-color:#008000'>{html.escape(text_compare[b0:b1])}</span>")
        elif opcode == 'replace':
            result.append(f"<span style='background-color:#ff0000'>{html.escape(text_compare[b0:b1])}</span>")
        elif opcode == 'delete':
            pass
    return ''.join(result)

def copy_to_clipboard(text, key):
    components.html(f"""
        <script>
        function copyText() {{
            navigator.clipboard.writeText(`{text}`).then(() => {{
                const btn = document.getElementById('{key}');
                btn.innerText = '✅ Скопировано';
                setTimeout(() => btn.innerText = '📋 Копировать', 1500);
            }});
        }}
        </script>
        <button id="{key}" onclick="copyText()" style="margin: 5px 0; padding: 6px 14px; border-radius: 6px; background-color: #21A038; color: white; border: none; cursor: pointer;">📋 Копировать</button>
    """, height=45)

def to_excel(dfs_dict):
    """Конвертирует словарь DataFrames в Excel файл в памяти"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for sheet_name, df in dfs_dict.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()

def highlight_excel_diff(row, common_cols, df_old_indexed, df_new_indexed):
    """Генерирует лог изменений для строки Excel"""
    idx = row.name
    changes = []
    try:
        old_row = df_old_indexed.loc[idx]
        new_row = df_new_indexed.loc[idx]
    except KeyError:
        return "Ошибка индекса"

    for col in common_cols:
        val_old = old_row[col]
        val_new = new_row[col]
        if str(val_old) != str(val_new):
            changes.append(f"{col}: '{val_old}' -> '{val_new}'")
    return "; ".join(changes)

# --- Функции для валидации XML ---

XML_DECLARATION_RE = re.compile(r'^\s*<\?xml[^>]*\?>', re.IGNORECASE)

def xml_input_block(title, key_prefix, file_types):
    """Блок ввода: файл или текст. Возвращает байты документа или None."""
    st.subheader(title)
    mode = st.radio(
        "Способ загрузки:",
        ["📁 Файл", "📝 Текст"],
        key=f"{key_prefix}_mode",
        horizontal=True,
    )
    if mode == "📁 Файл":
        uploaded = st.file_uploader("Выберите файл", type=file_types, key=f"{key_prefix}_file")
        if uploaded is not None:
            # Байты из файла передаём как есть — lxml сам учтёт кодировку из декларации
            return uploaded.getvalue().lstrip()
        return None
    else:
        text = st.text_area("Вставьте содержимое", height=350, key=f"{key_prefix}_text")
        if text.strip():
            # Текст из поля уже в Unicode: убираем декларацию (encoding="windows-1251" и т.п.),
            # чтобы она не конфликтовала с кодировкой UTF-8
            text = XML_DECLARATION_RE.sub('', text, count=1)
            return text.strip().encode('utf-8')
        return None

def safe_parser():
    """Парсер без загрузки внешних сущностей и сети (защита от XXE)"""
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024

ARCHIVE_TIMEOUT = 60  # секунд на распаковку одного архива

NO_ARCHIVE_TOOL = ("для RAR и 7z нужна программа распаковки, а на этом компьютере её не нашлось. "
                   "Windows: установите WinRAR или 7-Zip. Linux: пакет libarchive-tools (bsdtar) "
                   "или unar; для Streamlit Cloud добавьте строку libarchive-tools в packages.txt. "
                   "Либо перепакуйте схему в ZIP.")

def _is_bsdtar(cmd):
    try:
        r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        return "bsdtar" in (r.stdout + r.stderr).lower()
    except (OSError, subprocess.SubprocessError):
        return False

@st.cache_resource(show_spinner=False)
def archive_tools():
    """Программы распаковки RAR/7z, найденные на этом компьютере: [(вид, путь)]"""
    found = []

    def add(kind, path):
        if path and (kind, path) not in found:
            found.append((kind, path))

    add("unrar", shutil.which("unrar"))
    add("7z", shutil.which("7z") or shutil.which("7zz"))
    if os.name == "nt":
        for base in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
            for kind, rel in (("unrar", r"WinRAR\UnRAR.exe"), ("7z", r"7-Zip\7z.exe")):
                path = os.path.join(base, rel)
                if os.path.isfile(path):
                    add(kind, path)
    add("bsdtar", shutil.which("bsdtar"))
    tar = shutil.which("tar")
    if tar and _is_bsdtar(tar):  # встроенный tar в Windows 10/11 — это bsdtar, он умеет RAR
        add("bsdtar", tar)
    add("unar", shutil.which("unar"))
    return found

def _archive_cmd(kind, tool, archive, out):
    return {
        "unrar": [tool, "x", "-y", "-p-", "-idq", archive, out + os.sep],
        "7z": [tool, "x", "-y", "-p", f"-o{out}", archive],
        "bsdtar": [tool, "-x", "-f", archive, "-C", out],
        "unar": [tool, "-q", "-f", "-p", "", "-o", out, archive],
    }[kind]

def _collect_xsd(root):
    """Все .xsd из распакованной папки (без симлинков и выходов за её пределы)"""
    files, total = {}, 0
    root_real = os.path.realpath(root)
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            if not name.lower().endswith(".xsd") or os.path.islink(path):
                continue
            if not os.path.realpath(path).startswith(root_real + os.sep):
                continue
            total += os.path.getsize(path)
            if total > MAX_ARCHIVE_BYTES:
                return files
            with open(path, "rb") as f:
                files[os.path.relpath(path, root).replace(os.sep, "/")] = f.read()
    return files

def extract_archive(data, filename):
    """RAR / 7z → ({путь: байты} для .xsd, ошибка). Распаковывает внешней программой во временную папку."""
    ext = os.path.splitext(filename)[1].lower()
    tools = [(k, t) for k, t in archive_tools() if not (ext == ".7z" and k == "unrar")]
    if not tools:
        return {}, NO_ARCHIVE_TOOL
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "upload" + ext)
        with open(archive, "wb") as f:
            f.write(data)
        for i, (kind, tool) in enumerate(tools):
            out = os.path.join(tmp, f"out{i}")
            os.makedirs(out)
            try:
                r = subprocess.run(_archive_cmd(kind, tool, archive, out), stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=ARCHIVE_TIMEOUT)
            except subprocess.TimeoutExpired:
                errors.append(f"{kind}: распаковка дольше {ARCHIVE_TIMEOUT} с")
                continue
            except OSError as e:
                errors.append(f"{kind}: {e}")
                continue
            files = _collect_xsd(out)
            if files:
                return files, ""
            detail = (r.stderr or r.stdout).decode("utf-8", errors="replace").strip()
            if r.returncode == 0 and not detail:
                return {}, "в архиве нет .xsd файлов"
            errors.append(f"{kind}: {detail[:200] or 'не удалось распаковать'}")
    hint = " Возможно, архив защищён паролем или повреждён." if errors else ""
    return {}, "не удалось распаковать (" + "; ".join(errors) + ")." + hint

def read_xsd_uploads(uploads):
    """Загруженные XSD и архивы ZIP / RAR / 7z → ({путь: байты}, предупреждения). Из архивов берутся только .xsd"""
    files, warnings = {}, []
    for up in uploads:
        low = up.name.lower()
        if low.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(up.getvalue())) as z:
                    total = 0
                    for info in z.infolist():
                        name = info.filename
                        if not info.flag_bits & 0x800:
                            # Имя не в UTF-8 — архивы из Windows обычно хранят его в cp866
                            try:
                                name = name.encode("cp437").decode("cp866")
                            except UnicodeError:
                                pass
                        if info.is_dir() or not name.lower().endswith(".xsd"):
                            continue
                        total += info.file_size
                        if total > MAX_ARCHIVE_BYTES:
                            warnings.append(f"{up.name}: больше 50 МБ схем, остальные файлы пропущены")
                            break
                        files[name] = z.read(info)
            except zipfile.BadZipFile:
                warnings.append(f"{up.name}: не удалось открыть ZIP-архив")
        elif low.endswith((".rar", ".7z")):
            extracted, error = extract_archive(up.getvalue(), low)
            if error:
                warnings.append(f"{up.name}: {error}")
            files.update(extracted)
        else:
            files[up.name] = up.getvalue()
    return files, warnings

def xsd_input_block():
    """Ввод XSD: файлы / ZIP или текст. Возвращает {путь: байты} или None."""
    st.subheader("📐 XSD схема")
    mode = st.radio("Способ загрузки:", ["📁 Файлы или архив", "📝 Текст"],
                    key="xsd_mode", horizontal=True)
    if mode == "📁 Файлы или архив":
        uploads = st.file_uploader(
            "Один XSD, все XSD схемы сразу или архив (ZIP, RAR, 7z)",
            type=["xsd", "xml", "zip", "rar", "7z"], accept_multiple_files=True, key="xsd_files",
            help="Если схема подключает другие файлы через xs:import / xs:include, "
                 "загрузите их все вместе или одним архивом.")
        if not uploads:
            return None
        files, warnings = read_xsd_uploads(uploads)
        for w in warnings:
            st.warning(w)
        return files or None
    text = st.text_area("Вставьте содержимое", height=350, key="xsd_text")
    if text.strip():
        return {"schema.xsd": XML_DECLARATION_RE.sub('', text, count=1).strip().encode('utf-8')}
    return None

def log_rows(error_log, xml_root=None, package=None):
    """Превращает лог ошибок lxml в список словарей (для таблицы и кеша)"""
    ns = collect_namespaces(xml_root) if xml_root is not None else {}
    rows = []
    for e in error_log:
        row = {}
        if package is not None:
            fname = package.short_name(e.filename)
            row["Файл"] = "(файл не найден в пакете)" if fname == "<string>" else fname
        row.update({"Строка": e.line, "Колонка": e.column, "Уровень": e.level_name})
        if xml_root is not None:
            row["Элемент"] = error_element_path(e, xml_root, ns)
        row["Сообщение"] = e.message
        rows.append(row)
    return rows

@st.cache_data(show_spinner=False, max_entries=10)
def xsd_package_info(files):
    """Кандидаты в главную схему (на которые никто не ссылается). Возвращает (список, ошибка)."""
    try:
        return XsdPackage(files).main_candidates(), ""
    except ValueError as e:
        return [], str(e)

def _schema_tree(files, main):
    pkg = XsdPackage(files)
    return pkg, XsdTree([pkg.root(p) for p in pkg.reachable(main)], pkg.root(main))

@st.cache_data(show_spinner=False, max_entries=10)
def xsd_global_elements(files, main):
    """Глобальные элементы главной схемы и недостающие файлы. Возвращает (корни, недостающие, ошибка)."""
    try:
        pkg, tree = _schema_tree(files, main)
        return tree.global_elements, pkg.missing_references(main), ""
    except ValueError as e:
        return [], [], str(e)

@st.cache_data(show_spinner=False, max_entries=10)
def build_xsd_tree(files, main, root_name):
    _, tree = _schema_tree(files, main)
    return tree.build(root_name), tree.truncated

@st.cache_data(show_spinner=False, max_entries=10)
def run_xml_check(files, main, xml_bytes):
    """Разбор XML, компиляция схемы и валидация. Результат — простые данные для кеша."""
    res = {"stage": "", "msg": "", "rows": [], "presence": None, "err_by_path": {}, "xml_root": None}

    # XML разбираем первым: присутствие элементов нужно дереву даже при ошибке в схеме
    try:
        xml_doc = etree.fromstring(xml_bytes, safe_parser())
    except etree.XMLSyntaxError as e:
        res.update(stage="xml_syntax", rows=log_rows(e.error_log))
        return res
    res["presence"] = xml_presence(xml_doc)
    res["xml_root"] = etree.QName(xml_doc).localname

    pkg = XsdPackage(files)
    try:
        schema = pkg.schema(main)
    except (etree.XMLSyntaxError, ValueError) as e:
        res.update(stage="xsd_syntax", msg=str(e))
        return res
    except etree.XMLSchemaParseError as e:
        res.update(stage="xsd_schema", rows=log_rows(e.error_log, package=pkg))
        return res

    if schema.validate(xml_doc):
        res["stage"] = "ok"
    else:
        rows = log_rows(schema.error_log, xml_doc)
        err_by_path = {}
        for r in rows:
            if r["Элемент"]:
                err_by_path.setdefault(r["Элемент"], []).append(r["Сообщение"])
        res.update(stage="invalid", rows=rows, err_by_path=err_by_path)
    return res

def show_error_context(xml_bytes, errors_df, max_items=20):
    """Показывает строки XML, в которых найдены ошибки"""
    try:
        lines = xml_bytes.decode('utf-8', errors='replace').splitlines()
    except Exception:
        return
    shown = 0
    for line_no in sorted(set(errors_df["Строка"].dropna().astype(int))):
        if shown >= max_items:
            st.caption(f"Показаны первые {max_items} строк с ошибками.")
            break
        if 1 <= line_no <= len(lines):
            start = max(line_no - 2, 1)
            end = min(line_no + 1, len(lines))
            snippet = "\n".join(
                f"{'>>' if i == line_no else '  '} {i:>5} | {lines[i - 1]}"
                for i in range(start, end + 1)
            )
            st.code(snippet, language="")
            shown += 1

# --- Основной интерфейс ---

tabs = st.tabs([
    "🎲 Генератор",
    "🔠 Регистры текста",
    "🧮 Подсчёт символов",
    "⚔️ Сравнение строк",
    "🔐 JWT кодер",
    "📁 Base64 конвертер",
    "📊 Сравнение Excel",
    "✅ Валидация XML",  # Новая вкладка
])

# 1. Генератор
with tabs[0]:
    st.header("🎲 Генератор текста по символам")
    generator_type = st.radio("Выберите тип генератора:", ["Случайные символы", "GUID"])

    if generator_type == "Случайные символы":
        alphabet_type = st.radio("Выберите тип символов:", ["Кириллица", "Латиница", "Гибрид"])
        use_special = st.checkbox("Добавить спецсимволы и цифры")
        num_chars = st.number_input("Количество символов:", min_value=1, value=12, step=1)

        if 'generated_text' not in st.session_state:
            st.session_state.generated_text = ''

        if st.button("🎲 Сгенерировать"):
            if alphabet_type == "Кириллица":
                alphabet = cyrillic_letters
            elif alphabet_type == "Латиница":
                alphabet = latin_letters
            else:
                alphabet = cyrillic_letters + latin_letters

            if use_special:
                alphabet += special_chars

            st.session_state.generated_text = ''.join(random.choice(alphabet) for _ in range(num_chars))

        if st.session_state.generated_text:
            st.code(st.session_state.generated_text, language="")
            copy_to_clipboard(st.session_state.generated_text, "copy-btn-gen")

    else:  # Генерация GUID
        if st.button("🎲 Сгенерировать GUID"):
            generated_guid = str(uuid.uuid4())
            st.code(generated_guid, language="")
            copy_to_clipboard(generated_guid, "copy-btn-guid")

# 2. Регистры
with tabs[1]:
    st.header("🔠 Преобразование регистра текста")
    user_text = st.text_area("Введите текст:", height=200)
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("в нижний регистр"):
            result = user_text.lower()
            st.text_area("Результат:", result, height=150, key="lower")
            copy_to_clipboard(result, "copy-btn-lower")

    with col2:
        if st.button("В ВЕРХНИЙ РЕГИСТР"):
            result = user_text.upper()
            st.text_area("Результат:", result, height=150, key="upper")
            copy_to_clipboard(result, "copy-btn-upper")

    with col3:
        if st.button("Как в предложении"):
            result = '. '.join([s.strip().capitalize() for s in user_text.split('.')])
            st.text_area("Результат:", result, height=150, key="sentence")
            copy_to_clipboard(result, "copy-btn-sentence")

# 3. Подсчет
with tabs[2]:
    st.header("🧮 Подсчёт количества символов")
    count_text = st.text_area("Введите текст для подсчёта:", height=200, key="count_text_input")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("📊 Посчитать"):
            if count_text:
                with col2:
                    st.write(f"**Всего символов:** {len(count_text)}")
                with col3:
                    st.write(f"**Без пробелов:** {len(count_text.replace(' ', ''))}")
                with col4:
                    st.write(f"**Количество слов:** {len(count_text.split())}")

# 4. Сравнение строк
with tabs[3]:
    st.header("⚔️ Сравнение двух текстов")
    col1, col2 = st.columns(2)

    with col1:
        text1 = st.text_area("Текст 1", height=250, key="diff_input_1")
    with col2:
        text2 = st.text_area("Текст 2", height=250, key="diff_input_2")

    if text1 and text2:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Текст 1 с подсветкой:**")
            st.markdown(f"""
                <div style='white-space: pre-wrap; overflow-wrap: break-word; border:1px solid #ccc; padding:10px; border-radius:6px'>
                    {get_highlighted(text2, text1)}
                </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown("**Текст 2 с подсветкой:**")
            st.markdown(f"""
                <div style='white-space: pre-wrap; overflow-wrap: break-word; border:1px solid #ccc; padding:10px; border-radius:6px'>
                    {get_highlighted(text1, text2)}
                </div>
            """, unsafe_allow_html=True)

# 5. JWT
with tabs[4]:
    st.header("🔐 JWT кодер / декодер")
    st.subheader("Декодировать JWT")

    algorithm = st.selectbox("Алгоритм", AVAILABLE_ALGORITHMS, key="alg_select")
    jwt_input = st.text_area("Вставьте JWT токен", key="jwt_input")
    secret = st.text_input("Секрет (опционально)", type="password")

    if st.button("🧩 Декодировать"):
        try:
            decoded = jwt.decode(jwt_input, secret, algorithms=[algorithm]) if secret else jwt.decode(jwt_input, options={"verify_signature": False})
            st.code(json.dumps(decoded, indent=2, ensure_ascii=False), language="json")
        except InvalidTokenError as e:
            st.error(f"Неверный токен: {str(e)}")

    st.subheader("Создать JWT")
    payload_input = st.text_area("Введите JSON payload", value='{"sub": "1234567890", "name": "John Doe", "iat": 1516239022}', key="jwt_payload")
    secret_encode = st.text_input("Секрет для подписи", type="password", key="jwt_secret")

    if st.button("🔐 Закодировать"):
        try:
            payload_dict = json.loads(payload_input)
            token = jwt.encode(payload_dict, secret_encode, algorithm=algorithm)
            st.text_area("Сгенерированный JWT", value=token, height=100, key="jwt_result")
            copy_to_clipboard(token, "copy-jwt")
        except Exception as e:
            st.error(f"Ошибка кодирования: {str(e)}")

# 6. Base64
with tabs[5]:
    st.header("📁 Base64 конвертер")

    conversion_type = st.radio("Выберите тип конвертации:",
                              ["Текст в Base64", "Base64 в текст", "Файл в Base64", "Base64 в файл"])

    if conversion_type == "Текст в Base64":
        text_to_encode = st.text_area("Введите текст для кодирования:", height=150)
        if st.button("🔒 Кодировать в Base64"):
            if text_to_encode:
                encoded = base64.b64encode(text_to_encode.encode('utf-8')).decode('utf-8')
                st.text_area("Результат Base64:", encoded, height=150)
                copy_to_clipboard(encoded, "copy-base64-encode")
            else:
                st.warning("Введите текст для кодирования")

    elif conversion_type == "Base64 в текст":
        base64_to_decode = st.text_area("Введите Base64 для декодирования:", height=150)
        if st.button("🔓 Декодировать из Base64"):
            if base64_to_decode:
                try:
                    decoded = base64.b64decode(base64_to_decode).decode('utf-8')
                    st.text_area("Декодированный текст:", decoded, height=150)
                    copy_to_clipboard(decoded, "copy-base64-decode")
                except Exception as e:
                    st.error(f"Ошибка декодирования: {str(e)}")
            else:
                st.warning("Введите Base64 строку для декодирования")

    elif conversion_type == "Файл в Base64":
        uploaded_file = st.file_uploader("Загрузите файл для кодирования", type=None)
        if uploaded_file is not None:
            if st.button("📁 Кодировать файл в Base64"):
                file_bytes = uploaded_file.read()
                encoded_file = base64.b64encode(file_bytes).decode('utf-8')
                st.text_area("Base64 представление файла:", encoded_file, height=200)
                copy_to_clipboard(encoded_file, "copy-file-base64")

                st.download_button(
                    label="📥 Скачать Base64 как файл",
                    data=encoded_file,
                    file_name=f"{uploaded_file.name}.base64.txt",
                    mime="text/plain"
                )

    elif conversion_type == "Base64 в файл":
        base64_file_input = st.text_area("Введите Base64 строку файла:", height=150)
        original_filename = st.text_input("Имя файла для сохранения (с расширением):", "decoded_file.bin")

        if st.button("💾 Восстановить файл из Base64"):
            if base64_file_input:
                try:
                    file_data = base64.b64decode(base64_file_input)
                    st.download_button(
                        label="📥 Скачать восстановленный файл",
                        data=file_data,
                        file_name=original_filename,
                        mime="application/octet-stream"
                    )
                    st.success("Файл готов к скачиванию!")
                except Exception as e:
                    st.error(f"Ошибка декодирования файла: {str(e)}")
            else:
                st.warning("Введите Base64 строку файла")

# 7. Сравнение Excel
with tabs[6]:
    st.header("📊 Сравнение Excel таблиц")
    st.markdown("Загрузите два файла, выберите ключ (ID/Артикул) и получите отчет о добавленных, удаленных и измененных строках.")

    col_upl1, col_upl2 = st.columns(2)
    with col_upl1:
        file1 = st.file_uploader("Загрузите ПЕРВЫЙ файл (Старый)", type=["xlsx", "xls"], key="excel_old")
    with col_upl2:
        file2 = st.file_uploader("Загрузите ВТОРОЙ файл (Новый)", type=["xlsx", "xls"], key="excel_new")

    if file1 and file2:
        try:
            xl1 = pd.ExcelFile(file1)
            xl2 = pd.ExcelFile(file2)

            common_sheets = list(set(xl1.sheet_names) & set(xl2.sheet_names))

            if common_sheets:
                selected_sheet = st.selectbox("Выберите лист для сравнения", common_sheets, key="excel_sheet_select")
                df1 = pd.read_excel(file1, sheet_name=selected_sheet)
                df2 = pd.read_excel(file2, sheet_name=selected_sheet)
            else:
                st.warning("Листы не совпадают, используется первый лист.")
                df1 = pd.read_excel(file1, sheet_name=0)
                df2 = pd.read_excel(file2, sheet_name=0)

            df1 = df1.fillna("")
            df2 = df2.fillna("")

            common_columns = list(set(df1.columns) & set(df2.columns))
            key_col = st.selectbox(
                "Выберите ключевую колонку для сверки (ID, Артикул)",
                options=["-- Без ключа (сравнение строк) --"] + common_columns,
                key="excel_key_col"
            )

            if st.button("🚀 Сравнить файлы", key="excel_btn_compare", type="primary"):
                result_dfs = {}

                if key_col != "-- Без ключа (сравнение строк) --":
                    if not df1[key_col].is_unique or not df2[key_col].is_unique:
                        st.error(f"Ошибка: значения в колонке '{key_col}' не уникальны!")
                    else:
                        df1_idx = df1.set_index(key_col)
                        df2_idx = df2.set_index(key_col)

                        removed_keys = df1_idx.index.difference(df2_idx.index)
                        df_removed = df1_idx.loc[removed_keys].reset_index()

                        added_keys = df2_idx.index.difference(df1_idx.index)
                        df_added = df2_idx.loc[added_keys].reset_index()

                        common_keys = df1_idx.index.intersection(df2_idx.index)
                        cols_to_compare = [c for c in common_columns if c != key_col]

                        mask_diff = (df1_idx.loc[common_keys, cols_to_compare] != df2_idx.loc[common_keys, cols_to_compare]).any(axis=1)
                        changed_keys = common_keys[mask_diff]
                        df_changed = df2_idx.loc[changed_keys].reset_index()

                        if not df_changed.empty:
                            df_changed['LOG_ИЗМЕНЕНИЙ'] = df_changed.set_index(key_col).apply(
                                lambda row: highlight_excel_diff(row, cols_to_compare, df1_idx, df2_idx),
                                axis=1
                            ).values
                            cols = ['LOG_ИЗМЕНЕНИЙ'] + [c for c in df_changed.columns if c != 'LOG_ИЗМЕНЕНИЙ']
                            df_changed = df_changed[cols]

                        result_dfs['Added'] = df_added
                        result_dfs['Removed'] = df_removed
                        result_dfs['Changed'] = df_changed

                        t1, t2, t3 = st.tabs([f"🟢 Добавлено ({len(df_added)})", f"🔴 Удалено ({len(df_removed)})", f"🟡 Изменено ({len(df_changed)})"])
                        with t1: st.dataframe(df_added, use_container_width=True)
                        with t2: st.dataframe(df_removed, use_container_width=True)
                        with t3: st.dataframe(df_changed, use_container_width=True)

                else:
                    rows_old = set(tuple(x) for x in df1.to_numpy())
                    rows_new = set(tuple(x) for x in df2.to_numpy())

                    df_added = pd.DataFrame(list(rows_new - rows_old), columns=df2.columns)
                    df_removed = pd.DataFrame(list(rows_old - rows_new), columns=df1.columns)

                    result_dfs['Added_Rows'] = df_added
                    result_dfs['Removed_Rows'] = df_removed

                    c1, c2 = st.columns(2)
                    with c1:
                        st.subheader("🟢 Новые строки")
                        st.dataframe(df_added, use_container_width=True)
                    with c2:
                        st.subheader("🔴 Пропавшие строки")
                        st.dataframe(df_removed, use_container_width=True)

                if result_dfs:
                    st.download_button(
                        label="📥 Скачать результат (Excel)",
                        data=to_excel(result_dfs),
                        file_name="comparison_result.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="excel_download"
                    )

        except Exception as e:
            st.error(f"Ошибка при обработке файлов: {e}")

# 8. Валидация XML по XSD
def xml_validation_tab():
    st.header("✅ Валидация XML по XSD схеме")
    st.markdown("Загрузите XSD схему — появится её структура. Добавьте XML, чтобы проверить его по схеме "
                "и увидеть в дереве, каких элементов не хватает и где ошибки.")

    col_xsd, col_xml = st.columns(2)
    with col_xsd:
        xsd_files = xsd_input_block()
    with col_xml:
        xml_bytes = xml_input_block("📄 XML документ", "xml", ["xml"])

    if not xsd_files:
        st.info("Загрузите или вставьте XSD схему")
        return

    candidates, pkg_err = xsd_package_info(xsd_files)
    if pkg_err:
        st.error(f"❌ {pkg_err}")
        return

    if len(candidates) > 1:
        main = st.selectbox("Главная схема", candidates, key="xsd_main",
                            help="Файл, с которого начинается схема. Остальные подключаются "
                                 "из него через xs:import / xs:include.")
    else:
        main = candidates[0]
    if len(xsd_files) > 1:
        st.caption(f"Файлов схемы в пакете: {len(xsd_files)}")

    roots, missing, tree_err = xsd_global_elements(xsd_files, main)
    if missing:
        shown = "\n".join(f"- `{m}`" for m in missing[:8])
        more = f"\n- … и ещё {len(missing) - 8}" if len(missing) > 8 else ""
        st.warning("Схема ссылается на файлы, которых нет среди загруженных — "
                   "добавьте их или загрузите всю папку архивом:\n" + shown + more)

    check = run_xml_check(xsd_files, main, xml_bytes) if xml_bytes else None
    rows = check["rows"] if check else []

    # Итог проверки
    if check:
        stage = check["stage"]
        if stage == "ok":
            st.success("✅ XML соответствует XSD схеме")
        elif stage == "invalid":
            st.error(f"❌ XML не прошёл валидацию. Найдено ошибок: {len(rows)}")
        elif stage == "xml_syntax":
            st.error("❌ XML не является корректно сформированным (well-formed)")
        elif stage == "xsd_syntax":
            st.error(f"❌ {check['msg']}")
        elif stage == "xsd_schema":
            st.error("❌ Ошибка в XSD схеме — проверить XML по ней нельзя. Подробности на вкладке «Ошибки».")

    tab_tree, tab_errors = st.tabs(["🌳 Структура схемы", f"📋 Ошибки ({len(rows)})"])

    with tab_tree:
        if tree_err:
            st.error(f"❌ {tree_err}")
        elif not roots:
            st.warning("В главной схеме нет глобальных элементов (xs:element верхнего уровня) — "
                       "нечего показать в качестве корня. Возможно, выбрана не та главная схема.")
        else:
            xml_root = check["xml_root"] if check else None
            default_idx = roots.index(xml_root) if xml_root in roots else 0
            if len(roots) > 1:
                root_name = st.selectbox("Корневой элемент", roots, index=default_idx,
                                         key="xsd_tree_root")
            else:
                root_name = roots[0]

            tree_node, truncated = build_xsd_tree(xsd_files, main, root_name)
            presence = check["presence"] if check else None
            err_by_path = check["err_by_path"] if check else {}
            components.html(render_tree(tree_node, presence, err_by_path),
                            height=720, scrolling=True)

            if truncated:
                st.caption("Схема очень большая — дерево показано не полностью.")
            if xml_root and xml_root != root_name:
                st.caption(f"Корень XML — «{xml_root}», а в дереве выбран «{root_name}»: "
                           "отметки присутствия могут не совпасть.")

    with tab_errors:
        if not xml_bytes:
            st.info("Загрузите XML, чтобы проверить его по схеме")
        elif not rows:
            if check["stage"] == "ok":
                st.success("Ошибок нет")
            else:
                st.info("Подробностей нет — см. сообщение выше")
        else:
            errors_df = pd.DataFrame(rows)
            st.dataframe(errors_df, use_container_width=True, hide_index=True)

            if check["stage"] in ("invalid", "xml_syntax"):
                with st.expander("📍 Фрагменты XML с ошибками"):
                    show_error_context(xml_bytes, errors_df)

            st.download_button(
                label="📥 Скачать список ошибок (CSV)",
                data=errors_df.to_csv(index=False, sep=';').encode('utf-8-sig'),
                file_name="xml_validation_errors.csv",
                mime="text/csv",
                key="xml_errors_download",
            )

with tabs[7]:
    xml_validation_tab()
