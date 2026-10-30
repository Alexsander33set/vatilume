# Especificação inicial

Documento de referência inicial. As decisões de distribuição, apoio voluntário e IA com chave própria estão atualizadas em [DIRECAO.md](DIRECAO.md). Relatórios pessoais de validação permanecem locais, fora do Git.

Data: 2026-10-28. Estado: escopo elétrico e comparação de IA definidos pelo usuário. A primeira implementação do coletor está descrita em [operação](COLETOR.md) e `docs/validation/COLETOR-2026-10-28.md` (relatório local não versionado); as outras partes continuam como proposta.

## 1. Resultado esperado

O usuário deve conseguir deixar o computador registrando por dias ou meses, abrir a aplicação quando quiser e entender energia, custo, utilização e mudanças de comportamento. A interface precisa explicar o que os sensores cobrem e o que falta para responder à pergunta do custo total.

O sucesso inicial é obter uma série histórica confiável e interpretável. Não é necessário manter um modelo de IA carregado para coletar, calcular indicadores ou abrir o painel.

### Escopo inicial

- Hardware do PC, somente software, sem medidor externo; monitores e periféricos externos fora da estimativa inicial.
- Um PC Linux, armazenamento local e acesso pela própria máquina.
- Agente iniciado no boot, sem depender do login gráfico, da rede ou do painel.
- Coleta configurável e extensível por adaptadores de sensores.
- Histórico, indicadores determinísticos, comparação de períodos e exportação.
- Configuração e saúde do agente acessíveis pela interface.
- IA opcional com consultas autônomas limitadas e rastreáveis; comparação local/API autorizada, com provedor e teto de gasto ainda por definir.

### Evoluções previstas

Windows, múltiplos dispositivos, servidor remoto, análise por processo, notificações e relatórios agendados. A modelagem já deve identificar dispositivo, fonte e versão, sem implementar sincronização distribuída nesta fase. Medidor externo não faz parte do plano solicitado.

## 2. Política de medição

Há duas categorias no escopo escolhido:

| Categoria | Exemplo | O que pode afirmar |
| --- | --- | --- |
| Reportado por componente | Contador de energia do pacote da CPU; potência reportada pelo driver da GPU | Energia/potência daquele domínio, sujeita às limitações do sensor |
| Estimado para o gabinete | Sensores e premissas explícitas sobre partes não cobertas e perdas | Estimativa por software, sem precisão absoluta validada |

“Reportado” não implica medição física de precisão conhecida. Sem referência externa, não atribuir margem de erro numérica inventada. A versão solicitada não mede energia na tomada.

Regras obrigatórias:

- Não apresentar CPU + GPU como consumo total na tomada.
- Não somar domínios sobrepostos: por exemplo, `core` já está contido em `package`.
- Não usar limite de potência, TDP ou potência nominal da fonte como consumo observado.
- Falha de leitura resulta em valor ausente e motivo, nunca em zero silencioso.
- Identificar mudança de sensor, hardware, calibração e configuração no histórico.
- Preservar leituras brutas separadas dos resultados derivados.
- Identificar o gabinete como escopo inicial; qualquer ampliação exige outra configuração de escopo.

### Estimativa do gabinete por software

Criar uma série derivada separada das leituras brutas. O modelo pode combinar domínios internos não sobrepostos com hipóteses configuráveis para componentes não cobertos e perdas da fonte. Se a potência da GPU cobre apenas parte da placa, a parcela não coberta também precisa ser identificada. Baseline residual, eficiência e comportamento sob carga são parâmetros do modelo, não leituras do computador.

Não inserir um número fixo arbitrário como se fosse consumo conhecido. Buscar evidências para as premissas, permitir ajustes pela interface e registrar origem/versão; quando faltarem dados, mostrar cenários condicionais ou estimativa indisponível. Faixas baseadas em hipóteses não serão chamadas de intervalo de confiança estatístico. O relatório deve permitir ver quanto vem de sensores e quanto vem do modelo.

A validação inicial cobre coerência matemática, sensibilidade às premissas, ausência de dupla contagem e repetibilidade. Sem referência externa, não comprova erro absoluto do consumo na tomada e não permite concluir com certeza o custo real total. A IA precisa respeitar esse limite.

### Energia e custo

Para potência amostrada, integrar em intervalos válidos, usando duração real e método documentado, inicialmente trapezoidal:

`E_kWh = soma(((P_anterior_W + P_atual_W) / 2) × delta_t_s) / 3.600.000`

Para contador acumulado em microjoules:

`E_kWh = delta_energia_uj / 3.600.000.000.000`

