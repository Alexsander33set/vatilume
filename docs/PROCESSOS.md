# Processos e evidências de coincidência, 0.6.0

A coleta optativa registra CPU e memória residente (RSS) por processo visível ao serviço. O padrão é uma varredura a cada **30 s**, com os **cinco maiores consumidores de CPU e os cinco de RSS**, deduplicados por PID. A interface permite cadência de 5–3.600 s e ranking de 1–10 processos por métrica. A frequência efetiva depende do ciclo principal. Desativar o grupo interrompe novas coletas e mantém o histórico existente.

## Dados e limites

O adaptador lê somente `/proc/PID/stat`: nome curto (`comm`), PID, PID do pai (PPID), instante de início, contadores de CPU e páginas residentes. Não lê `cmdline`, `environ`, `cwd`, `exe`, `fd`, arquivos pessoais ou URLs. Nomes curtos podem ser nomes de auxiliares, estar truncados e agrupar programas diferentes; não são um inventário confiável dos nomes comerciais dos aplicativos. PIDs e nomes permanecem locais.

Há um orçamento de **50 ms de tempo de parede**, verificado entre leituras, e no máximo **4.096 PIDs candidatos** por varredura. Uma leitura de kernel não pode ser interrompida em Python; o adaptador tem o mesmo isolamento por thread e prazo externo dos outros sensores. Ao atingir um limite, o resultado fica marcado como parcial. O cursor gira dentro do conjunto limitado de candidatos; em sistemas acima do limite, não há promessa de cobrir todos os PIDs. Falta de permissão e desaparecimento de processos são contabilizados; não ganhamos permissões de root/ptrace nem enfraquecemos o serviço.

CPU usa `(ticks_atuais - ticks_anteriores) / ticks_por_segundo / segundos_monotônicos / CPUs_lógicas * 100`. Portanto, 100% representa a capacidade total da máquina, e um núcleo totalmente ocupado em uma máquina de 16 CPUs lógicas equivale a aproximadamente 6,25%. Não somamos tempos de filhos aos pais nem percorremos threads. RSS é `páginas_residentes * tamanho_da_página`; páginas compartilhadas podem aparecer em vários processos, portanto RSS não é RAM exclusiva nem deve ser somada como memória física única.

A primeira leitura de cada processo não tem referência de CPU. Troca de PID/início ou nome, contador regressivo, lacuna longa, suspensão, salto de relógio ou mudança de configuração invalidam a referência. Uma nova execução do coletor começa sem baselines anteriores. Aplicativos que abrem e fecham entre varreduras podem não aparecer. Não há dados por processo para períodos anteriores à ativação.

Os contadores de referência, duração, unidade de ticks e número de CPUs são preservados nas entradas retidas. A camada de análise refaz a conta e rejeita um percentual que não corresponda aos seus contadores. Campos ausentes ou inválidos continuam desconhecidos.

## Persistência e recursos

O contexto limitado é incluído em `collectors_json`, na mesma transação SQLite WAL/FULL dos sensores. Não há tabela de catálogo por PID, nem crescimento indefinido de metadados por processo. O cache de baselines tem teto de 4.096 PIDs. A leitura usa um único worker adicional; não executa ferramentas externas por PID. Gravações confirmadas usam a recuperação já existente, sem substituir o banco, criar um segundo escritor ou depender da interface/IA.

As estimativas de crescimento nos ensaios são do JSON adicional, não da alocação total do SQLite/WAL/backup. A medição de CPU/RAM observa o processo inteiro do coletor, incluindo threads; resultados curtos não equivalem a validação de meses de execução.

## Coincidências e interface

A página **Processos** usa o mesmo filtro de período. Mostra a disponibilidade das varreduras, leituras de CPU/RSS, instantes e detalhes locais. Para períodos grandes, retém no máximo uma varredura por intervalo agregado, escolhida pela proximidade do centro, até o limite de pontos do painel. O banco conserva os contextos originais; a retenção de tela não é um inventário completo.

**Aplicativos perto dos picos** consulta até três maiores médias dos intervalos de potência/uso de CPU ou GPU, separadas por pelo menos um intervalo. Escolhe a varredura retida mais próxima que tenha CPU efetivamente sobreposta ao intervalo do pico. O intervalo de CPU precisa estar dentro da janela selecionada. Proximidade de horário sem sobreposição não é suficiente. Só as entradas retidas entram na comparação; os grupos de aplicativo usam as regras descritas abaixo e somam seus percentuais capturados. O resultado identifica as entradas e a varredura de origem.

Isso mostra coincidência de CPU com uma média de potência/uso do mesmo intervalo, **sem atribuir energia, uso de GPU por processo ou causa**. Em períodos longos, a resolução é mais grosseira; reduza a janela para investigar um horário. Sem varredura compatível, a interface informa ausência de evidência, não ausência de aplicativos ativos. Não mede FPS, I/O, rede ou GPU por processo nesta versão.

## Agrupamento por aplicativo

