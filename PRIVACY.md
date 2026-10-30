# Privacidade no Vatilume

Responsável pelo projeto: **APFS**, contato **contato@apfs.com.br**. Este aviso descreve a distribuição local para Linux; serviços externos mantêm seus próprios termos. Revisão: 30/10/2026.

## O que fica no computador

O coletor registra leituras disponíveis de energia, potência, utilização, memória, temperatura e ventoinhas; horários, intervalos sem coleta, eventos de recuperação e configurações. Registra também modelo de CPU, arquitetura, versão do kernel, identificador aleatório persistente da instalação e identificadores de boot/sessão. Sensores disponíveis variam com hardware, drivers e permissões.

Quando a coleta de processos está habilitada, registra uma seleção limitada de nomes de processos, PID, parentesco, CPU e memória RSS, além de agrupamentos de aplicativos. Não coleta argumentos completos de execução, ambiente, conteúdo de arquivos, títulos de janelas, teclas digitadas, histórico de navegação, MAC ou número de série. Os nomes e horários registrados ainda podem revelar hábitos e atividade. Agrupamentos são parciais, não medem energia por aplicativo e não provam causalidade.

Quando habilitada, a coleta opcional de rede registra nome da interface local e contadores de bytes recebidos/enviados. Não identifica dispositivos remotos nem registra endereços IP, MAC, SSID, pacotes ou conteúdo de tráfego.

Contadores gravados em versões anteriores no grupo Sistema permanecem no histórico. A partir desta revisão, novas leituras de rede dependem de habilitar o grupo Rede.

Tarifas, perguntas, respostas de IA, evidências, custos e ajustes ficam em bancos/arquivos locais. A coleta continua com o painel fechado. A cota padrão limita novas gravações perto de 2 GiB. A limpeza automática vem desativada; se você habilitar retenção nas configurações, leituras antigas podem expirar pelo prazo escolhido ou antes para respeitar a cota. Relatórios, chave e gastos não são apagados por essa limpeza; exportações brutas antigas podem deixar de estar disponíveis. O programa não envia telemetria, relatórios de falha ou métricas automaticamente à APFS, nem exige conta no projeto.

## IA e envio opcional

Sem ativar IA, coleta, gráficos, tarifas e projeções calculadas localmente continuam funcionando. A interface atualmente integra a API OpenAI, por HTTPS, diretamente do computador, sem servidor intermediário do projeto.

Ao solicitar uma análise, a pergunta é enviada **como escrita**, junto com instruções de análise, métricas agregadas do período, horários, fatos calculados e resultados das consultas limitadas solicitadas pelo modelo. Na parte de processos enviada ao modelo, nomes de aplicativos são substituídos por aliases; os detalhes originais permanecem no PC. Não há envio automático de inventário completo, nomes/PIDs dos processos ou bancos. Isso reduz a exposição, mas **não garante anonimato**: horários, métricas e o texto livre podem identificar pessoas. Não inclua informações pessoais ou segredos na pergunta.

“Verificar acesso” consulta a disponibilidade do modelo no provedor sem gerar análise. Não confirma saldo ou faturamento. Essa consulta envia a chave por autenticação e o identificador do modelo; não envia recortes de métricas.

A chave é enviada ao provedor no cabeçalho de autenticação, não como evidência no prompt. O provedor recebe também metadados de conexão e da conta, como IP e uso para faturamento. A APFS não recebe sua chave, sua pergunta ou a resposta automaticamente.

As chamadas usam `store: false`. Segundo a [documentação da OpenAI](https://developers.openai.com/api/docs/guides/your-data), dados da API não são usados para treinar modelos por padrão, salvo adesão explícita; registros de monitoramento de abuso podem ser retidos por até 30 dias, com exceções previstas pelo provedor. `store: false` não equivale a Zero Data Retention. Verifique os termos, a localização de processamento, as condições da sua conta e as políticas vigentes antes de usar. Remover dados locais não apaga registros externos.

## Chaves, acesso e PC compartilhado

Na instalação `.deb`, o estado reside em `/var/lib/device-observability`; configuração base em `/etc/device-observability/collector.toml`; autorizações locais em `/var/lib/vatilume-access`. A chave da API fica em arquivo privado (modo 0600) da conta do serviço, **sem criptografia própria**. Não protege contra administrador/root, malware com privilégios suficientes ou acesso à conta do serviço. Backups completos também podem conter a chave.

O painel escuta somente em loopback (`127.0.0.1`) e usa autorização local e cookie de sessão de até 24 horas. O lançador prepara um arquivo de redirecionamento privado para abrir o navegador. O endereço sozinho não concede acesso; não compartilhe arquivos de acesso, cookies ou capturas que os revelem. Em navegadores Snap, o arquivo fica na área privada do perfil; em outros casos, no diretório temporário da sessão do usuário. Ele pode permanecer até o fim da sessão/perfil e deve ser protegido como credencial.

O administrador autoriza usuários do desktop a abrir o painel. Usuários autorizados do mesmo PC acessam o mesmo histórico, configurações e orçamento: esta versão **não separa contas individuais ou ambientes empresariais**. Outros programas executados com o mesmo usuário do desktop podem ler seus arquivos privados de abertura. Não exponha a porta na rede, não use proxy público e não amplie permissões para contornar erros.

## Controle, exportação e exclusão

Você pode alterar cadências, desabilitar grupos de coleta, consultar/exportar períodos, remover a chave e pausar análises. Limites de gasto são locais, baseados na tabela de preços incorporada e no uso reportado; não substituem os controles e a fatura do provedor. O limite acumulado de instalações novas começa em zero e precisa ser escolhido explicitamente.

`apt remove vatilume` preserva os dados e a configuração. `apt purge vatilume` apaga o estado gerenciado e a configuração do pacote. **Purge não apaga** backups em `/var/backups/vatilume`, cópias em outros diretórios, arquivos de exportação, histórico/cache do navegador, arquivos de desenvolvimento/instalações antigas nem registros do provedor de IA. Revogue a chave no provedor quando necessário. Faça um backup privado antes de excluir histórico que queira preservar.

## Suporte, código e apoio voluntário

Mensagens enviadas voluntariamente a contato@apfs.com.br são tratadas pela APFS para responder e investigar a solicitação. Envie somente dados necessários; prefira exemplos sintéticos. Não envie bancos, backups ou credenciais. Não há integração que extraia essas mensagens ou apague automaticamente cópias de e-mail: pedidos de acesso, correção ou exclusão devem ser dirigidos ao contato acima, sujeitos a obrigações legais aplicáveis.

GitHub, OpenAI e Nubank são serviços externos com políticas próprias. Issues públicas tornam seu conteúdo público; o pagamento de apoio por Pix é voluntário e pode informar ao recebedor dados da transação exigidos pelo sistema financeiro. Não há publicidade ou venda de dados pelo programa. A ausência de servidor próprio não elimina responsabilidades sobre dados recebidos em suporte ou apoio.

## Uso responsável

Use em computadores próprios ou onde tenha autorização. Monitoramento de terceiros, de ambientes de trabalho ou de dispositivos compartilhados requer avaliação específica de transparência, finalidade, base legal e direitos dos titulares. Este aviso não certifica conformidade automática com a LGPD para qualquer cenário.
