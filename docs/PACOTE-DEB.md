# Pacote Debian do Vatilume

Prévia 0.8.0 para **Ubuntu 24.04, amd64, Python 3.12 e systemd**. O pacote não instala modelos de IA e não contém dados, tokens ou chaves do computador de desenvolvimento. Suporte a outras versões do Ubuntu, arquiteturas ou distribuições precisa de validação própria.

## Instalar e abrir

```sh
sudo apt install ./vatilume_0.8.0-2_amd64.deb
vatilume
```

Também é possível abrir **Vatilume** no menu de aplicativos. O navegador padrão da sessão mostra a interface local. Na primeira abertura, a autenticação administrativa do Linux autoriza seu usuário a consultar o histórico compartilhado deste PC. Essa autorização permite também configurar o coletor, tarifa e IA; não há isolamento de dados entre usuários autorizados. A chave de IA começa vazia, com chamadas pausadas. Sem chave e aprovação na interface não há chamadas pagas.

É necessário ter uma sessão gráfica, navegador padrão e agente de autenticação polkit. Em ambientes GNOME/Ubuntu Desktop o desktop fornece o agente; sessões mínimas podem precisar do pacote recomendado `policykit-1-gnome`. A instalação não escolhe um navegador nem instala um desktop. O endereço é `127.0.0.1:8765`, acessível somente neste computador. Abrir esse endereço sem o lançador em um navegador novo não concede acesso.

O coletor inicia no boot. Fechar a aba não para a coleta. O worker web é ativado por socket e encerra após inatividade. As dependências Python do painel e os arquivos web compilados vêm no pacote; não se executa pip, npm ou download de código em scripts de instalação. O APT pode baixar dependências normais do sistema.

## Atualizar, remover e preservar dados

```sh
# Atualização: usar o arquivo da nova versão.
sudo apt install ./vatilume_NOVA-VERSAO_amd64.deb

# Remoção comum: para os serviços, preservando histórico e configurações.
sudo apt remove vatilume

# Exclusão completa e intencional dos dados gerenciados pelo pacote.
sudo apt purge vatilume
```

`remove` preserva `/var/lib/device-observability`, `/var/lib/vatilume-access` e o conffile `/etc/device-observability/collector.toml`. Isso inclui histórico, tarifa, ajustes, credencial de IA e gastos. Reinstalar recupera o estado. Os arquivos preservados permanecem privados; remover o programa não é uma forma de apagar credenciais.

`purge` apaga os dois diretórios fixos acima e o conffile. Faça backup antes. Um `data_dir` externo configurado manualmente não é percorrido nem apagado. A conta técnica do serviço é mantida para evitar reatribuição de UID a arquivos externos preservados. Cópias de segurança e sessões já abertas no navegador não são apagadas.

A configuração de coleta editada pela interface fica em `collector-overrides.json`, preservado nas atualizações. Alterações administrativas no conffile seguem a resolução de conflitos normal do dpkg. Os limites de IA existentes não são ampliados pela atualização.

## Instalação antiga em /opt

O pacote recusa instalações que tenham as unidades manuais em `/etc/systemd/system` ou o release em `/opt/device-observability/current`. Elas podem sobrepor as unidades do pacote. Não remova esses arquivos manualmente para contornar a proteção: use o [procedimento de migração com backup e retorno](MIGRACAO-DEB.md), que valida e retira somente a instalação conhecida. Construir ou testar o `.deb` não altera a instalação pessoal.

## Construir

Em ambiente de desenvolvimento Ubuntu 24.04 amd64, com Python 3.12 e Node 24:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
python3 -m pip download --only-binary=:all: --require-hashes -r backend/requirements.lock -d scripts/wheels
python3 scripts/prepare_third_party.py
python3 scripts/build_deb.py
```

O builder confere versões, hashes e plataforma dos wheels, inclui apenas entradas explícitas e gera `dist/*.deb` e seu SHA-256. Não exige root. Os pacotes e imagens de VM ficam fora do Git. Licença GPL-3.0-or-later. Os instaladores devem acompanhar as fontes correspondentes, avisos e checksums; veja [PUBLICACAO.md](PUBLICACAO.md).

## Validação

A validação de ciclo de vida usa VM descartável com imagem oficial Ubuntu 24.04 e systemd real, sem montar diretórios do host. O roteiro e as limitações estão em `scripts/validate_deb_vm.py`. A VM não reproduz os sensores físicos do PC: ela valida empacotamento e ciclo de vida, não compatibilidade com todas as GPUs/placas.

## Notas da candidata 0.8.0

A atualização invalida uma vez as sessões locais antigas e renova os arquivos de acesso dos usuários já autorizados. Abra novamente pelo menu. Isso corrige a abertura antiga que colocava o token local nos argumentos do navegador; não altera a chave da API nem o orçamento. O lançador depende de `python3-gi` (resolvido pelo APT), usa o navegador HTTP padrão e cria um arquivo privado de redirecionamento. Em Snap, o perfil do navegador precisa ter sido inicializado. Navegadores/ambientes ainda não testados devem ser tratados como suporte pendente.

O pacote inclui licença GPL, privacidade, política de segurança e inventário/avisos das dependências. Veja [as notas da prévia](releases/0.8.0.md) e [o escopo da verificação](PUBLICACAO.md).
