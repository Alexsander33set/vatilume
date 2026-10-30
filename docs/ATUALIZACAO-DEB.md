# Atualizar preservando o estado

## Pacote da prévia pública

Atualize com `sudo apt install ./vatilume_0.8.0-2_amd64.deb`, depois de conferir os checksums de Releases. O pacote preserva o estado existente e reinicia apenas seus serviços. A revisão Debian `-2` atualiza documentação/metadados da distribuição; o código da aplicação continua 0.8.0. Faça um backup privado antes de atualizar dados importantes. `apt remove vatilume` preserva o estado; `apt purge vatilume` apaga o estado gerenciado.

## Assistente da candidata privada anterior

O assistente abaixo é mantido como ferramenta de desenvolvimento da candidata privada 0.9.0-1. Ele exige os artefatos antigos e seu manifesto em `dist`; **não é o instalador da prévia pública -2**. O procedimento assistido usa o artefato local verificado e um backup privado antes da troca:

```sh
sudo python3 scripts/upgrade_deb.py --apply
```

Execute na raiz do projeto, no seu próprio terminal. A senha é solicitada pelo sudo; não deve ser enviada ao suporte. O script não aceita senhas e não faz chamadas de IA. A distribuição pública terá instruções compatíveis com os artefatos efetivamente publicados; este fluxo ainda usa os pacotes candidatos privados em `dist`.

O assistente aceita as origens 0.7.0-2, 0.8.0-1, 0.8.0-2 e a candidata 0.9.0-1, confere o manifesto/SHA-256, mantém um pacote anterior para retorno e pausa apenas os serviços do Vatilume durante a captura. Não faz upgrade geral do sistema nem manda o needrestart reiniciar serviços de terceiros.

O backup, em `/var/backups/vatilume/upgrade-*`, é acessível apenas a root e pode conter credenciais e atividade pessoal. Inclui bancos consistentes, arquivos de estado/configuração, autorizações de desktop e pacotes para recuperação. Cada banco é reaberto e comparado, e os arquivos do arquivo compactado têm seus hashes verificados antes da instalação. `before.json`, `before.tar.gz`, `snapshot/` e `upgrade.log` devem ser mantidos juntos. Backup no mesmo disco não protege contra perda do disco.

Após a instalação, verifica:

- Continuidade da coleta com novas amostras na versão esperada, sem descartes ou erros de gravação.
- Preservação de todos os registros anteriores, configuração, tarifas, chave e orçamento/gastos de IA.
- Serviços ativos/habilitados, entrada de menu e acesso pelo lançador.
- Renovação única do token local na transição para 0.8, mantendo os usuários já autorizados. A chave da API não é renovada.

Se uma verificação falhar depois da instalação, tenta reinstalar o pacote anterior, restaurar o snapshot e conferir a preservação. Não apague o backup ou `failed-state/` se houver erro. Uma falha na recuperação automática exige revisão administrativa antes de tentar outra atualização.

O sucesso mostra `backup: complete_verified` e `upgrade: passed`. Depois abra pelo menu ou com `vatilume`. A prova visual de abertura é separada das verificações de serviço; `launcher: ready` confirma acesso HTTP, não uma captura da janela do navegador.

Uma instalação que ainda não autorizou nenhum usuário pode ser atualizada: o resultado indica `authorization_required`, e a primeira abertura continua solicitando a autorização normal. Isso não concede acesso novo silenciosamente.

O assistente mantém explicitamente os arquivos de configuração alterados localmente (`--force-confold`) e fecha a entrada interativa dos subprocessos. Uma etapa inesperada que exija interação deve falhar e acionar a recuperação, em vez de aguardar uma pergunta oculta. As fases de instalação e verificação da coleta são informadas no terminal.

O teste `scripts/validate_conffile_vm.py` reproduz uma troca de versão com configuração personalizada usando APT/dpkg reais e dois minipacotes de teste. Exige a VM descartável marcada e não modifica a configuração do Vatilume.
