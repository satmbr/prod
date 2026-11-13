(() => {
  'use strict';
  const root = document.getElementById('lote-contas');
  if (!root) return;
  const form = document.getElementById('lote-form');
  const om = document.getElementById('lote-om');
  const busca = document.getElementById('lote-busca');
  const enviar = document.getElementById('lote-enviar');
  const progresso = document.getElementById('lote-progresso');
  const dialog = document.getElementById('lote-repeticao');
  const linhas = [...root.querySelectorAll('tr[data-conta-id]')];
  const check = row => row.querySelector('.lote-check');
  const resultado = (row, value) => { row.querySelector('.lote-resultado').textContent = value; };
  const selecionadas = () => linhas.filter(row => check(row).checked && row.dataset.concluida !== '1');
  const contador = () => { document.getElementById('lote-selecao').textContent = selecionadas().length + ' selecionada(s)'; };
  let ocupado = false;
  let resolver = null;
  const bloquear = value => {
    ocupado = value;
    form.querySelectorAll('input,select,button').forEach(el => { el.disabled = value; });
    linhas.filter(row => row.dataset.concluida === '1').forEach(row => { check(row).disabled = true; });
    enviar.disabled = value || om.options.length < 2 || !linhas.length;
  };
  busca.addEventListener('input', () => {
    const termo = busca.value.trim().toLocaleLowerCase('pt-BR');
    linhas.forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase('pt-BR').includes(termo); });
  });
  document.getElementById('lote-marcar').addEventListener('click', () => {
    linhas.filter(row => !row.hidden && !check(row).disabled).forEach(row => { check(row).checked = true; }); contador();
  });
  document.getElementById('lote-limpar').addEventListener('click', () => {
    linhas.forEach(row => { check(row).checked = false; }); contador();
  });
  form.addEventListener('change', contador);
  window.addEventListener('beforeunload', event => { if (ocupado) { event.preventDefault(); event.returnValue = ''; } });
  function decidir(value) {
    if (!resolver) return;
    const resolve = resolver; resolver = null; dialog.close(); resolve(value);
  }
  dialog.querySelectorAll('[data-decisao]').forEach(button => button.addEventListener('click', () => decidir(button.dataset.decisao)));
  dialog.addEventListener('cancel', event => { event.preventDefault(); decidir('parar'); });
  function revisar(row, duplicidades, anteriores = []) {
    document.getElementById('lote-repeticao-conta').textContent = 'Conta ' + row.dataset.numero + ' · ' + row.dataset.data + ' · R$ ' + row.dataset.valor.replace('.', ',');
    const lista = document.getElementById('lote-repeticoes'); lista.replaceChildren();
    duplicidades.forEach(item => {
      const li = document.createElement('li');
      li.textContent = 'OM ' + item.numero_om + ' · linha ' + item.numero_linha + ' · ' + item.data + ' · R$ ' + item.valor.replace('.', ',') + ' · ' + item.descricao;
      lista.appendChild(li);
    });
    anteriores.forEach(other => {
      const li = document.createElement('li'); li.textContent = 'Conta ' + other.dataset.numero + ' também selecionada neste lote, com a mesma data e valor.'; lista.appendChild(li);
    });
    dialog.showModal();
    return new Promise(resolve => { resolver = resolve; });
  }
  async function consultar(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', ...options, headers: {'Accept':'application/json', ...options.headers}});
    if (response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) {
      throw new Error('A sessão expirou ou o servidor não confirmou a operação. Atualize a página para conferir as vinculações antes de tentar novamente.');
    }
    const dados = await response.json();
    return {response, dados};
  }
  const endpoint = (base, row) => base.replace('/0/', '/' + row.dataset.contaId + '/');
  const chave = row => row.dataset.data + '|' + Number(row.dataset.valor).toFixed(2);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (ocupado) return;
    const lote = selecionadas();
    if (!om.value || !lote.length) { progresso.textContent = 'Selecione uma OM e pelo menos uma conta.'; return; }
    const omId = om.value;
    const aceitas = [];
    let vinculadas = 0, puladas = 0, erros = 0;
    bloquear(true);
    try {
      // Review every selected row before starting any writes.
      for (const [indice, row] of lote.entries()) {
        progresso.textContent = 'Revisando ' + (indice + 1) + ' de ' + lote.length + ': ' + row.dataset.numero;
        const {response, dados} = await consultar(endpoint(root.dataset.verificar, row));
        if (!response.ok) throw new Error('Não foi possível verificar a conta ' + row.dataset.numero + '. Nenhuma vinculação deste lote foi iniciada.');
        const anteriores = aceitas.map(item => item.row).filter(other => chave(other) === chave(row));
        let confirmar = false;
        if (dados.duplicidades.length || anteriores.length) {
          const decisao = await revisar(row, dados.duplicidades, anteriores);
          if (decisao === 'parar') { progresso.textContent = 'Revisão interrompida. Nenhuma conta deste lote foi vinculada.'; return; }
          if (decisao === 'pular') { puladas++; check(row).checked = false; resultado(row, 'Pulada por você'); continue; }
          confirmar = true;
        }
        aceitas.push({row, confirmar}); resultado(row, 'Revisada; aguardando envio');
      }
      for (const [indice, item] of aceitas.entries()) {
        const row = item.row;
        progresso.textContent = 'Vinculando ' + (indice + 1) + ' de ' + aceitas.length + ': ' + row.dataset.numero;
        // Revalidation on the server can discover a duplicate created after review.
        while (true) {
          const body = new URLSearchParams({om_id:omId, confirmar_duplicidade:item.confirmar ? '1' : '0', csrf_token:document.querySelector('meta[name="csrf-token"]').content});
          const {response, dados} = await consultar(endpoint(root.dataset.vincular, row), {method:'POST', body});
          if (response.status === 409 && dados.status === 'duplicidade') {
            const decisao = await revisar(row, dados.duplicidades);
            if (decisao === 'parar') throw new Error('Envio interrompido por você. As vinculações concluídas foram mantidas.');
            if (decisao === 'pular') { puladas++; check(row).checked = false; resultado(row, 'Pulada por você'); break; }
            item.confirmar = true; continue;
          }
          if (!response.ok || dados.status !== 'vinculada') {
            erros++; resultado(row, dados.mensagem || 'Falha na vinculação'); break;
          }
          vinculadas++; row.dataset.concluida = '1'; check(row).checked = false;
          resultado(row, 'Vinculada à OM selecionada'); break;
        }
      }
      progresso.textContent = 'Lote concluído: ' + vinculadas + ' vinculada(s), ' + puladas + ' pulada(s), ' + erros + ' com erro. Confira o resultado de cada linha.';
    } catch (erro) {
      progresso.textContent = 'Processamento interrompido. ' + vinculadas + ' vinculação(ões) confirmada(s). ' + erro.message + ' Em caso de falha de conexão, confira o painel antes de reenviar.';
    } finally { bloquear(false); contador(); }
  });
})();
