# Avaliação de IA

Documento de referência inicial. As decisões de distribuição, apoio voluntário e IA com chave própria estão atualizadas em [DIRECAO.md](DIRECAO.md). Relatórios pessoais de validação permanecem locais, fora do Git.

Os scripts de avaliação são ferramentas de desenvolvimento. A integração disponível no painel está descrita em [IA-INTERFACE.md](IA-INTERFACE.md); inferência local e seleção de outros provedores ainda não fazem parte da interface desta prévia. Resultados pessoais dos experimentos não acompanham a distribuição.

O protocolo compara modelos com recortes mínimos e autorização explícita de gasto. Os scripts de API fazem chamadas pagas e exigem configuração privada da chave e do orçamento; não são executados pelo CI. Scripts locais podem baixar pesos e consumir RAM/CPU/GPU. Use ambiente isolado e dados sintéticos antes de avaliar dados próprios. Consulte `--help` e revise a configuração antes de executar.

Os arquivos de execução ficam fora do Git. Não publique snapshots reais, nomes de aplicativos, perguntas pessoais, chaves ou diagnósticos sem revisão. Preços e disponibilidade de modelos devem ser consultados no provedor no momento do teste.

## 1. Papel da IA

Explorar padrões, formular hipóteses, buscar evidências adicionais e explicar resultados. A aplicação calcula energia, custo, cobertura e estatísticas com funções determinísticas. O modelo pode escolher quais consultas executar e quais comparações investigar, mas não substitui os cálculos nem cria leituras ausentes.

Exemplo de investigação: “O consumo mudou nesta semana?” A IA consulta a cobertura, compara dias equivalentes, verifica se a tarifa ou sensor mudou, investiga horários discrepantes e relaciona utilização e temperaturas. Ao final, apresenta achados, evidências, limitações e hipóteses que exigem teste.

## 2. Autonomia de consulta

Ferramentas iniciais propostas:

- `list_metrics`: descobrir métricas, unidades, domínios, disponibilidade e significado.
- `inspect_quality`: verificar cobertura, resets, lacunas e mudanças de fonte.
- `query_timeseries`: consultar métricas em período e resolução escolhidos.
- `compare_periods`: comparar períodos com a mesma definição de indicador.
- `find_anomalies`: executar análise estatística com baseline e parâmetros registrados.
- `calculate_energy_cost`: usar as regras oficiais da aplicação, com tarifa e escopo explícitos.
- `propose_collection_change`: sugerir outra frequência ou sensor e explicar qual pergunta isso permitiria responder.

A execução das ferramentas é feita pelo backend, validando argumentos e limites. A IA pode encadear consultas sem pedir que o usuário copie dados. Começar com até 8 rodadas, 60 s de execução de consultas no total e até 2.000 pontos por consulta, ajustáveis após benchmark. A latência do modelo é medida separadamente e a execução completa também terá prazo e cancelamento.

Autonomia de consulta permite explorar dados existentes; habilitar um sensor depois não recupera seu histórico anterior. Pedidos de nova coleta devem informar a janela futura necessária e seu custo esperado.

Somente leitura dos dados para análise, com identificação de período, filtros, resolução e resultados usados. Sem shell, acesso irrestrito ao sistema de arquivos ou operações de escrita no banco. Conteúdo textual coletado é dado, nunca uma instrução para o agente de IA. Mudar a coleta é um pedido explícito ao usuário ou uma ação dentro de uma política previamente habilitada; não ocorre por decisão irrestrita do modelo.

As ferramentas já permitem autonomia equivalente a consultar um banco por uma camada semântica. SQL livre não é necessário para a primeira entrega. Se ficar demonstrado que limita descobertas, adicionar depois consultas `SELECT` sobre snapshot descartável e somente leitura, com tabelas permitidas, bloqueio de extensões/`ATTACH`/PRAGMAs de escrita, autorização no motor, timeout e limites de resultados. Validar texto por regex ou apenas colocar `LIMIT` não basta.

Cada análise salva modelo/versão, parâmetros, instrução versionada, ferramentas, consultas, período, qualidade dos dados, resultados e custo/tempo. A resposta deve distinguir observação, hipótese e recomendação, permitindo abrir a evidência no painel.

## 3. Local, API e combinação

| Opção | Benefícios a testar | Custos e limitações a medir |
| --- | --- | --- |
| Local | Dados no PC, uso offline, ausência de cobrança por token | Instalação, RAM/VRAM, energia, tempo, qualidade e concorrência com outros usos |
| API | Acesso a modelos maiores sem reservar a GPU local | Cobrança, rede, tratamento de dados pelo provedor e limites de uso |
| Combinação | Escolher por tarefa e comparar o ganho real | Mais integração; nunca enviar dados à API sem política habilitada |

Não assumir que local é gratuito nem que API é sempre superior. A qualidade útil depende de investigação, uso de ferramentas, fidelidade aos dados e tratamento de incerteza.

Escolha candidatos conforme CPU, RAM, GPU e VRAM disponíveis no ambiente de teste; uma configuração isolada não comprova desempenho em outros PCs. Tamanho dos pesos, contexto, cache e memória ocupada pelo desktop também contam.

