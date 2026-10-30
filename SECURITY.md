# Segurança do Vatilume

Mantenedor: **APFS <contato@apfs.com.br>**. A versão desta prévia é 0.8.0; não há promessa de suporte indefinido a versões antigas. Correções verificadas serão documentadas com a versão e o escopo afetados.

## Relatar uma vulnerabilidade

Use o [canal privado do GitHub](https://github.com/Alexsander33set/vatilume/security/advisories/new) para relatar uma suspeita de falha de segurança. Entre em sua conta GitHub e preencha o relato privado; ele não abre uma issue pública. Se não conseguir usar esse canal, envie para **contato@apfs.com.br**. O recebimento nesse endereço foi confirmado por teste em 30/10/2026.

Inclua versão/pacote afetado, distribuição, passos sintéticos de reprodução, resultado esperado/observado e impacto possível. Não envie chave de API, cookie, arquivo de acesso, banco real ou backup. Não publique uma prova de exploração ou detalhes sensíveis em issues enquanto a correção é discutida.

Problemas de funcionamento e dúvidas de uso têm [formulários públicos próprios](https://github.com/Alexsander33set/vatilume/issues/new/choose); veja [SUPPORT.md](SUPPORT.md). O canal privado usa GitHub Private Vulnerability Reporting; [funcionamento do recurso](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

Não há programa de recompensa ou prazo de resposta garantido. Reportes serão triados conforme a disponibilidade do projeto. Combine divulgação responsável e evite coletar dados de terceiros para demonstrar um problema.

## Fronteiras de proteção

- Painel somente em loopback; não projetado para exposição pública, proxy remoto ou administração multiusuário pela rede.
- Autorização administrativa concede acesso ao mesmo estado do PC. Não há segregação entre usuários autorizados.
- Código do pacote pertence a root; o serviço usa uma conta própria sem login. Leitura de sensores/processos é limitada e depende das permissões reais do kernel.
- Abertura por arquivo privado evita colocar a credencial de sessão nos argumentos do navegador. O usuário do desktop, root e processos com privilégios equivalentes continuam sendo parte da fronteira de confiança.
- Cookie HttpOnly/SameSite Strict com validade máxima de 24 horas, verificação de Host/Origin, limites de corpo de requisição e CSP. Isso não protege contra comprometimento do navegador, extensão maliciosa ou administrador do computador.
- Chave de IA em arquivo 0600, sem criptografia própria; erros de validação não devem reproduzir a entrada. Perguntas são texto livre enviado à API: não incluir segredos.
- IA recebe ferramentas limitadas e fatos calculados. Não há shell/SQL livre nem autorização para alterar configuração por decisão do modelo. Texto de processos e perguntas deve ser tratado como dado não confiável, nunca instrução para ampliar privilégios.
- Reservas de orçamento são persistidas sob bloqueio; chamadas incertas mantêm a reserva. Preços locais podem envelhecer e não garantem igualdade com a fatura externa.

## Desenvolvimento e distribuição

Use fixtures sintéticas e API simulada no CI. Não desative autenticação, checagens de origem ou controles de gasto para fazer um teste passar. Não registre corpos de requisição ou cabeçalhos de autenticação.

O `.deb` inclui dependências travadas por versão/hash, runtime Python e interface; não baixa código de aplicação no pós-instalação. Dependências do sistema vêm do gerenciador de pacotes. Downloads de desenvolvimento vêm dos upstreams declarados nos lockfiles. Audite dependências e todo o histórico Git antes da publicação. Resultado sem advisories conhecidos não equivale a ausência de falhas.

Cada publicação binária deve incluir código-fonte correspondente, avisos de terceiros, inventário de dependências, instruções de build, checksums e origem do artefato. Um checksum sozinho não autentica o editor. Não se anuncia assinatura de pacote antes de definir e proteger a chave de distribuição.

Backups e diagnósticos locais podem conter credenciais e atividade. Veja [PRIVACY.md](PRIVACY.md). `purge` não elimina cópias externas ou backups.
