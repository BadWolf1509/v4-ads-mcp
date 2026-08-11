/* Comportamento do painel V4.
 *
 * Existe pra que a CSP possa rodar sem `script-src 'unsafe-inline'`: todo
 * handler que antes vivia em atributo (onclick/oninput/onchange/hx-on) virou
 * listener delegado no document, acionado por atributos `data-v4-*`.
 *
 * Delegar tambem conserta uma classe de bug estrutural: fragmento devolvido
 * por rota HTMX nao precisa mais re-emitir o handler pra continuar funcionando
 * depois do swap (era o F74).
 *
 * Guard: tests/unit/test_frontend_a11y_guards.py falha se voltar atributo
 * inline em template, e se algum data-v4-action usado nao existir aqui.
 */

// ---------------------------------------------------------------- utilidades

function showToast(message, kind) {
  kind = kind || 'success';
  const region = document.getElementById('v4-toast-region');
  if (!region) return;
  const toast = document.createElement('div');
  toast.className = 'v4-toast v4-toast--' + kind;
  // Erro interrompe a leitura; sucesso entra na fila educada.
  toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  toast.textContent = message;
  region.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('is-leaving');
    setTimeout(() => toast.remove(), 200);
  }, 3500);
}

// API publica: openConfirm({ title, message, okLabel, kind, onConfirm })
function openConfirm(opts) {
  const dlg = document.getElementById('v4-confirm-dialog');
  if (!dlg) return;
  document.getElementById('v4-confirm-title').textContent = opts.title || 'Confirmar?';
  document.getElementById('v4-confirm-message').textContent = opts.message || '';
  const okBtn = dlg.querySelector('[data-confirm-ok]');
  okBtn.textContent = opts.okLabel || 'Confirmar';
  okBtn.className = 'v4-btn v4-btn--small v4-btn--' + (opts.kind || 'danger');
  okBtn.onclick = () => { dlg.close(); if (opts.onConfirm) opts.onConfirm(); };
  dlg.querySelector('[data-confirm-cancel]').onclick = () => dlg.close();
  dlg.showModal();
}

function v4DropdownToggle(id) {
  const dd = document.getElementById(id);
  if (!dd) return;
  const isOpen = dd.classList.toggle('is-open');
  dd.querySelector('.v4-dropdown__trigger').setAttribute('aria-expanded', String(isOpen));
  if (isOpen) {
    const closeOnOutside = (e) => {
      if (!dd.contains(e.target)) {
        dd.classList.remove('is-open');
        dd.querySelector('.v4-dropdown__trigger').setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', closeOnOutside);
      }
    };
    setTimeout(() => document.addEventListener('click', closeOnOutside), 0);
  }
}

function v4ToggleRow(rowId) {
  const row = document.getElementById(rowId);
  const detail = document.getElementById(rowId + '-detail');
  if (!row || !detail) return;
  row.classList.toggle('is-open');
  detail.classList.toggle('is-open');
  row.setAttribute('aria-expanded', String(row.classList.contains('is-open')));
}

function toggleDrawer() {
  const drawer = document.getElementById('mobile-drawer');
  if (!drawer) return;
  const isOpen = drawer.classList.toggle('is-open');
  drawer.setAttribute('aria-hidden', String(!isOpen));
  document.querySelector('.v4-header__hamburger')?.setAttribute('aria-expanded', String(isOpen));
  document.body.style.overflow = isOpen ? 'hidden' : '';
  // Contem o Tab: o resto da pagina fica inerte enquanto a gaveta esta aberta.
  for (const el of [document.querySelector('header'), document.querySelector('main'), document.querySelector('footer')]) {
    if (el) el.inert = isOpen;
  }
  if (isOpen) {
    window._v4DrawerReturnFocus = document.activeElement;
    document.querySelector('.v4-drawer__panel a, .v4-drawer__panel button')?.focus();
  } else {
    window._v4DrawerReturnFocus?.focus();
    window._v4DrawerReturnFocus = null;
  }
}

async function copiarTexto(el) {
  const origem = el.dataset.v4CopyFrom;
  const texto = origem
    ? (document.querySelector(origem)?.innerText ?? '')
    : (el.dataset.v4CopyText ?? '');
  try {
    await navigator.clipboard.writeText(texto);
  } catch {
    // Contexto inseguro ou permissao negada — avisa em vez de falhar calado.
    showToast('Não foi possível copiar. Selecione e copie manualmente.', 'error');
    return;
  }
  showToast(el.dataset.v4CopyToast || 'Copiado!', 'success');
  const rotulo = el.dataset.v4CopiedLabel;
  if (rotulo) {
    const original = el.textContent;
    el.textContent = rotulo;
    setTimeout(() => { el.textContent = original; }, 2000);
  }
}

