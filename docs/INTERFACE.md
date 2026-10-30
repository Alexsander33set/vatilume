# Vatilume · Interface local 0.6.0

Vue/TypeScript compilado em `backend/static`, servido por FastAPI/Uvicorn. A interface lê o banco de telemetria em modo somente leitura e mantém tarifas/auditoria em `interface.sqlite3`, separado do histórico bruto. A página [Análises com IA](IA-INTERFACE.md) usa o mini quando solicitada, com orçamento e evidências validadas; abrir o painel não chama modelos.

## Instalar ou atualizar

Depois de preparar o build e as dependências opcionais locais:

```sh
sudo python3 scripts/install_service.py --with-interface
```

O instalador preserva a configuração existente, faz backup consistente da telemetria antes de atualizar, cria um ambiente Python separado com dependências travadas e verificadas por hash, atualiza o coletor e habilita o socket HTTP local. As dependências são instaladas a partir de wheels já preparados; a instalação administrativa não consulta PyPI.

```sh
vatilume
# Compatibilidade com instalações anteriores:
./open-ui.sh
```

O navegador abre a interface usando o acesso privado salvo em `var/interface-access.url` (permissão 0600, pertencente ao usuário que instalou). O segredo fica no fragmento inicial, é trocado por uma sessão HttpOnly/SameSite Strict e removido do endereço pelo frontend. Não compartilhe esse arquivo/link como se fosse um endereço público.

Abrir apenas `http://127.0.0.1:8765` funciona quando esse navegador já tem uma sessão válida. No primeiro acesso, use o lançador. Nenhuma conta ou senha adicional é criada. O acesso é restrito ao loopback, com validação de origem/host para as operações da API.

O comando `vatilume` é instalado para o proprietário em `~/.local/bin`, que já está no PATH deste PC. Pode ser usado de qualquer pasta, sem editar `.zshrc` e sem criar um serviço extra. `vatilume --browser firefox` escolhe outro navegador registrado; `vatilume --version` mostra a versão do lançador; `vatilume --check` confere o arquivo privado e a disponibilidade HTTP da interface, sem abrir o navegador ou enviar a chave. Essa checagem não substitui a validação da sessão autenticada. O instalador recusa sobrescrever um comando existente que não tenha sido criado por ele. Se mover a pasta do projeto, execute `python3 scripts/install_launcher.py` na nova pasta.

O navegador do Codex e o navegador padrão do desktop mantêm sessões independentes. Execute `./open-ui.sh` no seu terminal para conectar o navegador padrão (neste PC, o desktop informa `zen.desktop`). Sessões duram até 24 horas; navegação privada, limpeza de cookies e outro perfil exigem abrir novamente pelo lançador. Use o endereço `127.0.0.1` do lançador: cookies de `localhost` não são os mesmos. A porta não aceita acesso pela rede local ou por outro dispositivo. O botão de verificar sessão apenas consulta uma sessão existente; ele não lê o arquivo privado do PC nem cria autorização sozinho.

Se quiser outro navegador registrado, use por exemplo `./open-ui.sh --browser firefox` (se instalado). O lançador precisa rodar na sessão gráfica do computador e informa falha quando não consegue abrir o navegador. Não cole o link privado em conversas ou relatórios.

## Telas

- **Resumo:** filtros de 1 h, 6 h, 24 h, 7 dias, 30 dias ou datas personalizadas; energia, custo e tempo coberto separados por CPU/GPU; histórico de potência, uso ou temperatura; leituras recentes e eventos.
- **Sensores:** busca, filtro por grupo, valor convertido ou bruto, unidade, domínio, qualidade e instante da última leitura no período.
- **Eventos:** inicializações, encerramentos, recuperação, configuração, suspensão estimada, relógio e falhas, com detalhes técnicos expansíveis.
- **Configurações:** intervalos, grupos habilitados, confirmação de aplicação e tarifas por data de vigência.

Informações adicionais ficam em ícones acionáveis por foco, hover ou clique; Escape fecha. Os gráficos podem ser explorados com as setas. Uma leitura isolada é desenhada como ponto, inclusive quando a cadência térmica deixa intervalos vazios entre as amostras. Linhas unem apenas intervalos consecutivos com dados; os espaços não são interpolados. A busca de sensores tem somente a borda externa e o foco de teclado aparece no contorno do grupo. Layout e navegação foram preparados para desktop, tablet e celular. A atualização automática ocorre a cada 30 s quando a página está visível e não há formulário com alterações não salvas.

