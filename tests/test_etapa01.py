import io
import json
import os
import socket
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from streamlit.testing.v1 import AppTest

from pipeline import (
    MODEL_ID,
    ErroPipeline,
    executar_p01_extracao,
    executar_p02_aderencia,
    executar_p03_parecer,
    extrair_texto_pdf,
)

ROOT = Path(__file__).resolve().parents[1]
PRIVADO = "PESSOA_SINTETICA_SIGILOSA"
P01 = {
    "nome_candidato": PRIVADO,
    "cargo_atual": "Desenvolvimento",
    "anos_experiencia_total": 2,
    "habilidades_tecnicas": ["Python"],
    "formacao": "Curso sintetico",
}
P02 = {
    "analise_passo_a_passo": ["Evidencia sintetica"],
    "gaps_identificados": [],
    "score_aderencia": 80,
}
P03 = {
    "status_recomendacao": "Recomendado com Ressalvas",
    "resumo_executivo": "Parecer sintetico",
    "perguntas_entrevista": ["Pergunta 1", "Pergunta 2", "Pergunta 3"],
}


def cliente_simulado(*respostas):
    client = Mock()
    client.models.generate_content.side_effect = [
        SimpleNamespace(text=json.dumps(item, ensure_ascii=False)) for item in respostas
    ]
    return client


