# TriagemAI — Análise de evidências profissionais

MVP acadêmico para comparar currículos com os requisitos de uma vaga e preparar a
entrevista. A pontuação representa aderência documental e apoia a revisão humana;
não determina contratação ou rejeição.

A interface, o histórico e a exportação executam localmente. Novas avaliações dependem
da API do Google Gemini: o texto do currículo e o contexto da vaga são enviados ao Google.
O projeto usa um **pipeline sequencial de prompts com papéis especializados**,
sem agentes autônomos independentes.

## Estado da validação

Em 17/11/2026, os **67 testes automatizados passaram**, com Gemini simulado e rede
bloqueada. A interface foi inspecionada no navegador; SQLite e CSV foram exercitados
com dados sintéticos. **A integração real com Gemini está pendente**: não havia chave
configurada e o usuário optou por continuar sem ela. Foram feitas **0 chamadas reais**.
Não há evidência de funcionamento completo de ponta a ponta com o modelo real.
Veja [VALIDACAO_FINAL.md](VALIDACAO_FINAL.md) para resultados, capturas e ressalvas.

## Tecnologias e estrutura

Python, Streamlit, Google Gen AI SDK, Pydantic, pypdf e python-dotenv.
SQLite, CSV e testes usam a biblioteca padrão (`sqlite3`, `csv`, `io`, `unittest`).
Não há ORM ou serviço externo de armazenamento.

```text
app.py              Interface Streamlit, sessão e ações explícitas do usuário
pipeline.py         PDF, contratos Pydantic e chamadas P01 → P02 → P03
persistencia.py     Histórico SQLite e exportação CSV
requirements.txt    Dependências de execução
.env.example        Exemplo de configuração, sem credencial real
tests/              Testes de contratos, interface, lote e persistência
evidencias/         Capturas sintéticas e extrato dos testes da validação final
data/triagem.db     Banco local criado automaticamente; ignorado pelo Git
```

### Papéis do pipeline

1. **P01 — Extração:** transforma o texto em dados profissionais e experiências/projetos
   com trechos de evidência. Valores desconhecidos usam `null`, strings vazias ou listas
   vazias conforme o contrato. Não calcula durações ausentes.
2. **P02 — Aderência:** confronta requisitos explícitos da vaga com campos profissionais
   de P01, registra situação/evidência/esclarecimento e produz componentes e score.
3. **P03 — Parecer:** resume a avaliação, apresenta a classificação e exatamente três
   perguntas técnicas. Não produz outro score.

Cada JSON é validado com Pydantic antes do avanço. Tipos incorretos, campos extras,
evidências não localizadas, pontuação incoerente ou classificação incompatível interrompem
aquele currículo. O campo de nome é omitido das entradas de P02/P03. Os logs da aplicação
registram etapas, contagens e erros genéricos, sem nomes, arquivos ou respostas brutas.

O modelo é `gemini-2.5-flash`. Cada análise completa usa três chamadas. Os dois modos
configuram uma única tentativa por chamada no SDK, sem retries automáticos. Abrir detalhes,
salvar, consultar histórico e exportar não executa o modelo.

## Pontuação

| Categoria | Peso |
|---|---:|
| Requisitos obrigatórios | 70 |
| Experiência e senioridade | 20 |
| Desejáveis | 10 |

Somente categorias com requisitos expressos na vaga entram no cálculo. Cada requisito
tem o mesmo peso dentro de sua categoria e é avaliado uma única vez. Experiência e
senioridade usam a categoria própria; requisitos sem categoria explícita vão para obrigatórios.

- `demonstrado`: evidência suficiente para aquele requisito; recebe crédito.
- `nao_informado`: informação insuficiente; exige pergunta de esclarecimento.
- `nao_atendido`: incompatibilidade explícita; exige evidência e esclarecimento.

As duas últimas situações recebem zero crédito documental. Omissão no currículo não
significa ausência de competência. Listar uma tecnologia não comprova aplicação prática
ou duração quando o requisito exige essas informações.

P02 calcula `pontos da categoria = peso × demonstrados / avaliados`, com duas casas
decimais, e `score = 100 × soma dos pontos / soma dos pesos presentes`, arredondado a
inteiro. Metades são arredondadas para cima. Python confere os valores recebidos e rejeita
incoerências; não substitui a pontuação do modelo. Sem requisito avaliável, não há score válido.

| Score e condições | Classificação documental |
|---|---|
| Abaixo de 50 | Não Recomendado |
| De 50 a 84 | Recomendado com Ressalvas |
| A partir de 85, com todos os obrigatórios demonstrados | Altamente Recomendado |
| A partir de 85, com pendência obrigatória | Recomendado com Ressalvas |

Exemplo sintético: `70/70 + 0/20 + 10/10 = 80/100`, com ressalvas. Uma vaga somente
com obrigatórios demonstrados dá `70/70`, normalizado para `100/100`.
São faixas acadêmicas, sem estudo de validade preditiva ou acurácia.

## Executar localmente no WSL

Requer Python 3.10 ou superior e acesso à API para novas análises. O ambiente validado
usou Python 3.12.3. Na primeira instalação:

```bash
cd /home/carloscaetano/estudos/Triagem-ai
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
nano .env
```

Preencha `GEMINI_API_KEY` **somente no arquivo local** e salve. Também é possível usar
uma variável de ambiente. Não cole a chave em conversas, logs ou commits. `.env`, variantes
de credenciais, bancos, PDFs e exportações locais estão no `.gitignore`.

Inicie e abra `http://127.0.0.1:8501` no navegador:

