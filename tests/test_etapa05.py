import copy
import csv
import io
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch

import persistencia
import test_etapa01 as anteriores
import test_etapa04 as etapa04


def execucao(identificador="execucao-1", modo="individual", data="2026-11-17T12:00:00+00:00"):
    candidatos = []
    for nome, score in ([("CANDIDATO_EXEMPLO", 80)] if modo == "individual" else [("PRIMEIRO", 100), ("SEGUNDO", 80)]):
        dados, analise, parecer = etapa04.respostas(nome, score)
        candidatos.append({"dados": dados, "analise": analise, "parecer": parecer})
    return {"id": identificador, "data": data, "titulo_vaga": "Analista de Dados — São Paulo",
            "descricao_vaga": anteriores.VAGA, "modo": modo, "candidatos": candidatos, "quantidade_falhas": 0}


def ler_csv(conteudo):
    return list(csv.reader(io.StringIO(conteudo.decode("utf-8-sig")), delimiter=";"))


class PersistenciaTests(anteriores.SemRede):
    def test_banco_e_tabela_criados_automaticamente(self):
        self.assertFalse(self.caminho_banco.exists())
        self.assertEqual(persistencia.listar_historico(), [])
        self.assertTrue(self.caminho_banco.is_file())
        with closing(sqlite3.connect(self.caminho_banco)) as banco:
            tabelas = banco.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        self.assertEqual(tabelas, [("execucoes",)])

    def test_salva_individual_recupera_em_nova_conexao_sem_dados_brutos(self):
        dados = execucao()
        candidato = dados["candidatos"][0]
        candidato["dados"].update(texto_integral="CURRICULO_INTEGRAL_SIGILOSO", api_key="CHAVE_SIGILOSA")
        candidato.update(arquivo="ARQUIVO_NAO_SALVAR.pdf", pdf=b"PDF_ORIGINAL_SIGILOSO", logs=["LOG_SIGILOSO"], resposta_bruta="RESPOSTA_BRUTA_SIGILOSA")
        original = copy.deepcopy(dados)
        self.assertTrue(persistencia.salvar_analise(dados))
        with closing(sqlite3.connect(self.caminho_banco)) as banco:
            bruto = banco.execute("SELECT resultados_json FROM execucoes").fetchone()[0]
        recuperada = persistencia.consultar_analise(dados["id"])
        self.assertEqual(recuperada["candidatos"][0]["dados"], {"nome_candidato": "CANDIDATO_EXEMPLO"})
        self.assertEqual(recuperada["candidatos"][0]["analise"]["score_aderencia"], 80)
        self.assertEqual(len(recuperada["candidatos"][0]["parecer"]["perguntas_entrevista"]), 3)
        for marcador in ["CURRICULO_INTEGRAL_SIGILOSO", "CHAVE_SIGILOSA", "ARQUIVO_NAO_SALVAR", "PDF_ORIGINAL_SIGILOSO", "LOG_SIGILOSO", "RESPOSTA_BRUTA_SIGILOSA"]:
            self.assertNotIn(marcador, bruto)
        self.assertEqual(dados, original)

    def test_salva_lote_preserva_ordem_e_contagem_sem_falhas_identificaveis(self):
        dados = execucao(modo="lote")
        dados["quantidade_falhas"] = 1
        dados["falhas"] = [{"arquivo": "ARQUIVO_FALHOU_SIGILOSO.pdf"}]
        for candidato in dados["candidatos"]:
            candidato["arquivo"] = "ARQUIVO_VALIDO_SIGILOSO.pdf"
        persistencia.salvar_analise(dados)
        recuperada = persistencia.consultar_analise(dados["id"])
        self.assertEqual(recuperada["modo"], "lote")
        self.assertEqual([c["analise"]["score_aderencia"] for c in recuperada["candidatos"]], [100, 80])
        self.assertEqual(recuperada["quantidade_falhas"], 1)
        self.assertNotIn("ARQUIVO_", json.dumps(recuperada))

    def test_historico_ordena_datas_em_utc_nao_ordem_de_insercao(self):
        persistencia.salvar_analise(execucao("mais-nova", data="2026-11-17T10:00:00-03:00"))
        persistencia.salvar_analise(execucao("mais-antiga", data="2026-11-17T12:00:00+00:00"))
        self.assertEqual([r["id"] for r in persistencia.listar_historico()], ["mais-nova", "mais-antiga"])

    def test_mesmo_id_nao_duplica_nem_sobrescreve(self):
        dados = execucao()
        self.assertTrue(persistencia.salvar_analise(dados))
        dados["candidatos"][0]["dados"]["nome_candidato"] = "NOME_ALTERADO"
        self.assertFalse(persistencia.salvar_analise(dados))
        self.assertEqual(len(persistencia.listar_historico()), 1)
        self.assertEqual(persistencia.consultar_analise(dados["id"])["candidatos"][0]["dados"]["nome_candidato"], "CANDIDATO_EXEMPLO")

    def test_exclusao_e_consultas_parametrizadas(self):
        dados = execucao()
        dados["titulo_vaga"] = "Vaga'); DROP TABLE execucoes; --"
        persistencia.salvar_analise(dados)
        persistencia.salvar_analise(execucao("outra"))
        ataque = "' OR 1=1; --"
        self.assertIsNone(persistencia.consultar_analise(ataque))
        self.assertFalse(persistencia.excluir_analise(ataque))
        self.assertEqual(len(persistencia.listar_historico()), 2)
        self.assertTrue(persistencia.excluir_analise(dados["id"]))
        self.assertIsNone(persistencia.consultar_analise(dados["id"]))
        self.assertEqual([r["id"] for r in persistencia.listar_historico()], ["outra"])

    def test_resultados_invalidos_nao_sao_gravados(self):
        for caso in ["score", "perguntas", "classificacao", "vazio"]:
            with self.subTest(caso=caso):
                dados = execucao()
                if caso == "score":
                    dados["candidatos"][0]["analise"]["score_aderencia"] = 150
                elif caso == "perguntas":
                    dados["candidatos"][0]["parecer"]["perguntas_entrevista"] = []
                elif caso == "classificacao":
                    dados["candidatos"][0]["parecer"]["status_recomendacao"] = "Altamente Recomendado"
                else:
                    dados["candidatos"] = []
                with self.assertRaises(ValueError):
                    persistencia.salvar_analise(dados)
        self.assertEqual(persistencia.listar_historico(), [])

    def test_csv_colunas_bom_pontuacao_perguntas_e_privacidade_sem_banco(self):
        dados = execucao(modo="lote")
        dados["logs"] = ["LOG_NAO_EXPORTAR"]
        dados["candidatos"][0]["dados"]["curriculo"] = "CV_NAO_EXPORTAR"
        dados["candidatos"][0]["parecer"]["perguntas_entrevista"][0] = 'Como usa "SQL";\nem relatórios?'
        with patch("persistencia.sqlite3.connect", side_effect=AssertionError("CSV não deve acessar SQLite")):
            conteudo = persistencia.exportar_csv(dados)
        self.assertTrue(conteudo.startswith(b"\xef\xbb\xbf"))
        linhas = ler_csv(conteudo)
        self.assertEqual(len(linhas), 3)
        self.assertTrue(all(len(linha) == 9 for linha in linhas))
        self.assertEqual(linhas[1][:4], ["1", "PRIMEIRO", dados["titulo_vaga"], "100"])
        self.assertEqual(linhas[1][6:], dados["candidatos"][0]["parecer"]["perguntas_entrevista"])
        self.assertNotIn("LOG_NAO_EXPORTAR", conteudo.decode("utf-8-sig"))
        self.assertNotIn("CV_NAO_EXPORTAR", conteudo.decode("utf-8-sig"))
        individual = ler_csv(persistencia.exportar_csv(execucao()))
        self.assertEqual(individual[1][0], "")
        self.assertEqual(individual[1][3], "80")

    def test_csv_neutraliza_formulas_apenas_na_exportacao(self):
        for indice, valor in enumerate(['=1+1";=2+2', "+1+1", "-1+2", "@SOMA(1;2)", "\t=1+1", "\r=1+1", "\n=1+1", "  =1+1", "＝1+1", "＋1+1", "－1+1", "＠SOMA(1;2)"]):
            with self.subTest(valor=valor):
                dados = execucao(f"formula-{indice}")
                dados["titulo_vaga"] = valor
                dados["candidatos"][0]["dados"]["nome_candidato"] = valor
                dados["candidatos"][0]["parecer"]["resumo_executivo"] = valor
                dados["candidatos"][0]["parecer"]["perguntas_entrevista"][0] = valor
                original = copy.deepcopy(dados)
                linha = ler_csv(persistencia.exportar_csv(dados))[1]
                self.assertEqual(len(linha), 9)
                for coluna in [1, 2, 5, 6]:
                    self.assertTrue(linha[coluna].startswith("\t"))
                self.assertEqual(linha[3], "80")
                self.assertEqual(dados, original)
                persistencia.salvar_analise(dados)
                self.assertEqual(persistencia.consultar_analise(dados["id"])["titulo_vaga"], valor)


