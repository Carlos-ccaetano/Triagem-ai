import json
from typing import Annotated, Literal

from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pypdf import PdfReader
from pypdf.errors import PyPdfError

MODEL_ID = "gemini-2.5-flash"


class ErroPipeline(ValueError):
    """Falha com mensagem segura para exibição, sem conteúdo do candidato."""


class SaidaP01(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    nome_candidato: str
    cargo_atual: str
    anos_experiencia_total: float = Field(ge=0, allow_inf_nan=False)
    habilidades_tecnicas: list[str]
    formacao: str


class SaidaP02(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    analise_passo_a_passo: list[str]
    gaps_identificados: list[str]
    score_aderencia: int = Field(ge=0, le=100)


class SaidaP03(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    status_recomendacao: Literal["Altamente Recomendado", "Recomendado com Ressalvas", "Não Recomendado"]
    resumo_executivo: str = Field(min_length=1)
    perguntas_entrevista: list[Annotated[str, Field(min_length=1)]] = Field(min_length=3, max_length=3)

    @field_validator("resumo_executivo")
    @classmethod
    def limitar_linhas(cls, valor):
        if len(valor.splitlines()) > 4:
            raise ValueError("O resumo deve ter no máximo quatro linhas.")
        return valor


def _validar_resposta(texto, modelo, etapa) -> dict:
    try:
        return modelo.model_validate_json(texto).model_dump()
    except ValidationError:
        raise ErroPipeline(f"Resposta inválida na etapa {etapa}. Tente novamente.") from None


def extrair_texto_pdf(arquivo_pdf) -> str:
    """Extrai texto nativo, preservando a separação entre páginas."""
    try:
        arquivo_pdf.seek(0)
        reader = PdfReader(arquivo_pdf)
        texto = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except (PyPdfError, OSError, ValueError):
        raise ErroPipeline("Não foi possível ler o PDF. Envie um PDF válido ou cole o texto manualmente.") from None
    if not texto:
        raise ErroPipeline("O PDF não contém texto legível. Cole o currículo manualmente.")
    return texto


def executar_p01_extracao(client, texto_curriculo: str, log=print) -> dict:
    """P01: Role Prompt + Few-Shot para extração estruturada em JSON."""
    log(f"Executando P01 (Extração JSON) via {MODEL_ID}...")
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
    resultado = _validar_resposta(response.text, SaidaP01, "P01")
    log("Resposta P01 validada.")
    return resultado


def executar_p02_aderencia(client, dados_candidato: dict, descricao_vaga: str, log=print) -> dict:
    """P02: Chain of Thought (CoT) para análise de aderência Vaga x Candidato."""
    log("Injetando saída do P01 no Prompt P02 (Chain of Thought)...")
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
    resultado = _validar_resposta(response.text, SaidaP02, "P02")
    log("Resposta P02 validada.")
    return resultado


def executar_p03_parecer(client, dados_candidato: dict, analise_cot: dict, descricao_vaga: str, log=print) -> dict:
    """P03: Role Prompt + Zero-Shot Estruturado para parecer final e perguntas de entrevista."""
    log("Executando P03 (Parecer Final e Roteiro de Entrevista)...")
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
    resultado = _validar_resposta(response.text, SaidaP03, "P03")
    log("Resposta P03 recebida. Pipeline finalizado com sucesso.")
    return resultado