```bash
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Encerre com `Ctrl+C`. Se faltar suporte a `venv`/`ensurepip`, prepare-o na distribuição
antes de instalar. Sem chave, novas análises ficam desabilitadas; histórico e CSV continuam disponíveis.

## Análise individual e lote

Informe título, descrição e requisitos da vaga e escolha o modo:

- **Análise individual:** envie um PDF com texto selecionável ou cole o currículo.
  O texto manual preenchido tem prioridade sobre o PDF. Clique em **Analisar currículo**.
- **Análise em lote:** selecione de **1 a 10 PDFs** da mesma vaga e clique em
  **Analisar currículos**. Onze arquivos são recusados antes de criar o cliente Gemini.
  Não há entrada manual nesse modo; use a análise individual como alternativa.

PDFs corrompidos, vazios ou sem texto geram orientação segura. A extração preserva a
separação entre páginas. Não há OCR.

O lote processa um arquivo por vez. Falhas individuais não interrompem os demais e não
recebem score artificial. O ranking inclui somente avaliações completas, ordenadas pelo
score validado, em ordem decrescente; empates mantêm a ordem de envio. A ordenação é
feita em Python (`list.sort`), sem prompt P05 ou chamada adicional de IA.
Selecione **Ver avaliação individual** para consultar os detalhes.

A avaliação mostra nome identificado, score, classificação, resumo, requisitos, evidências
e três perguntas. Componentes e logs ficam em **Detalhes técnicos da análise**.
Resultados completos permanecem em `st.session_state` durante as reexecuções. Alterar
entradas ou modo invalida o resultado anterior; uma nova tentativa começa limpa.
Sem salvar no histórico, fechar a sessão ou reiniciar pode perder a avaliação atual.

## Histórico SQLite

Clique em **Salvar no histórico** depois de uma análise válida. O salvamento é explícito;
repetir o clique na mesma execução não duplica nem sobrescreve o registro. Uma nova análise
gera outro identificador, mesmo com as mesmas entradas.

O banco `data/triagem.db` contém uma tabela `execucoes`: identificador, data UTC, título e
descrição da vaga, modo e resultados estruturados em JSON. A interface mostra horário de
São Paulo. Guarda nome identificado, P02, P03 e contagem de falhas. Não guarda PDFs,
texto integral do currículo, P01 completo, nomes de arquivos, chaves, logs ou respostas brutas.
**Nome e evidências estruturadas ainda podem identificar pessoas.**

Em **Histórico**, selecione um registro e clique em **Abrir análise**. **Voltar à análise
atual** retorna à sessão. Para excluir, marque **Confirmo a exclusão desta análise** e
clique em **Excluir análise**. A exclusão remove o registro; não apaga CSVs baixados ou a
avaliação atual da sessão. Falhas de armazenamento mostram orientação e preservam o resultado atual.
Não há autenticação, criptografia ou backup automático; proteja o computador e o arquivo.

## Exportação CSV

**Baixar CSV** exporta a análise atual ou a aberta do histórico, em memória. Cada candidato
válido ocupa uma linha, sem exportar falhas. São nove colunas: posição (vazia no individual),
nome, vaga, score, classificação, resumo e três perguntas. O formato usa `;`, UTF-8 com BOM,
campos entre aspas e quebra de linha CRLF. Resumos com quebras de linha continuam em um campo CSV.

Textos com início de fórmula (`=`, `+`, `-`, `@`, variantes de largura completa e controles
iniciais) recebem uma tabulação dentro do campo exportado. A sessão e o banco não são
alterados. A tabulação permanece se o arquivo for lido programaticamente.

Na inspeção com Excel foi necessário escolher **Delimitado**, **UTF-8** e **ponto e vírgula**
no assistente, desmarcando tabulação como separador. O lote abriu com nove colunas;
`=1+1` e `+1+1` sintéticos permaneceram como texto. Isso não garante comportamento igual
em todo importador ou após editar/regravar o CSV. A largura das colunas depende do leitor.

## Testes e limitações

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
.venv/bin/python -m compileall -q app.py pipeline.py persistencia.py tests
```

Os testes usam currículos sintéticos, respostas simuladas, bancos temporários e bloqueio
de rede. Cobrem JSONs, rubrica, classificação, PDFs, erros seguros, sessão, lote, empates,
limites, SQLite, duplicidade, exclusão e CSV. AppTest simula uploads e respostas; não
substitui um teste completo no navegador com a API real.

A integração real, qualidade semântica, latência do Gemini, acurácia e vieses **não foram
validados nesta etapa**. Conferir trechos não prova autenticidade, relevância ou cobertura
de todos os requisitos. Instruções de sistema e validação reduzem interferências de comandos
nos dados, sem garantir imunidade a prompt injection. A revisão humana continua necessária.
As versões mínimas de todas as dependências e outras plataformas não foram testadas.

Não há OCR, e-mail automático, autenticação, agentes adicionais, P04 ou deploy.
O original `Entrega4.docx` foi localizado em Downloads na revisão de encerramento e
permanece inalterado, fora do repositório. A comparação de F01–F08, P01–P06, problemas e
planos da E4 está em [VALIDACAO_FINAL.md](VALIDACAO_FINAL.md#revisão-de-encerramento).
Os registros históricos da E4 não comprovam a integração real da versão atual.
O [roteiro mínimo de validação real](VALIDACAO_FINAL.md#procedimento-mínimo-para-validação-real)
usa um currículo fictício e até três chamadas, sem retries; ele não foi executado.