// ------------------------------------------------------------------- filtros

/** Filtro de linhas de tabela por atributos data-* na <tr>.
 *  Controles: [data-v4-filter="<seletor da tabela>"] com
 *    - data-v4-filter-fields="a,b"  -> texto, casa substring em qualquer campo
 *    - data-v4-filter-field="x"     -> select, casa exato ("all" = sem filtro)
 */
function aplicarFiltroDeTabela(seletorTabela) {
  const tabela = document.querySelector(seletorTabela);
  if (!tabela) return;
  const controles = [...document.querySelectorAll(`[data-v4-filter="${seletorTabela}"]`)];
  for (const tr of tabela.querySelectorAll('tbody tr')) {
    const visivel = controles.every((c) => {
      const v = (c.value || '').toLowerCase().trim();
      if (c.dataset.v4FilterFields) {
        if (!v) return true;
        return c.dataset.v4FilterFields
          .split(',')
          .some((campo) => (tr.dataset[campo.trim()] || '').toLowerCase().includes(v));
      }
      const campo = c.dataset.v4FilterField;
      return !campo || v === 'all' || (tr.dataset[campo] || '') === c.value;
    });
    tr.style.display = visivel ? '' : 'none';
  }
}

/** Matriz de acessos: filtra COLUNAS por gestor e LINHAS por conta.
 *  Estrutura distinta o bastante da tabela simples pra ter caminho proprio. */
function aplicarFiltroDaMatriz() {
  const gestor = (document.querySelector('[data-v4-matrix-filter="manager"]')?.value || '').toLowerCase();
  const conta = (document.querySelector('[data-v4-matrix-filter="account"]')?.value || '').toLowerCase();

  document.querySelectorAll('th[data-manager-email]').forEach((th) => {
    const visivel = !gestor || th.dataset.managerEmail.includes(gestor);
    th.style.display = visivel ? '' : 'none';
    const col = Array.from(th.parentNode.children).indexOf(th);
    document.querySelectorAll('tbody tr').forEach((tr) => {
      const cell = tr.children[col];
      if (cell) cell.style.display = visivel ? '' : 'none';
    });
  });

  document.querySelectorAll('tbody tr[data-account-name]').forEach((tr) => {
    const visivel = !conta
      || tr.dataset.accountName.includes(conta)
      || tr.dataset.accountId.includes(conta);
    tr.style.display = visivel ? '' : 'none';
  });
}

// -------------------------------------------------- despacho de acoes (click)

const ACOES = {
  'drawer-toggle': () => toggleDrawer(),
  'dropdown-toggle': (el) => v4DropdownToggle(el.dataset.v4Target),
  // Link ou botao dentro da linha (ex.: "Detalhe") navega em vez de expandir —
  // substitui o antigo onclick="event.stopPropagation()" no proprio link.
  'row-toggle': (el, e) => {
    if (e && e.target.closest('a, button')) return;
    v4ToggleRow(el.dataset.v4Target);
  },
  'dialog-open': (el) => document.getElementById(el.dataset.v4Target)?.showModal(),
  'dialog-close': (el) => document.getElementById(el.dataset.v4Target)?.close(),
  copy: (el) => copiarTexto(el),
  confirm: (el) => openConfirm({
    title: el.dataset.v4ConfirmTitle,
    message: el.dataset.v4ConfirmMessage,
    okLabel: el.dataset.v4ConfirmOk,
    kind: el.dataset.v4ConfirmKind || 'danger',
    onConfirm: () => {
      // F75: o `target` do htmx.ajax resolve via querySelector — nada de
      // "closest tr" aqui. Sem alvo, swap:"none".
      const opts = { swap: el.dataset.v4Swap || 'none' };
      if (el.dataset.v4Target) opts.target = el.dataset.v4Target;
      const req = htmx.ajax('POST', el.dataset.v4Post, opts);
      if (el.dataset.v4Reload !== undefined) req.then(() => window.location.reload());
    },
  }),
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-v4-action]');
  if (!el) return;
  const acao = ACOES[el.dataset.v4Action];
  if (acao) acao(el, e);
});

