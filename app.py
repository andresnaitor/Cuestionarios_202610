# app.py — Streamlit quiz app (Kahoot-like)
# Run locally:  streamlit run app.py
# Deploy free:  Streamlit Community Cloud (share.streamlit.io)

import time
import random
import string
import threading
from dataclasses import dataclass, field
from typing import Dict, List

import streamlit as st

# -----------------------------
# Shared state (process-wide)
# -----------------------------

@dataclass
class Question:
    qid: int
    text: str
    A: str
    B: str
    C: str
    D: str
    correct: str  # 'A'|'B'|'C'|'D'

@dataclass
class Quiz:
    title: str = ""
    time_per_q: int = 20
    questions: List[Question] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    # map qid -> list of {name, answer, correct}
    responses: Dict[int, List[Dict]] = field(default_factory=dict)
    # scores: name -> points
    scores: Dict[str, int] = field(default_factory=dict)
    # live state
    started: bool = False
    current_q: int = 0
    reveal: bool = False
    started_at: float = 0.0

class QuizManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.quizzes: Dict[str, Quiz] = {}

    def new_pin(self) -> str:
        with self.lock:
            while True:
                pin = f"{random.randint(1000,9999)}"
                if pin not in self.quizzes:
                    self.quizzes[pin] = Quiz()
                    return pin

    def get(self, pin: str) -> Quiz | None:
        with self.lock:
            return self.quizzes.get(pin)

    def update(self, pin: str, quiz: Quiz):
        with self.lock:
            self.quizzes[pin] = quiz

# one manager per process
@st.cache_resource
def get_manager():
    return QuizManager()

mgr = get_manager()

# -----------------------------
# Small UI helpers
# -----------------------------

def pill(text):
    st.markdown(f"<span style='background:#eef2ff;padding:4px 10px;border-radius:999px'>{text}</span>", unsafe_allow_html=True)

# -----------------------------
# Pages
# -----------------------------

def page_teacher():
    st.title("Quices en Vivo — Docente")

    col1, col2 = st.columns([1,2])
    with col1:
        st.subheader("1) Crear / Configurar")
        if 'active_pin' not in st.session_state:
            st.session_state.active_pin = None

        if st.button("Generar PIN", type="primary"):
            st.session_state.active_pin = mgr.new_pin()

        pin = st.session_state.active_pin
        if pin:
            pill(f"PIN: {pin}")
            quiz = mgr.get(pin)
            quiz.title = st.text_input("Título", quiz.title, placeholder="Ej. Repaso Semana 3")
            quiz.time_per_q = st.number_input("Segundos por pregunta", 5, 300, value=quiz.time_per_q, step=5)
            mgr.update(pin, quiz)

            st.divider()
            st.caption("Añadir pregunta")
            qtext = st.text_area("Enunciado", height=100)
            A = st.text_input("Opción A")
            B = st.text_input("Opción B")
            C = st.text_input("Opción C")
            D = st.text_input("Opción D")
            correct = st.selectbox("Respuesta correcta", ['A','B','C','D'])
            if st.button("Agregar pregunta", type="secondary"):
                if all([qtext, A, B, C, D]):
                    qid = (quiz.questions[-1].qid + 1) if quiz.questions else 1
                    quiz.questions.append(Question(qid, qtext, A, B, C, D, correct))
                    mgr.update(pin, quiz)
                    st.success("Pregunta agregada")
                else:
                    st.error("Completa todas las opciones")

    with col2:
        st.subheader("2) Preguntas del cuestionario")
        pin = st.session_state.get('active_pin')
        if not pin:
            st.info("Genera un PIN para comenzar")
            return
        quiz = mgr.get(pin)
        if not quiz.questions:
            st.warning("Aún no hay preguntas")
        else:
            st.dataframe(
                [{
                    "#": q.qid,
                    "Pregunta": q.text,
                    "A": q.A,
                    "B": q.B,
                    "C": q.C,
                    "D": q.D,
                    "Correcta": q.correct
                } for q in quiz.questions],
                use_container_width=True,
                hide_index=True
            )
        if st.button("Borrar todas", type="primary"):
            quiz.questions = []
            quiz.responses = {}
            quiz.scores = {}
            quiz.started = False
            quiz.current_q = 0
            quiz.reveal = False
            quiz.started_at = 0.0
            mgr.update(pin, quiz)
            st.toast("Cuestionario reiniciado")

        st.subheader("3) Control en vivo")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Preguntas", len(quiz.questions))
        with c2:
            st.metric("Participantes", len(quiz.participants))
        with c3:
            st.metric("Actual", quiz.current_q if quiz.started else 0)
        with c4:
            st.metric("Tiempo/ pregunta", quiz.time_per_q)

        colA, colB, colC = st.columns(3)
        with colA:
            if not quiz.started:
                st.button("Iniciar", type="primary", disabled=not quiz.questions, on_click=start_quiz, args=(pin,))
            else:
                st.button("← Anterior", disabled=quiz.current_q<=1, on_click=prev_q, args=(pin,))
        with colB:
            if quiz.started:
                st.button("Siguiente →", disabled=quiz.current_q>=len(quiz.questions), on_click=next_q, args=(pin,))
        with colC:
            if quiz.started:
                st.button("Revelar / Ocultar", on_click=toggle_reveal, args=(pin,))
        if quiz.started:
            st.button("Terminar sesión", type="secondary", on_click=stop_quiz, args=(pin,))

        # Live panel
        st.divider()
        if not quiz.started:
            st.info("Cuando inicies, los estudiantes podrán unirse con el PIN y responder en vivo.")
            return
        # auto-refresh
        st.experimental_rerun() if st.button("Actualizar") else None

        # current question
        qrow = next(q for q in quiz.questions if q.qid == quiz.current_q)
        st.markdown(f"### Pregunta {quiz.current_q}/{len(quiz.questions)}")

        st.markdown(qrow.text, unsafe_allow_html=False)
        st.write(f"A) {qrow.A}")
        st.write(f"B) {qrow.B}")
        st.write(f"C) {qrow.C}")
        st.write(f"D) {qrow.D}")

        # countdown
        left = max(int(quiz.time_per_q - (time.time() - quiz.started_at)), 0)
        pill(f"Tiempo restante: {left}s")

        # responses
        df = quiz.responses.get(quiz.current_q, [])
        counts = {k:0 for k in ['A','B','C','D']}
        for r in df:
            counts[r['answer']] = counts.get(r['answer'], 0) + 1
        st.markdown("#### Respuestas en tiempo real")
        st.write({k: counts.get(k,0) for k in ['A','B','C','D']})
        if quiz.reveal:
            st.success(f"Respuesta correcta: {qrow.correct}")

        # leaderboard
        st.markdown("#### Ranking")
        if not quiz.scores:
            st.caption("Sin respuestas correctas aún")
        else:
            sorted_scores = sorted(quiz.scores.items(), key=lambda kv: (-kv[1], kv[0]))
            st.table({"Nombre": [k for k,_ in sorted_scores], "Puntos": [v for _,v in sorted_scores]})