class HistoricoInterfaceTests(anteriores.SemRede):
    def setUp(self):
        super().setUp()
        self.client = anteriores.cliente_simulado(anteriores.P01, anteriores.P02, anteriores.P03)
        self.factory = patch("google.genai.Client", return_value=self.client)
        self.factory_mock = self.factory.start()
        self.addCleanup(self.factory.stop)
        ambiente = patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": "CHAVE_SINTETICA"})
        ambiente.start()
        self.addCleanup(ambiente.stop)
        self.app = anteriores.AppTest.from_file(str(anteriores.ROOT / "app.py"), default_timeout=15)

    def analisar(self):
        self.app.run()
        self.app.text_input[0].set_value("Vaga sintetica")
        self.app.text_area[0].set_value(anteriores.VAGA)
        self.app.text_area[1].set_value("CV sintetico")
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)

    def test_salvamento_so_explicito_e_repeticao_nao_duplica(self):
        self.analisar()
        identificador = self.app.session_state["execucao"]["id"]
        self.app.run()
        self.assertEqual(persistencia.listar_historico(), [])
        self.app.button(key="salvar_historico").click().run()
        self.app.button(key="salvar_historico").click().run()
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual([r["id"] for r in persistencia.listar_historico()], [identificador])
        self.assertEqual(self.app.session_state["execucao"]["id"], identificador)
        self.assertEqual(self.client.models.generate_content.call_count, 3)
        self.assertEqual(self.factory_mock.call_count, 1)

    def test_erros_de_armazenamento_preservam_resultado_e_nao_expoem_detalhes(self):
        self.analisar()
        resultado = copy.deepcopy(self.app.session_state["resultado"])
        for operacao in ["salvar_analise", "listar_historico"]:
            with self.subTest(operacao=operacao), patch(f"persistencia.{operacao}", side_effect=sqlite3.OperationalError(anteriores.PRIVADO)):
                if operacao == "salvar_analise":
                    self.app.button(key="salvar_historico").click().run()
                else:
                    self.app.run()
                self.assertEqual(len(self.app.exception), 0)
                self.assertEqual(self.app.session_state["resultado"], resultado)
                self.assertEqual(self.app.metric[1].value, "80 / 100")
                self.assertTrue(self.app.error)
                self.assertNotIn(anteriores.PRIVADO, "\n".join(item.value for item in self.app.error))
        self.assertEqual(self.client.models.generate_content.call_count, 3)

    def test_nova_sessao_recupera_e_exporta_sem_chave_ou_chamadas(self):
        self.analisar()
        self.app.button(key="salvar_historico").click().run()
        identificador = self.app.session_state["execucao"]["id"]
        nova = anteriores.AppTest.from_file(str(anteriores.ROOT / "app.py"), default_timeout=15)
        with patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": ""}):
            nova.run()
            nova.button(key="abrir_historico").click().run()
            self.assertEqual(len(nova.exception), 0)
            self.assertNotIn("resultado", nova.session_state)
            self.assertNotIn("execucao", nova.session_state)
            self.assertEqual(nova.session_state["historico_aberto"], identificador)
            self.assertEqual(nova.metric[1].value, "80 / 100")
            for pergunta in anteriores.P03["perguntas_entrevista"]:
                self.assertIn(pergunta, "\n".join(item.value for item in nova.markdown))
            with patch("streamlit.download_button", return_value=True) as download:
                nova.run()
            linhas = ler_csv(download.call_args.kwargs["data"])
            self.assertEqual(linhas[1][1], anteriores.PRIVADO)
            self.assertEqual(linhas[1][6:], anteriores.P03["perguntas_entrevista"])
        self.assertEqual(self.client.models.generate_content.call_count, 3)
        self.assertEqual(self.factory_mock.call_count, 1)

    def test_lote_historico_reutiliza_ranking_e_detalhes_sem_substituir_sessao(self):
        arquivos = [etapa04.pdf(1), etapa04.pdf(2)]
        etapa04.configurar(self.client, [*etapa04.respostas("A"), *etapa04.respostas("B", 100)])
        with patch("streamlit.file_uploader", side_effect=lambda *args, accept_multiple_files=False, **kwargs: arquivos if accept_multiple_files else None):
            self.app.run()
            self.app.radio[0].set_value("Análise em lote").run()
            self.app.text_input[0].set_value("Vaga sintetica")
            self.app.text_area[0].set_value(anteriores.VAGA)
            self.app.button[0].click().run()
            lote = copy.deepcopy(self.app.session_state["lote"])
            self.app.button(key="salvar_historico").click().run()
            identificador = self.app.session_state["execucao"]["id"]
            self.app.button(key="abrir_historico").click().run()
            self.app.selectbox(key=f"candidato_historico_{identificador}").set_value(1).run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(self.app.metric[0].value, "A")
            self.assertEqual(self.app.session_state["lote"], lote)
            self.assertEqual(len(self.app.code), 0)
            with patch("streamlit.download_button", return_value=True) as download:
                self.app.run()
            linhas = ler_csv(download.call_args.kwargs["data"])
            self.assertEqual([linha[3] for linha in linhas[1:]], ["100", "80"])
            self.assertEqual([linha[0] for linha in linhas[1:]], ["1", "2"])
            self.app.button(key="voltar_atual").click().run()
            self.assertEqual(self.app.session_state["lote"], lote)
        self.assertEqual(self.client.models.generate_content.call_count, 6)

    def test_exclusao_exige_confirmacao_e_fecha_registro_removido(self):
        persistencia.salvar_analise(execucao("antiga", data="2026-11-17T10:00:00+00:00"))
        persistencia.salvar_analise(execucao("nova", data="2026-11-17T12:00:00+00:00"))
        self.app.run()
        self.assertTrue(self.app.button(key="excluir_historico").disabled)
        self.app.button(key="abrir_historico").click().run()
        self.app.checkbox(key="confirmar_exclusao_nova").set_value(True).run()
        self.assertFalse(self.app.button(key="excluir_historico").disabled)
        self.app.button(key="excluir_historico").click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual([r["id"] for r in persistencia.listar_historico()], ["antiga"])
        self.assertNotIn("historico_aberto", self.app.session_state)
        self.assertEqual(len(self.app.metric), 0)
        self.assertTrue(self.app.button(key="excluir_historico").disabled)
        self.client.models.generate_content.assert_not_called()
        self.factory_mock.assert_not_called()
