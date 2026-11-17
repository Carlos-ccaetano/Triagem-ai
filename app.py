import os
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from google import genai

from pipeline import (
    ErroPipeline,
    executar_p01_extracao,
    executar_p02_aderencia,
    executar_p03_parecer,
    extrair_texto_pdf,
)

# Carrega variáveis de ambiente (.env)
load_dotenv()

st.set_page_config(
    page_title="TriagemAI — Triagem Automatizada de Currículos",
    page_icon="📄",
    layout="wide",
)

# Inicializa cliente Gemini
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None


def log_execucao(mensagem: str):
    """Registra logs no terminal e na sessão para auditoria/evidência."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(linha)


# ================= INTERFACE STREAMLIT =================
st.title("📄 TriagemAI — Análise e Triagem Automatizada de Currículos")
st.caption("Protótipo Inicial Funcional (Entrega 4) — Encadeamento Real de Prompts com Google Gemini")

if not api_key:
    st.error("⚠️ Chave `GEMINI_API_KEY` não encontrada! Configure o arquivo `.env` na raiz do projeto antes de executar.")
    st.stop()

col_vaga, col_cv = st.columns(2)

with col_vaga:
    st.subheader("1. Dados da Vaga (F01)")
    cargo_vaga = st.text_input("Título da Vaga", placeholder="Ex: Analista de Dados Júnior")
    requisitos_vaga = st.text_area(
        "Requisitos Obrigatórios, Desejáveis e Senioridade",
        height=220,
        placeholder="Ex: Buscamos Analista de Dados Júnior com domínio em SQL, Python (Pandas) e Power BI. Diferencial: experiência com Git e bancos em nuvem.",
    )

with col_cv:
    st.subheader("2. Currículo do Candidato (F05)")
    arquivo_pdf = st.file_uploader("Upload de Currículo (.pdf nativo)", type=["pdf"])
    texto_cv_manual = st.text_area(
        "Ou cole o texto do currículo diretamente (prioridade sobre o PDF):",
        height=145,
        placeholder="Cole aqui o conteúdo do currículo caso não envie PDF...",
    )

if st.button("🚀 Analisar Candidato", type="primary", use_container_width=True):
    st.session_state.logs = []
    if not cargo_vaga.strip() or not requisitos_vaga.strip():
        st.warning("Preencha o título e os requisitos da vaga antes de continuar.")
    elif arquivo_pdf is None and not texto_cv_manual.strip():
        st.warning("Insira o texto do currículo ou envie um PDF com texto legível.")
    else:
        try:
            texto_final_cv = texto_cv_manual.strip()
            if texto_final_cv:
                log_execucao("Texto manual recebido.")
            else:
                texto_final_cv = extrair_texto_pdf(arquivo_pdf)
                log_execucao(f"PDF_EXTRACTED_CHARS: {len(texto_final_cv)}")
            log_execucao("--- INICIANDO PIPELINE TRIAGEM-AI ---")
            descricao_completa_vaga = f"Cargo: {cargo_vaga}\nRequisitos: {requisitos_vaga}"

            with st.status("Executando cadeia de prompts no Gemini...", expanded=True) as status:
                st.write("🔍 **Etapa 1 (P01):** Extraindo entidades estruturadas do currículo...")
                dados_p01 = executar_p01_extracao(client, texto_final_cv, log=log_execucao)

                st.write("🧠 **Etapa 2 (P02):** Avaliando evidências por requisito...")
                analise_p02 = executar_p02_aderencia(client, dados_p01, descricao_completa_vaga, log=log_execucao)

                st.write("📋 **Etapa 3 (P03):** Gerando parecer executivo e perguntas de entrevista...")
                parecer_p03 = executar_p03_parecer(client, dados_p01, analise_p02, descricao_completa_vaga, log=log_execucao)

                status.update(label="Pipeline concluído com sucesso!", state="complete", expanded=False)

            st.divider()
            st.subheader("📊 Resultado da Triagem")

            m1, m2, m3 = st.columns(3)
            m1.metric("Candidato", dados_p01.get("nome_candidato", "Não identificado"))
            m2.metric("Score de Aderência", f"{analise_p02.get('score_aderencia', 0)} / 100")
            m3.metric("Status", parecer_p03.get("status_recomendacao", "—"))
            st.caption("Classificação de aderência documental para apoio à revisão humana; não é uma decisão automática de contratação ou rejeição.")

            st.info(f"**Resumo Executivo (P03):** {parecer_p03.get('resumo_executivo', '')}")

            tab1, tab2, tab3, tab4 = st.tabs([
                "🎯 Perguntas de Entrevista (P03)",
                "🧠 Evidências e Pontuação (P02)",
                "🗂️ JSON Extraído (P01)",
                "🖥️ Logs de Execução Real",
            ])

            with tab1:
                for pergunta in parecer_p03.get("perguntas_entrevista", []):
                    st.markdown(f"- {pergunta}")

            with tab2:
                st.table([
                    {
                        "Requisito": item["requisito"],
                        "Categoria": item["categoria"].replace("_", " "),
                        "Situação": {"demonstrado": "Demonstrado", "nao_informado": "Não informado", "nao_atendido": "Não atendido explicitamente"}[item["situacao"]],
                        "Evidência": item["evidencia"] or "Não informada",
                        "Esclarecer em entrevista": item["esclarecer_entrevista"] or "—",
                    }
                    for item in analise_p02["avaliacoes_requisitos"]
                ])
                for parte in analise_p02["pontuacao_categorias"]:
                    st.write(f"{parte['categoria'].replace('_', ' ')}: {parte['pontos_obtidos']:g}/{parte['pontos_maximos']}")
                st.caption("Score normalizado pelas categorias presentes. Não informado significa ausência de evidência documental, não ausência de competência.")
                st.markdown("**Síntese técnica:**")
                for passo in analise_p02.get("analise_passo_a_passo", []):
                    st.markdown(f"- {passo}")
                st.markdown("**Pontos a esclarecer e requisitos não atendidos explicitamente:**")
                for gap in analise_p02.get("gaps_identificados", []):
                    st.markdown(f"- ⚠️ {gap}")

            with tab3:
                st.json(dados_p01)

            with tab4:
                st.code("\n".join(st.session_state.logs), language="text")

        except ErroPipeline as e:
            log_execucao("ERROR: Falha na validação do PDF ou da resposta do modelo.")
            st.error(str(e))
        except Exception:
            log_execucao("ERROR: Falha durante o processamento do modelo.")
            st.error("Não foi possível concluir a análise. Verifique a configuração e tente novamente.")

# Módulo F06 (Mockado conforme documentado na E4)
with st.expander("📁 Triagem em Lote — Simulação Mockada (F06 - Em desenvolvimento para E5)"):
    st.caption("Dados simulados em memória para validação da interface de ranking comparativo.")
    mock_ranking = [
        {"Posição": "1º", "Candidato": "Mariana Costa", "Score": "88/100", "Status": "Altamente Recomendada"},
        {"Posição": "2º", "Candidato": "Lucas Andrade", "Score": "74/100", "Status": "Recomendado com Ressalvas"},
        {"Posição": "3º", "Candidato": "Rafael Mendes", "Score": "5/100", "Status": "Não Recomendado"},
    ]
    st.table(mock_ranking)