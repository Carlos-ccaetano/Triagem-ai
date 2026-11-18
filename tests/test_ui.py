import copy
from unittest.mock import patch

import test_etapa01 as anteriores
import test_etapa05 as etapa05
import persistencia


class HumanizacaoInterfaceTests(anteriores.SemRede):
    def setUp(self):
        super().setUp()
        self.client = anteriores.cliente_simulado(anteriores.P01, anteriores.P02, anteriores.P03)
        for troca in [patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": "CHAVE_SINTETICA"}),
                      patch("google.genai.Client", return_value=self.client)]:
            troca.start()
            self.addCleanup(troca.stop)
        self.app = anteriores.AppTest.from_file(str(anteriores.ROOT / "app.py"), default_timeout=15)

    def analisar(self):
        self.app.run()
        self.app.text_input[0].set_value("Vaga atual")
        self.app.text_area[0].set_value(anteriores.VAGA)
        self.app.text_area[1].set_value("CV sintetico")
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)

    def test_historico_sem_chave_nao_exige_nova_analise(self):
        salvo = etapa05.execucao("salva")
        persistencia.salvar_analise(salvo)
        with patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": ""}):
            self.app.run()
            self.assertEqual([aba.label for aba in self.app.tabs], ["Nova análise", "Histórico"])
            self.assertEqual(self.app.radio[0].options, ["Um currículo", "Vários currículos"])
            self.assertTrue(self.app.button[0].disabled)
            self.app.button(key="abrir_historico").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(self.app.tabs[1].metric[1].value, "80 / 100")
            self.assertEqual(len(self.app.tabs[0].metric), 0)
        self.client.models.generate_content.assert_not_called()

    def test_historico_exibe_data_em_sao_paulo(self):
        persistencia.salvar_analise(etapa05.execucao("fuso", data="2026-11-17T12:00:00+00:00"))
        with patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": ""}):
            self.app.run()
            self.assertEqual(len(self.app.tabs[1].error), 0)
            self.assertIn("17/11/2026 09:00:00", self.app.selectbox(key="analise_historico").options[0])
            self.app.button(key="abrir_historico").click().run()
            self.assertEqual(len(self.app.exception), 0)
            self.assertEqual(len(self.app.tabs[1].error), 0)
            self.assertTrue(any("17/11/2026 às 09:00:00" in item.value for item in self.app.caption))
        self.client.models.generate_content.assert_not_called()

    def test_avaliacao_atual_e_salva_tem_detalhes_e_exportacoes_separados(self):
        salvo = etapa05.execucao("salva", modo="lote")
        persistencia.salvar_analise(salvo)
        self.analisar()
        atual = copy.deepcopy(self.app.session_state["resultado"])
        self.app.button(key="abrir_historico").click().run()
        self.assertEqual(self.app.tabs[0].metric[1].value, "80 / 100")
        self.assertEqual(self.app.tabs[1].metric[1].value, "100 / 100")
        ranking = self.app.tabs[1].table[0].value
        self.assertEqual(ranking["Posição"].tolist(), [1, 2])
        self.assertEqual(list(ranking.columns), ["Posição", "Candidato", "Pontuação", "Classificação"])
        self.app.selectbox(key="candidato_historico_salva").set_value(1).run()
        with patch("streamlit.download_button", return_value=False) as download:
            self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertEqual(self.app.session_state["resultado"], atual)
        self.assertEqual(download.call_count, 2)
        csv_atual, csv_salvo = [etapa05.ler_csv(c.kwargs["data"]) for c in download.call_args_list]
        self.assertEqual(len(csv_atual), 2)
        self.assertEqual(len(csv_salvo), 3)
        self.assertEqual(csv_atual[1][2], "Vaga atual")
        self.assertEqual(csv_salvo[1][2], salvo["titulo_vaga"])
        self.assertEqual([row[3] for row in csv_salvo[1:]], ["100", "80"])
        self.app.button(key="salvar_historico").click().run()
        self.app.button(key="salvar_historico").click().run()
        self.assertEqual(len(persistencia.listar_historico()), 2)
        self.assertEqual(self.client.models.generate_content.call_count, 3)

    def test_nao_informado_e_incompatibilidade_explicita_continuam_distintos(self):
        for situacao in ["nao_informado", "nao_atendido"]:
            with self.subTest(situacao=situacao):
                dados = dict(anteriores.P01, cargo_atual="Desenvolvedor Júnior")
                analise = copy.deepcopy(anteriores.P02)
                item = analise["avaliacoes_requisitos"][1]
                item["situacao"] = situacao
                item["evidencia"] = None if situacao == "nao_informado" else "Júnior"
                self.client.models.generate_content.side_effect = anteriores.cliente_simulado(
                    dados, analise, anteriores.P03
                ).models.generate_content.side_effect
                self.analisar()
                self.assertEqual(self.app.metric[1].value, "80 / 100")
                textos = "\n".join(x.value for x in self.app.markdown)
                self.assertIn("O que foi demonstrado", textos)
                self.assertIn("Pontos a esclarecer", textos)
                self.assertIn(item["esclarecer_entrevista"], textos)
                if situacao == "nao_informado":
                    self.assertIn("O currículo não traz informação suficiente", textos)
                    self.assertNotIn("A evidência apresentada não atende", textos)
                else:
                    self.assertIn("A evidência apresentada não atende", textos)
                self.assertEqual(self.app.session_state["resultado"]["analise"], analise)
