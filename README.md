# TriagemAI — Análise de evidências profissionais

> **Disciplina:** Engenharia de Prompt e Fundamentos de Inteligência Artificial
> **Entrega de origem:** E4 — Protótipo Inicial Funcional
> **Área de Impacto:** Recursos Humanos / Recrutamento e Seleção

MVP acadêmico executado localmente com Streamlit e Google Gemini (`gemini-2.5-flash`).
Recebe uma vaga e um currículo em texto ou PDF nativo. A avaliação considera evidências
profissionais e apoia a revisão humana; não contrata nem rejeita candidatos automaticamente.

## Execução local

Python 3.10 ou superior é necessário. A chave do Google AI Studio é exigida para novas
análises; histórico e CSV funcionam sem chamar o Gemini, inclusive sem chave. A `.venv`
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

## Interface e estado da sessão — Etapa 03

A análise individual tem quatro áreas: Vaga, Currículo, Avaliação e Perguntas para entrevista.
Os logs e os componentes da pontuação ficam em **Detalhes técnicos da análise**.
A pontuação apoia a revisão humana, sem alterar os rótulos internos do parecer.

- O pipeline executa somente ao clicar em **Analisar currículo** ou **Analisar currículos**, com entradas preenchidas.
- `st.session_state["resultado"]` guarda apenas a última análise completa: dados extraídos,
  avaliação e parecer. A apresentação fica fora do bloco do botão e reutiliza esse resultado.
- Alterar título, requisitos, texto manual ou upload limpa resultado, erro e logs pelos
  callbacks `on_change`. É preciso clicar novamente para analisar as novas entradas.
- Uma nova tentativa limpa a avaliação anterior antes de validar ou processar os dados.
  Se falhar, nenhum resultado parcial é salvo e nenhuma avaliação antiga aparece como atual.
- A mensagem segura de erro permanece na sessão até editar uma entrada ou tentar novamente.
  O andamento usa `st.status` em três etapas, sem percentuais ou estimativas artificiais.
- Nome vazio aparece como **Não informado**. Pontuação é exibida somente após validação;
  um score ausente ou inválido não recebe zero como valor padrão.

A sessão usa memória. Se não usar **Salvar no histórico**, fechar a sessão, recarregar
completamente a página ou reiniciar o processo pode perder o resultado atual. O histórico
SQLite da Etapa 05 complementa a sessão e permite recuperar as avaliações salvas.

## Análise individual e lote — Etapa 04

Em **Tipo de análise**, escolha o modo e informe o título e os requisitos da mesma vaga.

- **Análise individual:** envie um PDF ou cole o texto e clique em **Analisar currículo**.
  Quando ambos estiverem preenchidos, o texto manual tem prioridade.
- **Análise em lote:** selecione de **1 a 10 PDFs** e clique em **Analisar currículos**.
  Mais de 10 arquivos são recusados antes de iniciar as chamadas. Não há texto manual
  nesse modo; para um PDF sem texto, use a alternativa manual na análise individual.

O lote processa um currículo por vez, reutilizando P01 → P02 → P03 e seus schemas.
Cada avaliação completa usa três chamadas ao Gemini. Uma falha pode interromper aquele
currículo antes disso, sem impedir os demais. Não há paralelismo nem retries automáticos.
O progresso informa a posição real, por exemplo, “Analisando currículo 2 de 5”.

O ranking é ordenado em Python pelo `score_aderencia` validado de P02, do maior para o menor.
Empates mantêm a ordem de envio. Não há nova fórmula, alteração da rubrica 70/20/10 ou
chamada extra ao Gemini. A tabela mostra posição, nome, pontuação e classificação; ela
apoia a análise humana e não determina contratação ou rejeição.

Selecione um candidato em **Ver avaliação individual** para abrir o resumo, os requisitos,
as evidências, os pontos a esclarecer e as três perguntas. Essa tela reutiliza os mesmos
componentes da análise individual. Selecionar candidatos ou reexecutar a página não chama
o Gemini novamente.

Arquivos com erro são identificados na interface, separados dos resultados válidos e
excluídos do ranking; não recebem zero como representação da falha. Se todos falharem,
nenhuma avaliação é apresentada. Os logs técnicos registram posição e etapa, sem nomes
de arquivos, conteúdo de currículos, respostas completas ou detalhes das exceções.

`st.session_state["lote"]` guarda o ranking e a lista de falhas, separado de `resultado`
da análise individual. Trocar o modo, alterar a vaga ou mudar os arquivos limpa os
resultados anteriores. Uma nova execução também começa limpa. É necessário solicitar
outra análise; o aplicativo não reprocessa entradas automaticamente. Os arquivos podem
precisar ser selecionados novamente ao trocar de modo. Até usar **Salvar no histórico**,
esses resultados permanecem somente na sessão.

Os 43 testes anteriores permanecem. Os testes do lote usam PDFs sintéticos reais em memória,
Gemini simulado e conexões de rede bloqueadas. Cobrem chamadas às etapas existentes,
ordenação, empates, limites, falhas isoladas, sessão, seleção sem novas chamadas e os modos.
Uploads e seus callbacks são simulados no AppTest; não substituem inspeção manual do navegador.

