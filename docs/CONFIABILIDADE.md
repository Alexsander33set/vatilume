# Coleta, armazenamento e IA na 0.9.0

Esta revisão está em preparação. A prévia publicada permanece a 0.8.0 até uma nova publicação explícita.

## Tempo observado e projeção

A prévia da IA usa, por padrão, a média de tempo diário observado pelo coletor nos últimos 30 dias até o fim da janela escolhida. Conta intervalos contínuos válidos, inclusive baixo uso; exclui suspensão, saltos de relógio, sessões diferentes e lacunas grandes. Não representa presença do usuário. Dias sem leituras são desconhecidos, e não dias comprovadamente desligados.

Quando existem dias completos, a média exclui o primeiro dia registrado e o dia corrente. Na base inicial, usa dias parciais e avisa que a rotina pode estar subestimada. Nenhum uso antes da instalação é inventado. O cálculo lê somente horários, sessões e configuração de cadência; não precisa carregar os valores de todos os sensores.

Você pode escolher “Informar horas por dia”. Uma duração numérica explícita na pergunta, como “18 horas diárias”, prevalece sobre a escolha da interface. A prévia mostra a premissa usada antes de qualquer inferência paga. Energia por hora vem da janela de carga selecionada; as horas diárias vêm do histórico mais longo. Ambas as bases podem ser insuficientes para representar uma rotina.

A projeção continua sendo um cenário de 30 dias, por componente, com tarifa manual. Não é a fatura medida, nem consumo na tomada. O tempo ocioso continua consumindo energia e entra no tempo observado. Uma baixa utilização não comprova ausência do usuário, e coincidência de processo com pico não comprova causa.

## Domínios de energia

O pacote de CPU não é somado a seus subdomínios. Leituras AMD reconhecidas como SoC podem incluir CPU e GPU, portanto ficam separadas nos sensores e não entram como GPU independente. A tabela factual de PCI IDs foi extraída dos registros explícitos do driver amdgpu em uma revisão fixa do Linux, identificada no módulo `amd_domains.py`; entradas genéricas de descoberta de IP foram excluídas. IDs desconhecidos permanecem desconhecidos.

Identificadores novos que incluem o tipo PCI iniciam uma série de energia própria. Leituras antigas continuam disponíveis e os gráficos brutos preservam o local físico, mas o cálculo não une contadores/fontes nem promove domínios antigos desconhecidos. Ao selecionar uma janela que cruza a atualização, a cobertura energética da GPU pode inicialmente ser menor.

Uma GPU sem domínio confirmado pode ter seu próprio cálculo parcial, mas não é somada à CPU. Múltiplas GPUs/fontes ambíguas não são escolhidas alfabeticamente. A interface avisa; as leituras brutas continuam consultáveis. Isso prioriza evitar dupla contagem. Não afirma calibragem do sensor ou suporte universal, especialmente para novos notebooks/GPUs.

## Rede opcional

Ative “Rede (contadores por interface)” em Configurações → Coletor. O adaptador lê apenas bytes recebidos/enviados em `/proc/net/dev`, em varredura limitada. Não captura pacotes, sites, IPs, MACs, SSIDs, dispositivos remotos ou conteúdo. Não sonda a rede nem executa mudanças no sistema. Os valores aparecem em Sensores; são contadores cumulativos, não uma medição de energia.

O nome da interface identifica a interface local naquele momento; não autentica um dispositivo físico. Renomeações, reinícios e interfaces virtuais podem alterar a identidade ou reiniciar contadores. Tráfego pode aparecer em mais de uma interface, por isso não há soma automática como total independente. A coleta continua separada de qualquer controle de hardware.

## Armazenamento e limpeza

A cota padrão é **2 GiB** de estado local gerenciado. Há aviso a partir de 80% e bloqueio antecipado de novas gravações para preservar o que já foi confirmado. Instalações novas também reservam 256 MiB livres no disco; valores explícitos anteriores são mantidos. A cota pode ser ajustada em Configurações.

