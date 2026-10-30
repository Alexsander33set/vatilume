# Comparação de modelos para a interface — 30/10/2026

Foram executados quatro casos agregados sintéticos, três vezes por modelo, com a mesma chave/projeto OpenAI: projeção mensal com tarifa, comparação da potência da CPU entre metades, limite da medição do gabinete e projeção sem tarifa. A ordem dos modelos foi rotacionada entre repetições. Não foram enviados dados do PC ao provedor neste ensaio.

| Modelo | Resposta principal pertinente | Mediana por análise | Estimativa total das 12 análises |
| --- | --- | --- | --- |
| GPT-6 Luna | 12/12 | 2,19 s | US$ 0,005721 |
| GPT-5.4 mini | 11/12 | 1,17 s | US$ 0,023608 |
| GPT-6.1 Terra | 12/12 | 2,84 s | US$ 0,068543 |

Todos os modelos concluíram as 12 análises dentro do contrato de fatos/evidências. “Concluída” não significa que a resposta foi a mais útil: em uma repetição, o mini escolheu a limitação genérica do gabinete em vez da comparação solicitada. Luna e Terra escolheram as quatro respostas esperadas em todas as repetições. A referência de pertinência é o ID esperado de cada caso; os [resultados normalizados](benchmarks/ai-0.9.0-2026-10-30.json) permitem conferir a seleção, o texto calculado e as ferramentas.

O Luna custou cerca de 4,1 vezes menos que o mini neste recorte e foi aproximadamente um segundo mais lento. O Terra apresentou mais dados de apoio e consultas adicionais, sem melhorar a resposta principal esperada, com custo cerca de 2,9 vezes maior que o mini. Isso favorece testar o Luna no uso cotidiano; o mini permanece o padrão para preservar a escolha anterior. A seleção pode ser alterada em Configurações, sem trocar a chave quando o projeto tem acesso ao modelo.

A tabela não é uma avaliação geral da inteligência dos modelos. São poucos casos, dados simples e uma aplicação em que o backend faz cálculos e escreve os fatos; a IA escolhe consultas e respostas. Perguntas sobre processos/aplicativos, lacunas complexas e múltiplas fontes precisam de ensaios próprios. Latência varia com rede, cache, conta, tamanho dos dados e disponibilidade do provedor. Custos são estimativas conservadoras pelos tokens, sem descontos de cache e com a margem de entrada documentada; não são a fatura da OpenAI.

Uma primeira rodada tinha um erro no conjunto sintético: o caso sem tarifa ainda carregava custos nos dados de apoio. Ela foi descartada da comparação de qualidade. O gerador foi corrigido e ganhou teste de consistência; o gasto anterior permaneceu contabilizado no mesmo registro e no teto original do ensaio.

A divergência do mini motivou um reforço posterior no contrato: uma comparação explícita de potência/uso de um componente entre as metades da janela passa a consultar esse cálculo antes da inferência e exige sua seleção como resposta principal. Sem dados suficientes, retorna a limitação específica da comparação. A mudança é testada localmente; os tempos/custos acima foram medidos antes desse reforço, com o validador `observed-domain-model-2`.

O projeto não alterou automaticamente o modelo nem aumentou orçamento. Não há nova rodada paga prevista. [Controles, privacidade e reprodução](CONFIABILIDADE.md).
