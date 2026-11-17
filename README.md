# TriagemAI — Análise de evidências profissionais

> **Disciplina:** Engenharia de Prompt e Fundamentos de Inteligência Artificial
> **Entrega de origem:** E4 — Protótipo Inicial Funcional
> **Área de Impacto:** Recursos Humanos / Recrutamento e Seleção

MVP acadêmico executado localmente com Streamlit e Google Gemini (`gemini-2.5-flash`).
Recebe uma vaga e um currículo em texto ou PDF nativo. A avaliação considera evidências
profissionais e apoia a revisão humana; não contrata nem rejeita candidatos automaticamente.

## Execução local

Python 3.10 ou superior e uma chave do Google AI Studio são necessários. A `.venv`
do checkout atual já está preparada; em uma instalação nova, crie-a com
`python3 -m venv .venv` antes dos comandos abaixo.

```bash
cd /home/carloscaetano/estudos/Triagem-ai
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n .env.example .env
# Preencha GEMINI_API_KEY no .env antes de executar.
streamlit run app.py --server.address 127.0.0.1
```

No checkout existente, use `/home/carloscaetano/estudos/Triagem-ai`. Na ausência do módulo
venv/ensurepip, prepare o suporte a ambientes virtuais na distribuição antes da instalação.
O texto manual, quando preenchido, tem prioridade sobre o PDF. PDFs sem texto exigem
texto manual; não há OCR. Executar uma análise pela interface faz chamadas reais à API;
os testes abaixo usam respostas simuladas e bloqueiam conexões de rede.

## Pipeline e contratos — Etapa 02

- `app.py`: interface, mensagens e logs mínimos da execução. A aba P02 mostra requisitos,
  evidências, perguntas de esclarecimento e componentes da pontuação.
- `pipeline.py`: extração de PDF, schemas Pydantic e P01 → P02 → P03. Os retornos são
  validados antes do avanço; respostas inválidas interrompem o fluxo.
- **P01:** preserva os cinco campos originais e acrescenta `experiencias`, com
  `cargo_ou_projeto`, `periodo`, `tecnologias` e `evidencia`. Empregos e projetos podem
  demonstrar aplicação prática. Períodos e experiência total desconhecidos usam `null`;
  strings antigas desconhecidas usam `""` e listas desconhecidas usam `[]`.
  Não calcula duração ausente nem atribui a cada tecnologia todos os anos de carreira.
  Evidências são trechos do currículo, conferidos sem distinguir caixa ou espaços repetidos.
- **P02:** mantém `score_aderencia`, `gaps_identificados` e a chave legada
  `analise_passo_a_passo`. Esta última contém somente conclusões objetivas, sem raciocínio
  interno privado. Acrescenta `avaliacoes_requisitos` e `pontuacao_categorias`.
  Cada requisito registra categoria, situação, evidência e esclarecimento para entrevista.
  Requisitos devem citar a vaga; evidências devem citar campos profissionais do P01.
- **P03:** mantém `status_recomendacao`, resumo de até quatro linhas e exatamente três
  perguntas técnicas. Não recebe autorização para calcular pontuação nem pode devolver
  um campo de score. A classificação deve corresponder à análise validada.

Os JSONs ampliados exigem os novos campos. Consumidores diretos que forneçam respostas
simuladas precisam atualizar suas fixtures. A aplicação e os 20 testes anteriores foram
adaptados sem remover seus cenários de regressão.

## Situações e rubrica

- `demonstrado`: evidência suficiente para o requisito específico; recebe crédito.
- `nao_informado`: informação insuficiente; exige esclarecimento e recebe zero crédito
  documental. Não significa que a pessoa não tenha a competência.
- `nao_atendido`: informação explícita incompatível com o requisito; exige evidência
  e esclarecimento. Omissão não permite essa classificação.

| Categoria | Peso |
|---|---:|
| Requisitos obrigatórios | 70 |
| Experiência e senioridade pertinentes | 20 |
| Requisitos desejáveis | 10 |

Somente categorias com requisitos expressos na vaga são incluídas. Experiência/senioridade
usa a categoria própria, mesmo quando obrigatória; requisitos sem categoria explícita
são tratados como obrigatórios. Cada requisito é avaliado uma única vez e tem o mesmo peso
que os demais da sua categoria. Uma menção a uma tecnologia não comprova aplicação
prática ou duração quando o requisito exige essas informações.

P02 calcula os pontos por categoria como `peso × demonstrados / avaliados`, com duas casas
decimais. Calcula o score como `100 × soma dos pontos / soma dos pesos presentes`, arredondado
a inteiro. Os arredondamentos usam metades para cima. Python apenas confere a resposta;
não corrige nem substitui o número do modelo. Um score incoerente interrompe o pipeline.
Sem requisitos avaliáveis, a resposta não é aceita: é preciso esclarecer a vaga.

Classificação: abaixo de 50, `Não Recomendado`; de 50 a 84, `Recomendado com Ressalvas`;
a partir de 85, `Altamente Recomendado` somente se todos os obrigatórios estiverem demonstrados.
Com pendência obrigatória, permanece `Recomendado com Ressalvas`. São faixas acadêmicas
para aderência documental, sem validação preditiva ou decisão automática de contratação.

## Exemplos sintéticos

1. **Quatro anos de carreira; seis meses em um projeto Python.** Vaga: automação de
   relatórios (obrigatório), quatro anos de Python (experiência), SQL (desejável).
   Projeto com Python e consultas PostgreSQL comprova aplicação e SQL, mas não quatro anos
   de Python. Pontos: `70/70 + 0/20 + 10/10 = 80/100`. Classificação com ressalvas;
   perguntar sobre o tempo total de Python em outras experiências.
2. **Vaga com somente SQL, atendido por consultas PostgreSQL documentadas.** Apenas
   obrigatórios: `70/70`, normalizado para `100/100`; categorias ausentes não penalizam.
3. **Python demonstrado e Git não informado, ambos obrigatórios.** `35/70`, normalizado
   para `50/100`. Formulação: “O currículo não informa experiência com Git; esclarecer
   o uso dessa ferramenta na entrevista.” Não afirmar que a pessoa não sabe Git.
4. **Um de quatro requisitos demonstrado, só obrigatórios.** `17,50/70 = 25/100`.
   Preservar casas decimais evita distorção antes da normalização.

## Testes e limites

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Os 20 testes da Etapa 01 permanecem. Os testes da Etapa 02 cobrem contexto profissional,
projetos, omissão versus não atendimento explícito, sinônimos, evidências inventadas,
categorias ausentes, componentes e score incoerentes, classificação, instruções embutidas,
privacidade dos logs e apresentação das evidências. Usam dados sintéticos e Gemini simulado.

Instruções da aplicação ficam em `system_instruction`; currículo, vaga e saídas são dados
JSON. O campo `nome_candidato` é omitido das entradas de P02/P03. Isso reduz interferência, mas testes simulados não
comprovam resistência do modelo real a toda instrução maliciosa. A conferência textual
não prova relevância semântica, autenticidade ou cobertura completa de todos os requisitos.
A categorização, os sinônimos e o significado das evidências ainda dependem do modelo e
da revisão humana. Não foi feita avaliação real de acurácia ou vieses.

Não há persistência, lote real, CSV, e-mails ou agentes adicionais. O ranking de exemplo
original continua identificado como simulado. Resultados ainda não são preservados após
reexecuções da página. Os logs não incluem nome, currículo, resposta completa ou detalhes
brutos das exceções. Arquivos de credenciais e dados locais estão no `.gitignore`.
