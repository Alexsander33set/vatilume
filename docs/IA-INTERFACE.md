# Análises com IA na interface 0.9.0

## Uso

Abra `./open-ui.sh` e escolha **Análises com IA**. Selecione o período e escreva a pergunta, ou use um dos atalhos de investigação. **Preparar análise** cria um snapshot local e uma prévia, sem chamar modelo. A prévia informa modelo, dados enviados, período, quantidade de amostras e gasto máximo. **Analisar por até US$…** inicia o trabalho.

O padrão é `gpt-5.4-mini-2026-03-17`. Modelo, chave e limites ficam em **Configurações → Inteligência artificial**; Luna e Terra são opções explícitas para avaliação, sem fallback automático. Veja [premissas e controle de gastos](CONFIABILIDADE.md). Há uma análise ativa por instalação, com até cinco consultas adicionais, seis rodadas de inferência e prazo total de 120 s. A última rodada deve finalizar; chamadas nunca são repetidas automaticamente após erro.

Os resultados aparecem após validação. A resposta principal vem primeiro; os dados de apoio ficam recolhidos. O histórico mostra também a pergunta original. Registros anteriores continuam disponíveis no formato em que foram salvos, sem reescrever conclusões nem refazer chamadas pagas. **Ver evidências** abre período, origem, método, valores, unidades, intervalos usados e detalhes completos da consulta. Para energia/custo, **Baixar leituras de origem (CSV)** exporta os contadores/potências originais, unidades/escalas, relógios, qualidade, sessões e cadência, incluindo a leitura anterior necessária para a diferença inicial. Um limite por ID de amostra congela o histórico de origem; amostras posteriores não entram no download. Esse arquivo não é enviado ao modelo. Os registros ficam no PC e podem ser reabertos em **Análises recentes**. Dados brutos podem expirar se você habilitar retenção; isso não apaga o relatório e suas evidências calculadas. Reutilizar a mesma pergunta, snapshot, modelo e versão de validação usa o cache sem nova chamada. Alterar período, leituras ou tarifas produz outro snapshot.

## Projeção mensal