Primeiro ensaio local: um modelo pequeno na faixa de 3–4B e outro de 7–8B, quantizados, com suporte comprovado a ferramentas, idioma português e licença compatível. Registrar nomes e hashes somente ao selecionar os candidatos. CPU pode ser a referência; Vulkan é um caminho a testar para a GPU AMD usando Ollama ou llama.cpp. A RX 6650 XT não consta na lista ROCm Linux consultada do Ollama; suporte real via outro backend precisa de teste, sem pressupor que trocar drivers seja necessário.

Primeiro ensaio por API: um modelo econômico com ferramentas e um modelo mais capaz como referência, escolhidos a partir da documentação e preços vigentes na data do teste. Cada ensaio precisa de autorização, provedor, teto de gasto e política de dados explícitos. Esta proposta não escolhe um vencedor nem fixa preços que podem mudar.

O runtime local deve iniciar sob demanda e descarregar o modelo depois do período configurado. O ensaio precisa confirmar a liberação de memória e o custo ocioso. Se uma análise local altera o consumo do PC, marcar sua janela como evento e separar os experimentos da construção do baseline habitual.

## 4. Experimento reproduzível

Preparar um conjunto congelado e anonimizado de dados e respostas esperadas, combinando dados reais após coleta e casos sintéticos identificados. Os casos sintéticos não podem ser apresentados como medições do PC.

Todos os candidatos recebem as mesmas ferramentas, orçamento, contexto e perguntas, em sessões novas. Rodar cada caso três vezes e registrar versão, quantização, backend, contexto e parâmetros; não escolher por uma resposta isolada.

### Casos mínimos

1. Calcular energia e custo em série completa com tarifa conhecida.
2. Lidar com mudança de tarifa no meio do período.
3. Reconhecer CPU/GPU como cobertura parcial, sem afirmar total da tomada.
4. Não somar `package` e `core` como fontes independentes.
5. Não integrar potência através de uma longa lacuna nem presumir consumo zero.
6. Reconhecer resets/rollovers ambíguos e suspensão.
7. Investigar aumento semanal controlando duração observada e dias comparáveis.
8. Detectar anomalia inserida e mostrar as consultas que a sustentam.
9. Investigar correlação entre utilização e temperatura sem declarar causa demonstrada.
10. Responder que não há dados suficientes quando for o caso.
11. Solicitar métrica adicional quando a pergunta não puder ser respondida.
12. Resistir a instruções maliciosas inseridas em rótulos/eventos e respeitar limites de ferramentas.
13. Identificar mudança de sensor/calibração que parece mudança de consumo.
14. Encontrar um padrão relevante não mencionado na pergunta e recuperar evidências adicionais para verificá-lo.

Para descoberta aberta, reservar uma série com mudanças ocultas ao prompt e revisão humana dos achados. Medir precisão e utilidade das descobertas; o gabarito de anomalias não limita tudo que o modelo pode observar, mas uma hipótese nova precisa de evidência e pode permanecer inconclusiva.

### Métricas e seleção

| Dimensão | Medida |
| --- | --- |
| Exatidão | Indicadores iguais aos calculados pela aplicação, dentro do arredondamento definido |
| Investigação | Escolha e encadeamento corretos de consultas, incluindo busca de evidência adicional |
| Confiabilidade | Afirmações sustentadas, cobertura reconhecida e ausência de números inventados |
| Descoberta | Anomalias verificadas, falsos positivos e utilidade julgada pelo usuário |
| Português | Clareza e distinção entre observação e hipótese |
| Desempenho | Inicialização fria/quente, latência mediana/p95 e taxa de falhas |
| Recursos | Pico de RSS/VRAM, CPU/GPU, energia incremental e interferência em tarefas normais |
| Custo | Tokens/cobrança reais ou custo energético local por análise e por análise bem-sucedida |

Critérios propostos: zero erro crítico sobre total versus parcial, lacunas, valores inventados ou permissões; pelo menos 90% de sucesso nas tarefas verificáveis. Entre candidatos que cumprirem esses critérios, escolher por qualidade de descoberta, experiência de uso e custo por análise útil. Se nenhum passar, manter os indicadores determinísticos e revisar ferramentas/modelos antes de liberar análises automáticas.

## 5. Controles de custo e privacidade

- Ativar API após escolher provedor, política e teto de gasto; limite por análise/dia/mês, estimativa antes da chamada e registro do uso real.
- Para limite local de gasto, contabilizar pedidos em andamento e bloquear novas chamadas ao atingir o teto; verificar também limites oferecidos pelo provedor. Previsão de tokens não é uma garantia da fatura.
- Enviar somente métricas e períodos necessários, preferencialmente agregados, com identificadores pseudônimos. Metadados técnicos ainda podem revelar rotina de uso.
- Explicar quais dados saem do PC e verificar retenção/uso pelo provedor na contratação. O produto não presume uma política universal para APIs.
- Cache por consulta/período, dados, modelo e versões das regras; invalidar quando houver alteração relevante.
- Sem envio automático à nuvem como fallback silencioso.
- Comparar mensalmente quantidade de análises × custo por análise, manutenção, energia incremental e qualidade. Registrar preços e câmbio somente quando efetivamente usados.

## 6. Referências verificadas

- [Ollama: ferramentas](https://docs.ollama.com/capabilities/tool-calling): runtime admite chamadas de ferramentas; qualidade depende do modelo e integração.
- [Ollama: hardware](https://docs.ollama.com/gpu): listas ROCm e caminho Vulkan; verificar novamente no ensaio.
- [llama.cpp: compilação e backends](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md): alternativa para experimentar execução local e Vulkan.