`P_media_W = delta_energia_uj / 1.000.000 / delta_t_s`

Tratar rollover com o alcance informado pelo contador, somente quando um único rollover for plausível. Após reboot, reset, suspensão ou intervalo que torne o delta ambíguo, iniciar outro segmento e sinalizar a incerteza. Não ligar dois pontos de potência atravessando uma lacuna longa. Um contador acumulado pode recuperar energia de um intervalo sem amostras apenas se sua continuidade e ausência de rollover ambíguo forem verificáveis; a distribuição temporal continua desconhecida.

`custo = soma(E_kWh_do_intervalo × tarifa_aplicável_ao_intervalo)`

Tarifas terão moeda, valor, vigência e origem. Começar por tarifa efetiva informada pelo usuário, documentando se já inclui tributos e bandeiras; não adicionar esses itens duas vezes. Encargos fixos e iluminação pública não devem ser atribuídos automaticamente ao PC. O custo representa a energia do escopo observado, não uma reprodução integral da fatura.

Requisito confirmado de interface: cadastrar e editar **R$/kWh**, com entrada no padrão brasileiro, distribuidora/localidade, início da vigência e indicação do que o valor inclui. Distribuidora, localidade, classe/modalidade e valor efetivo devem ser informados por cada usuário. Manter histórico de tarifas; uma correção retroativa deve ser explícita, com recálculo identificável, sem alterar as amostras.

Contratos com gestoras ou comercializadoras podem diferir da tarifa pública da distribuidora. Na etapa da interface, avaliar obtenção dinâmica de referências tarifárias, com origem, modalidade e vigência verificáveis. Distribuidora, gestor/comercializador e preço efetivo da conta devem ser conceitos distintos; descontos, créditos ou condições contratuais só entram após evidência. Consultar uma tarifa pública da distribuidora não comprova o custo efetivo do contrato. Coleta e cálculos básicos continuam funcionando sem acesso a esses serviços.

Sem tarifa, apresentar kWh e o estado “Configure a tarifa para calcular o custo”, em vez de R$ 0. Uma tarifa de simulação deve ter esse rótulo. Referências públicas da distribuidora podem ajudar no preenchimento, mas não substituir automaticamente o valor efetivo da fatura. Tarifas por faixa horária podem ser acrescentadas se a modalidade contratada exigir.

Projeções devem indicar janela de referência, cobertura e premissas. Dados de poucos minutos não fundamentam uma afirmação sobre o mês inteiro. Energia reportada por componente pode ter custo equivalente calculado, sempre identificado como parcial.

## 3. Coleta e configuração

### Métricas iniciais

| Grupo | Exemplos | Frequência inicial proposta |
| --- | --- | --- |
| Energia | Contadores de CPU e potência de GPU disponíveis | 10 s |
| Utilização | CPU, GPU, RAM, VRAM, taxas de I/O e rede | 10 s |
| Condição | Temperaturas e ventoinhas disponíveis | 30 s |
| Inventário | CPU, GPU, memória, kernel e capacidades dos sensores | No início e quando mudar |
| Eventos | Boot, início/fim de coleta, suspensão/retorno, falhas e alterações | Conforme ocorrência |

O padrão não coleta conteúdo de arquivos, tráfego de rede, títulos de janelas, argumentos de processos nem histórico de navegação. Análise por aplicativo será opcional e terá custo e privacidade avaliados separadamente.

Cada adaptador fornece descoberta de capacidades, identificador estável da fonte, unidade, semântica, frequência suportada e resultado de leitura com qualidade. Índices como `hwmon4` não são identificadores permanentes. Adaptadores defeituosos terão timeout, isolamento e retentativa, sem bloquear os demais.

Configuração: sensores habilitados, intervalos por grupo, destino, retenção, limites de disco, logs, privacidade e política de análise. Validar antes de aplicar; alterações são atômicas e versionadas, com retorno à última versão válida. A frequência realmente aplicada deve aparecer na interface.

## 4. Arquitetura proposta

### Agente no host

Processo Python dedicado, sem dependências do frontend ou SDKs de IA. Leituras de `/proc`, `/sys`, biblioteca de métricas quando necessária e adaptadores específicos. SQLite local é o registro primário. Uma unidade systemd de sistema inicia o agente no boot, executando com usuário dedicado e permissões mínimas para os sensores escolhidos.

O agente é o único escritor do banco de telemetria. Um socket Unix local com permissões restritas oferece operações tipadas de status, configuração e consulta. Um executor de consultas separado do laço de coleta aplica limites de tempo, pontos e concorrência. Agregações e manutenção não podem atrasar a persistência das leituras.

