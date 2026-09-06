/* Download multiplo dentro il browser interno delle app su iPhone.
 *
 * Sette scenari, uno per contesto: desktop, Android, Safari iOS, Chrome iOS
 * (devono restare com'erano), Instagram e Facebook su iOS (devono passare dal
 * riquadro nuovo), piu' il download di una foto sola e la condivisione
 * /fs/{token}.
 *
 * Si usa WebKit quando c'e' (e' il motore vero di iOS); altrimenti Chromium,
 * che per questa logica — riconoscimento del contesto e percorso del
 * riquadro — si comporta allo stesso modo, essendo tutta roba JavaScript.
 */
const { webkit, chromium } = require("playwright");

const BASE = process.env.PC_BASE || "https://photocarcifo.ch";
const ALBUM = process.env.PC_ALBUM ||
  "/n/raduno-zona-industriale-castione-06-09-2026";

const UA = {
  desktop: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 " +
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
  android: "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36",
  androidInstagram: "Mozilla/5.0 (Linux; Android 15; 22081212UG) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Version/4.0 Chrome/152.0.7977.69 Mobile Safari/537.36 " +
    "Instagram 445.0.0.45.83 Android",
  safariIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) " +
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.6 Mobile/15E148 Safari/604.1",
  chromeIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) " +
    "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/152.0.0.0 Mobile/15E148 Safari/604.1",
  instagramIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_6_1 like Mac OS X) " +
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/23G83 " +
    "Instagram 445.0.0.34.44 (iPhone16,1; iOS 26_6_1; it_IT; it; scale=3.00; " +
    "1179x2556; IABMV/1; 1053791553) Safari/604.1",
  facebookIos: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) " +
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/22H352 " +
    "[FBAN/FBIOS;FBAV/500.0.0.35.107;FBBV/1;FBDV/iPhone14,5]",
};

const esiti = [];
function verifica(nome, atteso, ottenuto) {
  const ok = atteso === ottenuto;
  esiti.push({ nome, ok, atteso, ottenuto });
  console.log(`${ok ? "PASS" : "FAIL"}  ${nome}` +
    (ok ? "" : `\n        atteso=${atteso} ottenuto=${ottenuto}`));
}

/* Il pannello di condivisione non esiste su un server Linux: lo si finge,
   perche' il punto del test e' il percorso della pagina, non l'API di Apple.
   Con condivisibile=false si controlla il ripiego (istruzioni per Safari). */
function finteApiCondivisione(condivisibile) {
  return `
    window.__condiviso = null;
    navigator.canShare = function (d) { return ${condivisibile} && !!(d && d.files); };
    navigator.share = function (d) {
      window.__condiviso = d.files.map(function (f) {
        return { nome: f.name, byte: f.size, tipo: f.type };
      });
      return Promise.resolve();
    };`;
}

/* L'avviso sui cookie coprirebbe i bottoni: si arriva con il consenso gia'
   dato, come chi ha gia' visitato il sito una volta. */
async function nuovoContesto(browser, ua, viewport, initScript) {
  const context = await browser.newContext({
    userAgent: ua,
    viewport: viewport || { width: 390, height: 844 },
    acceptDownloads: true,
  });
  await context.addCookies([{
    name: "pc_cookie_ok", value: "1", url: BASE,
  }]);
  if (initScript) await context.addInitScript(initScript);
  return context;
}

async function apri(browser, ua, viewport, initScript) {
  const context = await nuovoContesto(browser, ua, viewport, initScript);
  const page = await context.newPage();
  await page.goto(BASE + ALBUM, { waitUntil: "domcontentloaded" });
  return { context, page };
}

/* Entra in modalita' selezione e sceglie n fotografie. La barra dei bottoni
   e' appiccicata in alto e coprirebbe le prime celle: si manda il click
   direttamente all'elemento, che e' quello che il sito ascolta. */
async function selezionaFoto(page, n) {
  await page.click("#selMode");
  const celle = page.locator(".photo-grid .photo");
  await celle.first().waitFor({ timeout: 15000 });
  for (let i = 0; i < n; i++) await celle.nth(i).dispatchEvent("click");
}

async function caso1_desktop(browser) {
  const { context, page } = await apri(browser, UA.desktop, { width: 1280, height: 800 });
  const limitata = await page.evaluate(() => {
    const ua = navigator.userAgent;
    return /iPhone|iPad|iPod/.test(ua) && !/Version\/|CriOS|FxiOS|EdgiOS|OPiOS/.test(ua);
  });
  verifica("CASO 1 desktop: nessun percorso webview", false, limitata);
  await selezionaFoto(page, 2);
  const scarico = page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
  await page.click("#dlSel");
  const d = await scarico;
  verifica("CASO 1 desktop: il download parte come sempre", true, d !== null);
  verifica("CASO 1 desktop: nessun riquadro iOS", 0,
    await page.locator(".iosdl").count());
  await context.close();
}

