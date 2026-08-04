const OWN_DB_API = "https://script.google.com/macros/s/AKfycbyWdEvWnYWBLS-HnHrJf-4rNsjEOYE08Bp1mVneIXMqPOO0g-28nCwLU70ltJFxNbDi/exec";
const PER_PAGE = 50;
const MAX_PAGES = 300;
const REQUEST_TIMEOUT_MS = 120000;
const MAX_RETRIES_PER_PAGE = 5;
const PAGE_DELAY_MS = 2000;

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

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
      const isTimeout = err.name === "AbortError";
      console.warn(`  página ${page}: tentativa ${attempt + 1} falhou (${isTimeout ? "TIMEOUT após " + REQUEST_TIMEOUT_MS + "ms" : err.message}), tentando de novo...`);
      await sleep(3000 * (attempt + 1));
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
    await sleep(PAGE_DELAY_MS);
  }
  console.log(`Coletados ${rawMangas.length} registros brutos.`);
  const snapshot = {
    generatedAt: Date.now(),
    generatedAtIso: new Date().toISOString(),
    rawTotal,
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