O controle de pausar/retomar coleta mantém o agente vivo para poder retomá-la. Reiniciar o processo ou alterar sua inicialização exigirá uma operação local específica e limitada, caso entre no escopo; o backend não recebe autorização genérica para executar comandos privilegiados.

### Aplicação de análise

Backend FastAPI e frontend Vue/TypeScript, executados sob demanda no início. O backend consulta o agente pelo socket e mantém configurações de apresentação, tarifas e análises em armazenamento próprio. O frontend recebe dados agregados com resolução adequada à janela, em vez de milhões de amostras.

Somente o backend tem acesso ao adaptador de IA. As consultas de IA usam a mesma camada de dados e cálculos do painel. Resultados pesados serão trabalhos canceláveis; falha de IA ou backend não interrompe o agente.

O acesso começa em loopback, com sessão/token local, validação de origem e proteção das operações de escrita contra requisições indevidas do navegador. Chaves de API ficam no backend, fora de exportações e logs.

### Docker

Não é necessário para a primeira coleta. Inicialmente, executar agente e aplicação no host reduz a configuração de sensores e permissões. Um perfil Docker Compose para painel ou runtime de IA pode vir depois, com volumes persistentes e acesso restrito ao socket, sem contêiner privilegiado ou acesso ao socket do Docker. O agente permanece independente do runtime de contêineres.

### Decisões de stack

Python é a primeira hipótese por facilitar sensores, SQLite, APIs e testes. Medir antes de declarar seu custo aceitável. Se o coletor ultrapassar o orçamento após otimizações simples, comparar um agente Go ou Rust mantendo o contrato de dados. Banco de séries temporais dedicado, fila externa e serviços distribuídos ficam condicionados a uma necessidade medida.

## 5. Persistência e recuperação

SQLite em disco local, `journal_mode=WAL` e `synchronous=FULL` em todas as conexões escritoras. Cada ciclo de coleta confirma suas leituras em uma transação, sem reter vários ciclos somente em memória. Confirmar “salvo” apenas depois do commit durável.

O objetivo é preservar transações confirmadas após falha do processo, reboot ou kernel crash, sob as garantias do sistema de arquivos e dispositivo de armazenamento. Não prometer perda zero absoluta: uma leitura ainda não confirmada pode se perder, e falha física, corrupção de memória ou armazenamento que não respeita sincronização escapam dessa garantia. Com ciclo de 10 s, a meta é perder no máximo o ciclo em andamento durante coleta saudável; o período até o sistema voltar é uma lacuna separada.

Requisitos de operação:

- Reinício automático após falha, com atraso, limites de tentativas e recuperação após falhas transitórias; evitar bloqueio permanente pela política de reinícios.
- Inicialização no boot, independentemente da disponibilidade do painel ou da internet.
- Identificar dispositivo, boot e sessão do agente; sequências únicas evitam duplicação.
- UTC para instantes, fuso explícito para apresentação e relógio monotônico para deltas dentro de um boot.
- Detectar saltos de relógio, atrasos de coleta, suspensão, reinícios e lacunas; desligamento abrupto não prova sozinho um kernel panic.
- Após suspensão, redescobrir sensores e validar continuidade dos contadores. Tempo sem leitura não será inventado como consumo zero.
- Falha de um sensor não derruba o ciclo inteiro; persistir leituras válidas e erros associados.
- Buffer de falha limitado e diagnóstico visível em caso de disco cheio, leitura somente ou erro de escrita. Não acumular RAM indefinidamente nem apagar histórico silenciosamente.
- Logs rotacionados e métricas da saúde do próprio agente.
- Checkpoints e compactação com limites; backup consistente pela API de backup do SQLite, com teste de restauração. Não copiar apenas o `.db` de um banco ativo em WAL.
- Backup antes de migração de esquema; atualização não deve zerar o histórico.

O agente volta quando o sistema operacional voltar. Ele não continua executando durante um kernel crash nem pode religar sozinho um computador desligado. No escopo apenas por software, esses períodos ficam sem observação; energia em suspensão ou standby não deve ser inventada como zero.

### Histórico e retenção

Proposta inicial, ainda configurável: leituras brutas por 90 dias, agregados por minuto por 24 meses e resumos diários sem expiração automática. Exclusão por retenção só será habilitada após configuração explícita, com política visível e agregados verificados.

Agregados precisam reter energia integrada, duração coberta, duração esperada, quantidade, mínimos, máximos e somas ponderadas adequadas. Média de médias sem ponderação pode alterar os resultados; percentis exigem método próprio, não podem ser reconstruídos de mínimo/média/máximo.

