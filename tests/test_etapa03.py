import copy
import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import test_etapa01 as anteriores


class Etapa03Tests(anteriores.SemRede):
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

    def responder(self, *respostas):
        self.client.models.generate_content.side_effect = [
            SimpleNamespace(text=json.dumps(item)) for item in respostas
        ]

    def analisar(self, texto="CV sintetico"):
        self.app.run()
        self.app.text_input[0].set_value("Vaga sintetica")
        self.app.text_area[0].set_value(anteriores.VAGA)
        self.app.text_area[1].set_value(texto)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)

    def verificar_sem_resultado(self):
        self.assertNotIn("resultado", self.app.session_state)
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.success), 0)

    def test_resultado_e_logs_permanecem_em_reruns_sem_chamadas(self):
        self.analisar()
        resultado = copy.deepcopy(self.app.session_state["resultado"])
        logs = list(self.app.session_state["logs"])
        for _ in range(2):
            self.app.run()
            self.assertEqual(self.app.session_state["resultado"], resultado)
            self.assertEqual(self.app.session_state["logs"], logs)
            self.assertEqual(self.app.metric[1].value, "80 / 100")
            self.assertEqual(len(self.app.success), 1)
            self.assertEqual(self.client.models.generate_content.call_count, 3)
            self.assertEqual(self.factory_mock.call_count, 1)

    def test_editar_entradas_limpa_resultado_sem_executar_modelo(self):
        for campo in ["titulo", "requisitos", "texto"]:
            with self.subTest(campo=campo):
                self.responder(anteriores.P01, anteriores.P02, anteriores.P03)
                self.analisar()
                chamadas = self.client.models.generate_content.call_count
                widget = self.app.text_input[0] if campo == "titulo" else self.app.text_area[0 if campo == "requisitos" else 1]
                widget.set_value("Entrada alterada").run()
                self.verificar_sem_resultado()
                self.assertEqual(self.app.session_state["logs"], [])
                self.assertEqual(self.client.models.generate_content.call_count, chamadas)

    def test_callback_de_upload_invalida_pdf_com_mesmo_nome_sem_chamadas(self):
        arquivo = [anteriores.pdf_com_textos("Python")]
        mudou = [False]

        def uploader(*args, on_change, **kwargs):
            if mudou[0]:
                on_change()
                mudou[0] = False
            return arquivo[0]

        # AppTest não envia arquivos; simula o evento chamando o callback registrado.
        with patch("streamlit.file_uploader", side_effect=uploader):
            self.analisar(texto="")
            chamadas = self.client.models.generate_content.call_count
            nome = arquivo[0].name
            arquivo[0] = anteriores.pdf_com_textos("Python", "SQL")
            self.assertEqual(arquivo[0].name, nome)
            mudou[0] = True
            self.app.run()
            self.verificar_sem_resultado()
            self.assertEqual(self.client.models.generate_content.call_count, chamadas)

    def test_nova_analise_substitui_o_resultado_e_permanece_visivel(self):
        self.analisar()
        outro = dict(anteriores.P01, nome_candidato="OUTRO_CANDIDATO_SINTETICO")
        self.responder(outro, anteriores.P02, anteriores.P03)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.error), 0)
        self.assertEqual(self.app.metric[0].value, outro["nome_candidato"])
        self.assertEqual(self.app.session_state["resultado"]["dados"]["nome_candidato"], outro["nome_candidato"])
        self.app.run()
        self.assertEqual(self.app.metric[0].value, outro["nome_candidato"])
        self.assertEqual(self.client.models.generate_content.call_count, 6)
        self.assertEqual(self.factory_mock.call_count, 2)

    def test_falha_nova_remove_sucesso_anterior_e_preserva_erro_seguro(self):
        for tipo in [RuntimeError, anteriores.ErroPipeline]:
            with self.subTest(tipo=tipo):
                self.responder(anteriores.P01, anteriores.P02, anteriores.P03)
                self.analisar()
                chamadas = self.client.models.generate_content.call_count
                self.client.models.generate_content.side_effect = tipo(anteriores.PRIVADO)
                output = io.StringIO()
                with redirect_stdout(output):
                    self.app.button[0].click().run()
                    self.app.run()
                self.assertEqual(len(self.app.exception), 0)
                self.verificar_sem_resultado()
                self.assertEqual(len(self.app.error), 1)
                self.assertNotIn(anteriores.PRIVADO, self.app.error[0].value)
                self.assertNotIn(anteriores.PRIVADO, "\n".join(self.app.session_state["logs"]))
                self.assertNotIn(anteriores.PRIVADO, output.getvalue())
                self.assertEqual(self.client.models.generate_content.call_count, chamadas + 1)

    def test_score_ausente_ou_invalido_nao_vira_zero_nem_mantem_resultado(self):
        for valor in ["ausente", None, True, "80", 80.5, 150]:
            with self.subTest(valor=valor):
                self.responder(anteriores.P01, anteriores.P02, anteriores.P03)
                self.analisar()
                chamadas = self.client.models.generate_content.call_count
                invalido = copy.deepcopy(anteriores.P02)
                if valor == "ausente":
                    invalido.pop("score_aderencia")
                else:
                    invalido["score_aderencia"] = valor
                self.responder(anteriores.P01, invalido)
                self.app.button[0].click().run()
                self.verificar_sem_resultado()
                self.assertEqual(len(self.app.error), 1)
                self.assertEqual(self.client.models.generate_content.call_count, chamadas + 2)

    def test_zero_validado_e_exibido_como_pontuacao_real(self):
        analise = copy.deepcopy(anteriores.P02)
        analise["score_aderencia"] = 0
        for item in analise["avaliacoes_requisitos"]:
            item.update(situacao="nao_informado", evidencia=None, esclarecer_entrevista="Pode esclarecer este requisito?")
        for parte in analise["pontuacao_categorias"]:
            parte["pontos_obtidos"] = 0
        parecer = dict(anteriores.P03, status_recomendacao="Não Recomendado")
        self.responder(anteriores.P01, analise, parecer)
        self.analisar()
        self.assertEqual(len(self.app.error), 0)
        self.assertEqual(self.app.metric[1].value, "0 / 100")

    def test_nome_desconhecido_aparece_como_nao_informado(self):
        for nome in ["", "   "]:
            with self.subTest(nome=nome):
                self.responder(dict(anteriores.P01, nome_candidato=nome), anteriores.P02, anteriores.P03)
                self.analisar()
                self.assertEqual(len(self.app.error), 0)
                self.assertEqual(self.app.metric[0].value, "Não informado")
