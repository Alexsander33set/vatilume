import {test,expect} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'

test.beforeEach(async({context})=>{
  const token=readFileSync(resolve('../var/validation/ui-data/interface-token'),'utf8').trim()
  expect((await context.request.post('/api/session',{headers:{Origin:'http://127.0.0.1:8766',Authorization:`Bearer ${token}`}})).ok()).toBeTruthy()
})

test('history and new questions do not mix or let a late response overwrite selection',async({page})=>{
  const fixture=JSON.parse(readFileSync(resolve('../var/validation/process-ui-fixture.json'),'utf8')).record
  const first={...fixture,id:'history-first',question:'Pergunta antiga A'}
  const second={...fixture,id:'history-second',question:'Pergunta antiga B'}
  await page.route('**/api/ai/analyses',route=>route.fulfill({json:{analyses:[first,second]}}))
  await page.route('**/api/ai/analyses/history-first',async route=>{await new Promise(resolve=>setTimeout(resolve,700));await route.fulfill({json:first})})
  await page.route('**/api/ai/analyses/history-second',route=>route.fulfill({json:second}))
  await page.goto('/?view=ai')
  await page.locator('.ai-history-item').first().click()
  await page.locator('.ai-history-item').nth(1).click()
  await expect(page.locator('.ai-answered-question')).toHaveText('Pergunta antiga B')
  await page.waitForTimeout(900)
  await expect(page.locator('.ai-answered-question')).toHaveText('Pergunta antiga B')
  await page.getByLabel('O que você quer investigar?',{exact:true}).fill('Pergunta nova sobre custo mensal de energia')
  await expect(page.locator('.ai-result')).toHaveCount(0)
  await expect(page.locator('.ai-evidence-area')).toHaveCount(0)
  await page.getByRole('button',{name:'Preparar análise',exact:true}).click()
  await expect(page.getByRole('region',{name:'Prévia da análise'})).toBeVisible()
  await expect(page.getByRole('region',{name:'Prévia da análise'})).toContainText('conforme tempo observado pelo coletor')
  await page.getByRole('button',{name:'Nova pergunta',exact:true}).click()
  await expect(page.getByLabel('O que você quer investigar?',{exact:true})).toBeEmpty()
  await expect(page.getByRole('region',{name:'Prévia da análise'})).toHaveCount(0)
})

test('AI settings, storage safety and network choice are discoverable and accessible',async({page})=>{
  await page.goto('/?view=settings')
  await page.getByRole('link',{name:'IA: chave e gastos',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Inteligência artificial',exact:true})).toBeFocused()
  await expect(page.getByRole('heading',{name:'Inteligência artificial',exact:true})).toBeVisible()
  await expect(page.getByLabel('Nova chave OpenAI')).toHaveValue('')
  await expect(page.getByLabel('Modelo',{exact:true})).toHaveValue('gpt-5.4-mini-2026-03-17')
  await expect(page.getByLabel('Modelo',{exact:true}).locator('option')).toHaveCount(3)
  await expect(page.getByLabel('Limpeza automática')).toHaveValue('0')
  await expect(page.getByLabel('Cota de dados locais (GiB)')).toHaveValue('2')
  await expect(page.getByLabel('Rede (contadores por interface)',{exact:true})).not.toBeChecked()
  await expect(page.getByRole('heading',{name:'Diagnóstico',exact:true})).toBeVisible()
  await expect(page.getByText('Nenhum diagnóstico é enviado automaticamente.',{exact:false})).toBeVisible()
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBeFalsy()
    const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()
    expect(audit.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))).toEqual([])
    await page.screenshot({path:test.info().outputPath(`settings-${width}.png`),fullPage:true})
  }
})

test('storage pressure is visible outside settings without deleting data',async({page})=>{
  await page.route('**/api/status',async route=>{const response=await route.fetch();const body=await response.json();await route.fulfill({response,json:{...body,storage:{warning:true,blocked:true,limit_bytes:2*1024**3,active_bytes:2*1024**3,free_bytes:1024**3}}})})
  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('limitando novas gravações')
  await page.getByRole('button',{name:'Ver armazenamento',exact:true}).click()
  await expect(page.getByLabel('Limpeza automática')).toHaveValue('0')
})
