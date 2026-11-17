import copy
import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pipeline
import test_etapa01 as anteriores


def pdf(numero, texto="CV sintetico"):
    arquivo = anteriores.pdf_com_textos(texto)
    arquivo.name = f"{anteriores.PRIVADO}-{numero}.pdf"
    return arquivo


def respostas(nome, score=80):
    dados = dict(anteriores.P01, nome_candidato=nome)
    analise = copy.deepcopy(anteriores.P02)
    parecer = copy.deepcopy(anteriores.P03)
    if score == 0:
        analise["score_aderencia"] = 0
        for item in analise["avaliacoes_requisitos"]:
            item.update(situacao="nao_informado", evidencia=None, esclarecer_entrevista="Pode esclarecer este requisito?")
        for parte in analise["pontuacao_categorias"]:
            parte["pontos_obtidos"] = 0
        parecer["status_recomendacao"] = "Não Recomendado"
    elif score == 100:
        analise["score_aderencia"] = 100
        analise["avaliacoes_requisitos"][1].update(situacao="demonstrado", evidencia="Desenvolvimento", esclarecer_entrevista=None)
        analise["pontuacao_categorias"][1]["pontos_obtidos"] = 20
        parecer["status_recomendacao"] = "Altamente Recomendado"
    else:
        assert score == 80
    return dados, analise, parecer


def configurar(client, itens):
    client.models.generate_content.side_effect = [
        item if isinstance(item, Exception) else SimpleNamespace(text=json.dumps(item))
        for item in itens
    ]


class LoteTests(anteriores.SemRede):
    def test_reutiliza_etapas_sequencialmente_ordena_e_preserva_empates_e_zero(self):
        arquivos = [pdf(i, f"CV{i}") for i in range(1, 5)]
        client = Mock()
        configurar(client, [item for nome, score in [("ZERO", 0), ("MAIOR", 100), ("EMPATE_A", 80), ("EMPATE_B", 80)]
                           for item in respostas(nome, score)])
        progresso = Mock()
        with patch("pipeline.executar_p01_extracao", wraps=pipeline.executar_p01_extracao) as p01, \
             patch("pipeline.executar_p02_aderencia", wraps=pipeline.executar_p02_aderencia) as p02, \
             patch("pipeline.executar_p03_parecer", wraps=pipeline.executar_p03_parecer) as p03:
            lote = pipeline.executar_lote(client, arquivos, anteriores.VAGA, log=lambda mensagem: None, progresso=progresso)
        self.assertEqual([item["analise"]["score_aderencia"] for item in lote["ranking"]], [100, 80, 80, 0])
        self.assertEqual([item["ordem"] for item in lote["ranking"]], [2, 3, 4, 1])
        self.assertEqual(lote["falhas"], [])
        self.assertEqual([p01.call_count, p02.call_count, p03.call_count], [4, 4, 4])
        self.assertEqual([chamada.args for chamada in progresso.call_args_list], [(1, 4), (2, 4), (3, 4), (4, 4)])
        self.assertEqual(client.models.generate_content.call_count, 12)
        for i in range(4):
            self.assertIn(f"CV{i + 1}", client.models.generate_content.call_args_list[3 * i].kwargs["contents"])

    def test_falhas_pdf_api_p02_p03_nao_interrompem_demais_nem_criam_scores(self):
        corrompido = io.BytesIO(b"%PDF-1.7\ninvalido")
        corrompido.name = f"{anteriores.PRIVADO}-corrompido.pdf"
        arquivos = [corrompido] + [pdf(i) for i in range(2, 7)]
        ruim_p02 = list(respostas("FALHA_P02"))
        ruim_p02[1]["score_aderencia"] = 150
        ruim_p03 = list(respostas("FALHA_P03"))
        ruim_p03[2]["status_recomendacao"] = "Altamente Recomendado"
        client = Mock()
        configurar(client, [*respostas("VALIDO_A"), RuntimeError(anteriores.PRIVADO),
                           *ruim_p02[:2], *ruim_p03, *respostas("VALIDO_B", 100)])
        logs = []
        lote = pipeline.executar_lote(client, arquivos, anteriores.VAGA, log=logs.append)
        self.assertEqual([item["ordem"] for item in lote["ranking"]], [6, 2])
        self.assertEqual([item["ordem"] for item in lote["falhas"]], [1, 3, 4, 5])
        self.assertEqual(client.models.generate_content.call_count, 12)
        for falha in lote["falhas"]:
            self.assertEqual(set(falha), {"ordem", "arquivo"})
        self.assertNotIn(anteriores.PRIVADO, "\n".join(logs))
        self.assertNotIn("CV sintetico", "\n".join(logs))
        self.assertNotIn("VALIDO_A", "\n".join(logs))

    def test_limite_rejeita_vazio_e_onze_sem_chamadas_e_aceita_dez(self):
        client = Mock()
        for quantidade in [0, 11]:
            with self.subTest(quantidade=quantidade), self.assertRaises(pipeline.ErroPipeline):
                pipeline.executar_lote(client, [pdf(i) for i in range(quantidade)], anteriores.VAGA)
        client.models.generate_content.assert_not_called()
        configurar(client, [item for i in range(10) for item in respostas(f"CANDIDATO_{i}")])
        lote = pipeline.executar_lote(client, [pdf(i) for i in range(10)], anteriores.VAGA, log=lambda mensagem: None)
        self.assertEqual(len(lote["ranking"]), 10)
        self.assertEqual(client.models.generate_content.call_count, 30)


