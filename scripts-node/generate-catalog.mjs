// Gera catalog.json com o catálogo completo, buscando do Apps Script
// UMA vez a partir do GitHub Actions (não do navegador de cada
// visitante). O site (database.js) passa a ler esse JSON estático
// primeiro, e só cai pro Apps Script ao vivo se o arquivo não existir
// ou estiver com erro — isso tira o Apps Script do caminho crítico de
// carregamento pra quem visita o site, resolvendo os timeouts sob
// tráfego alto.
//
// Uso: node scripts-node/generate-catalog.mjs
// Saída: ./catalog.json na raiz do repo (mesmo lugar servido pelo
// Neocities em https://rollcake.site/catalog.json)

const OWN_DB_API = "https://script.google.com/macros/s/AKfycbyWdEvWnYWBLS-HnHrJf-4rNsjEOYE08Bp1mVneIXMqPOO0g-28nCwLU70ltJFxNbDi/exec";
const PER_PAGE = 50;
const MAX_PAGES = 300;
const REQUEST_TIMEOUT_MS = 120000; // roda num servidor, sem pressa do usuário — pode ser mais folgado
const MAX_RETRIES_PER_PAGE = 3;

async function fetchPage(page) {
  const url = new URL(OWN_DB_API);
  url.searchParams.set("action", "catalog");
  url.searchParams.set("page", String(page));
  url.searchParams.set("perPage", String(PER_PAGE));

  let lastErr;
  for (let attempt = 0; attempt <= MAX_RETRIES_PER_PAGE; attempt++) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(url.toString(), { signal: controller.signal });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      clearTimeout(timeoutId);
      lastErr = err;
      console.warn(`  página ${page}: tentativa ${attempt + 1} falhou (${err.message}), tentando de novo...`);
      await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
    }
  }
  throw new Error(`página ${page} falhou depois de ${MAX_RETRIES_PER_PAGE + 1} tentativas: ${lastErr?.message}`);
}

async function main() {
  console.log("Buscando página 1 pra saber o total...");
  const first = await fetchPage(1);
  const rawMangas = [...(first.mangas || [])];
  const rawTotal = first.totalResults || 0;
  const totalPages = rawTotal ? Math.ceil(rawTotal / PER_PAGE) : (first.hasNextPage ? 2 : 1);
  console.log(`Total reportado: ${rawTotal} mangás em ${totalPages} páginas.`);

  for (let page = 2; page <= Math.min(totalPages, MAX_PAGES); page++) {
    console.log(`Buscando página ${page}/${totalPages}...`);
    const res = await fetchPage(page);
    rawMangas.push(...(res.mangas || []));
  }

  console.log(`Coletados ${rawMangas.length} registros brutos.`);

  const snapshot = {
    generatedAt: Date.now(),
    generatedAtIso: new Date().toISOString(),
    rawTotal,
    // guarda os registros CRUS (como o Apps Script devolve), sem
    // normalizar — o database.js já sabe normalizar/deduplicar/ordenar
    // isso do jeito que faz hoje com a resposta ao vivo, então não
    // duplicamos essa lógica aqui.
    mangas: rawMangas
  };

  const fs = await import("node:fs/promises");
  await fs.writeFile("catalog.json", JSON.stringify(snapshot), "utf-8");
  console.log(`catalog.json escrito com sucesso (${rawMangas.length} mangás).`);
}

main().catch(err => {
  console.error("Falha ao gerar catalog.json:", err);
  process.exit(1);
});
