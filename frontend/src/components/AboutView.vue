<script setup lang="ts">
import { ExternalLink, ShieldCheck, KeyRound, Scale } from '@lucide/vue'
defineProps<{version?:string}>()
</script>

<template>
<div class="about-layout">
  <section class="settings-section">
    <div class="section-heading"><h2>Vatilume</h2><span class="section-meta">v{{ version || '—' }} · APFS</span></div>
    <p>Energia e sinais do seu PC, com histórico e evidências. As leituras dos componentes não medem o consumo total na tomada.</p>
    <div class="about-fact"><ShieldCheck :size="20"/><div><h3>Histórico neste computador</h3><p>Sem conta online ou telemetria automática para o projeto. Nomes de processos e horários podem revelar sua atividade. Em PCs compartilhados, usuários autorizados veem o mesmo histórico.</p></div></div>
    <div class="about-fact"><KeyRound :size="20"/><div><h3>IA é opcional</h3><p>Coleta e cálculos funcionam sem IA. Ao pedir uma análise, sua pergunta e recortes de métricas vão diretamente à OpenAI, com sua chave e seus limites de gasto. Não inclua informações pessoais ou segredos na pergunta.</p></div></div>
    <details><summary>Armazenamento e remoção</summary><p>O histórico não tem expiração automática. A chave fica em arquivo local privado, sem criptografia própria. Administradores do PC podem acessá-la. Remover o pacote preserva os dados; purgar apaga o estado gerenciado, mas não apaga backups, exportações ou registros do provedor de IA.</p></details>
    <a class="text-button about-link" href="/legal/privacy" target="_blank" rel="noopener">Ler aviso de privacidade completo<ExternalLink :size="14"/></a>
  </section>
  <section class="settings-section">
    <div class="section-heading"><Scale :size="19"/><h2>Software livre</h2></div>
    <p>Copyright © 2026 APFS. Vatilume é distribuído sob GNU GPL versão 3 ou, à sua escolha, qualquer versão posterior. Você pode estudar, modificar e redistribuir o programa nos termos da licença.</p>
    <p>Sem garantia, inclusive de comercialização ou adequação a uma finalidade específica, na extensão permitida pela legislação aplicável. As dependências mantêm suas próprias licenças.</p>
    <div class="about-links"><a href="/legal/license" target="_blank" rel="noopener">Licença GPL-3.0</a><a href="/legal/third-party" target="_blank" rel="noopener">Avisos de terceiros</a><a href="/legal/security" target="_blank" rel="noopener">Segurança</a></div>
    <p class="field-hint">Contato: <a href="mailto:contato@apfs.com.br">contato@apfs.com.br</a>. Não envie chaves, bancos ou backups.</p>
    <p class="field-hint">Código e fontes da versão distribuída devem acompanhar a publicação do pacote. Enquanto esta prévia estiver privada, solicite acesso ao mantenedor.</p>
  </section>
</div>
</template>

<style scoped>
.about-layout{max-width:880px;display:grid;gap:28px}.about-layout p{line-height:1.7}.about-fact{display:flex;gap:14px;margin:26px 0}.about-fact>svg{flex:none;margin-top:3px;color:var(--primary)}.about-fact h3{margin:0 0 6px}.about-fact p{margin:0}.about-link{margin-top:18px}.about-links{display:flex;gap:20px;flex-wrap:wrap;margin:22px 0}.about-layout details p{max-width:75ch}
</style>
