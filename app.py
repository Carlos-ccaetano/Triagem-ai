import os
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

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

from persistencia import consultar_analise, excluir_analise, exportar_csv, listar_historico, salvar_analise

load_dotenv()
st.set_page_config(page_title="TriagemAI — Análise de currículos", page_icon="📄", layout="wide")
# shortcut: seletores de tabela do Streamlit 1.39; revisar ao atualizar o Streamlit.
st.markdown("""<style>
[data-testid="stTableStyledTable"] th.blank,
[data-testid="stTableStyledTable"] th.row_heading { display: none; }
</style>""", unsafe_allow_html=True)

ERRO_ANALISE = "Não conseguimos concluir a análise. Confira a vaga, o currículo e a configuração do acesso ao Gemini. Se o problema continuar, tente mais tarde."
ERRO_PDF = "Não conseguimos ler texto neste PDF. Ele pode estar inválido ou conter apenas imagens. Use outro PDF com texto selecionável ou cole o currículo no campo de texto."


def limpar_avaliacao():
    """Mudanças de entrada e novas tentativas invalidam o resultado anterior."""
    st.session_state.pop("resultado", None)
    st.session_state.pop("execucao", None)
    st.session_state.pop("historico_aberto", None)
    st.session_state.pop("lote", None)
    st.session_state.pop("candidato_lote", None)
    st.session_state.pop("erro", None)
    st.session_state.logs = []


def excluir_do_historico():
    identificador = st.session_state.analise_historico
    if not st.session_state.get(f"confirmar_exclusao_{identificador}"):
        return
    try:
        excluir_analise(identificador)
    except Exception:
        st.session_state.erro_exclusao = "Não conseguimos excluir a análise. Tente novamente."
    else:
        if st.session_state.get("historico_aberto") == identificador:
            st.session_state.pop("historico_aberto", None)
        st.session_state.pop("analise_historico", None)


def log_execucao(mensagem: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}"
    print(linha)
    if "logs" not in st.session_state:
        st.session_state.logs = []
    st.session_state.logs.append(linha)


