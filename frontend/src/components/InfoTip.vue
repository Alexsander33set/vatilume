<script setup lang="ts">
import { ref, useId, onBeforeUnmount } from 'vue'
import { Info } from '@lucide/vue'
defineProps<{ label: string }>()
const id = useId(), open = ref(false), pinned = ref(false), trigger = ref<HTMLButtonElement>(), position = ref({left:'0px',top:'0px'})
function show() {
  if (trigger.value) {
    const b=trigger.value.getBoundingClientRect()
    position.value={left:Math.max(12,Math.min(b.left-120,window.innerWidth-312))+'px',top:Math.max(12,Math.min(b.bottom+10,window.innerHeight-205))+'px'}
  }
  open.value=true
}
function hide() {if(!pinned.value)open.value=false}
function toggle(){pinned.value=!pinned.value;if(pinned.value)show();else open.value=false}
function escape(e:KeyboardEvent){if(e.key==='Escape'){open.value=false;pinned.value=false}}
window.addEventListener('keydown',escape)
onBeforeUnmount(()=>window.removeEventListener('keydown',escape))
</script>
<template><span class="info-wrap"><button ref="trigger" type="button" class="info-button" :aria-label="label" :aria-expanded="open" :aria-describedby="open?id:undefined" @mouseenter="show" @mouseleave="hide" @focus="show" @blur="pinned=false;open=false" @click="toggle"><Info :size="15" aria-hidden="true"/></button><Teleport to="body"><div v-if="open" :id="id" role="tooltip" class="info-popover" :style="position"><slot/></div></Teleport></span></template>
