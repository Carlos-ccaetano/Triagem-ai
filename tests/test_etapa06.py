from unittest.mock import patch

import test_etapa01 as anteriores
import test_etapa04 as etapa04


class ValidacaoFinalTests(anteriores.SemRede):
    def test_clientes_individual_e_lote_desabilitam_retries_automaticos(self):
        client = anteriores.cliente_simulado(anteriores.P01, anteriores.P02, anteriores.P03)
        app = anteriores.AppTest.from_file(str(anteriores.ROOT / "app.py"), default_timeout=15)
        with patch.dict(anteriores.os.environ, {"GEMINI_API_KEY": "CHAVE_SINTETICA"}), \
             patch("google.genai.Client", return_value=client) as criar:
            app.run()
            app.text_input[0].set_value("Vaga sintetica")
            app.text_area[0].set_value(anteriores.VAGA)
            app.text_area[1].set_value("CV sintetico")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            arquivos = [etapa04.pdf(1), etapa04.pdf(2)]
            etapa04.configurar(client, [*etapa04.respostas("A"), *etapa04.respostas("B")])
            with patch("streamlit.file_uploader", side_effect=lambda *args, accept_multiple_files=False, **kwargs: arquivos if accept_multiple_files else None):
                app.radio[0].set_value("Análise em lote").run()
                app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
        self.assertEqual(criar.call_count, 2)
        for chamada in criar.call_args_list:
            self.assertEqual(chamada.kwargs["http_options"]["retry_options"]["attempts"], 1)
        self.assertEqual(client.models.generate_content.call_count, 9)
