import streamlit as st
import random
import string
import streamlit.components.v1 as components

st.set_page_config(page_title="Утилиты для текста", layout="centered")

# --- Константы --- #
cyrillic_letters = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
latin_letters = string.ascii_lowercase
special_chars = string.punctuation + string.digits

# --- JS для копирования текста --- #
def copy_to_clipboard(text, button_key):
    components.html(f"""
        <script>
        function copyText() {{
            navigator.clipboard.writeText(`{text}`).then(function() {{
                const btn = document.getElementById('{button_key}');
                btn.innerText = '✅ Скопировано';
                setTimeout(() => btn.innerText = '📋 Копировать', 1500);
            }});
        }}
        </script>
        <button id="{button_key}" onclick="copyText()" style="margin-top: 8px; padding: 6px 14px; border-radius: 6px; background-color: #21A038; color: white; border: none; cursor: pointer;">📋 Копировать</button>
    """, height=45)

# --- Вкладки --- #
tabs = st.tabs(["🔡 Генератор символов", "🧰 Регистры текста"])

# --- Вкладка 1: Генератор символов --- #
with tabs[0]:
    st.header("🔡 Генератор текста по символам")

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

# --- Вкладка 2: Преобразование регистра --- #
with tabs[1]:
    st.header("🧰 Преобразование регистра текста")

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