def pdf_com_textos(*textos):
    writer = PdfWriter()
    for texto in textos:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }),
            }),
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({texto}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    arquivo = io.BytesIO()
    writer.write(arquivo)
    arquivo.name = f"{PRIVADO}.pdf"
    return arquivo


class SemRede(unittest.TestCase):
    def setUp(self):
        bloqueio = patch.object(socket.socket, "connect", side_effect=AssertionError("Rede proibida nos testes"))
        bloqueio.start()
        self.addCleanup(bloqueio.stop)


class PipelineTests(SemRede):
    def test_respostas_validas_e_configuracao_gemini(self):
        client = cliente_simulado(P01, P02, P03)
        dados = executar_p01_extracao(client, "CV sintetico")
        analise = executar_p02_aderencia(client, dados, "Vaga sintetica")
        parecer = executar_p03_parecer(client, dados, analise, "Vaga sintetica")
        self.assertEqual(dados, P01)
        self.assertEqual(analise, P02)
        self.assertEqual(parecer, P03)
        for chamada, temperatura in zip(client.models.generate_content.call_args_list, [0.1, 0.2, 0.3]):
            self.assertEqual(chamada.kwargs["model"], MODEL_ID)
            self.assertEqual(MODEL_ID, "gemini-2.5-flash")
            self.assertEqual(chamada.kwargs["config"].temperature, temperatura)
            self.assertEqual(chamada.kwargs["config"].response_mime_type, "application/json")

    def test_p01_rejeita_campos_tipos_e_valores_invalidos(self):
        casos = [[], {}, None, dict(P01, anos_experiencia_total=-1),
                 dict(P01, anos_experiencia_total="2"), dict(P01, anos_experiencia_total=True),
                 dict(P01, anos_experiencia_total=float("inf")),
                 dict(P01, habilidades_tecnicas=[123]), dict(P01, campo_extra=PRIVADO)]
        for resposta in casos:
            with self.subTest(resposta=resposta):
                client = cliente_simulado(resposta)
                with self.assertRaisesRegex(ErroPipeline, "P01"):
                    executar_p01_extracao(client, "CV sintetico")
                self.assertEqual(client.models.generate_content.call_count, 1)

    def test_json_malformado_ou_resposta_ausente_tem_erro_seguro(self):
        for texto in ["JSON INVALIDO " + PRIVADO, "", None]:
            with self.subTest(texto=texto):
                client = Mock()
                client.models.generate_content.return_value = SimpleNamespace(text=texto)
                with self.assertRaises(ErroPipeline) as erro:
                    executar_p01_extracao(client, "CV sintetico")
                self.assertNotIn(PRIVADO, str(erro.exception))

    def test_p02_rejeita_score_e_listas_invalidos(self):
        casos = [dict(P02, score_aderencia=score) for score in [-1, 101, "80", 80.5, True]]
        casos += [[], {}, dict(P02, gaps_identificados="gap"), dict(P02, analise_passo_a_passo=[3])]
        for resposta in casos:
            with self.subTest(resposta=resposta):
                with self.assertRaisesRegex(ErroPipeline, "P02"):
                    executar_p02_aderencia(cliente_simulado(resposta), P01, "Vaga")

    def test_p03_rejeita_status_perguntas_e_resumo_invalidos(self):
        casos = [dict(P03, status_recomendacao="Outro"),
                 dict(P03, perguntas_entrevista=["Uma", "Duas"]),
                 dict(P03, perguntas_entrevista=["1", "2", "3", "4"]),
                 dict(P03, perguntas_entrevista="Tres perguntas"),
                 dict(P03, perguntas_entrevista=["1", "2", ""]),
                 dict(P03, resumo_executivo=""),
                 dict(P03, resumo_executivo="1\n2\n3\n4\n5"), {}]
        for resposta in casos:
            with self.subTest(resposta=resposta):
                with self.assertRaisesRegex(ErroPipeline, "P03"):
                    executar_p03_parecer(cliente_simulado(resposta), P01, P02, "Vaga")

    def test_logs_pipeline_nao_contem_dados_do_candidato(self):
        output = io.StringIO()
        client = cliente_simulado(P01, P02, P03)
        with redirect_stdout(output):
            dados = executar_p01_extracao(client, PRIVADO)
            analise = executar_p02_aderencia(client, dados, "Vaga")
            executar_p03_parecer(client, dados, analise, "Vaga")
        self.assertNotIn(PRIVADO, output.getvalue())
        self.assertIn("Resposta P01 validada", output.getvalue())

    def test_pdf_corrompido(self):
        with self.assertRaisesRegex(ErroPipeline, "cole o texto manualmente"):
            extrair_texto_pdf(io.BytesIO(b"%PDF-1.7\nconteudo invalido"))

    def test_pdf_arquivo_vazio(self):
        with self.assertRaises(ErroPipeline):
            extrair_texto_pdf(io.BytesIO())

    def test_pdf_sem_paginas(self):
        with self.assertRaisesRegex(ErroPipeline, "não contém texto"):
            extrair_texto_pdf(pdf_com_textos())

    def test_pdf_pagina_sem_texto(self):
        writer = PdfWriter()
        writer.add_blank_page(width=600, height=800)
        arquivo = io.BytesIO()
        writer.write(arquivo)
        with self.assertRaisesRegex(ErroPipeline, "não contém texto"):
            extrair_texto_pdf(arquivo)

    def test_pdf_multiplas_paginas_e_reposicionamento(self):
        arquivo = pdf_com_textos("Python", "SQL")
        self.assertGreater(arquivo.tell(), 0)
        self.assertEqual(extrair_texto_pdf(arquivo), "Python\nSQL")


class InterfaceTests(SemRede):
    def setUp(self):
        super().setUp()
        self.client = cliente_simulado(P01, P02, P03)
        for troca in [patch.dict(os.environ, {"GEMINI_API_KEY": "CHAVE_SINTETICA"}),
                      patch("google.genai.Client", return_value=self.client)]:
            troca.start()
            self.addCleanup(troca.stop)
        self.app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)

    def analisar(self, texto="CV sintetico", cargo="Vaga sintetica"):
        self.app.run()
        self.app.text_input[0].set_value(cargo)
        self.app.text_area[0].set_value("Python")
        self.app.text_area[1].set_value(texto)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.exception), 0)

    def test_interface_com_respostas_validas(self):
        self.analisar()
        self.assertEqual(len(self.app.error), 0)
        self.assertEqual(self.client.models.generate_content.call_count, 3)
        self.assertEqual(self.app.metric[0].value, PRIVADO)
        self.assertEqual(self.app.metric[1].value, "80 / 100")
        self.assertNotIn(PRIVADO, "\n".join(self.app.session_state["logs"]))

    def test_resposta_invalida_interrompe_na_etapa_correta(self):
        for respostas, etapa, chamadas in [([[]], "P01", 1),
                                         ([P01, dict(P02, score_aderencia=150)], "P02", 2),
                                         ([P01, P02, dict(P03, perguntas_entrevista=[])], "P03", 3)]:
            with self.subTest(etapa=etapa):
                self.client.models.generate_content.reset_mock()
                self.client.models.generate_content.side_effect = [
                    SimpleNamespace(text=json.dumps(item)) for item in respostas
                ]
                self.analisar()
                self.assertEqual(self.client.models.generate_content.call_count, chamadas)
                self.assertIn(etapa, self.app.error[0].value)
                self.assertEqual(len(self.app.metric), 0)

    def test_erro_provedor_nao_expoe_conteudo_nos_logs_ou_mensagem(self):
        self.client.models.generate_content.side_effect = RuntimeError(PRIVADO)
        output = io.StringIO()
        with redirect_stdout(output):
            self.analisar()
        self.assertEqual(len(self.app.error), 1)
        self.assertNotIn(PRIVADO, self.app.error[0].value)
        self.assertNotIn(PRIVADO, "\n".join(self.app.session_state["logs"]))
        self.assertNotIn(PRIVADO, output.getvalue())

    def test_pdf_invalido_sem_manual_nao_chama_modelo(self):
        arquivo = io.BytesIO(b"%PDF-1.7\ninvalido")
        arquivo.name = f"{PRIVADO}.pdf"
        with patch("streamlit.file_uploader", return_value=arquivo):
            self.analisar(texto="")
        self.assertEqual(self.client.models.generate_content.call_count, 0)
        self.assertIn("PDF", self.app.error[0].value)
        self.assertNotIn(PRIVADO, "\n".join(self.app.session_state["logs"]))

    def test_texto_manual_tem_prioridade_sobre_pdf_invalido(self):
        arquivo = io.BytesIO(b"invalido")
        arquivo.name = f"{PRIVADO}.pdf"
        with patch("streamlit.file_uploader", return_value=arquivo), \
             patch("pipeline.extrair_texto_pdf", side_effect=AssertionError("Nao deve ler PDF")):
            self.analisar(texto="TEXTO_MANUAL_SINTETICO")
        self.assertEqual(len(self.app.error), 0)
        self.assertEqual(self.client.models.generate_content.call_count, 3)
        self.assertIn("TEXTO_MANUAL_SINTETICO", self.client.models.generate_content.call_args_list[0].kwargs["contents"])

    def test_log_pdf_preserva_contagem_sem_nome_arquivo(self):
        with patch("streamlit.file_uploader", return_value=pdf_com_textos("Python", "SQL")):
            self.analisar(texto="")
        logs = "\n".join(self.app.session_state["logs"])
        self.assertIn("PDF_EXTRACTED_CHARS", logs)
        self.assertNotIn(PRIVADO, logs)
        self.assertEqual(len(self.app.error), 0)

    def test_vaga_vazia_nao_chama_modelo(self):
        self.analisar(cargo=" ")
        self.assertEqual(len(self.app.warning), 1)
        self.assertEqual(self.client.models.generate_content.call_count, 0)

    def test_curriculo_ausente_nao_chama_modelo(self):
        self.analisar(texto=" ")
        self.assertEqual(len(self.app.warning), 1)
        self.assertEqual(self.client.models.generate_content.call_count, 0)

    def test_chave_ausente_nao_chama_modelo(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.app.run()
        self.assertEqual(len(self.app.exception), 0)
        self.assertIn("GEMINI_API_KEY", self.app.error[0].value)
        self.assertEqual(self.client.models.generate_content.call_count, 0)


if __name__ == "__main__":
    unittest.main()
