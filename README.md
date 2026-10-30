# Vatilume

**Energia e sinais do seu PC, com histórico e evidências.**

Vatilume acompanha energia reportada, uso, temperatura e processos ao longo do tempo. A interface local abre no navegador padrão e permite consultar o histórico, configurar a coleta e a tarifa de energia e investigar períodos com IA opcional.

**Estado:** prévia 0.8.0 para testes e uso inicial. Há um pacote `.deb` com runtime incluído para Ubuntu 24.04 amd64/Python 3.12; veja [instalação, preservação de dados e escopo dos testes](docs/PACOTE-DEB.md). A instalação pessoal anterior foi validada em Zorin OS 18.1, baseado em Ubuntu 24.04, x86_64. Isso não comprova suporte a todas as distribuições ou combinações de hardware. Flatpak e Windows não têm instalador.

## Direção do projeto

- Linux primeiro, começando por sistemas baseados em Debian/Ubuntu que possam ser testados.
- Coletor leve independente da interface, iniciado pelo sistema.
- Interface no navegador padrão, sem conta online obrigatória.
- Software livre e open source, gratuito, com apoio voluntário ao projeto.
- IA opcional com a chave do próprio usuário e controles de gasto locais. Outros provedores e modelos locais são evolução futura da interface.
- Código sob GPL-3.0-or-later: você pode usar, estudar, modificar e redistribuir conforme a licença.

Código sob **GPL-3.0-or-later**, mantido pela **APFS <contato@apfs.com.br>**. Veja [licença](LICENSE), [privacidade](PRIVACY.md), [segurança](SECURITY.md) e [avisos de terceiros](THIRD_PARTY_NOTICES.md). O apoio por Pix é voluntário; não há cobrança de assinatura ou recursos exclusivos para apoiadores. Veja [decisões e próximos passos](docs/DIRECAO.md).

## Apoie o Vatilume

