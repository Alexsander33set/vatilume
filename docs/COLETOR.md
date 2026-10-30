# Coletor Linux 0.1.1

O coletor usa Python 3.11 ou superior e sua biblioteca padrão. Não depende de Docker, painel, rede ou IA. O escopo é o hardware interno do PC; sensores de periféricos USB/hidpp são excluídos.

## Executar nesta pasta

```sh
python3 -m device_observability doctor
python3 -m device_observability run
```

`doctor` descobre e lê sensores sem criar banco. `run` permanece no terminal até Ctrl+C/SIGTERM; não oferece inicialização no boot por conta própria. Para uma execução curta, use `run --cycles 3`. O caminho padrão é `config/collector.toml`, e os dados ficam em `var/collector/`. Caminhos relativos da configuração são resolvidos em relação ao próprio arquivo TOML.

```sh
python3 -m device_observability status
python3 -m device_observability tail --limit 1
python3 -m device_observability check
python3 -m device_observability backup /tmp/device-observability-backup.sqlite3
```

Os comandos produzem JSON. `status` verifica PID, instante de criação do processo, boot e atualização da saúde, distinguindo execução, degradação e estado parado/obsoleto. `check` verifica integridade e referências do SQLite. O destino de backup deve ser novo; arquivos existentes não são sobrescritos. Para restaurar, pare o agente e use o backup em **outro diretório de dados**, preservando o banco original e seus arquivos WAL/SHM para investigação.

## Instalar como serviço de sistema

