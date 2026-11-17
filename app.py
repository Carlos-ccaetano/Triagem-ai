import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from google import genai

from pipeline import (
    LIMITE_LOTE,
    executar_lote,
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
    st.session_state.pop("lote", None)
    st.session_state.pop("candidato_lote", None)
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

modo = st.radio("Tipo de análise", ["Análise individual", "Análise em lote"], horizontal=True, on_change=limpar_avaliacao)
em_lote = modo == "Análise em lote"

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
    st.subheader("Currículos" if em_lote else "Currículo")
    if em_lote:
        arquivos_pdf = st.file_uploader(
            "Envie os currículos em PDF", type=["pdf"], accept_multiple_files=True,
            on_change=limpar_avaliacao,
        )
        st.caption(f"Selecione até {LIMITE_LOTE} PDFs com texto selecionável para a mesma vaga.")
    else:
        arquivo_pdf = st.file_uploader("Envie um currículo em PDF", type=["pdf"], on_change=limpar_avaliacao)
        texto_cv_manual = st.text_area(
            "Ou cole o texto do currículo",
            height=145,
            placeholder="Cole aqui as informações do currículo.",
            on_change=limpar_avaliacao,
        )
        st.caption("Se você preencher o texto, ele será usado no lugar do PDF. O PDF precisa ter texto selecionável.")

if st.button("Analisar currículos" if em_lote else "Analisar currículo", type="primary", use_container_width=True):
    limpar_avaliacao()
    if not cargo_vaga.strip() or not requisitos_vaga.strip():
        st.warning("Preencha o título e a descrição da vaga antes de continuar.")
    elif em_lote and not arquivos_pdf:
        st.warning("Selecione os currículos em PDF antes de continuar.")
    elif em_lote and len(arquivos_pdf) > LIMITE_LOTE:
        st.warning(f"Selecione no máximo {LIMITE_LOTE} currículos por análise.")
    elif not em_lote and arquivo_pdf is None and not texto_cv_manual.strip():
        st.warning("Cole o texto do currículo ou envie um PDF com texto legível.")
    else:
        mensagem_erro = ERRO_ANALISE
        descricao_completa_vaga = f"Cargo: {cargo_vaga}\nRequisitos: {requisitos_vaga}"
        with st.status("Analisando currículos..." if em_lote else "Analisando currículo...", expanded=True) as status:
            try:
                if em_lote:
                    client = genai.Client(api_key=api_key)
                    lote = executar_lote(
                        client, arquivos_pdf, descricao_completa_vaga, log=log_execucao,
                        progresso=lambda indice, total: status.update(label=f"Analisando currículo {indice} de {total}"),
                    )
                    total_validos = len(lote["ranking"])
                    status.update(
                        label=f"Lote concluído: {total_validos} de {len(arquivos_pdf)} currículos analisados",
                        state="complete" if total_validos else "error", expanded=False,
                    )
                    st.session_state.lote = lote
                else:
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
resultado = st.session_state.get("resultado") if not em_lote else None
lote = st.session_state.get("lote") if em_lote else None
if lote is not None:
    st.subheader("Ranking")
    st.caption("A ordem representa aderência documental à mesma vaga e apoia a análise humana, sem decisão automática de contratação.")
    st.write(f"{len(lote['ranking'])} currículo(s) analisado(s); {len(lote['falhas'])} arquivo(s) não analisado(s).")
    for falha in lote["falhas"]:
        st.warning(f"Não foi possível analisar o arquivo {falha['arquivo']}. Confira o PDF e tente uma nova análise.")
    if lote["ranking"]:
        linhas_ranking = [
            {
                "Posição": posicao,
                "Nome identificado": item["dados"]["nome_candidato"].strip() or "Não informado",
                "Pontuação de aderência": item["analise"]["score_aderencia"],
                "Classificação": item["parecer"]["status_recomendacao"],
            }
            for posicao, item in enumerate(lote["ranking"], 1)
        ]
        st.table(linhas_ranking)
        selecao = st.selectbox(
            "Ver avaliação individual", range(len(lote["ranking"])), key="candidato_lote",
            format_func=lambda pos: f"{pos + 1}º — {linhas_ranking[pos]['Nome identificado']}",
        )
        resultado = lote["ranking"][selecao]
        st.caption(f"Arquivo selecionado: {resultado['arquivo']}")

st.subheader("Avaliação")
if st.session_state.get("erro"):
    st.error(st.session_state.erro)
elif lote is not None and not lote["ranking"]:
    st.error("Nenhum currículo pôde ser analisado. Confira os arquivos e tente novamente.")
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
