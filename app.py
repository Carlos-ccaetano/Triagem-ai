import json
import os
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pypdf import PdfReader

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
MODEL_ID = "gemini-2.5-flash"


def log_execucao(mensagem: str):
    """Registra logs no terminal e na sessão para auditoria/evidência."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(linha)


def extrair_texto_pdf(arquivo_pdf) -> str:
    """Extrai texto nativo de um arquivo PDF."""
    reader = PdfReader(arquivo_pdf)
    texto = ""
    for page in reader.pages:
        texto += page.extract_text() or ""
    return texto.strip()


def executar_p01_extracao(texto_curriculo: str) -> dict:
    """P01: Role Prompt + Few-Shot para extração estruturada em JSON."""
    log_execucao(f"Executando P01 (Extração JSON) via {MODEL_ID}...")
    prompt = f"""
Você é um especialista em extração de dados de currículos (ATS Parser).
Extraia as informações do currículo abaixo e retorne ESTRITAMENTE um objeto JSON válido com as chaves:
- "nome_candidato" (string)
- "cargo_atual" (string)
- "anos_experiencia_total" (number)
- "habilidades_tecnicas" (lista de strings)
- "formacao" (string)

Exemplo de saída esperada:
{{
  "nome_candidato": "Ana Silva",
  "cargo_atual": "Desenvolvedora Júnior",
  "anos_experiencia_total": 2,
  "habilidades_tecnicas": ["Python", "SQL", "Git"],
  "formacao": "Ciência da Computação"
}}

Currículo:
\"\"\"
{texto_curriculo}
\"\"\"
"""
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    resultado = json.loads(response.text)
    log_execucao(f"Resposta P01 recebida: {json.dumps(resultado, ensure_ascii=False)}")
    return resultado


def executar_p02_aderencia(dados_candidato: dict, descricao_vaga: str) -> dict:
    """P02: Chain of Thought (CoT) para análise de aderência Vaga x Candidato."""
    log_execucao("Injetando saída do P01 no Prompt P02 (Chain of Thought)...")
    prompt = f"""
Você é um Recrutador Técnico Sênior. Avalie a aderência do candidato abaixo em relação à vaga descrita.
Use raciocínio passo a passo (Chain of Thought) antes de calcular a pontuação final.
Considere sinônimos técnicos válidos (ex: PostgreSQL atende SQL). Não invente habilidades que não estejam no JSON do candidato.

Retorne ESTRITAMENTE um objeto JSON válido com as chaves:
- "analise_passo_a_passo" (lista de strings detalhando cada etapa: requisitos obrigatórios, senioridade e diferenciais)
- "gaps_identificados" (lista de strings com requisitos ausentes)
- "score_aderencia" (inteiro de 0 a 100)

Dados Estruturados do Candidato (Saída P01):
{json.dumps(dados_candidato, ensure_ascii=False, indent=2)}

Descrição e Requisitos da Vaga:
\"\"\"
{descricao_vaga}
\"\"\"
"""
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    resultado = json.loads(response.text)
    log_execucao(f"Resposta P02 recebida (Score: {resultado.get('score_aderencia')}/100)")
    return resultado


def executar_p03_parecer(dados_candidato: dict, analise_cot: dict, descricao_vaga: str) -> dict:
    """P03: Role Prompt + Zero-Shot Estruturado para parecer final e perguntas de entrevista."""
    log_execucao("Executando P03 (Parecer Final e Roteiro de Entrevista)...")
    prompt = f"""
Você é um Gestor de RH Executivo. Com base na análise técnica abaixo, redija um parecer direto para tomada de decisão.
O resumo executivo deve ter no máximo 4 linhas.

Retorne ESTRITAMENTE um objeto JSON válido com as chaves:
- "status_recomendacao" ("Altamente Recomendado", "Recomendado com Ressalvas" ou "Não Recomendado")
- "resumo_executivo" (string)
- "perguntas_entrevista" (lista com 3 perguntas técnicas direcionadas aos pontos fortes ou gaps do candidato)