Primeiro, validar os testes e o preflight:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/install_service.py --check
```

Instalação administrativa no terminal do usuário:

```sh
sudo python3 scripts/install_service.py
```

O instalador cria a conta de sistema `device-observability`, publica uma cópia versionada e pertencente a root em `/opt/device-observability/releases/`, mantém `/opt/device-observability/current` como referência da versão, cria a configuração em `/etc/device-observability/collector.toml` somente se ainda não existir e instala a unidade `device-observability.service`. O serviço recebe apenas escrita no seu estado, em `/var/lib/device-observability`. Configurações existentes são preservadas. Uma unidade preexistente sem a identificação do instalador é recusada.

Reexecutar o instalador publica a nova versão e reinicia somente esse serviço. Histórico, versões anteriores e configuração permanecem. A instalação **não importa automaticamente** dados de testes em `var/`; cada diretório contém um histórico independente. Nenhum teste deve usar o diretório de dados de produção.

Para instalar/atualizar e em seguida executar o teste controlado de recuperação, use `sudo python3 scripts/install_service.py --validate-recovery`. Esse teste encerra somente o processo do coletor e verifica o reinício automático, o prefixo de amostras confirmado e o backup. Não reinicia o PC.

```sh
systemctl status device-observability.service
systemctl is-enabled device-observability.service
journalctl -u device-observability.service -n 50 --no-pager
```

Como os dados pertencem à conta dedicada, a inspeção detalhada pode ser feita com:

```sh
cd /opt/device-observability/current
sudo -u device-observability python3 -m device_observability --config /etc/device-observability/collector.toml status
```

A unidade usa `Type=notify`, watchdog de 60 s, reinício após 5 s e inicialização em `multi-user.target`, sem login gráfico. Limites: 128 MiB de memória e 32 tarefas; esses limites protegem o host e não substituem a medição da meta de 80 MiB/1% de um núcleo. Nenhuma alteração de frequência, potência, driver ou permissão de sensor é feita pelo instalador. Sensores sem acesso são reportados como erro; não são substituídos por zero.

Para editar frequência/sensores, alterar a configuração TOML e executar `sudo systemctl reload device-observability`. Configuração inválida é recusada, preservando a anterior durante essa execução. Alteração de `data_dir` exige reinício. Configuração inválida no início impede a partida, para não gravar silenciosamente em outro local. Retenção e exclusão automática ainda não são implementadas.

Grupos lentos são alinhados aos ciclos planejados, sem acumular o tempo das leituras no próximo prazo. A resolução mínima é a do ciclo principal: uma frequência térmica menor que o intervalo principal resulta em uma leitura por ciclo. Cada observação preserva os instantes reais, em vez de presumir cadência perfeita.

## Persistência e falhas

- Um escritor por diretório, protegido por `flock`.
- SQLite WAL e `synchronous=FULL`, uma transação por ciclo. O commit confirma também catálogo, configuração e eventos associados.
- Contadores brutos e suas unidades são preservados. Domínios sobrepostos da CPU ficam identificados; o coletor não soma `core` a `package`.
- Arquivo de saúde atômico para progresso e falhas, sem tratá-lo como registro durável de telemetria.
- Até três ciclos em memória durante erro de gravação, por padrão. Ao exceder o limite, os mais antigos são descartados e a perda é contabilizada; na recuperação, um evento registra falhas e perdas. O histórico confirmado não é apagado.
- Reserva padrão de 16 MiB livres antes de gravar. Banco, WAL e logs precisam ser monitorados; ainda não há compactação/retention automática.
- Cada adaptador usa um único leitor com prazo compartilhado de 2 s por ciclo. Um leitor travado fica isolado em sua própria thread, sem criar substitutos indefinidamente; os outros continuam. Resultados atrasados não são atribuídos a uma coleta mais recente. Leituras de kernel em estado ininterruptível não podem ser canceladas pelo Python; o watchdog/reinício do processo é a última defesa.
- Identificação de sessão/boot, timestamps UTC, monotônicos e BOOTTIME, além de eventos de alteração de relógio, suspensão estimada, atraso e retomada sem encerramento limpo.
- `SIGTERM`/Ctrl+C tenta concluir a gravação e registra parada. `SIGKILL` exige nova partida (manual ou systemd); a próxima sessão identifica a interrupção sem alegar uma causa como kernel panic.

As garantias de energia/períodos sem leitura ficam para a camada de análise. Nesta versão não existe cálculo de consumo total do gabinete, tarifa ou custo. Preservar um commit após falha do processo não comprova tolerância a kernel crash, queda de energia ou defeito físico. O serviço retoma quando o sistema operacional volta.

## Testes e medição

```sh
python3 -m unittest discover -s tests -v
python3 scripts/benchmark.py --config config/collector.toml --seconds 1805 --output var/benchmark-30min
```

O benchmark precisa de um diretório de saída novo e nenhum agente usando o mesmo `data_dir`. Ele inicia um coletor, observa seu processo completo (incluindo threads), registra dados a cada 5 s e o encerra ao final. O observador é externo ao processo medido. Relatórios: `resources.jsonl`, `summary.json` e `agent.log`. A porcentagem de CPU é relativa a um núcleo. Esse teste de 30 minutos não comprova estabilidade por dias/meses.

Os testes usam diretórios descartáveis, processos filhos e limite de páginas do SQLite para simular disco cheio, sem encher o disco real. Mudanças de boot/relógio são simuladas; o computador principal não é reiniciado, suspenso ou submetido a kernel crash pelos testes.

### Confirmar após um reboot real

Antes do reboot, registrar o `boot_id`, sessão e último ID confirmado. Depois que o usuário reiniciar o PC em uma ocasião conveniente, verificar:

1. Serviço ativo e habilitado, sem depender de abrir o painel ou terminal.
2. Novo `boot_id` e nova sessão no mesmo banco, com amostras dos dois boots preservadas.
3. Novas leituras confirmadas e nenhuma perda silenciosa de histórico.
4. Integridade do banco e logs do boot (`journalctl -u device-observability -b`).

O teste de recuperação salva `var/validation/reboot-baseline.json`, sem substituir um baseline já existente. Após um reboot realizado pelo usuário, executar `sudo python3 scripts/validate_service.py --verify-reboot`. O comando compara o histórico confirmado, exige um `boot_id` novo e verifica novas amostras no banco. Se o boot ainda for o mesmo, recusa declarar sucesso.

Não confundir `is-enabled` com prova de partida em um reboot já realizado.

## Fora desta entrega

O ensaio 0.1.1 acima não inclui a interface. Na versão 0.2.0, a [interface local](INTERFACE.md) acrescenta consultas, configuração por override/SIGHUP, integração de energia por componente e tarifa manual por vigência. Estimativa do gabinete, tarifas automáticas, IA, agregação e retenção automática permanecem fora da entrega. Modalidade, valores, descontos/créditos e acesso aos dados da conta precisam ser verificados por cada usuário, sem presumir desconto ou preço efetivo.
