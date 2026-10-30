<script setup lang="ts">
import {ref,onMounted} from 'vue'
import type {AISettings,AILimits} from '../ai-types'
const state=ref<AISettings|null>(null),key=ref(''),model=ref(''),total=ref(0),busy=ref(false),message=ref(''),error=ref('')
const limits=ref<AILimits>({enabled:false,per_analysis_usd:.05,daily_usd:1,monthly_usd:2})
async function api<T>(path:string,options:RequestInit={}):Promise<T>{const response=await fetch(path,{...options,headers:{'Content-Type':'application/json'}});const body=await response.json();if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Revise os campos e tente novamente.');return body}
async function load(keepDraft=false){state.value=await api<AISettings>('/api/ai/settings');if(!keepDraft){limits.value={...state.value.limits};total.value=state.value.authorized_total_usd;model.value=state.value.model}}
async function act(task:()=>Promise<unknown>,success:string){busy.value=true;error.value='';message.value='';try{await task();if(success)message.value=success}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
async function saveKey(){await act(async()=>{await api('/api/ai/key',{method:'PUT',body:JSON.stringify({key:key.value})});key.value='';await load(true)},'Chave salva no arquivo privado do serviço. O navegador não pode recuperá-la.')}
async function removeKey(){await act(async()=>{await api('/api/ai/key',{method:'DELETE'});key.value='';limits.value.enabled=false;await load(true)},'Chave removida e novas chamadas pausadas. Revogue-a no provedor se necessário; backups podem conter cópias.')}
async function check(){await act(async()=>{const result=await api<{message:string}>('/api/ai/key/check',{method:'POST'});message.value=result.message},'');}
async function save(){await act(async()=>{await api('/api/ai/model',{method:'PUT',body:JSON.stringify({model:model.value})});await api('/api/ai/settings',{method:'PUT',body:JSON.stringify({...limits.value,authorized_total_usd:total.value})});await load()},'Modelo e limites salvos. O histórico de gastos foi preservado.')}
onMounted(()=>act(load,''))
</script>
<template>
<section class="settings-section ai-settings" aria-labelledby="ai-settings-title">
<h2 id="ai-settings-title" tabindex="-1">Inteligência artificial</h2>
<p class="muted">Opcional e sob demanda. A coleta não usa IA automaticamente. Sua pergunta e os recortes necessários são enviados à OpenAI somente ao aprovar uma análise.</p>
<p v-if="error" role="alert" class="banner error">{{error}}</p><p v-if="message" role="status" class="banner success">{{message}}</p>
<template v-if="state">
<h3>Chave da API</h3><p>{{state.key_configured?'Chave configurada neste PC.':'Nenhuma chave configurada.'}}</p>
<form @submit.prevent="saveKey"><label>Nova chave OpenAI<input v-model="key" type="password" autocomplete="new-password" spellcheck="false" minlength="10" maxlength="1024" required></label><div class="form-footer"><button class="button" :disabled="busy||!key">Salvar chave</button><button type="button" class="button" :disabled="busy||!state.key_configured" @click="check">Verificar acesso</button></div></form>
<button v-if="state.key_configured" class="text-button" :disabled="busy" @click="removeKey">Remover chave e pausar chamadas</button>
<p class="field-hint">Verificar acesso consulta a disponibilidade do modelo sem gerar análise. Não confirma créditos. A chave não volta na resposta da aplicação e não é salva no armazenamento do navegador.</p>
<form @submit.prevent="save">
<label for="ai-selected-model">Modelo</label><select id="ai-selected-model" v-model="model"><option v-for="item in state.models" :key="item.id" :value="item.id">{{item.label}} · entrada US$ {{item.input}} / saída US$ {{item.output}} por milhão de tokens</option></select>
<p class="field-hint">A mesma chave pode atender aos modelos liberados no seu projeto OpenAI. Sem troca automática de modelo. Estimativas usam margem conservadora para gravação de cache nos modelos GPT-6; a fatura do provedor prevalece.</p>
<label class="check-row"><input v-model="limits.enabled" type="checkbox">Permitir análises solicitadas por mim</label>
<label>Limite acumulado (US$)<input v-model.number="total" type="number" min="0" max="1000" step=".001" required></label>
<label>Por análise (US$)<input v-model.number="limits.per_analysis_usd" type="number" min=".001" max="5" step=".001" required></label>
<label>Por dia (US$)<input v-model.number="limits.daily_usd" type="number" min=".001" max="1000" step=".001" required></label>
<label>Por mês (US$)<input v-model.number="limits.monthly_usd" type="number" min=".001" max="1000" step=".001" required></label>
<p class="field-hint">Gasto acumulado estimado: US$ {{state.usage.total_usd.toFixed(4)}}. Alterar limites não apaga gastos nem reservas incertas. Estes limites cobrem somente esta instalação.</p>
<button class="button primary" :disabled="busy">Salvar modelo e limites</button>
</form></template>
</section>
</template>