async function caso2_android(browser) {
  for (const [nome, ua] of [["Android", UA.android], ["Android+Instagram", UA.androidInstagram]]) {
    const { context, page } = await apri(browser, ua);
    await selezionaFoto(page, 2);
    const scarico = page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
    await page.click("#dlSel");
    const d = await scarico;
    verifica(`CASO 2 ${nome}: download normale, nessun riquadro`, true,
      d !== null && (await page.locator(".iosdl").count()) === 0);
    await context.close();
  }
}

async function caso3_safariIos(browser) {
  for (const [nome, ua] of [["Safari iOS", UA.safariIos], ["Chrome iOS", UA.chromeIos]]) {
    const { context, page } = await apri(browser, ua);
    await selezionaFoto(page, 2);
    const scarico = page.waitForEvent("download", { timeout: 15000 }).catch(() => null);
    await page.click("#dlSel");
    const d = await scarico;
    verifica(`CASO 3 ${nome}: download normale, nessun riquadro`, true,
      d !== null && (await page.locator(".iosdl").count()) === 0);
    await context.close();
  }
}

async function caso4_instagramIos(browser) {
  // Con il pannello di condivisione disponibile: due tocchi, poi i file
  // arrivano davvero al pannello.
  const { context, page } = await apri(browser, UA.instagramIos, null,
    finteApiCondivisione(true));
  await selezionaFoto(page, 2);
  await page.click("#dlSel");
  await page.waitForSelector(".iosdl", { timeout: 10000 });
  verifica("CASO 4 Instagram iOS: compare il riquadro", 1,
    await page.locator(".iosdl").count());
  verifica("CASO 4 Instagram iOS: riquadro accessibile (dialog+etichetta)", true,
    (await page.getAttribute(".iosdl", "role")) === "dialog" &&
    (await page.getAttribute(".iosdl", "aria-modal")) === "true" &&
    !!(await page.getAttribute(".iosdl", "aria-labelledby")));
  const salva = page.locator(".iosdl-azioni .btn-accent");
  await salva.waitFor({ state: "visible", timeout: 60000 });
  await salva.click();
  await page.waitForFunction(() => window.__condiviso !== null, { timeout: 20000 });
  const condiviso = await page.evaluate(() => window.__condiviso);
  verifica("CASO 4 Instagram iOS: un archivio consegnato al pannello", 1,
    condiviso ? condiviso.length : 0);
  verifica("CASO 4 Instagram iOS: l'archivio non e' vuoto", true,
    !!condiviso && condiviso[0].byte > 0);
  console.log("        file condiviso:", JSON.stringify(condiviso));
  await context.close();

  // Senza pannello di condivisione: deve arrivare alle istruzioni, non a un
  // errore generico.
  const b = await apri(browser, UA.instagramIos, null, finteApiCondivisione(false));
  await selezionaFoto(b.page, 2);
  await b.page.click("#dlSel");
  await b.page.waitForSelector(".iosdl", { timeout: 10000 });
  const salva2 = b.page.locator(".iosdl-azioni .btn-accent");
  await salva2.waitFor({ state: "visible", timeout: 60000 });
  await salva2.click();
  await b.page.waitForFunction(() => {
    const t = document.querySelector(".iosdl-testo");
    return t && /Safari/i.test(t.textContent);
  }, { timeout: 15000 }).catch(() => {});
  const testo = await b.page.textContent(".iosdl-testo");
  const bottoni = await b.page.locator(".iosdl-azioni .btn").allTextContents();
  verifica("CASO 4 senza pannello: istruzioni per Safari", true, /Safari/i.test(testo));
  verifica("CASO 4 senza pannello: tre azioni (Safari, copia, annulla)", 3, bottoni.length);
  console.log("        azioni:", JSON.stringify(bottoni));
  await b.context.close();
}

async function caso5_facebookIos(browser) {
  const { context, page } = await apri(browser, UA.facebookIos, null,
    finteApiCondivisione(true));
  await selezionaFoto(page, 2);
  await page.click("#dlSel");
  await page.waitForSelector(".iosdl", { timeout: 10000 });
  verifica("CASO 5 Facebook iOS: riconosciuto come webview", 1,
    await page.locator(".iosdl").count());
  const titolo = await page.textContent(".iosdl-titolo");
  await context.close();
  console.log("        titolo iniziale:", JSON.stringify(titolo));
}

