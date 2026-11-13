const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/pagamentos_lote.js', 'utf8');
class Element {
  constructor() { this.events={}; this.dataset={}; this.disabled=false; this.checked=false; this.textContent=''; this.children=[]; }
  addEventListener(name, fn) { this.events[name]=fn; }
  appendChild(item) { this.children.push(item); }
  replaceChildren() { this.children=[]; }
  close() {}
}
async function run({decisions=[], amounts=['100.00','200.00'], duplicateIds=[], conflict=false, stopReview=false, network=false}) {
  const ids=['lote-contas','lote-form','lote-om','lote-busca','lote-enviar','lote-progresso','lote-repeticao','lote-marcar','lote-limpar','lote-selecao','lote-repeticao-conta','lote-repeticoes'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
  const rows=amounts.map((valor,i)=>{
    const r=new Element(); r.dataset={contaId:String(i+1),numero:'CP-'+(i+1),data:'2026-11-13',valor};
    r.check=new Element();r.check.checked=true;r.result=new Element();
    r.querySelector=selector=>selector==='.lote-check'?r.check:r.result;
    return r;
  });
  const buttons=['parar','pular','vincular'].map(value=>{const e=new Element();e.dataset.decisao=value;return e;});
  const calls=[], prompts=[];
  elements['lote-contas'].dataset={verificar:'/contas/0/duplicidades',vincular:'/contas/0/vincular'};
  elements['lote-contas'].querySelectorAll=()=>rows;
  elements['lote-form'].querySelectorAll=()=>[...rows.map(r=>r.check),elements['lote-om'],elements['lote-enviar']];
  elements['lote-om'].options=['','OM'];elements['lote-om'].value='3';
  elements['lote-repeticao'].querySelectorAll=()=>buttons;
  elements['lote-repeticao'].showModal=()=>{
    prompts.push({posts:calls.filter(c=>c.post).length, details:elements['lote-repeticoes'].children.map(x=>x.textContent)});
    const decision=decisions.shift();assert.ok(decision,'Unexpected repetition prompt');
    queueMicrotask(()=>buttons.find(b=>b.dataset.decisao===decision).events.click());
  };
  const duplicate={numero_om:'OM-8',numero_linha:1,data:'13/11/2026',valor:'100.00',descricao:'Anterior'};
  let conflicted=false;
  const context={document:{getElementById:id=>elements[id],querySelector:()=>({content:'csrf-test'}),createElement:()=>new Element()},
    window:{addEventListener(){}},URLSearchParams, console, fetch:async(url,options)=>{
      const id=Number(url.split('/')[2]);const post=options.method==='POST';
      calls.push({id,post,confirmation:options.body?.get('confirmar_duplicidade')});
      if (post) assert.equal(options.body.get('csrf_token'),'csrf-test');
      if(post && network) throw Error('Falha de conexão');
      let status=200,data=post?{status:'vinculada'}:{duplicidades:duplicateIds.includes(id)?[duplicate]:[]};
      if (post && conflict && !conflicted) { conflicted=true;status=409;data={status:'duplicidade',duplicidades:[duplicate]}; }
      return {ok:status===200,status,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data};
    }};
  vm.runInNewContext(source,context);
  await elements['lote-form'].events.submit({preventDefault(){}});
  return {calls,prompts,rows,message:elements['lote-progresso'].textContent,disabled:elements['lote-enviar'].disabled};
}
(async()=>{
  let r=await run({duplicateIds:[1],decisions:['pular']});
  assert.deepEqual(r.calls.map(x=>[x.id,x.post]),[[1,false],[2,false],[2,true]]);
  assert.equal(r.prompts[0].posts,0);assert.match(r.message,/1 vinculada.*1 pulada/);
  r=await run({amounts:['100.00','100.00'],decisions:['vincular']});
  assert.match(r.prompts[0].details[0],/mesma data e valor/);
  assert.deepEqual(r.calls.filter(x=>x.post).map(x=>x.confirmation),['0','1']);
  assert.equal(r.prompts[0].posts,0);assert.match(r.message,/2 vinculada/);
  r=await run({duplicateIds:[1],decisions:['parar']});
  assert.equal(r.calls.filter(x=>x.post).length,0);assert.equal(r.disabled,false);
  r=await run({conflict:true,decisions:['pular']});
  assert.match(r.message,/1 vinculada.*1 pulada/);
  r=await run({network:true});
  assert.equal(r.calls.filter(x=>x.post).length,1);assert.match(r.message,/interrompido/);
  assert.equal(r.disabled,false);
  console.log('5 cenários de revisão e envio em lote passaram.');
})().catch(error=>{ console.error(error);process.exitCode=1; });
