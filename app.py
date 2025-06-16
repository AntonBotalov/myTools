import streamlit as st
import random
import string
from difflib import SequenceMatcher
import html
import streamlit.components.v1 as components
import jwt
import json
from jwt.exceptions import InvalidTokenError
import uuid  # Добавлен импорт модуля uuid

st.set_page_config(page_title="Утилиты для текста", layout="wide")

cyrillic_letters = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
latin_letters = string.ascii_lowercase
special_chars = string.punctuation + string.digits

AVAILABLE_ALGORITHMS = ["HS256"]

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

tabs = st.tabs(["🎲 Генератор символов", "🔠 Регистры текста", "🧮 Подсчёт символов", "⚔️ Сравнение строк", "🔐 JWT кодер / декодер"])

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