async function caso6_downloadSingolo(browser) {
  // Fuori dalle webview: il click nativo, invariato.
  const { context, page } = await apri(browser, UA.safariIos);
  await page.locator(".photo").first().dispatchEvent("click");
  await page.waitForSelector(".lb-actions .btn-accent", { timeout: 10000 });
  const scarico = page.waitForEvent("download", { timeout: 20000 }).catch(() => null);
  await page.locator(".lb-actions .btn-accent").first().click();
  const d = await scarico;
  verifica("CASO 6 Safari iOS: foto singola scaricata normalmente", true, d !== null);
  verifica("CASO 6 Safari iOS: nessun riquadro per la foto singola", 0,
    await page.locator(".iosdl").count());
  await context.close();

  // Dentro la webview: stesso percorso, ma senza istruzioni anticipate.
  const b = await apri(browser, UA.instagramIos, null, finteApiCondivisione(true));
  await b.page.locator(".photo").first().dispatchEvent("click");
  await b.page.waitForSelector(".lb-actions .btn-accent", { timeout: 10000 });
  await b.page.locator(".lb-actions .btn-accent").first().click();
  await b.page.waitForSelector(".iosdl", { timeout: 10000 });
  const salva = b.page.locator(".iosdl-azioni .btn-accent");
  await salva.waitFor({ state: "visible", timeout: 60000 });
  const testoPrima = await b.page.textContent(".iosdl-titolo");
  await salva.click();
  await b.page.waitForFunction(() => window.__condiviso !== null, { timeout: 20000 });
  const condiviso = await b.page.evaluate(() => window.__condiviso);
  verifica("CASO 6 Instagram iOS: la foto singola arriva al pannello", true,
    !!condiviso && condiviso[0].byte > 0);
  verifica("CASO 6 Instagram iOS: nessuna istruzione anticipata", false,
    /Safari/i.test(testoPrima));
  console.log("        foto condivisa:", JSON.stringify(condiviso));
  await b.context.close();
}

async function caso7_condivisioneMultipla(browser, token) {
  if (!token) {
    esiti.push({ nome: "CASO 7 /fs/{token}", ok: null, saltato: true });
    console.log("SKIP  CASO 7 /fs/{token}: nessun token di prova disponibile");
    return;
  }
  const context = await nuovoContesto(browser, UA.instagramIos,
    { width: 390, height: 844 }, finteApiCondivisione(true));
  const page = await context.newPage();
  await page.goto(`${BASE}/fs/${token}`, { waitUntil: "domcontentloaded" });
  const quante = await page.getAttribute("#dlTutto", "data-quante");
  await page.click("#dlTutto");
  await page.waitForSelector(".iosdl", { timeout: 10000 });
  verifica("CASO 7 /fs/{token}: stesso percorso della pagina album", true,
    (await page.locator(".iosdl").count()) === 1);
  console.log("        foto nella condivisione:", quante);
  await context.close();
}

async function verificaVisiva(browser) {
  for (const vp of [{ width: 390, height: 844 }, { width: 430, height: 932 }]) {
    const { context, page } = await apri(browser, UA.instagramIos, vp,
      finteApiCondivisione(false));
    await selezionaFoto(page, 2);
    await page.click("#dlSel");
    await page.waitForSelector(".iosdl", { timeout: 10000 });
    const salva = page.locator(".iosdl-azioni .btn-accent");
    await salva.waitFor({ state: "visible", timeout: 60000 });
    await salva.click();
    await page.waitForTimeout(500);
    const m = await page.evaluate(() => {
      const s = document.querySelector(".iosdl");
      const r = s.getBoundingClientRect();
      const bottoni = Array.from(document.querySelectorAll(".iosdl-azioni .btn"))
        .map(function (b) {
          const br = b.getBoundingClientRect();
          return { largo: Math.round(br.width), alto: Math.round(br.height) };
        });
      return {
        larghezza: Math.round(r.width),
        dentroLoSchermo: r.left >= 0 && r.right <= window.innerWidth,
        scrollOrizzontale: document.documentElement.scrollWidth > window.innerWidth,
        testoVisibile: !!document.querySelector(".iosdl-testo").textContent.trim(),
        bottoni: bottoni,
      };
    });
    const bottoniOk = m.bottoni.length > 0 && m.bottoni.every(b => b.alto >= 40 && b.largo > 100);
    verifica(`VISIVA ${vp.width}x${vp.height}: niente overflow orizzontale`, false, m.scrollOrizzontale);
    verifica(`VISIVA ${vp.width}x${vp.height}: riquadro dentro lo schermo`, true, m.dentroLoSchermo);
    verifica(`VISIVA ${vp.width}x${vp.height}: bottoni toccabili (>=40px)`, true, bottoniOk);
    console.log(`        riquadro ${m.larghezza}px, bottoni ${JSON.stringify(m.bottoni)}`);
    await page.screenshot({ path: `/tmp/iosdl-${vp.width}x${vp.height}.png` });
    await context.close();
  }
}

(async () => {
  let motore = webkit, nomeMotore = "WebKit";
  let browser;
  try {
    browser = await motore.launch();
  } catch (e) {
    motore = chromium; nomeMotore = "Chromium";
    browser = await motore.launch();
  }
  console.log(`Motore: ${nomeMotore}\nSito: ${BASE}${ALBUM}\n`);
  try {
    await caso1_desktop(browser);
    await caso2_android(browser);
    await caso3_safariIos(browser);
    await caso4_instagramIos(browser);
    await caso5_facebookIos(browser);
    await caso6_downloadSingolo(browser);
    await caso7_condivisioneMultipla(browser, process.env.PC_TOKEN);
    await verificaVisiva(browser);
  } finally {
    await browser.close();
  }
  const falliti = esiti.filter(e => e.ok === false);
  const saltati = esiti.filter(e => e.saltato);
  console.log(`\nPassed: ${esiti.filter(e => e.ok === true).length}` +
    `  Failed: ${falliti.length}  Skipped: ${saltati.length}`);
  process.exit(falliti.length ? 1 : 0);
})();
