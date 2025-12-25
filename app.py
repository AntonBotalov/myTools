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
import pandas as pd  # Добавлена библиотека pandas

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

# --- Основной интерфейс ---

tabs = st.tabs([
    "🎲 Генератор", 
    "🔠 Регистры текста", 
    "🧮 Подсчёт символов", 
    "⚔️ Сравнение строк", 
    "🔐 JWT кодер", 
    "📁 Base64 конвертер",
    "📊 Сравнение Excel"  # Новая вкладка
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

# 7. Сравнение Excel (НОВОЕ)
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
            # Чтение имен листов
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

            # Выбор ключа
            common_columns = list(set(df1.columns) & set(df2.columns))
            key_col = st.selectbox(
                "Выберите ключевую колонку для сверки (ID, Артикул)", 
                options=["-- Без ключа (сравнение строк) --"] + common_columns,
                key="excel_key_col"
            )

            if st.button("🚀 Сравнить файлы", key="excel_btn_compare", type="primary"):
                result_dfs = {}
                
                if key_col != "-- Без ключа (сравнение строк) --":
                    # Сравнение по ключу
                    if not df1[key_col].is_unique or not df2[key_col].is_unique:
                        st.error(f"Ошибка: значения в колонке '{key_col}' не уникальны!")
                    else:
                        df1_idx = df1.set_index(key_col)
                        df2_idx = df2.set_index(key_col)

                        # Удаленные
                        removed_keys = df1_idx.index.difference(df2_idx.index)
                        df_removed = df1_idx.loc[removed_keys].reset_index()
                        
                        # Добавленные
                        added_keys = df2_idx.index.difference(df1_idx.index)
                        df_added = df2_idx.loc[added_keys].reset_index()
                        
                        # Измененные
                        common_keys = df1_idx.index.intersection(df2_idx.index)
                        cols_to_compare = [c for c in common_columns if c != key_col]
                        
                        # Маска изменений
                        mask_diff = (df1_idx.loc[common_keys, cols_to_compare] != df2_idx.loc[common_keys, cols_to_compare]).any(axis=1)
                        changed_keys = common_keys[mask_diff]
                        df_changed = df2_idx.loc[changed_keys].reset_index()

                        # Детализация
                        if not df_changed.empty:
                            df_changed['LOG_ИЗМЕНЕНИЙ'] = df_changed.set_index(key_col).apply(
                                lambda row: highlight_excel_diff(row, cols_to_compare, df1_idx, df2_idx), 
                                axis=1
                            ).values
                            # Перенос лога в начало
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
                    # Сравнение множеств
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

                # Кнопка скачивания
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