def exibir_resultados(resultado, lote, execucao, logs, historico=False):
    """Apresenta a mesma avaliação na sessão e no histórico, sem reprocessar dados."""
    if execucao is not None:
        st.caption(f"Vaga analisada: {execucao['titulo_vaga']}")
    if lote is not None:
        st.subheader("Ranking")
        st.caption("Pontuação de 0 a 100, em ordem de aderência documental. Empates mantêm a ordem de envio.")
        total_falhas = lote.get("total_falhas", len(lote["falhas"]))
        total_avaliados = len(lote["ranking"])
        avaliados = f"{total_avaliados} currículo avaliado" if total_avaliados == 1 else f"{total_avaliados} currículos avaliados"
        falhas = f"{total_falhas} arquivo não analisado" if total_falhas == 1 else f"{total_falhas} arquivos não analisados"
        st.write(f"{avaliados} · {falhas}")
        if total_falhas:
            with st.expander("Arquivos não analisados", expanded=True):
                for falha in lote["falhas"]:
                    st.warning(f"Não foi possível analisar o arquivo {falha['arquivo']}. Confira o PDF ou use o texto manual em uma análise individual.")
                if not lote["falhas"]:
                    st.write("O histórico guarda a quantidade de falhas, sem os nomes dos arquivos.")
        if lote["ranking"]:
            linhas = [
                {"Posição": posicao, "Nome identificado": item["dados"]["nome_candidato"].strip() or "Não informado",
                 "Pontuação de aderência": item["analise"]["score_aderencia"], "Classificação": item["parecer"]["status_recomendacao"]}
                for posicao, item in enumerate(lote["ranking"], 1)
            ]
            # Tabela sem exportação paralela: todo CSV passa pelo tratamento da persistência.
            st.table([
                {"Posição": linha["Posição"], "Candidato": linha["Nome identificado"],
                 "Pontuação": linha["Pontuação de aderência"], "Classificação": linha["Classificação"]}
                for linha in linhas
            ])
            selecao = st.selectbox(
                "Abrir avaliação de", range(len(lote["ranking"])),
                key=f"candidato_historico_{execucao['id']}" if historico else "candidato_lote",
                format_func=lambda pos: f"{pos + 1}º — {linhas[pos]['Nome identificado']}",
            )
            resultado = lote["ranking"][selecao]
            if "arquivo" in resultado:
                st.caption(f"Currículo selecionado: {resultado['arquivo']}")
        else:
            st.error("Nenhum currículo pôde ser analisado. Confira os arquivos ou use o texto manual em uma análise individual.")

    if resultado is not None:
        dados = resultado["dados"]
        analise = resultado["analise"]
        parecer = resultado["parecer"]
        st.subheader("Avaliação")
        st.success("Avaliação concluída")
        nome, pontuacao = st.columns([2, 1])
        nome.metric("Nome identificado", dados["nome_candidato"].strip() or "Não informado")
        pontuacao.metric("Aderência documental", f"{analise['score_aderencia']} / 100")
        st.write(f"**Classificação:** {parecer['status_recomendacao']}")
        st.caption("A pontuação apoia a revisão humana; não mede toda a competência da pessoa nem decide contratação ou rejeição.")
        st.write(parecer["resumo_executivo"])

        demonstrados = [item for item in analise["avaliacoes_requisitos"] if item["situacao"] == "demonstrado"]
        pendencias = [item for item in analise["avaliacoes_requisitos"] if item["situacao"] != "demonstrado"]
        st.markdown("#### O que foi demonstrado")
        for item in demonstrados:
            st.markdown(f"**{item['requisito']}**")
            st.write(f"Evidência: {item['evidencia']}")
        if not demonstrados:
            st.write("Não foram encontradas evidências suficientes para demonstrar os requisitos avaliados.")
        st.markdown("#### Pontos a esclarecer")
        for item in pendencias:
            st.markdown(f"**{item['requisito']}**")
            if item["situacao"] == "nao_informado":
                st.write("O currículo não traz informação suficiente para confirmar este requisito.")
            else:
                st.write("A evidência apresentada não atende a este requisito da vaga.")
            if item["evidencia"]:
                st.write(f"Evidência: {item['evidencia']}")
            st.write(f"Na entrevista: {item['esclarecer_entrevista']}")
        if not pendencias:
            st.write("Não há requisitos pendentes nesta avaliação documental.")
        st.caption("Não informado significa falta de informação no currículo, não falta de competência.")

        st.subheader("Perguntas para entrevista")
        for numero, pergunta in enumerate(parecer["perguntas_entrevista"], 1):
            st.markdown(f"{numero}. {pergunta}")

    if resultado is not None or logs:
        with st.expander("Detalhes técnicos da análise"):
            if resultado is not None:
                st.markdown("**Avaliação completa dos requisitos**")
                st.table([
                    {"Requisito": item["requisito"],
                     "Situação": {"demonstrado": "Demonstrado", "nao_informado": "Não informado", "nao_atendido": "Não atendido explicitamente"}[item["situacao"]],
                     "Evidência": item["evidencia"] or "Não informada",
                     "Esclarecer em entrevista": item["esclarecer_entrevista"] or "—"}
                    for item in analise["avaliacoes_requisitos"]
                ])
                st.markdown("**Pontuação por categoria**")
                for parte in analise["pontuacao_categorias"]:
                    st.write(f"{parte['categoria'].replace('_', ' ')}: {parte['pontos_obtidos']:g}/{parte['pontos_maximos']}")
                st.caption("Rubrica 70/20/10, normalizada pelas categorias presentes. A interface exibe o score validado, sem recalcular.")
                st.markdown("**Síntese técnica**")
                for conclusao in analise["analise_passo_a_passo"]:
                    st.markdown(f"- {conclusao}")
                for ponto in analise["gaps_identificados"]:
                    st.markdown(f"- {ponto}")
            if logs:
                st.markdown("**Logs da execução**")
                st.code("\n".join(logs), language="text")

    if execucao is not None:
        salvar, exportar = st.columns(2)
        if not historico:
            with salvar:
                if st.button("Salvar no histórico", key="salvar_historico", use_container_width=True):
                    try:
                        salvo = salvar_analise(execucao)
                        st.success("Análise salva no histórico." if salvo else "Esta execução já está salva no histórico.")
                    except Exception:
                        st.error("Não conseguimos salvar no histórico. Sua avaliação continua disponível; tente novamente.")
        with exportar:
            try:
                st.download_button(
                    "Exportar resultados (CSV)", data=exportar_csv(execucao), file_name="triagemai-resultados.csv",
                    mime="text/csv", key=f"exportar_csv_{execucao['id']}" if historico else "exportar_csv", use_container_width=True,
                )
            except Exception:
                st.error("Não conseguimos preparar o CSV. Sua avaliação continua disponível.")