A limpeza automática vem **desativada**. Para preservar todo o histórico, mantenha assim: ao atingir a cota, a coleta fica degradada até liberar espaço ou aumentar a cota. Dados não gravados durante esse bloqueio podem se perder; o buffer é limitado. Há diagnóstico e indicação de falha, sem repetição ilimitada em memória.

Ao escolher retenção, você autoriza excluir leituras antigas. O prazo é um máximo: sob pressão de cota, leituras podem ser excluídas antes para abrir espaço. A manutenção trabalha em lotes de até 1.000 linhas por minuto e mantém as duas amostras mais recentes; não há parada longa para compactar toda a base. Páginas SQLite livres são reutilizadas, portanto o arquivo físico pode não diminuir. Há também um limite de páginas no banco de telemetria. A cota não é uma partição rígida: transações, arquivos temporários, WAL e pequenas alterações de estado podem ocupar margem adicional.

Tarifas, chave, limites/gastos de IA, relatórios e backups não são apagados pela retenção. O CSV bruto de um relatório pode expirar, com explicação ao tentar baixá-lo; evidências calculadas já salvas continuam no relatório. Ainda não há agregação permanente de longo prazo: escolha a retenção conforme o histórico bruto que quer manter. Backups externos, exportações e logs do sistema ficam fora da cota e precisam de gestão própria.

## IA em Configurações

Chave, modelo, pausa e limites ficam em **Configurações → Inteligência artificial**. A tela de análises mantém um atalho e o resumo de gasto. Não há análise automática, agendada ou causada pelo simples uso da interface.

Há três modelos explícitos suportados: GPT-5.4 mini (padrão), GPT-6 Luna e GPT-6.1 Terra. A mesma chave OpenAI pode ser usada se o projeto tiver acesso ao modelo. O modelo escolhido fica congelado com a prévia; não existe fallback silencioso, troca automática de provedor ou reinício de orçamento. Outros provedores e IA local na interface continuam fora desta revisão.

As referências de preços são das páginas oficiais de [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra) e [mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini), consultadas em 30/10/2026. Estimativas usam entrada sem desconto; nos GPT-6, a margem de entrada considera gravação de cache de 30 minutos. Isso pode superestimar o custo. Preços incorporados precisam de revisão quando o provedor os alterar; a fatura externa prevalece.

“Verificar acesso” faz uma consulta autenticada à disponibilidade do modelo. Não gera uma análise, não confirma créditos nem liberação de faturamento. Erros distinguem autenticação, permissão/modelo, saldo/limite, indisponibilidade e conexão. Mensagens brutas do provedor não são devolvidas ao navegador. Remover a chave pausa novas chamadas; não revoga a credencial externa nem remove backups.

## Comparação reproduzível

`scripts/compare_models.py` mostra o plano sem fazer chamadas. Com `--apply`, exige o terminal do administrador somente para preparar um diretório privado e assumir a conta do serviço; abandona os privilégios antes de importar a aplicação/acessar a API. O ensaio usa quatro casos sintéticos, três repetições e os três modelos, girando a ordem. Mede conclusão sob o contrato de evidências, latência e custo estimado. A avaliação semântica das respostas exige revisão humana; uma taxa de conclusão isolada não prova melhor qualidade.

O ensaio compartilha chave, trava de análise e registro de gastos da instalação; não cria orçamento paralelo. Há teto adicional fixo de US$ 0,30 e todos os limites menores existentes continuam valendo. Não há repetição automática de chamadas incertas. O relatório fica em diretório privado em `/var/tmp`, cujo caminho é mostrado ao final, sem chave. O coletor continua funcionando.

## Diagnóstico e suporte

Configurações → Diagnóstico verifica coleta recente, confirmação da configuração, espaço/cota e presença da chave. É uma verificação local e não um monitoramento remoto. Para erros do instalador, veja [instalação e recuperação](PACOTE-DEB.md) e [formulários de suporte](https://github.com/Alexsander33set/vatilume/issues/new/choose). Nenhum relatório é enviado automaticamente.

Ao pedir suporte, inclua versão, distribuição, hardware relevante, passos para reproduzir e mensagem visível. Nunca publique chave, URL de acesso privado, cookie, banco ou backup. Use o relato privado de vulnerabilidade para problemas de segurança.