class LoteInterfaceTests(anteriores.SemRede):
    def setUp(self):
        super().setUp()
        self.client = Mock()
        self.arquivos = [pdf(1), pdf(2)]
        self.upload_alterado = False
        self.multiplo = False
        self.factory = patch("google.genai.Client", return_value=self.client)
        self.factory_mock = self.factory.start()
        self.addCleanup(self.factory.stop)
        for troca in [patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": "CHAVE_SINTETICA"}),
                      patch("streamlit.file_uploader", side_effect=self.uploader)]:
            troca.start()
            self.addCleanup(troca.stop)
        self.app = anteriores.AppTest.from_file(str(anteriores.ROOT / "app.py"), default_timeout=15)

    def uploader(self, *args, accept_multiple_files=False, on_change, **kwargs):
        self.multiplo = accept_multiple_files
        if accept_multiple_files and self.upload_alterado:
            on_change()
            self.upload_alterado = False
        return self.arquivos if accept_multiple_files else None

    def analisar_lote(self):
        self.app.run()
        self.app.radio[0].set_value("Análise em lote").run()
        self.app.text_input[0].set_value("Vaga sintetica")
        self.app.text_area[0].set_value(anteriores.VAGA)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertTrue(self.multiplo)

    def responder_dois(self):
        configurar(self.client, [*respostas("PRIMEIRO"), *respostas("SEGUNDO", 100)])

    def test_ranking_e_detalhes_preservados_sem_chamadas_na_selecao_e_rerun(self):
        self.responder_dois()
        self.analisar_lote()
        lote = copy.deepcopy(self.app.session_state["lote"])
        self.assertNotIn("resultado", self.app.session_state)
        self.assertEqual(self.app.table[0].value["Pontuação de aderência"].tolist(), [100, 80])
        self.assertEqual(self.app.metric[0].value, "SEGUNDO")
        self.app.run()
        self.app.selectbox[0].set_value(1).run()
        self.assertEqual(self.app.metric[0].value, "PRIMEIRO")
        self.assertEqual(self.app.metric[1].value, "80 / 100")
        self.assertEqual(self.app.session_state["lote"], lote)
        self.assertEqual(self.client.models.generate_content.call_count, 6)
        self.assertEqual(self.factory_mock.call_count, 1)

    def test_editar_vaga_ou_selecao_invalida_ranking_sem_chamadas(self):
        for campo in ["titulo", "requisitos", "arquivos"]:
            with self.subTest(campo=campo):
                self.arquivos = [pdf(1), pdf(2)]
                self.responder_dois()
                self.analisar_lote()
                chamadas = self.client.models.generate_content.call_count
                if campo == "titulo":
                    self.app.text_input[0].set_value("Nova vaga").run()
                elif campo == "requisitos":
                    self.app.text_area[0].set_value("Novos requisitos").run()
                else:
                    self.arquivos = [pdf(1, "Novo conteudo")]
                    self.upload_alterado = True
                    self.app.run()
                self.assertNotIn("lote", self.app.session_state)
                self.assertNotIn("resultado", self.app.session_state)
                self.assertEqual(len(self.app.table), 0)
                self.assertEqual(len(self.app.metric), 0)
                self.assertEqual(self.client.models.generate_content.call_count, chamadas)

    def test_nova_execucao_substitui_lote_e_todas_as_falhas_nao_exibem_sucesso_antigo(self):
        self.responder_dois()
        self.analisar_lote()
        self.app.selectbox[0].set_value(1).run()
        self.arquivos = [pdf(3)]
        self.upload_alterado = True
        self.app.run()
        configurar(self.client, respostas("NOVO_CANDIDATO"))
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(len(self.app.session_state["lote"]["ranking"]), 1)
        self.assertEqual(self.app.metric[0].value, "NOVO_CANDIDATO")
        self.assertEqual(self.app.selectbox[0].value, 0)
        corrompido = io.BytesIO(b"%PDF-1.7\ninvalido")
        corrompido.name = f"{anteriores.PRIVADO}-novo.pdf"
        self.arquivos = [corrompido]
        self.upload_alterado = True
        self.app.run()
        configurar(self.client, [])
        self.app.button[0].click().run()
        self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state["lote"]["ranking"], [])
        self.assertEqual(len(self.app.session_state["lote"]["falhas"]), 1)
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.success), 0)
        self.assertEqual(len(self.app.error), 1)
        self.assertEqual(self.client.models.generate_content.call_count, 9)

    def test_vazio_e_acima_do_limite_na_interface_nao_criam_cliente(self):
        for quantidade in [0, 11]:
            with self.subTest(quantidade=quantidade):
                self.arquivos = [pdf(i) for i in range(quantidade)]
                self.analisar_lote()
                self.assertEqual(len(self.app.warning), 1)
                self.assertEqual(len(self.app.metric), 0)
                self.assertNotIn("lote", self.app.session_state)
        self.factory_mock.assert_not_called()
        self.client.models.generate_content.assert_not_called()

    def test_modos_nao_misturam_resultados_e_individual_continua_funcionando(self):
        configurar(self.client, respostas("INDIVIDUAL"))
        self.app.run()
        self.app.text_input[0].set_value("Vaga sintetica")
        self.app.text_area[0].set_value(anteriores.VAGA)
        self.app.text_area[1].set_value("CV manual")
        self.app.button[0].click().run()
        self.assertEqual(self.app.metric[0].value, "INDIVIDUAL")
        self.assertIn("resultado", self.app.session_state)
        self.app.radio[0].set_value("Análise em lote").run()
        self.assertNotIn("resultado", self.app.session_state)
        self.assertEqual(self.client.models.generate_content.call_count, 3)
        self.responder_dois()
        self.app.button[0].click().run()
        self.assertIn("lote", self.app.session_state)
        self.assertNotIn("resultado", self.app.session_state)
        self.app.radio[0].set_value("Análise individual").run()
        self.assertNotIn("lote", self.app.session_state)
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(self.client.models.generate_content.call_count, 9)
        configurar(self.client, respostas("INDIVIDUAL_NOVO"))
        self.app.text_area[1].set_value("Novo CV manual")
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.metric[0].value, "INDIVIDUAL_NOVO")
        self.assertNotIn("lote", self.app.session_state)
        self.assertEqual(self.client.models.generate_content.call_count, 12)

    def test_falha_identifica_arquivo_so_na_interface_e_preserva_validos(self):
        corrompido = io.BytesIO(b"%PDF-1.7\ninvalido")
        corrompido.name = f"{anteriores.PRIVADO}-falhou.pdf"
        self.arquivos = [corrompido, pdf(2)]
        configurar(self.client, respostas("VALIDO_LOCAL"))
        output = io.StringIO()
        with redirect_stdout(output):
            self.analisar_lote()
        self.assertEqual(len(self.app.session_state["lote"]["ranking"]), 1)
        self.assertEqual(self.app.metric[0].value, "VALIDO_LOCAL")
        self.assertIn(corrompido.name, self.app.warning[0].value)
        self.assertNotIn(anteriores.PRIVADO, "\n".join(self.app.session_state["logs"]))
        self.assertNotIn(anteriores.PRIVADO, self.app.code[0].value)
        self.assertNotIn(anteriores.PRIVADO, output.getvalue())
        self.assertEqual(self.client.models.generate_content.call_count, 3)