## Configuração do coletor

O backend roda com a mesma conta dedicada do coletor, sem root. Grava somente os campos permitidos em `/var/lib/device-observability/collector-overrides.json`, de forma atômica e sincronizada, e envia SIGHUP ao processo cuja identidade/boot foram verificados. A configuração de instalação em `/etc` e o destino do banco não são editáveis pela interface.

O coletor valida o documento, mantém a última configuração válida em execução e publica o hash aplicado. A interface distingue salvar de aplicar; em caso de falha de sinalização, a configuração anterior é restaurada. A revisão do formulário evita sobrescrever alterações de outra sessão. O override persiste após reinicialização.

## Energia e custo

CPU usa o delta do contador acumulado do pacote. `core` não é somado ao pacote. GPU usa integração trapezoidal da potência reportada. Duração monotônica determina energia; UTC localiza os intervalos na janela e nas tarifas. Sessões diferentes, suspensão, saltos relevantes de relógio, leituras inválidas e lacunas longas interrompem a integração.

O alcance do contador e um limite técnico amplo de plausibilidade (2.000 W para rejeitar deltas ambíguos da CPU) evitam interpretar múltiplos rollovers como energia válida. Esse limite não estima o consumo do PC; intervalos muito longos podem resultar em energia indisponível. Os dados brutos continuam preservados.

Não há soma apresentada como consumo total do gabinete. Valores de energia sem intervalos suficientes ficam ausentes. Custos sem tarifa ficam ausentes. Custos de períodos parcialmente tarifados são identificados como parciais. Uma tarifa nova vale a partir de meia-noite da data escolhida, no fuso de São Paulo; intervalos que cruzam a vigência são divididos. Corrigir uma tarifa na mesma data gera auditoria e recálculo, sem alterar leituras.

O CSV contém as médias por intervalo usadas nos gráficos, até 240 pontos, com instantes UTC em milissegundos e unidades nos nomes das colunas. Não é uma exportação integral das leituras brutas.

## Recursos e operação

`device-observability-web.socket` escuta em `127.0.0.1:8765`. O backend inicia no primeiro acesso e encerra após 10 minutos sem solicitações. O socket permite uma nova ativação depois. O coletor permanece independente da interface, do ambiente opcional e da internet.

```sh
systemctl status device-observability-web.socket
systemctl status device-observability-web.service
journalctl -u device-observability-web.service -n 50 --no-pager
```

As consultas usam snapshot consistente, agregação com memória limitada, cache de quatro janelas e prazo de 25 s. Há limite de 31 dias/400 mil ciclos por consulta; o usuário precisa reduzir o período se o limite for excedido, sem truncamento silencioso. Janelas muito grandes ainda devem ser medidas após acumular histórico real; agregados persistentes/retention continuam para outra etapa.

## Desenvolvimento e verificações

```sh
UV_CACHE_DIR=/tmp/device-observability-uv uv venv --python /usr/bin/python3 backend/.venv
UV_CACHE_DIR=/tmp/device-observability-uv uv pip sync --python backend/.venv/bin/python backend/requirements.lock
cd frontend
npm ci --cache /tmp/device-observability-npm
npm run build
```

O build executa TypeScript/Vue antes do Vite. Para testar a API, instalar `httpx2` apenas no ambiente de desenvolvimento e executar `backend/.venv/bin/python -m unittest discover -s tests -v` a partir da raiz. Os testes de navegador em `frontend/tests` são restritos ao backend descartável em `127.0.0.1:8766`, separado do banco/conta/tarifa reais.

Estimativa total do gabinete, obtenção automática de preço efetivo de contratos com distribuidoras/gestoras, novos sensores e agregação persistente não fazem parte desta entrega. A IA consulta somente os dados existentes e não muda o coletor.

## Processos

A página Processos abre agrupada por aplicativo, com nomes amigáveis por regras locais de nome/parentesco e detalhes expansíveis dos membros. Processos técnicos mantém a leitura individual. Desconhecidos não são agrupados apenas pelo nome genérico; somas cobrem só membros retidos. Compara CPU/RSS retidos com os maiores intervalos médios de potência/uso. Configurações permite ativar/desativar o grupo, ajustar a cadência e o tamanho do ranking. A coleta é optativa; o passado não é reconstruído. [Método, privacidade e verificação](PROCESSOS.md).