O Vatilume é um projeto independente e gratuito. Se ele for útil para você e quiser contribuir com seu desenvolvimento, pode [apoiar via Pix pelo Nubank](https://nubank.com.br/cobrar/mr23i/6ae37aad-7e87-48e3-be17-f4153a29130a). O apoio é opcional e não desbloqueia funcionalidades. Os custos da IA, quando ativada com chave própria, são pagos diretamente ao provedor escolhido.

## Instalação por pacote

Baixe o instalador e `SHA256SUMS` da [prévia 0.8.0 em Releases](https://github.com/Alexsander33set/vatilume/releases/tag/v0.8.0). Suporte inicial: **Ubuntu 24.04 amd64**. Não é necessário ativar IA para usar a aplicação.

Na pasta dos arquivos baixados:

```sh
sha256sum --ignore-missing --check SHA256SUMS
sudo apt install ./vatilume_0.8.0-2_amd64.deb
vatilume
```

Confirme que o instalador aparece como `OK` antes de instalar. O checksum detecta alterações; esta prévia ainda não tem assinatura do editor. Veja [notas e limitações da 0.8.0](docs/releases/0.8.0.md).

Abra também pelo menu **Vatilume**. Dependências de runtime vêm no pacote; APT instala dependências do sistema. Não precisa de Docker, Node, pip ou conta online para usar o painel. O primeiro acesso requer autorização administrativa para consultar o histórico deste PC. `sudo apt remove vatilume` preserva dados e configurações; `sudo apt purge vatilume` apaga os dados gerenciados. Consulte [o procedimento completo](docs/PACOTE-DEB.md), incluindo atualização e a proteção contra sobrepor a instalação antiga em `/opt`.

Para a instalação de desenvolvimento 0.6.0 em `/opt`, use o [procedimento de migração com backup verificável e retorno automático](docs/MIGRACAO-DEB.md). Ele usa o pacote já validado e preserva o estado existente; a instalação normal do `.deb` continua recusando a sobreposição direta das unidades antigas.

## Em desenvolvimento

A próxima revisão 0.9.0 reúne correções de análises recentes, tempo observado para projeções, configurações de IA visíveis, diagnóstico, rede opcional e proteção de armazenamento. Veja [comportamento, limites e testes](docs/CONFIABILIDADE.md). A prévia disponível em Releases continua a 0.8.0.

## O que funciona

- Coleta Linux em background, cadências configuráveis e serviço systemd.
- Persistência SQLite WAL/FULL, detecção de interrupções e retomada da coleta.
- Histórico de potência, uso e temperatura, sensores e eventos.
- Configuração do coletor e tarifa manual com vigência.
- CPU/RSS por processo, agrupamento por aplicativo com regras de nome/parentesco e acesso aos membros originais.
- Projeção mensal condicional e análises com GPT-5.4 mini, usando fatos calculados e evidências consultáveis/CSV.
- Chave própria configurável na interface, prévia de gasto, limites por análise/dia/mês e acumulado. Instalações novas começam com IA desativada e teto acumulado zero; ativá-la exige escolha explícita do orçamento.

CPU/GPU são componentes reportados, **não uma medição do gabinete inteiro ou da tomada**. Lacunas não viram zero. Agrupamentos somam apenas os processos retidos; coincidência temporal não prova causa e não mede watts por aplicativo. A IA não recebe shell ou SQL livre e não altera o coletor por conta própria.

## Executar a partir do código

Requisitos do ambiente de desenvolvimento validado: Linux, Python 3.12, Node.js 24 e npm. O coletor usa biblioteca padrão; o painel e os testes web têm dependências separadas.

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
backend/.venv/bin/python -m unittest discover -s tests
```

Os testes usam dados sintéticos e transporte de IA simulado; não precisam de chave nem fazem chamadas pagas. O build da interface e os testes Python são executados pelo CI. Testes de navegador e medições no PC real têm preparação própria e não equivalem ao CI.

Para uma coleta de desenvolvimento isolada, revise `config/collector.toml` antes de executar:

```sh
python3 -m device_observability --config config/collector.toml run
```

### Instalação no sistema: procedimento de desenvolvimento

O instalador atual é destinado à preparação/desenvolvimento, com dependências offline previamente baixadas. Precisa de systemd, Python compatível, `uv` e permissão administrativa. Confira [operação do coletor](docs/COLETOR.md) e [interface](docs/INTERFACE.md). Ele não é apresentado como instalador universal para usuários finais.

Depois de compilar a interface, prepare os wheels para a plataforma/Python usados:

```sh
backend/.venv/bin/python -m pip download --require-hashes -r backend/requirements.lock -d scripts/wheels
python3 scripts/install_service.py --with-interface --check
sudo python3 scripts/install_service.py --with-interface --with-processes
```

O serviço instalado usa uma cópia protegida em `/opt`; editar o projeto não atualiza a instalação automaticamente. A instalação preserva histórico e configuração. A interface instalada abre pelo comando `vatilume` ou `./open-ui.sh`. No primeiro acesso de cada navegador, use o lançador para criar a sessão local privada.

## Privacidade e versionamento

Dados, bancos, credenciais, modelos, ambientes, builds, backups e relatórios pessoais ficam fora do Git. O repositório contém código, testes, configuração de exemplo e documentação compartilhável. A cópia remota do código não substitui o backup privado dos dados.

```sh
python3 scripts/check_repository.py
```

A checagem lê o índice Git, bloqueia caminhos privados e padrões de credenciais e compara os valores locais disponíveis sem imprimi-los. É complementar a scanners especializados e revisão humana, não uma auditoria completa.

## Ajuda e relatos

Para dificuldades de uso ou problemas, use os [formulários públicos de atendimento](https://github.com/Alexsander33set/vatilume/issues/new/choose). Consulte primeiro [a ajuda e o diagnóstico opcional](SUPPORT.md). Para suspeitas de vulnerabilidade, use o [canal privado de segurança](https://github.com/Alexsander33set/vatilume/security/advisories/new). Não publique credenciais ou dados pessoais.

## Documentação

- [Ajuda e relato de problemas](SUPPORT.md).
- [Notas da prévia 0.8.0](docs/releases/0.8.0.md).

- [Preparação para publicação](docs/PUBLICACAO.md).
- [Direção atual e distribuição Linux](docs/DIRECAO.md).
- [Coletor e recuperação](docs/COLETOR.md).
- [Interface local](docs/INTERFACE.md).
- [Processos e limites dos agrupamentos](docs/PROCESSOS.md).
- [IA, chave e controle de gasto](docs/IA-INTERFACE.md).
- [Identidade e pesquisa preliminar de marca](docs/IDENTIDADE.md).
- [Especificação original](docs/ESPECIFICACAO.md) e [plano](docs/PLANO.md), com notas de evolução.

Relatórios operacionais pessoais e o estudo financeiro anterior são mantidos localmente, fora do repositório. Não compartilhe bancos, arquivos de acesso ou backups como evidência pública.
