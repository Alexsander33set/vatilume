# Validação do pacote Ubuntu 24.04

Ensaio de 29/10/2026, em VM descartável. A instalação pessoal em `/opt` não foi atualizada por este ensaio. A prévia continua privada e não declara suporte universal a Debian/Ubuntu.

## Ambiente

- Imagem oficial `noble-server-cloudimg-amd64.img`, Ubuntu 24.04.5 LTS, build 20261017.
- SHA-256 da imagem: `04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`, conferido contra o `SHA256SUMS` obtido por HTTPS no [servidor oficial Ubuntu](https://cloud-images.ubuntu.com/noble/current/).
- QEMU 8.2.2, emulação TCG, 2 vCPUs, 3 GiB de RAM, disco overlay descartável e systemd como PID 1. Sem montagem de pastas/discos do host; SSH encaminhado apenas em loopback.
- Sessão gráfica real com LightDM/XFCE/Xorg e agente polkit. Navegador padrão: GNOME Web/Epiphany, instalado do repositório Ubuntu.
- O browser GTK exigiu renderização Cairo para este ambiente sem aceleração gráfica. Variáveis de teste ficam somente na sessão da VM; o pacote não impõe flags ao navegador do usuário. O carregamento lento em TCG não é benchmark de inicialização em hardware real. [GTK: renderer de fallback](https://docs.gtk.org/gtk4/running.html#gsk_renderer).
- Sem chaves ou dados pessoais copiados. Tarifa, ajustes, chave inválida e lançamento de gasto são fixtures locais; nenhuma chamada de IA é feita.

## Roteiro e evidências

O [validador de ciclo de vida](../scripts/validate_deb_vm.py) exige um marcador explícito de VM descartável, Ubuntu 24.04, virtualização QEMU e systemd real. Os scripts nunca devem receber acesso SSH à instalação pessoal. O marcador é `/etc/vatilume-disposable-test-vm`, com conteúdo `vatilume-deb-test`.

1. Instalar a revisão inicial pelo APT; verificar serviço ativo e habilitado, primeira coleta, API autenticada e bloqueio de acesso sem sessão.
2. Criar tarifa fictícia, cadência de 12 s, coleta de processos, chave inválida, limites reduzidos/pausados e gasto simulado de US$ 0,0123. Alterar também o conffile administrativo.
3. Usar o [auxiliar gráfico](../scripts/validate_deb_desktop.py): preparar apenas o usuário de teste, reiniciar a sessão LightDM, localizar Vatilume no Application Finder e selecionar a entrada real. Autorizar no diálogo polkit, usando somente a senha temporária dessa VM. Inspecionar o painel aberto no navegador padrão.
4. Registrar o checkpoint incluindo o arquivo privado de acesso do usuário, atualizar a revisão Debian pelo APT e conferir os hashes dos arquivos preservados, as tarifas e o prefixo completo das amostras já gravadas.
5. Reiniciar a VM de verdade e verificar boot ID novo, coleta automática e integridade do histórico anterior.
6. Remover pelo APT: serviços parados, socket fechado, comando/menu removidos, estado privado preservado. Reinstalar e conferir retomada automática e os mesmos dados.
7. Fazer `purge`: apagar os diretórios gerenciados e o conffile, preservando um diretório externo de teste.
8. Simular uma unidade de instalação manual e verificar que o pacote recusa a sobreposição, sem alterar essa unidade nem criar estado.

Os relatórios operacionais e capturas ficam em `var/validation/deb-vm`, fora do Git. O scanner de credenciais para publicação é aplicado ao índice Git exportado, sem incluir os bancos, modelos, chaves ou backups locais.

## Resultado e limites

A validação inicial encontrou um defeito real na reinstalação: remover os links de enablement fazia o helper interpretar o serviço como desabilitado pelo administrador. O pacote foi corrigido para usar máscaras gerenciadas pelo `deb-systemd-helper`, manter a intenção de inicialização e restaurar apenas suas próprias máscaras. O preinst reconhece essas máscaras sem aceitar uma unidade manual no lugar delas.

A repetição após essa correção passou em todas as etapas:

| Verificação | Resultado |
| --- | --- |
| Instalação limpa da revisão 0.7.0-1 corrigida | Aprovada; coletor ativo/habilitado, IA pausada e sem chave |
| Menu real, diálogo polkit e navegador padrão | Aprovados; painel autenticado visível |
| Atualização 0.7.0-1 → 0.7.0-2 | Aprovada; histórico anterior, tarifa, ajustes, chave fictícia, acesso e gastos preservados |
| Remoção comum | Aprovada; serviços parados, porta fechada, comando/menu removidos e dados privados preservados |
| Reinstalação 0.7.0-2 | Aprovada; serviços retomaram automaticamente, mantendo os dados anteriores |
| Reboot após reinstalar | Aprovado; novo boot ID, coleta automática e histórico íntegro |
| Purge da revisão final | Aprovado; estado e conffile removidos, diretório externo preservado |
| Instalação limpa adicional do arquivo final 0.7.0-2 após purge | Aprovada; sem máscaras ou configurações residuais impedindo o uso |
| Segundo purge após essa instalação | Aprovado |
| Proteção contra instalação manual existente | Aprovada; unidade simulada preservada e sobreposição recusada |

Arquivo validado: `vatilume_0.7.0-2_amd64.deb`, 2.506.816 bytes. SHA-256: `292f81ff4b4753ab086810b539b2b13bfd501246bd644c2a558f1a4caaf01173`.

Os 114 testes Python, o build Vue/Vite, a sintaxe dos maintainer scripts e a inspeção de conteúdo/permissões do pacote também passaram. O scanner aplicado aos arquivos preparados para o Git não encontrou credenciais. O CI remoto executa testes e constrói o pacote, mas não substitui o ensaio gráfico/boot descrito aqui.

Os testes Python cobrem também as fronteiras do auxiliar privilegiado e os insumos do builder: identidade polkit, dono/permissões do token, symlink/FIFO, diretório de concessão, wheels não fixados, dependências ausentes e caminhos que escapariam do diretório de extração.

A VM valida empacotamento, sessão gráfica, autenticação e ciclo de vida. Não comprova sensores de placas/GPU, consumo de recursos em hardware real, GNOME/Wayland, outras distribuições ou migração automática do instalador antigo em `/opt`. O teste de upgrade é entre revisões Debian da mesma versão funcional 0.7.0; não demonstra uma migração futura de esquema.