st.title("TriagemAI")
st.caption("Compare currículos com a vaga, confira as evidências e prepare a entrevista.")
nova_analise, historico = st.tabs(["Nova análise", "Histórico"])

with nova_analise:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        st.info("Para iniciar uma análise, configure o acesso ao Gemini. Você pode consultar avaliações salvas na aba Histórico.")
        with st.expander("Como configurar o acesso"):
            st.error("Defina GEMINI_API_KEY no arquivo .env local e reinicie o aplicativo. Não compartilhe a chave.")

    modo = st.radio("Quantos currículos você quer analisar?", ["Análise individual", "Análise em lote"], horizontal=True,
                    format_func=lambda valor: {"Análise individual": "Um currículo", "Análise em lote": "Vários currículos"}[valor],
                    on_change=limpar_avaliacao)
    em_lote = modo == "Análise em lote"

    col_vaga, col_cv = st.columns(2)
    with col_vaga:
        st.subheader("Informações da vaga")
        cargo_vaga = st.text_input("Título da vaga", placeholder="Ex.: Analista de Dados Júnior", on_change=limpar_avaliacao)
        requisitos_vaga = st.text_area(
            "Descrição e requisitos",
            height=180,
            placeholder="Descreva as atividades, os requisitos e a experiência esperada.",
            on_change=limpar_avaliacao,
        )

    with col_cv:
        st.subheader("Currículos" if em_lote else "Currículo")
        if em_lote:
            arquivos_pdf = st.file_uploader(
                "Selecionar currículos (PDF)", type=["pdf"], accept_multiple_files=True,
                on_change=limpar_avaliacao,
            )
            st.caption(f"Selecione até {LIMITE_LOTE} PDFs com texto selecionável para a mesma vaga.")
        else:
            arquivo_pdf = st.file_uploader("Selecionar currículo (PDF)", type=["pdf"], on_change=limpar_avaliacao)
            texto_cv_manual = st.text_area(
                "Ou cole o texto do currículo",
                height=110,
                placeholder="Cole aqui as informações do currículo.",
                on_change=limpar_avaliacao,
            )
            st.caption("Texto preenchido tem prioridade sobre o PDF. Use um PDF com texto selecionável; se for uma imagem, cole o texto acima.")

    if st.button("Analisar currículos" if em_lote else "Analisar currículo", type="primary", use_container_width=True, disabled=not api_key) and api_key:
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
            with st.status("Analisando currículos..." if em_lote else "Lendo o currículo...", expanded=True) as status:
                try:
                    if em_lote:
                        client = genai.Client(api_key=api_key, http_options={"retry_options": {"attempts": 1}})
                        lote = executar_lote(
                            client, arquivos_pdf, descricao_completa_vaga, log=log_execucao,
                            progresso=lambda indice, total: status.update(label=f"Analisando currículo {indice} de {total}"),
                        )
                        total_validos = len(lote["ranking"])
                        status.update(
                            label="Análise finalizada",
                            state="complete" if total_validos else "error", expanded=False,
                        )
                        st.session_state.lote = lote
                    else:
                        st.write("Lendo o currículo...")
                        texto_final_cv = texto_cv_manual.strip()
                        if texto_final_cv:
                            log_execucao("Texto manual recebido.")
                        else:
                            mensagem_erro = ERRO_PDF
                            texto_final_cv = extrair_texto_pdf(arquivo_pdf)
                            log_execucao(f"PDF_EXTRACTED_CHARS: {len(texto_final_cv)}")
                            mensagem_erro = ERRO_ANALISE
                        log_execucao("--- INICIANDO PIPELINE TRIAGEM-AI ---")
                        client = genai.Client(api_key=api_key, http_options={"retry_options": {"attempts": 1}})
                        dados_p01 = executar_p01_extracao(client, texto_final_cv, log=log_execucao)

                        status.update(label="Comparando com a vaga...")
                        st.write("Comparando com a vaga...")
                        analise_p02 = executar_p02_aderencia(client, dados_p01, descricao_completa_vaga, log=log_execucao)

                        status.update(label="Preparando a avaliação...")
                        st.write("Preparando a avaliação...")
                        parecer_p03 = executar_p03_parecer(client, dados_p01, analise_p02, descricao_completa_vaga, log=log_execucao)

                        status.update(label="Análise finalizada", state="complete", expanded=False)
                        st.session_state.resultado = {"dados": dados_p01, "analise": analise_p02, "parecer": parecer_p03}
                    if not em_lote or lote["ranking"]:
                        st.session_state.execucao = {
                            "id": uuid4().hex, "data": datetime.now(timezone.utc).isoformat(),
                            "titulo_vaga": cargo_vaga, "descricao_vaga": requisitos_vaga,
                            "modo": "lote" if em_lote else "individual",
                            "candidatos": lote["ranking"] if em_lote else [st.session_state.resultado],
                            "quantidade_falhas": len(lote["falhas"]) if em_lote else 0,
                        }
                except Exception:
                    log_execucao("ERROR: Não foi possível concluir a avaliação.")
                    st.session_state.erro = mensagem_erro
                    status.update(label="Não foi possível concluir a avaliação", state="error", expanded=False)


    # A apresentação reutiliza a sessão; navegar não executa o modelo.
    resultado = st.session_state.get("resultado") if not em_lote else None
    lote = st.session_state.get("lote") if em_lote else None
    if st.session_state.get("erro"):
        st.error(st.session_state.erro)
    elif resultado is None and lote is None:
        st.caption("Informe a vaga e selecione de 1 a 10 PDFs para começar." if em_lote else
                   "Informe a vaga e selecione um currículo ou cole o texto para começar. A avaliação aparecerá abaixo.")
    exibir_resultados(resultado, lote, st.session_state.get("execucao"), st.session_state.get("logs", []))