A pergunta “Com os dados que temos, qual seria o meu custo mensal de energia?” calcula um cenário para **30 dias**. A opção padrão usa o tempo diário observado pelo coletor, incluindo baixo uso. A base inicial pode ser parcial. Você pode escolher informar horas por dia como hipótese; tempo observado não mede presença do usuário. [Detalhes da base temporal](CONFIABILIDADE.md#tempo-observado-e-projeção). Uma duração explícita como “8 horas por dia” na pergunta tem prioridade e aparece na prévia. Durações diárias conflitantes são rejeitadas para não escolher uma hipótese silenciosamente.

Para cada componente disponível, o cálculo é `energia_kwh / (covered_seconds / 3600) * horas_por_dia * 30`. A soma só é permitida entre domínios confirmados como independentes e usa a tarifa configurada vigente no fim do período-base, mantida constante na projeção. Não extrapola o custo histórico quando ele contém tarifas antigas ou intervalos sem preço. Cada componente usa sua própria duração válida; lacunas nunca viram tempo desligado ou potência zero. Sem tarifa, apresenta kWh e solicita o valor para converter em reais. Sem intervalos válidos, explica a ausência de base, sem inventar consumo zero.

A prévia já apresenta o cálculo local, sem chamada ao modelo ou gasto de tokens. A execução com IA continua opcional para investigar outros aspectos. O controle de chave e orçamento da preparação continua sendo o mesmo do fluxo de IA; a prévia não é um serviço independente de calculadora.

O resultado identifica CPU/GPU como componentes reportados, lista componentes sem dados e mantém fora placa-mãe, memória, armazenamento e perdas da fonte. Não é previsão de fatura, medição do gabinete inteiro nem limite superior de consumo. A hipótese repete a carga observada nas horas selecionadas e deixa o restante do dia fora da conta. Bases curtas, lacunas e testes de IA presentes na janela aparecem nas premissas e limites.

**Conferir cálculo e dados** abre fórmula, duração válida, cobertura, média, projeção de kWh/reais por componente, tarifa e evidência do cálculo original com CSV. Horas e origem da hipótese fazem parte do snapshot e do cache; mudar o cenário exige nova prévia. A análise usa o cenário aprovado mesmo que o campo da tela mude depois.

## O que é validado

A IA escolhe consultas e seleciona fatos relevantes. Não fornecemos texto livre do modelo como afirmação ao usuário: a resposta final contém uma referência à resposta principal e referências a fatos e sugestões recuperados nesta execução. O backend rejeita referências inexistentes, campos extras e formato incorreto.

Cada fato tem redação, números e unidades produzidos pela aplicação. O schema enviado à API enumera os IDs disponíveis em cada rodada e exige uma resposta principal disponível e limita a seleção a oito fatos e três sugestões; quando não há sugestões, exige a lista vazia. A validação do backend continua independente dessas restrições. Energia/custo usam `analysis.overview`, que já trata contador de pacote, sobreposição com core, potência da GPU, duração monotônica, lacunas, sessões e vigências de tarifa. Comparações e desvios usam funções determinísticas e deixam o método registrado. A mesma regra impede uma leitura de uso em porcentagem de virar watts no texto. O snapshot tem hash conferido antes de analisar.

Isso valida cálculo e sustentação, não a calibração física dos sensores. O backend mantém explícitos o alcance parcial CPU/GPU, a cobertura temporal e a ausência de comprovação causal. As ferramentas não oferecem SQL livre, shell, leitura de arquivos arbitrários nem alteração do coletor. Sugestões de coleta são somente propostas.

Ferramentas disponíveis: qualidade, energia/custo observado, projeção mensal, coincidência de CPU por processo com picos de potência/uso, comparação das duas metades do período por métrica, desvios por baseline robusto, pontos de série e sugestão de contexto por processo. As séries consultadas pelo modelo têm até 12 pontos; os detalhes de comparações/desvios preservam os intervalos agregados usados nas estatísticas e suas lacunas. Energia/custo mantêm os resultados determinísticos, vigências e referência às leituras brutas preservadas pelo coletor. A descoberta ainda está limitada a esses contratos e ao snapshot selecionado.

## Gastos e chave

Em instalações novas, IA começa desativada e o teto acumulado é **US$ 0**. O usuário informa sua chave e escolhe o limite acumulado na interface antes de ativar análises. Limites menores iniciais: **US$ 0,05 por análise, US$ 1 por dia e US$ 2 por mês**; devem caber no acumulado quando habilitados. A interface aceita acumulado de até US$ 1.000 e por análise de até US$ 5. Dia/mês usam Brasília. Atualizações preservam os limites existentes, gastos e reservas; não concedem crédito nem aumentam orçamento automaticamente. Pausar bloqueia novas chamadas; uma chamada já enviada pode consumir tokens.

Antes de cada requisição, uma reserva conservadora considera o tamanho do conteúdo, overhead e máximo de tokens de saída. O controle inclui chamadas em andamento e reservas incertas; limites são conferidos com bloqueio de arquivo para impedir corrida entre solicitações. O máximo mostrado na prévia é congelado e não aumenta se outro navegador elevar os limites depois. O teto acumulado não é reiniciado a cada análise, atualização, dia ou mês.

Ao receber uso confirmado, a reserva é substituída pela estimativa calculada pelos tokens. Em timeout/erro incerto ela é mantida; não há repetição automática. A interface distingue gasto estimado e reservas pendentes. Desconto de cache e fatura/saldo do provedor não são consultados; o contador não controla outras aplicações da conta. Os ensaios GPT-6 usam ainda uma margem de cache-write na estimativa. Alterar o teto acumulado exige salvá-lo explicitamente na interface; reduzi-lo não apaga gastos nem reservas e não permite ficar abaixo do consumo já registrado. Os limites menores continuam valendo até ajuste explícito na interface.

A chave pode ser atualizada em **Credencial da API**, com entrada oculta. É salva em arquivo 0600 da conta do serviço e nunca é retornada por GET, colocada no prompt, nos argumentos de processo, no histórico do navegador ou no relatório. A instalação migra a chave já configurada no projeto sem imprimi-la. O modelo não recebe essa chave.

## Privacidade e dados

O envio ocorre na análise solicitada. A coleta e os indicadores continuam funcionando offline. Os prompts usam fatos, números e recortes necessários, sem inventário, identificadores do PC, rótulos brutos ou credenciais. Para processos, o agrupamento por aplicativo usa regras locais de nome e parentesco e soma somente os membros retidos. Nomes, PIDs e ancestrais ficam locais; a IA recebe apelidos, resolvidos no texto final pela aplicação. A pergunta do usuário não é anonimizada. A pergunta digitada também é enviada. Não há fallback automático para outro provedor.

Usamos Responses com `store=false`; isso não significa retenção zero. A documentação do provedor descreve registros de monitoramento de abuso normalmente por até 30 dias e ausência de uso para treinamento por padrão, ressalvadas opções da conta. Consulte [controles de dados](https://developers.openai.com/api/docs/guides/your-data).

## Instalação e recuperação

```sh
sudo python3 scripts/install_service.py --with-interface
```

O instalador preserva telemetria, configuração e tarifas. Migra o histórico de gastos por IDs, sem duplicá-lo, mantém despesas futuras da interface em atualizações e copia os horários dos ensaios locais para contextualizar análises. Depois da migração, os scripts pagos antigos são bloqueados para não criar um segundo orçamento; testes locais continuam disponíveis.

Arquivos da conta do serviço, em `/var/lib/device-observability`: `ai.sqlite3` (snapshots, resultados e evidências), `ai-budget.json`/`.lock`, `ai-limits.json`, `ai-api-key` e `ai-experiment-windows.json`. O coletor não depende desses arquivos. O backend continua sob demanda, com encerramento após inatividade; nenhum runtime de modelo local é instalado no boot.

Se houver reinício durante uma análise, ela é marcada como interrompida, sem replay pago. O snapshot e as reservas permanecem. Outra instância não marca uma execução ativa como interrompida quando o bloqueio de execução continua ocupado. Análises concluídas são imutáveis, mesmo que uma tarifa seja corrigida depois; uma nova análise usa a versão nova dos dados.

## Verificação

```sh
python3 scripts/verify_ai.py
# Executa uma análise paga sob os limites instalados, quando explicitamente desejado:
python3 scripts/verify_ai.py --paid-smoke
# Para conferir a resposta de projeção mensal com 8 h/dia:
python3 scripts/verify_ai.py --paid-smoke --monthly --hours-per-day 8
```

O primeiro comando consulta somente estado e orçamento. O segundo verifica uma execução real, cada evidência, o teto da prévia e a preservação da configuração do coletor. Os testes Playwright usam exclusivamente `127.0.0.1:8766` e dados descartáveis com transporte de IA simulado; eles não fazem chamadas pagas. O ensaio real do mini é registrado separadamente.

## Processos

A versão 0.6.0 inclui consulta de coincidência temporal com CPU/RSS retidos, nomes resolvidos somente no PC e CSV por evidência. Não existe atribuição de causa, energia ou GPU por aplicativo. [Coleta, limites e método](PROCESSOS.md).