def start_quiz(pin: str):
    quiz = mgr.get(pin)
    if not quiz or not quiz.questions:
        return
    quiz.started = True
    quiz.current_q = 1
    quiz.reveal = False
    quiz.started_at = time.time()
    quiz.responses[1] = []
    mgr.update(pin, quiz)


def next_q(pin: str):
    quiz = mgr.get(pin)
    if quiz and quiz.current_q < len(quiz.questions):
        quiz.current_q += 1
        quiz.reveal = False
        quiz.started_at = time.time()
        quiz.responses.setdefault(quiz.current_q, [])
        mgr.update(pin, quiz)


def prev_q(pin: str):
    quiz = mgr.get(pin)
    if quiz and quiz.current_q > 1:
        quiz.current_q -= 1
        quiz.reveal = False
        quiz.started_at = time.time()
        mgr.update(pin, quiz)


def toggle_reveal(pin: str):
    quiz = mgr.get(pin)
    if quiz:
        quiz.reveal = not quiz.reveal
        mgr.update(pin, quiz)


def stop_quiz(pin: str):
    quiz = mgr.get(pin)
    if quiz:
        quiz.started = False
        quiz.current_q = 0
        quiz.reveal = False
        quiz.started_at = 0.0
        mgr.update(pin, quiz)


# ---------------------------------
# Student page
# ---------------------------------

def page_student():
    st.title("Quices en Vivo — Estudiante")

    pin = st.text_input("PIN del quiz", key="s_pin")
    name = st.text_input("Tu nombre", key="s_name")

    if st.button("Unirme", type="primary"):
        if not pin or not name:
            st.error("Ingresa PIN y nombre")
        else:
            quiz = mgr.get(pin)
            if not quiz:
                st.error("PIN inválido")
            else:
                if name not in quiz.participants:
                    quiz.participants.append(name)
                    quiz.scores.setdefault(name, 0)
                    mgr.update(pin, quiz)
                st.session_state.joined = True
                st.session_state.joined_pin = pin
                st.session_state.student_name = name

    if st.session_state.get('joined'):
        pin = st.session_state.joined_pin
        name = st.session_state.student_name
        quiz = mgr.get(pin)
        if not quiz:
            st.warning("El quiz fue cerrado")
            return
        if not quiz.started:
            st.info("Esperando a que el docente inicie…")
            return

        # live view
        qrow = next(q for q in quiz.questions if q.qid == quiz.current_q)
        st.markdown(f"### Pregunta {quiz.current_q}/{len(quiz.questions)}")
        st.markdown(qrow.text, unsafe_allow_html=False)
        left = max(int(quiz.time_per_q - (time.time() - quiz.started_at)), 0)
        pill(f"Tiempo: {left}s")

        # has answered?
        answered = False
        for r in quiz.responses.get(quiz.current_q, []):
            if r['name'] == name:
                answered = True
                break

        if not answered:
            choice = st.radio("Elige una opción:", [
                f"A) {qrow.A}", f"B) {qrow.B}", f"C) {qrow.C}", f"D) {qrow.D}"
            ], index=None)
            if st.button("Enviar respuesta", type="secondary"):
                if not choice:
                    st.warning("Selecciona una opción")
                else:
                    letter = choice.split(")")[0]
                    correct_flag = (letter == qrow.correct)
                    # save
                    quiz.responses.setdefault(quiz.current_q, [])
                    quiz.responses[quiz.current_q].append({
                        'name': name,
                        'answer': letter,
                        'correct': correct_flag
                    })
                    if correct_flag:
                        quiz.scores[name] = quiz.scores.get(name, 0) + 1
                    mgr.update(pin, quiz)
                    st.success("Respuesta enviada ✔")
        else:
            pill("Respuesta enviada ✔")

        if quiz.reveal:
            st.success(f"Respuesta correcta: {qrow.correct}")


# ---------------------------------
# Router
# ---------------------------------

st.set_page_config(page_title="Quices en Vivo", page_icon="📝", layout="wide")
page = st.sidebar.radio("Modo", ["Docente", "Estudiante"], horizontal=False)
if page == "Docente":
    page_teacher()
else:
    page_student()