A cada 10 s são 8.640 ciclos/dia ou 3.153.600/ano de operação contínua. Isso não é uma previsão de bytes: uma linha por ciclo e uma linha por métrica têm custos diferentes. O protótipo deve comparar representação por grupos de métricas, índices e compressão/arquivamento antes de fechar o esquema físico e o orçamento de disco.

### Contrato mínimo de dados

Dispositivos; fontes e capacidades; amostras; eventos; sessões de boot/coleta; configurações versionadas; agregados; tarifas com vigência; modelos de estimativa/calibração; execuções de análise e evidências.

Uma amostra identifica dispositivo, fonte/domínio, métrica, unidade, instante UTC, referência monotônica e boot, valor bruto, qualidade, sequência e configuração. Ausência tem motivo. Deduções e análises registram versões dos algoritmos e referências aos dados usados.

## 6. Interface e indicadores

| Área | Entregas propostas |
| --- | --- |
| Visão geral | Energia do período, custo compatível com o escopo, potência média e cobertura |
| Histórico | Séries temporais, zoom, comparação, eventos e lacunas visíveis |
| Uso | Tempo observado, utilização, temperatura e intervalos de maior demanda |
| Coletor | Estado, última leitura/commit, erros, intervalos, pausa/retomada e espaço usado |
| Energia | Tarifa e vigência, escopo, fontes disponíveis, premissas da estimativa e limitações |
| Análises | Achados determinísticos, conversa com IA, evidências, consultas e custos |
| Dados | Exportação CSV/JSON, backup, restauração e política de retenção |

Os indicadores básicos não dependem de IA: energia integrada, custo, média ponderada, máximo observado, comparação entre períodos equivalentes, duração e cobertura. Máximo amostrado não significa pico elétrico absoluto. Tempo de máquina ligada, tempo observado e tempo de atividade do usuário são conceitos distintos; o último depende de um sensor adicional.

Detecção estatística pode destacar desvios de baseline por horário/dia, tendências térmicas e mudanças de utilização. Correlação serve como pista para investigação e não demonstra causa. Economia projetada exige cenário explícito; classificações como “jogando” ou “ocioso” precisam de regra e qualidade conhecidas.

## 7. Orçamento de recursos e critérios de aceite

Metas provisórias para um agente, coleta padrão, sem perfil por processo:

- RSS estável até 80 MiB e CPU média até 1% de **um núcleo**, medida como CPU-segundos/tempo × 100, em janela de pelo menos 30 minutos.
- Zero processo/modelo de IA necessário para a coleta; execução de IA somente por solicitação ou agenda habilitada.
- Disponibilidade de leitura por sensor de pelo menos 99% nos períodos acordados de operação com sensor suportado; suspensões, pausas e falhas permanecem contabilizadas e visíveis em separado.
- Escrita por ciclo medida em p50/p95, sem crescimento de fila; atraso p95 inferior ao intervalo configurado.
- Consumo de disco, escrita diária, crescimento de WAL e comportamento por sete dias medidos antes de assumir capacidade mensal.
- Ensaio A/B do agente ligado/desligado: CPU/RAM e telemetria disponível, reconhecendo que sensores internos não comprovam o impacto total na tomada.

Testes obrigatórios: kill do agente durante transação; reboot controlado; falha de sensor; suspensão/retorno; relógio alterado em ambiente de teste; disco cheio simulado; concorrência de consulta; restauração; migração e coerência dos agregados. Simular falha do SO em VM/ambiente descartável antes de qualquer teste desse tipo no PC principal. `kill -9` sozinho não prova durabilidade contra falha do kernel ou energia.

## 8. Referências verificadas

- [Kernel: sensores de potência da GPU AMD](https://kernel.org/doc/html/latest/gpu/amdgpu/thermal.html): semântica e unidades do `amdgpu`.
- [Kernel: powercap](https://cdn.kernel.org/doc/html/latest/power/powercap/powercap.html): domínios, contadores, alcance e controles.
- [SQLite: synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous): escolha de durabilidade em WAL.
- [SQLite: WAL](https://www.sqlite.org/wal.html): concorrência e checkpoints.
- [SQLite: backup](https://www.sqlite.org/backup.html): cópia consistente de um banco ativo.
- [systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html): supervisão e reinícios; validar opções contra a versão instalada na implementação.
- [ANEEL: perguntas sobre bandeiras tarifárias](https://www.gov.br/aneel/pt-br/assuntos/tarifas/bandeiras-tarifarias/faq-bandeiras-tarifarias): contexto de composição da tarifa; nenhum valor tarifário atual foi assumido para o usuário.
