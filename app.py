import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from google import genai

from pipeline import (
    executar_p01_extracao,
    executar_p02_aderencia,
    executar_p03_parecer,
    extrair_texto_pdf,
)

load_dotenv()
st.set_page_config(page_title="TriagemAI — Análise de currículos", page_icon="📄", layout="wide")

ERRO_ANALISE = "Não conseguimos concluir a análise. Confira os dados da vaga e do currículo e tente novamente."
ERRO_PDF = "Não conseguimos ler este PDF. Tente outro arquivo ou cole o texto do currículo."


def limpar_avaliacao():
    """Mudanças de entrada e novas tentativas invalidam o resultado anterior."""
    st.session_state.pop("resultado", None)
    st.session_state.pop("erro", None)
    st.session_state.logs = []


def log_execucao(mensagem: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(linha)


st.title("TriagemAI — Análise de currículos")
st.caption("Compare as evidências profissionais com os requisitos da vaga e prepare a entrevista.")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("Configure a chave GEMINI_API_KEY no arquivo .env para iniciar a análise.")
    st.stop()

col_vaga, col_cv = st.columns(2)
with col_vaga:
    st.subheader("Vaga")
    cargo_vaga = st.text_input("Título da vaga", placeholder="Ex.: Analista de Dados Júnior", on_change=limpar_avaliacao)
    requisitos_vaga = st.text_area(
        "Descrição e requisitos",
        height=220,
        placeholder="Descreva as atividades, os requisitos e a experiência esperada.",
        on_change=limpar_avaliacao,
    )

with col_cv:
    st.subheader("Currículo")
    arquivo_pdf = st.file_uploader("Envie um currículo em PDF", type=["pdf"], on_change=limpar_avaliacao)
    texto_cv_manual = st.text_area(
        "Ou cole o texto do currículo",
        height=145,
        placeholder="Cole aqui as informações do currículo.",
        on_change=limpar_avaliacao,
    )
    st.caption("Se você preencher o texto, ele será usado no lugar do PDF. O PDF precisa ter texto selecionável.")

if st.button("Analisar currículo", type="primary", use_container_width=True):
    limpar_avaliacao()
    if not cargo_vaga.strip() or not requisitos_vaga.strip():
        st.warning("Preencha o título e a descrição da vaga antes de continuar.")
    elif arquivo_pdf is None and not texto_cv_manual.strip():
        st.warning("Cole o texto do currículo ou envie um PDF com texto legível.")
    else:
        mensagem_erro = ERRO_ANALISE
        with st.status("Analisando currículo...", expanded=True) as status:
            try:
                st.write("1. Lendo as informações profissionais.")
                texto_final_cv = texto_cv_manual.strip()
                if texto_final_cv:
                    log_execucao("Texto manual recebido.")
                else:
                    mensagem_erro = ERRO_PDF
                    texto_final_cv = extrair_texto_pdf(arquivo_pdf)
                    log_execucao(f"PDF_EXTRACTED_CHARS: {len(texto_final_cv)}")
                    mensagem_erro = ERRO_ANALISE
                log_execucao("--- INICIANDO PIPELINE TRIAGEM-AI ---")
                descricao_completa_vaga = f"Cargo: {cargo_vaga}\nRequisitos: {requisitos_vaga}"
                client = genai.Client(api_key=api_key)
                dados_p01 = executar_p01_extracao(client, texto_final_cv, log=log_execucao)

                st.write("2. Comparando com os requisitos da vaga.")
                analise_p02 = executar_p02_aderencia(client, dados_p01, descricao_completa_vaga, log=log_execucao)

                st.write("3. Preparando o resumo e as perguntas.")
                parecer_p03 = executar_p03_parecer(client, dados_p01, analise_p02, descricao_completa_vaga, log=log_execucao)

                status.update(label="Avaliação concluída", state="complete", expanded=False)
                st.session_state.resultado = {"dados": dados_p01, "analise": analise_p02, "parecer": parecer_p03}
            except Exception:
                log_execucao("ERROR: Não foi possível concluir a avaliação.")
                st.session_state.erro = mensagem_erro
                status.update(label="Não foi possível concluir a avaliação", state="error", expanded=False)

# A apresentação não depende do botão e não executa chamadas ao modelo.
st.subheader("Avaliação")
resultado = st.session_state.get("resultado")
if st.session_state.get("erro"):
    st.error(st.session_state.erro)
elif resultado is None:
    st.info("A avaliação aparecerá aqui quando você analisar um currículo.")

if resultado is not None:
    dados_p01 = resultado["dados"]
    analise_p02 = resultado["analise"]
    parecer_p03 = resultado["parecer"]
    st.success("Avaliação concluída")
    m1, m2, m3 = st.columns(3)
    m1.metric("Nome identificado", dados_p01["nome_candidato"].strip() or "Não informado")
    m2.metric("Pontuação de aderência", f"{analise_p02['score_aderencia']} / 100")
    m3.metric("Classificação", parecer_p03["status_recomendacao"])
    st.caption("A pontuação apoia a revisão humana; não é uma decisão automática de contratação ou rejeição.")
    st.write(parecer_p03["resumo_executivo"])
    st.markdown("**Requisitos e pontos a esclarecer**")
    st.table([
        {
            "Requisito": item["requisito"],
            "Situação": {"demonstrado": "Demonstrado", "nao_informado": "Não informado", "nao_atendido": "Não atendido explicitamente"}[item["situacao"]],
            "Evidência": item["evidencia"] or "Não informada",
            "Esclarecer em entrevista": item["esclarecer_entrevista"] or "—",
        }
        for item in analise_p02["avaliacoes_requisitos"]
    ])
    st.caption("Quando o currículo não informa uma competência, esse ponto pode ser esclarecido na entrevista.")

    st.subheader("Perguntas para entrevista")
    for numero, pergunta in enumerate(parecer_p03["perguntas_entrevista"], 1):
        st.markdown(f"{numero}. {pergunta}")

if resultado is not None or st.session_state.get("logs"):
    with st.expander("Detalhes técnicos da análise"):
        if resultado is not None:
            st.markdown("**Pontuação por categoria**")
            for parte in analise_p02["pontuacao_categorias"]:
                st.write(f"{parte['categoria'].replace('_', ' ')}: {parte['pontos_obtidos']:g}/{parte['pontos_maximos']}")
            st.caption("Score normalizado pelas categorias presentes. Não informado significa ausência de evidência documental, não ausência de competência.")
            st.markdown("**Síntese técnica**")
            for conclusao in analise_p02["analise_passo_a_passo"]:
                st.markdown(f"- {conclusao}")
            for ponto in analise_p02["gaps_identificados"]:
                st.markdown(f"- {ponto}")
        st.markdown("**Logs da execução**")
        st.code("\n".join(st.session_state.get("logs", [])), language="text")