## Histórico local e CSV — Etapa 05

Depois de concluir uma análise individual ou um lote com resultados válidos, clique em
**Salvar no histórico**. Reexecuções e abertura de detalhes não salvam automaticamente.
Cada execução tem um identificador único; repetir o clique não duplica nem sobrescreve o
registro. Uma nova análise gera outro identificador, mesmo que use as mesmas entradas.

O banco é criado automaticamente em `data/triagem.db`, relativo à pasta do projeto.
Usa `sqlite3`, sem ORM ou migrations. Uma única tabela `execucoes` contém:

| Campo | Conteúdo |
|---|---|
| `id` | Identificador único da execução |
| `data` | Data da conclusão, em UTC; a interface mostra horário de São Paulo |
| `titulo_vaga`, `descricao_vaga` | Contexto da vaga |
| `modo` | `individual` ou `lote` |
| `resultados_json` | Candidatos válidos e quantidade de arquivos que falharam |

Para cada candidato, guarda nome identificado, avaliação estruturada de P02 (pontuação,
requisitos, evidências, componentes e sínteses objetivas) e parecer de P03 (classificação,
resumo e três perguntas). Não guarda PDF, texto integral, histórico profissional completo
de P01, nomes de arquivos, chaves, logs ou respostas brutas. Falhas do lote ficam somente
como contagem, sem nomes de arquivos. Os dados estruturados ainda podem identificar pessoas.
A pasta `data/`, incluindo o banco e arquivos auxiliares do SQLite, está ignorada pelo Git.

Abra **Histórico**, selecione uma análise por data/vaga e clique em **Abrir análise**.
Os resultados usam a mesma apresentação da avaliação atual, inclusive seleção no ranking.
**Voltar à análise atual** retorna aos dados que continuam na sessão. Uma falha de SQLite
mostra orientação sem apagar esses resultados. Nenhuma dessas ações executa o Gemini.

Para excluir, marque **Confirmo a exclusão desta análise** e clique em **Excluir análise**.
Isso remove o registro do histórico; não remove a análise atual da memória nem CSVs já
baixados. Não há autenticação, criptografia ou backup automático: proteja o acesso ao
computador e ao arquivo local. Não compartilhe o banco com dados reais de candidatos.

Use **Baixar CSV** na análise atual ou em uma análise aberta do histórico. O arquivo é
montado em memória com `csv` e `io`, sem CSV temporário no disco. Usa **ponto e vírgula**
como separador, **UTF-8 com BOM** e campos entre aspas. Cada candidato válido ocupa uma linha:
posição (vazia na análise individual), nome, título da vaga, score, classificação, resumo
e três perguntas. Não exporta falhas, currículos, logs ou chaves.

Exemplo sintético de um candidato em lote (BOM não representado):

```csv
"Posição";"Nome identificado";"Vaga";"Score de aderência";"Classificação";"Resumo da avaliação";"Pergunta de entrevista 1";"Pergunta de entrevista 2";"Pergunta de entrevista 3"
"1";"Pessoa Exemplo";"Analista de Dados";"80";"Recomendado com Ressalvas";"Python demonstrado; esclarecer tempo de experiência.";"Como aplicou Python?";"Como construiu as consultas SQL?";"Qual seu tempo de uso de Python?"
```

Na exportação, textos com início de fórmula (`=`, `+`, `-`, `@`, variantes de largura
completa e controles iniciais) recebem uma tabulação dentro do campo entre aspas. Os
dados da sessão e do banco não recebem esse prefixo. A medida segue a
[orientação da OWASP para CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection),
voltada ao Excel. Outros importadores podem interpretar o prefixo de forma diferente;
não existe tratamento universal para todas as planilhas e usos posteriores. A tabulação
permanece no valor se o CSV for lido programaticamente. Não houve validação manual no Excel.

Os testes usam bancos temporários por caso, nunca `data/triagem.db` real. Cobrem criação,
salvamento individual/lote, nova conexão e nova sessão, ordenação, duplicidade, exclusão
confirmada, privacidade, erro sem perda da sessão e exportação com três perguntas, sem
novas chamadas ao Gemini. O clique de download é simulado no AppTest.

## Pipeline e contratos — Etapa 02

- `app.py`: interface, mensagens e logs mínimos da execução. A área Avaliação mostra requisitos,
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

Os testes da Etapa 03 verificam reexecuções sem novas chamadas, invalidação nas mudanças
de entrada, substituição do resultado, falhas sem sucesso antigo, erros seguros, pontuações
inválidas, zero válido e nome desconhecido. O upload é simulado com seu callback registrado;
AppTest não substitui inspeção visual/manual do navegador.

Não há e-mails, OCR, autenticação ou agentes adicionais. Histórico e CSV são exclusivamente
locais, sem serviço externo de armazenamento. O ranking usa avaliações reais do pipeline,
sem dados simulados na aplicação. Sua qualidade
depende das evidências e da interpretação do modelo; não foi aferida com chamadas reais
nos testes de desenvolvimento. Credenciais e dados locais estão no `.gitignore`.
