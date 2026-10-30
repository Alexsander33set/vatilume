# Migrar a instalação pessoal para o pacote

Procedimento específico para a instalação de desenvolvimento **0.6.0 em `/opt`**, na base Ubuntu 24.04/amd64/Python 3.12, usando o arquivo privado `vatilume_0.7.0-2_amd64.deb` já validado. O script confere a identidade e o SHA-256 do pacote; não baixa outra versão nem redefine tarifas ou limites de IA.

## Executar

Na pasta do projeto, em um terminal da sua própria sessão gráfica:

```sh
sudo python3 scripts/migrate_to_deb.py --apply && gtk-launch vatilume
```

A autenticação administrativa acontece somente no terminal do proprietário. Não compartilhe a senha. Para apenas conferir os pré-requisitos, sem parar serviços, use `--check` em vez de `--apply`.

O script usa `SUDO_USER` para identificar o dono do desktop. Para uma execução administrativa sem sudo, informe `--owner NOME` explicitamente. Não executa o navegador como root: `gtk-launch` está depois do comando sudo e usa a entrada registrada pelo pacote, a mesma usada pelo menu de aplicativos.

## O que é preservado e verificado

- Bancos de telemetria, interface/tarifas e análises de IA, incluindo todos os registros anteriores ao ponto de troca.
- Conffile do coletor e seus overrides, cadências, grupos e ranking de processos.
- Chave privada, token local, histórico de gastos, orçamento acumulado e limites efetivos de IA. Se a versão antiga usava limites implícitos, esses mesmos valores são materializados para evitar adotar os padrões de uma instalação nova.
- Conta técnica do serviço. O diretório de dados permanece `/var/lib/device-observability`.
- Acesso do proprietário, transferido para o arquivo privado do lançador do pacote. O comando antigo em `~/.local/bin/vatilume` vira um link para `/usr/bin/vatilume`, preservando também o caminho que o shell possa ter guardado.

As dependências do APT são preparadas antes da pausa. O script bloqueia o início de análises de IA durante a troca, não interrompe uma análise ativa, para os serviços, captura e verifica o backup e só então retira as unidades manuais e o link `current`. Mantém os releases antigos em `/opt` para recuperação. Unidades desconhecidas, drop-ins, conffile externo, launcher não gerenciado e desktop entry do usuário que sobrescreveria o pacote exigem revisão: o script recusa esses casos antes da troca.

O APT preserva o conffile existente sem exigir uma escolha interativa entre versões. O fim da migração exige unidades provenientes do pacote, duas novas amostras duráveis, mesma configuração efetiva, prefixos dos bancos intactos e chave/tarifa/gastos preservados também nas respostas da interface. Nenhuma chamada de IA é feita.

## Backup e retorno

Cada execução cria um diretório **privado, pertencente ao root**, em `/var/backups/vatilume/migration-*`. Ele contém:

- `before.tar.gz`: snapshots SQLite consistentes, arquivos privados, configuração, unidades, runtime antigo e launcher.
- `before.json`: SHA-256 do arquivo, integridade e fingerprints das tabelas, arquivos e configuração.
- `scripts/migrate_to_deb.py` e `device_observability/`: cópia da ferramenta de recuperação, independente de futuras edições no projeto.
- `RESTORE.md`: comando específico para recuperar esse checkpoint.
- `result.json` em caso de sucesso; logs privados e `rollback.json` se o retorno for necessário.

O backup contém credenciais. Não deve ser anexado a uma release ou enviado junto com um relatório público. É um checkpoint no mesmo disco; não inclui o sistema operacional inteiro nem substitui uma cópia em outro armazenamento.

Se a troca falhar após o backup, o script remove apenas o pacote, restaura o estado anterior e retoma o coletor antigo. Não usa `apt purge`. Qualquer trecho coletado depois da troca é primeiro guardado em `failed-state-*.tar.gz`, para não descartá-lo durante a restauração do checkpoint. Uma falha de retorno é informada explicitamente, mantendo o backup e os logs.

O comando de recuperação manual, se necessário, é:

```sh
sudo python3 /var/backups/vatilume/migration-SEU-CHECKPOINT/scripts/migrate_to_deb.py \
  --restore-backup /var/backups/vatilume/migration-SEU-CHECKPOINT
```

Ele devolve os dados gerenciados ao ponto do backup e guarda o estado mais recente em um arquivo privado antes de fazê-lo. Não é uma forma de combinar automaticamente históricos de versões diferentes.

## Conferência no desktop

Depois de `migration: passed`, o segundo comando abre a entrada Vatilume no navegador padrão. Confira também Vatilume na busca do menu de aplicativos. O relatório automático indica `menu_visual_check: pending_desktop_launch`: registro/lançador podem ser verificados por código, mas a presença da janela precisa de conferência na sessão gráfica real.

Os ensaios usam uma instalação 0.6.0 sintética na VM Ubuntu 24.04, tarifa e chave inválida de teste e nenhum dado pessoal. O [auxiliar da VM](../scripts/validate_legacy_migration_vm.py) exige o marcador de ambiente descartável. O roteiro cobre falha de instalação antes do pacote existir, falha depois da troca, retorno à coleta antiga e migração completa com os limites implícitos da versão antiga. Resultados operacionais ficam fora do Git, em `var/validation/migration-*`.

Ensaios de 29/10/2026 aprovados:

| Caso | Resultado |
| --- | --- |
| Falha proposital após instalar o pacote | Backup verificado, retorno automático à 0.6.0 e histórico intacto |
| Falha proposital antes de instalar, já sem as unidades antigas | Retorno automático aprovado, mesmo sem unidades carregadas |
| Migração completa e limites implícitos de IA | Duas novas amostras, mesma tarifa, chave, configurações e gasto; sem adotar a pausa padrão de uma instalação nova |
| Restauração pelo script autocontido no backup | Retorno aprovado à coleta antiga, sem depender da ferramenta na pasta do projeto |
| Testes Python | 123 aprovados; sem inferência paga |

Esses resultados comprovam o procedimento na VM. A execução e a abertura visual na instalação pessoal precisam ser conferidas depois do comando administrativo; não são declaradas concluídas pela preparação da ferramenta.
