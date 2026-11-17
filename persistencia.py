import csv
import io
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pipeline import LIMITE_LOTE, SaidaP02, SaidaP03, _classificacao_esperada

CAMINHO_BANCO = Path(__file__).resolve().parent / "data" / "triagem.db"


@contextmanager
def _conexao():
    CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(CAMINHO_BANCO)) as conexao:
        conexao.row_factory = sqlite3.Row
        with conexao:
            conexao.execute("""CREATE TABLE IF NOT EXISTS execucoes (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                titulo_vaga TEXT NOT NULL,
                descricao_vaga TEXT NOT NULL,
                modo TEXT NOT NULL CHECK (modo IN ('individual', 'lote')),
                resultados_json TEXT NOT NULL
            )""")
            yield conexao


def _dados_execucao(execucao):
    for campo in ["id", "titulo_vaga", "descricao_vaga"]:
        if not isinstance(execucao[campo], str) or not execucao[campo].strip():
            raise ValueError("Dados da execução inválidos.")
    data = datetime.fromisoformat(execucao["data"])
    if data.tzinfo is None:
        raise ValueError("A data da execução deve informar o fuso horário.")
    modo = execucao["modo"]
    falhas = execucao["quantidade_falhas"]
    candidatos = execucao["candidatos"]
    if modo not in ("individual", "lote") or type(falhas) is not int or falhas < 0 or not isinstance(candidatos, list):
        raise ValueError("Execução inválida.")
    if (modo == "individual" and (len(candidatos) != 1 or falhas != 0)) or not 1 <= len(candidatos) + falhas <= LIMITE_LOTE or not candidatos:
        raise ValueError("Quantidade de resultados inválida.")
    resultados = []
    for candidato in candidatos:
        nome = candidato["dados"]["nome_candidato"]
        if not isinstance(nome, str):
            raise ValueError("Nome inválido.")
        analise = SaidaP02.model_validate(candidato["analise"]).model_dump()
        parecer = SaidaP03.model_validate(candidato["parecer"]).model_dump()
        if parecer["status_recomendacao"] != _classificacao_esperada(analise):
            raise ValueError("Parecer incompatível com a avaliação.")
        resultados.append({"dados": {"nome_candidato": nome}, "analise": analise, "parecer": parecer})
    return {
        "id": execucao["id"], "data": data.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        "titulo_vaga": execucao["titulo_vaga"], "descricao_vaga": execucao["descricao_vaga"],
        "modo": modo, "candidatos": resultados, "quantidade_falhas": falhas,
    }


def salvar_analise(execucao: dict) -> bool:
    dados = _dados_execucao(execucao)
    conteudo = json.dumps({"candidatos": dados["candidatos"], "quantidade_falhas": dados["quantidade_falhas"]}, ensure_ascii=False, allow_nan=False)
    with _conexao() as conexao:
        cursor = conexao.execute(
            "INSERT INTO execucoes (id, data, titulo_vaga, descricao_vaga, modo, resultados_json) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (dados["id"], dados["data"], dados["titulo_vaga"], dados["descricao_vaga"], dados["modo"], conteudo),
        )
        return cursor.rowcount == 1


def listar_historico() -> list:
    with _conexao() as conexao:
        return [dict(linha) for linha in conexao.execute(
            "SELECT id, data, titulo_vaga, modo FROM execucoes ORDER BY data DESC, rowid DESC"
        )]


def consultar_analise(identificador: str):
    with _conexao() as conexao:
        linha = conexao.execute("SELECT * FROM execucoes WHERE id = ?", (identificador,)).fetchone()
    if linha is None:
        return None
    conteudo = json.loads(linha["resultados_json"])
    metadados = {campo: linha[campo] for campo in ["id", "data", "titulo_vaga", "descricao_vaga", "modo"]}
    return _dados_execucao({**conteudo, **metadados})


def excluir_analise(identificador: str) -> bool:
    with _conexao() as conexao:
        return conexao.execute("DELETE FROM execucoes WHERE id = ?", (identificador,)).rowcount == 1


def _texto_csv(valor):
    if isinstance(valor, str) and (valor.startswith(("\t", "\r", "\n")) or valor.lstrip().startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠"))):
        # Prefixo literal para planilhas; nunca modifica o resultado armazenado.
        return "\t" + valor
    return valor


def exportar_csv(execucao: dict) -> bytes:
    dados = _dados_execucao(execucao)
    saida = io.StringIO(newline="")
    writer = csv.writer(saida, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["Posição", "Nome identificado", "Vaga", "Score de aderência", "Classificação", "Resumo da avaliação",
                     "Pergunta de entrevista 1", "Pergunta de entrevista 2", "Pergunta de entrevista 3"])
    for posicao, candidato in enumerate(dados["candidatos"], 1):
        linha = [posicao if dados["modo"] == "lote" else "", candidato["dados"]["nome_candidato"].strip() or "Não informado",
                 dados["titulo_vaga"], candidato["analise"]["score_aderencia"], candidato["parecer"]["status_recomendacao"],
                 candidato["parecer"]["resumo_executivo"], *candidato["parecer"]["perguntas_entrevista"]]
        writer.writerow([_texto_csv(valor) for valor in linha])
    return saida.getvalue().encode("utf-8-sig")