// Linha expansivel tambem responde a teclado (Enter/Espaco).
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const el = e.target.closest?.('[data-v4-action="row-toggle"]');
  if (!el) return;
  e.preventDefault();
  v4ToggleRow(el.dataset.v4Target);
});

// ------------------------------------------------ despacho de input / change

function aoFiltrar(e) {
  const el = e.target;
  if (el.dataset?.v4Filter) aplicarFiltroDeTabela(el.dataset.v4Filter);
  if (el.dataset?.v4MatrixFilter) aplicarFiltroDaMatriz();
}
document.addEventListener('input', aoFiltrar);
document.addEventListener('change', (e) => {
  aoFiltrar(e);
  if (e.target.dataset?.v4Autosubmit !== undefined) e.target.form?.submit();
});

// Envio unico: desabilita o botao DEPOIS que o submit valido saiu.
document.addEventListener('submit', (e) => {
  if (e.target.dataset?.v4SubmitOnce === undefined) return;
  const btn = e.target.querySelector('button[type=submit]');
  if (btn) setTimeout(() => { btn.disabled = true; }, 0);
});

// Voltar pelo historico (bfcache) reabilita botoes travados pelo submit-once.
window.addEventListener('pageshow', (e) => {
  if (!e.persisted) return;
  document.querySelectorAll('form button[type=submit][disabled]').forEach((b) => { b.disabled = false; });
});

// Escape fecha a gaveta.
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const drawer = document.getElementById('mobile-drawer');
  if (drawer?.classList.contains('is-open')) toggleDrawer();
});

// ------------------------------------------------------------- ganchos HTMX

document.addEventListener('DOMContentLoaded', () => {
  // HX-Trigger: {"toast": {"message": "...", "kind": "success"}}
  document.body.addEventListener('toast', (e) => showToast(e.detail.message, e.detail.kind));
  // Requisicao que falha (4xx/5xx/rede) nao morre calada.
  document.body.addEventListener('htmx:responseError', () => showToast('Erro na requisição — a ação pode não ter sido aplicada.', 'error'));
  document.body.addEventListener('htmx:sendError', () => showToast('Falha de rede — a ação não foi aplicada.', 'error'));

  // Checkbox da matriz de acessos: toast no sucesso, reverte no erro.
  // Delegado de proposito — o fragmento de reposicao servido pela rota nao
  // precisa carregar handler nenhum pra continuar funcionando (F74).
  document.body.addEventListener('htmx:afterRequest', (e) => {
    const el = e.target;
    if (!el.matches?.('[data-v4-access-toggle]')) return;
    if (e.detail.successful) {
      showToast(el.checked ? 'Acesso liberado' : 'Acesso revogado', 'success');
    } else {
      el.checked = !el.checked;
    }
  });
});

// ------------------------------------- medicao da barra de filtros (sticky)

// Offset sticky = altura MEDIDA, nao estimada (licao do F79). A barra de
// filtros da auditoria embrulha conforme a largura (medido: 88px a partir de
// 831px, 164px a partir de 618px, 240px abaixo), e os cabecalhos de dia grudam
// logo abaixo dela. Como os pontos de quebra emergem da largura do conteudo —
// nao de breakpoints padrao — nem literal nem media query acerta em toda
// janela. Sem JS o valor estatico de v4-tokens.css vale como fallback.
(function () {
  const barra = document.querySelector('[data-sticky-measure]');
  if (!barra || typeof ResizeObserver === 'undefined') return;
  let ultimo = null;
  const publicar = () => {
    // Barra nao-sticky (max-sm:static no celular) nao empurra nada abaixo.
    const empilha = getComputedStyle(barra).position === 'sticky';
    const altura = empilha ? Math.round(barra.getBoundingClientRect().height) : 0;
    if (altura === ultimo) return;
    ultimo = altura;
    document.documentElement.style.setProperty('--v4-filter-bar-h', altura + 'px');
  };
  // O observer pega mudanca de ALTURA (embrulho). O listener de resize pega a
  // mudanca de POSITION no breakpoint, que pode ocorrer sem mudar altura — e
  // evita duplicar o valor do breakpoint aqui no JS. Ambos saem cedo quando
  // nada mudou, entao o custo e duas leituras por evento.
  new ResizeObserver(publicar).observe(barra);
  window.addEventListener('resize', publicar, { passive: true });
  publicar();
})();