A visualização padrão **Aplicativos** dá nomes reconhecíveis aos processos. **Processos técnicos** mantém nomes curtos, PIDs, RSS e intervalos originais. Cada grupo pode ser aberto para conferir seus membros, a regra e os vínculos de parentesco registrados. Processos desconhecidos ficam separados por PID e instante de início, mesmo quando têm o mesmo nome genérico.

O catálogo local versionado em `device_observability/applications.py` contém regras exatas de nome, como `aces` → War Thunder, `zen` → Zen Browser, `steamwebhelper` → Steam e `ChatGPT` → ChatGPT / Codex. São identificações por nome, **não verificação da identidade do executável**. Um nome é alterável e não distingue instalações ou perfis do mesmo produto. A interface informa que a identificação é por regra.

Para auxiliares genéricos conhecidos, como `Isolated Web Co` e `QtWebEngineProc`, a coleta retém até 16 vínculos de pais já observados na mesma passagem por `stat`, somente nas entradas que entram no ranking. A identificação atravessa auxiliares e intermediários conhecidos (incluindo `forkserver` e `bwrap`) e procura um aplicativo conhecido nessa cadeia, conferindo PPID, início e ausência de ciclos. A passagem por processos não é atômica; uma corrida entre saída/reutilização de PID e a leitura pode tornar o parentesco ambíguo, por isso ele continua sendo identificação por regra. Não atribui ao GNOME todos os programas que ele abriu, nem adota filhos genéricos como Python. Auxiliar órfão, com pai ausente ou com reutilização detectável pelo início permanece desconhecido. Um jogo com nome próprio reconhecido não é absorvido pelo Steam.

O agrupamento roda na consulta local, sem modelo, processo externo ou leitura extra por PID. O coletor continua guardando no máximo os dez processos padrão (vinte com ranking máximo); não passa a guardar todos os membros de cada aplicativo. As somas de CPU/RSS são **dos membros retidos**, não o uso total do aplicativo. CPU sem referência não vira zero: o grupo mostra quantos membros têm cálculo disponível. RSS soma páginas residentes e pode repetir páginas compartilhadas.

Nomes reconhecidos diretamente podem ser apresentados de forma amigável no histórico existente. Parentesco não é reconstruído para períodos que não o registraram. Relatórios de IA já concluídos permanecem como foram salvos. Novas análises usam a versão nova do validador; a IA recebe somente apelidos de grupos, percentuais e contagens, enquanto nomes, PIDs e ancestrais ficam no PC. O CSV adiciona aplicativo, método de identificação, PPID e cadeia registrada aos contadores originais.

## IA e privacidade

A ferramenta `inspect_process_activity` é somente leitura e aceita uma das quatro métricas permitidas. Não oferece shell, SQL livre ou alteração do coletor. A pergunta sobre aplicativos/processos recebe essa consulta inicial, e o modelo pode solicitar outras métricas dentro dos limites de consultas e gasto já existentes.

Os nomes são mapeados localmente para apelidos como `A001`. O modelo recebe fatos calculados, valores e apelidos, **sem nomes, PIDs, sessões, caminhos ou contadores identificadores dos processos**. A pergunta digitada pelo usuário continua sendo enviada, como informado na prévia. A resposta final seleciona IDs de fatos; a aplicação resolve a redação com os nomes somente para a interface local. Isso é minimização de dados, não garantia de anonimização completa.

**Conferir cálculo e dados** abre as médias e intervalos, nomes locais, apelidos, PIDs e contadores de origem. **Baixar evidências de processos (CSV)** exporta somente as entradas que sustentam as coincidências da consulta salva. O arquivo contém nomes locais; prefixos de fórmula são neutralizados para abertura em planilha. Nenhum CSV é enviado automaticamente ao provedor. Relatórios antigos permanecem imutáveis; a nova versão do validador impede reutilizar resultados de outro contrato.

## Instalação e verificação

```sh
sudo python3 scripts/install_service.py --with-interface --with-processes --validate-recovery
```

`--with-processes` é a ativação explícita do novo grupo e preserva as demais configurações, tarifas, chave e gastos. Atualizações futuras sem essa flag preservam a escolha de ativar/desativar feita pelo proprietário. O teste de recuperação interrompe somente o coletor e verifica seu reinício; não reinicia o PC.

```sh
python3 scripts/verify_processes.py
# Uma investigação paga sob os limites cumulativos instalados, quando solicitada:
python3 scripts/verify_processes.py --paid-smoke
# Após instalar a 0.6.0: confere também somas, membros, identificação e migração de teto.
python3 scripts/verify_processes.py --applications --paid-smoke --metric cpu_w
python3 scripts/verify_processes.py --applications --paid-smoke --metric gpu_w
```

A verificação aguarda duas varreduras válidas. O ensaio pago utiliza o mesmo GPT-5.4 mini e o orçamento explicitamente autorizado pelo operador, sem outro contador ou fallback. Conferências de CPU/RSS, interface e CSV não exigem chamadas pagas.

Referências: [documentação do Linux sobre /proc](https://docs.kernel.org/filesystems/proc.html), [ferramentas na API OpenAI](https://developers.openai.com/api/docs/guides/function-calling).
