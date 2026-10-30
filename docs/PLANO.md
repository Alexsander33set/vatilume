# Plano de execução

Direção atual: versão de referência 0.6.0, Linux primeiro, interface no navegador, apoio voluntário e IA com chave própria. A ordem de trabalho vigente está em [DIRECAO.md](DIRECAO.md). O texto abaixo preserva o planejamento inicial e não é uma lista atualizada de recursos pendentes.

Registro histórico das primeiras entregas (28/10/2026): coletor, configuração, SQLite, CLI e instalação systemd implementados. A interface 0.2.0 também está instalada, com histórico, filtros, sensores, eventos, configuração e tarifa manual por vigência, validada no `docs/validation/INTERFACE-2026-10-28.md` (relatório local não versionado). O `docs/validation/COLETOR-2026-10-28.md` (relatório local não versionado) preserva o ensaio original e as pendências de reboot/longa duração. IA permanece para a etapa seguinte.

## 1. Detalhar fontes e tarifa

Escopo escolhido: hardware do PC, somente software. Adotar Linux local como primeira plataforma provisória. Identificar sensores, unidades e sobreposições, e registrar quais parcelas do gabinete ficam fora das leituras. Prever configuração de tarifa pela interface; cada usuário deve confirmar o preço efetivo de sua conta.

Escopo confirmado novamente: hardware interno, excluindo periféricos externos. Na interface, verificar viabilidade de obter tarifas dinamicamente, preservando a configuração manual e distinguindo referência pública do preço efetivo.

**Saída:** inventário e política de medição, distinguindo energia reportada parcial e estimativa do gabinete. Tarifa ausente não bloqueia a coleta.

## 2. Provar coleta e persistência

Construir um agente mínimo com descoberta estável de CPU/GPU, utilização, temperatura, configuração e SQLite. Comparar formatos físicos de armazenamento e medir CPU, memória, duração de escrita e crescimento do banco/WAL com a frequência padrão. Confirmar que consultas e falhas de sensores não bloqueiam coleta.

**Saída:** ensaio de 24–48 horas, dados reais e orçamento de recursos medido. Revisar stack ou frequência se as metas não forem atingidas.

## 3. Provar recuperação e operação contínua

Adicionar instalação systemd, boot sem login, supervisão, controle local, backup e migrações. Executar falhas de processo, reboot, suspensão, indisponibilidade de sensor e disco cheio simulado. Testar falha do SO em ambiente descartável e depois acompanhar o host por pelo menos sete dias, com logs e lacunas inspecionados.

**Saída:** relatório de quais testes passaram, quais garantias de recuperação foram demonstradas e quais dependem de validação no hardware real. Preservar um banco com dados confirmados e confrontar sequências antes/depois, não apenas verificar se o processo voltou.

## 4. Entregar o painel útil sem IA

Implementar histórico, eventos, cobertura, energia por fonte, tarifa, custos coerentes com o escopo, comparações e gerenciamento da coleta. Adicionar exportação, visualização da retenção e testes de consistência entre dados brutos e agregados. Validar janelas grandes sem carregar todo o histórico no navegador.

**Saída:** responder perguntas básicas com dados auditáveis. O custo do gabinete será explicitamente estimado; custos equivalentes de componentes terão cobertura parcial identificada.

## 5. Avaliar a estimativa por software

Modelar componentes e perdas não cobertos pelos sensores usando premissas identificadas, configuráveis e versionadas. Testar cenários de uso habitual, consistência dos cálculos e sensibilidade aos parâmetros. Verificar que valores reportados e estimados continuam distinguíveis no painel e nas ferramentas de IA.

**Saída:** estimativa com contribuição de cada premissa e limitações visíveis. Sem medidor externo, não há precisão absoluta comprovada para o total na tomada. Quando faltarem premissas defensáveis, mostrar cenários ou total indisponível em vez de um número com falsa precisão.

## 6. Comparar IAs e integrar a opção vencedora

Implementar ferramentas de consulta e auditoria antes de selecionar o modelo. Aplicar o [protocolo de avaliação](AVALIACAO-IA.md), começando com dados sintéticos e depois com histórico real. A comparação local/API já foi autorizada; definir provedor e teto de gasto antes das chamadas pagas. Mostrar qualidade, custo e latência para escolha informada.

**Saída:** resultados comparáveis, opção padrão selecionada por evidência, controles de gasto e análises que citam seus dados. Modelos que falhem nos critérios críticos não entram como analistas autônomos.

## 7. Ampliar somente após uso real

Sensores por processo, alertas, agendamento de IA, Windows e múltiplos dispositivos entram conforme perguntas que o histórico atual não consegue responder. Distribuição com Docker é uma opção para a aplicação/IA, sem tornar a coleta dependente do desktop. Medidor externo não integra o escopo escolhido.

## Decisões confirmadas e pontos em aberto

| Decisão | Estado atual | O que falta |
| --- | --- | --- |
| Escopo elétrico | Hardware do PC; gabinete como referência, sem monitores/periféricos externos | Detalhar parcelas que os sensores cobrem |
| Tarifa | Configurável pela interface, com vigência; distribuidora/localidade opcionais | R$/kWh, classe/modalidade e composição da conta |
| Medidor externo | Fora do escopo; usuário escolheu apenas software | Nenhuma compra prevista |
| Plataforma | Um PC Linux local | Necessidade de Windows já na primeira entrega |
| IA remota | Comparação com IA local autorizada, com controle de dados e gasto | Provedor, política concreta e teto em reais |
| Frequência | Energia/utilização 10 s; temperatura 30 s | Resultado do ensaio e necessidade de resolução maior |
| Retenção | Brutos 90 dias; minuto 24 meses; diário sem expiração | Espaço aceitável, backup e política de exclusão |
| Stack | Python/SQLite/systemd; FastAPI/Vue | Medição do overhead do coletor |
| Docker | Opcional após viabilidade | Conveniência de instalação e operação |

### Referência tarifária

A tarifa é informada pelo usuário, com vigência e descrição. Valores públicos podem não incluir todos os componentes da cobrança. A aplicação não escolhe uma distribuidora nem considera uma referência genérica como o preço final da conta.

## Escopo deste documento

Este plano registra a proposta inicial. O estado entregue e as decisões de distribuição estão no [README](../README.md), em [DIRECAO.md](DIRECAO.md) e nas [notas da prévia](releases/0.8.0.md). Metas de retenção, Windows ou IA local aqui citadas não representam funcionalidades entregues. Relatórios de inspeção do computador de desenvolvimento são privados e não acompanham esta cópia.
