<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import type { Point } from '../types'
const props=defineProps<{points:Point[];kind:string}>()
const active=ref<number|null>(null)
const container=ref<HTMLElement>(), width=ref(960)
let observer:ResizeObserver|undefined
onMounted(()=>{observer=new ResizeObserver(entries=>{width.value=Math.max(300,entries[0]!.contentRect.width)});if(container.value)observer.observe(container.value)})
onBeforeUnmount(()=>observer?.disconnect())
const modes:Record<string,{keys:string[];labels:string[];unit:string}>={power:{keys:['cpu_w','gpu_w'],labels:['CPU','GPU'],unit:'W'},usage:{keys:['cpu_percent','gpu_percent'],labels:['CPU','GPU'],unit:'%'},temperature:{keys:['cpu_temp','gpu_temp'],labels:['CPU','GPU'],unit:'°C'}}
const mode=computed(()=>modes[props.kind]||modes.power)
const maximum=computed(()=>{const values=props.points.flatMap(p=>mode.value.keys.map(k=>valid(p[k])?p[k]:0));const top=Math.max(1,...values);return props.kind==='usage'?100:Math.ceil(top/10)*10})
const y=(v:number)=>224-(v/maximum.value)*194
const x=(index:number)=>45+index/Math.max(1,props.points.length-1)*(width.value-65)
const valid=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)
function geometry(key:string){
  const runs:number[][]=[]
  let run:number[]=[]
  for(let i=0;i<props.points.length;i++){
    if(valid(props.points[i]?.[key])){run.push(i)}else if(run.length){runs.push(run);run=[]}
  }
  if(run.length)runs.push(run)
  return {path:runs.filter(r=>r.length>1).map(r=>r.map((index,i)=>`${i?'L':'M'}${x(index).toFixed(2)},${y(props.points[index]![key]!).toFixed(2)}`).join(' ')).join(' '),isolated:runs.filter(r=>r.length===1).flat()}
}
const traces=computed(()=>mode.value.keys.map(geometry))
const any=computed(()=>props.points.some(p=>mode.value.keys.some(k=>valid(p[k]))))
const isolatedCount=computed(()=>traces.value.reduce((sum,trace)=>sum+trace.isolated.length,0))
watch(()=>[props.kind,props.points],()=>{active.value=null})
const selected=computed(()=>active.value===null?null:props.points[active.value])
const time=(value:number)=>new Intl.DateTimeFormat('pt-BR',{hour:'2-digit',minute:'2-digit',timeZone:'America/Sao_Paulo'}).format(value)
function move(event:MouseEvent){const b=(event.currentTarget as HTMLElement).getBoundingClientRect();active.value=Math.max(0,Math.min(props.points.length-1,Math.round((event.clientX-b.left-45)/(width.value-65)*(props.points.length-1))))}
function key(event:KeyboardEvent){if(props.points.length&&(event.key==='ArrowLeft'||event.key==='ArrowRight')){event.preventDefault();active.value=Math.max(0,Math.min(props.points.length-1,(active.value??0)+(event.key==='ArrowRight'?1:-1)))}if(event.key==='Escape')active.value=null}
</script>
<template><div ref="container" class="chart" tabindex="0" role="group" :aria-label="`Histórico de ${kind==='power'?'potência':kind==='usage'?'uso':'temperatura'}. Use as setas para explorar os valores.`" @mousemove="move" @mouseleave="active=null" @keydown="key">
<svg v-if="any" :viewBox="`0 0 ${width} 265`" role="img" :aria-label="`CPU e GPU em ${mode.unit}`"><g v-for="n in [0,1,2,3,4]" :key="n"><line x1="45" :x2="width-20" :y1="y(maximum*n/4)" :y2="y(maximum*n/4)" class="chart-grid"/><text x="36" :y="y(maximum*n/4)+4" text-anchor="end" class="chart-label">{{Math.round(maximum*n/4)}}</text></g><g v-for="(trace,i) in traces" :key="mode.keys[i]" :data-series="mode.keys[i]"><path :d="trace.path" fill="none" :class="i?'trace-gpu':'trace-cpu'" stroke-width="2.4" :stroke-dasharray="i?'6 3':undefined"/><circle v-for="index in trace.isolated" :key="index" :cx="x(index)" :cy="y(points[index]![mode.keys[i]!]!)" r="2.6" :class="['chart-reading',i?'point-gpu':'point-cpu']"/></g><text v-for="i in [0,Math.floor((points.length-1)/2),points.length-1]" :key="i" :x="x(i)" y="253" :text-anchor="i===0?'start':i===points.length-1?'end':'middle'" class="chart-label">{{time(points[i]!.time_ms)}}</text><g v-if="active!==null"><line :x1="x(active)" :x2="x(active)" y1="25" y2="224" class="chart-cursor"/><template v-for="(key,i) in mode.keys" :key="key"><circle v-if="valid(selected?.[key])" :cx="x(active)" :cy="y(selected![key]!)" r="4" :class="i?'point-gpu':'point-cpu'"/></template></g></svg>
<div v-else class="chart-empty">Não há leituras suficientes deste tipo no período selecionado.</div>
<div class="chart-caption" aria-live="polite"><span v-if="selected">{{time(selected.time_ms)}} <span v-for="(key,i) in mode.keys" :key="key"> · {{mode.labels[i]}} {{!valid(selected[key])?'sem leitura':selected[key]!.toLocaleString('pt-BR',{maximumFractionDigits:1})+' '+mode.unit}}</span></span><span v-else-if="isolatedCount">Pontos mostram leituras isoladas; intervalos sem dados ficam em branco. Use o cursor ou as setas para explorar.</span><span v-else>Explore o histórico com o cursor ou as setas do teclado.</span></div></div></template>