with historico:
    st.subheader("Avaliações salvas")
    st.caption("Consulte as avaliações salvas neste computador. Abrir ou exportar um resultado não faz uma nova análise.")
    if st.session_state.get("erro_exclusao"):
        st.error(st.session_state.pop("erro_exclusao"))
    try:
        registros = listar_historico()
        if not registros:
            st.info("Nenhuma avaliação salva ainda. Depois de analisar um currículo, use Salvar no histórico.")
        else:
            rotulos = {}
            for registro in registros:
                data_local = datetime.fromisoformat(registro["data"]).astimezone(ZoneInfo("America/Sao_Paulo"))
                modo_salvo = {"individual": "Um currículo", "lote": "Vários currículos"}[registro["modo"]]
                rotulos[registro["id"]] = f"{registro['titulo_vaga']} · {data_local:%d/%m/%Y %H:%M:%S} · {modo_salvo}"
            selecionada = st.selectbox("Selecione uma avaliação", list(rotulos), format_func=rotulos.get, key="analise_historico")
            st.button("Abrir avaliação", key="abrir_historico", on_click=lambda: st.session_state.update(historico_aberto=st.session_state.analise_historico))
            with st.expander("Excluir avaliação salva"):
                st.caption(f"Você vai excluir: {rotulos[selecionada]}")
                st.caption("A exclusão remove o registro deste computador. CSVs já baixados não são apagados.")
                confirmar = st.checkbox("Confirmo a exclusão desta análise", key=f"confirmar_exclusao_{selecionada}")
                st.button("Excluir análise", key="excluir_historico", disabled=not confirmar, on_click=excluir_do_historico)
    except Exception:
        st.error("Não conseguimos acessar o histórico. Sua avaliação atual continua na aba Nova análise; tente novamente.")

    if st.session_state.get("historico_aberto"):
        try:
            registro = consultar_analise(st.session_state.historico_aberto)
            if registro is None:
                st.warning("Esta avaliação não foi encontrada. Selecione outro registro do histórico.")
                st.session_state.pop("historico_aberto", None)
            else:
                st.divider()
                data_local = datetime.fromisoformat(registro["data"]).astimezone(ZoneInfo("America/Sao_Paulo"))
                total_resultados = len(registro["candidatos"])
                disponiveis = "avaliação disponível" if total_resultados == 1 else "avaliações disponíveis"
                st.caption(f"Salva em {data_local:%d/%m/%Y às %H:%M:%S} · {total_resultados} {disponiveis}")
                st.button("Fechar avaliação salva", key="voltar_atual", on_click=lambda: st.session_state.pop("historico_aberto", None))
                lote_salvo = {"ranking": registro["candidatos"], "falhas": [], "total_falhas": registro["quantidade_falhas"]} if registro["modo"] == "lote" else None
                resultado_salvo = None if lote_salvo is not None else registro["candidatos"][0]
                exibir_resultados(resultado_salvo, lote_salvo, registro, [], historico=True)
        except Exception:
            st.error("Não conseguimos abrir a avaliação salva. Selecione outra ou tente novamente; sua análise atual continua disponível.")
            st.session_state.pop("historico_aberto", None)