Candidato: {json.dumps(dados_candidato, ensure_ascii=False)}
Análise Técnica (P02): {json.dumps(analise_cot, ensure_ascii=False)}
Vaga: {descricao_vaga}
"""
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    resultado = json.loads(response.text)
    log_execucao("Resposta P03 recebida. Pipeline finalizado com sucesso.")
    return resultado


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
        "Ou cole o texto do currículo diretamente:",
        height=145,
        placeholder="Cole aqui o conteúdo do currículo caso não envie PDF...",
    )

if st.button("🚀 Analisar Candidato", type="primary", use_container_width=True):
    texto_final_cv = ""
    if arquivo_pdf is not None:
        texto_final_cv = extrair_texto_pdf(arquivo_pdf)
        log_execucao(f"PDF_EXTRACTED_CHARS: {len(texto_final_cv)} chars from '{arquivo_pdf.name}'")
    elif texto_cv_manual.strip():
        texto_final_cv = texto_cv_manual.strip()

    if not cargo_vaga.strip() or not requisitos_vaga.strip():
        st.warning("Preencha o título e os requisitos da vaga antes de continuar.")
    elif not texto_final_cv:
        st.warning("Insira o texto do currículo ou envie um PDF com texto legível.")
    else:
        st.session_state.logs = []
        log_execucao("--- INICIANDO PIPELINE TRIAGEM-AI ---")
        descricao_completa_vaga = f"Cargo: {cargo_vaga}\nRequisitos: {requisitos_vaga}"

        try:
            with st.status("Executando cadeia de prompts no Gemini...", expanded=True) as status:
                st.write("🔍 **Etapa 1 (P01):** Extraindo entidades estruturadas do currículo...")
                dados_p01 = executar_p01_extracao(texto_final_cv)

                st.write("🧠 **Etapa 2 (P02):** Avaliando aderência via Chain of Thought...")
                analise_p02 = executar_p02_aderencia(dados_p01, descricao_completa_vaga)

                st.write("📋 **Etapa 3 (P03):** Gerando parecer executivo e perguntas de entrevista...")
                parecer_p03 = executar_p03_parecer(dados_p01, analise_p02, descricao_completa_vaga)

                status.update(label="Pipeline concluído com sucesso!", state="complete", expanded=False)

            st.divider()
            st.subheader("📊 Resultado da Triagem")

            m1, m2, m3 = st.columns(3)
            m1.metric("Candidato", dados_p01.get("nome_candidato", "Não identificado"))
            m2.metric("Score de Aderência", f"{analise_p02.get('score_aderencia', 0)} / 100")
            m3.metric("Status", parecer_p03.get("status_recomendacao", "—"))

            st.info(f"**Resumo Executivo (P03):** {parecer_p03.get('resumo_executivo', '')}")

            tab1, tab2, tab3, tab4 = st.tabs([
                "🎯 Perguntas de Entrevista (P03)",
                "🧠 Raciocínio CoT & Gaps (P02)",
                "🗂️ JSON Extraído (P01)",
                "🖥️ Logs de Execução Real",
            ])

            with tab1:
                for pergunta in parecer_p03.get("perguntas_entrevista", []):
                    st.markdown(f"- {pergunta}")

            with tab2:
                st.markdown("**Análise Passo a Passo:**")
                for passo in analise_p02.get("analise_passo_a_passo", []):
                    st.markdown(f"- {passo}")
                st.markdown("**Gaps Identificados:**")
                for gap in analise_p02.get("gaps_identificados", []):
                    st.markdown(f"- ⚠️ {gap}")

            with tab3:
                st.json(dados_p01)

            with tab4:
                st.code("\n".join(st.session_state.logs), language="text")

        except Exception as e:
            log_execucao(f"ERROR: {str(e)}")
            st.error(f"Erro durante o processamento do LLM: {e}")

# Módulo F06 (Mockado conforme documentado na E4)
with st.expander("📁 Triagem em Lote — Simulação Mockada (F06 - Em desenvolvimento para E5)"):
    st.caption("Dados simulados em memória para validação da interface de ranking comparativo.")
    mock_ranking = [
        {"Posição": "1º", "Candidato": "Mariana Costa", "Score": "88/100", "Status": "Altamente Recomendada"},
        {"Posição": "2º", "Candidato": "Lucas Andrade", "Score": "74/100", "Status": "Recomendado com Ressalvas"},
        {"Posição": "3º", "Candidato": "Rafael Mendes", "Score": "5/100", "Status": "Não Recomendado"},
    ]
    st.table(mock_ranking)