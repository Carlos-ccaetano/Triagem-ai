# 📄 TriagemAI — Sistema Multiagente para Análise e Triagem Automatizada de Currículos

> **Disciplina:** Engenharia de Prompt e Fundamentos de Inteligência Artificial  
> **Entrega:** E4 — Protótipo Inicial Funcional  
> **Área de Impacto:** Recursos Humanos / Recrutamento e Seleção  

## 🎯 Sobre o Projeto
O **TriagemAI** automatiza a etapa inicial de triagem de currículos para pequenas e médias empresas. A partir da descrição de uma vaga e do currículo de um candidato, o sistema executa um **pipeline encadeado de prompts em tempo real** utilizando o modelo **Google Gemini (`gemini-2.5-flash`)** para extrair entidades, avaliar aderência técnica passo a passo e gerar um roteiro personalizado de entrevista.

## 🧠 Arquitetura de Prompts Implementada (Tempo Real)
1. **`P01` (Role Prompt + Few-Shot):** Converte o texto livre do currículo em um objeto JSON estruturado (`response_mime_type="application/json"`).
2. **`P02` (Chain of Thought - CoT):** Recebe o JSON gerado pelo `P01` e cruza com os requisitos da vaga, detalhando requisitos atendidos, gaps e calculando um score de `0 a 100`.
3. **`P03` (Role Prompt + Zero-Shot Estruturado):** Consolida o diagnóstico em um parecer executivo e formula 3 perguntas técnicas direcionadas aos pontos de atenção do candidato.

## 🚀 Como Executar Localmente

### Pré-requisitos
- Python 3.10 ou superior
- Chave de API válida do Google AI Studio (`GEMINI_API_KEY`)

### Passo a passo
1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/mauriciolopesjr/triagem-ai-e4.git](https://github.com/mauriciolopesjr/triagem-ai-e4.git)
   cd triagem-ai-e4