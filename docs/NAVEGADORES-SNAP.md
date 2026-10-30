# Navegadores Snap no Ubuntu 24.04

O painel é uma aplicação local no navegador. A coleta continua independente dele. A candidata 0.8 usa um arquivo HTML privado para abrir a sessão, evitando colocar o token de acesso nos argumentos do navegador.

Firefox e Chromium instalados por Snap não têm o mesmo acesso ao sistema de arquivos de um navegador nativo. O lançador identifica o navegador HTTP padrão via GIO e usa a área privada do respectivo Snap: `~/snap/firefox/common/vatilume` ou `~/snap/chromium/common/vatilume`. O arquivo recebe 0600 e o diretório 0700; os diretórios ancestrais precisam pertencer ao usuário e impedir escrita por outros. Não relaxe permissões ou o confinamento para contornar falhas.

No primeiro uso de um navegador Snap recém-instalado, abra o navegador uma vez para inicializar o perfil e concluir os diálogos próprios dele. Depois use `vatilume` ou a entrada do menu. O lançador informa essa necessidade quando a área do perfil ainda não existe. Não cria conta no navegador nem pede a senha da API para abrir o painel.

## Ensaio desta candidata

Alvo: VM descartável Ubuntu 24.04.5 amd64, kernel 6.8.0-147, sessão XFCE/X11, snapd 2.77.1. Snaps do canal `latest/stable`, com assinaturas verificadas pelo snapd:

| Navegador | Versão | Revisão |
| --- | --- | --- |
| Firefox (Mozilla) | 159.0-1 | 9137 |
| Chromium (Canonical) | 156.0.8078.47 | 3569 |

O teste prepara o perfil, escolhe o navegador HTTP padrão, ativa Vatilume no menu real da sessão e inspeciona a janela. Também confere as permissões do redirecionamento, o token atual, os argumentos dos processos e o perfil AppArmor em modo `enforce`. Não usa `--no-sandbox`, `--devmode`, mudança para modo clássico ou perfil pessoal do mantenedor. As versões/revisões são as instaladas neste ensaio, não uma promessa sobre versões futuras.

Scripts: `scripts/validate_snap_browser.py` e `scripts/validate_deb_desktop.py`, restritos à VM marcada de testes. Capturas e diagnósticos ficam privados em `var/validation`, sem chamadas de IA. O ensaio não comprova outros canais Snap, instalações paralelas com nomes personalizados, todas as sessões Wayland/distribuições ou navegadores Flatpak.

A VM não fornece sensores físicos de energia/temperatura; a ausência desses dados é esperada. Ela serve à validação de instalação, isolamento, navegador e persistência, não a uma medição de consumo do hardware real.

Referências oficiais: [diretórios de dados Snap](https://snapcraft.io/docs/reference/administration/data-locations/) e [variáveis de ambiente](https://snapcraft.io/docs/reference/development/environment-variables/). O caminho `SNAP_USER_COMMON` é compartilhado entre revisões e pode ser incluído em snapshots de dados do Snap; trate o arquivo de abertura como uma credencial local.
