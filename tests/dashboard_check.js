// Test du tableau de bord dans un navigateur simulé (jsdom).
// Usage : node tests/dashboard_check.js docs/index.html   (nécessite : npm i jsdom)
const fs = require("fs");
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");
const file = process.argv[2] || "docs/index.html";
const html = fs.readFileSync(file, "utf8");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://example.org/", pretendToBeVisual: true,
  beforeParse(w) { w.prompt = () => "Note de test"; w.alert = (m) => errors.push("alert: " + m);
    w.addEventListener("error", (e) => errors.push(e.message)); } });
const w = dom.window, d = w.document;
const ok = (c, m) => { if (!c) { errors.push(m); console.log("✗ " + m); } else console.log("✓ " + m); };

const V = w.VEILLE;
ok(V && Array.isArray(V.notices), "données intégrées présentes");
const nFr = V.notices.filter(n => n.country === "FRA").length;
ok(d.querySelectorAll("#tb-fr tr.nr").length === nFr, `onglet France : ${nFr} lignes`);
ok(d.querySelectorAll("#tb-fr tr.nr")[0].children.length === 8, "8 colonnes par ligne");
ok(d.querySelectorAll("#statsGrid .sc").length === 6, "6 cartes de synthèse");
ok(d.getElementById("kwList").textContent.length > 50, "mots-clés surveillés affichés");
ok(d.getElementById("srcStatus").textContent.includes("BOAMP"), "panneau sources & vérification");
ok(d.getElementById("modeBanner").textContent.length > 10, "bandeau d'état de la collecte");

// tri par pertinence : premier = meilleur score
const first = d.querySelector("#tb-fr tr.nr .score").textContent;
const max = Math.max(...V.notices.filter(n => n.country === "FRA").map(n => n.score));
ok(+first === max, "tri par pertinence (premier score = " + max + ")");

// filtre priorité haute
d.getElementById("pf").value = "high"; d.getElementById("pf").dispatchEvent(new w.Event("change"));
const highs = V.notices.filter(n => n.country === "FRA" && n.priority === "high").length;
ok(d.querySelectorAll("#tb-fr tr.nr").length === highs, `filtre haute priorité : ${highs}`);
d.getElementById("pf").value = ""; d.getElementById("pf").dispatchEvent(new w.Event("change"));

// recherche
d.getElementById("q").value = "bpifrance"; d.getElementById("q").dispatchEvent(new w.Event("input"));
ok(d.querySelectorAll("#tb-fr tr.nr").length >= 1, "recherche texte");
d.getElementById("q").value = ""; d.getElementById("q").dispatchEvent(new w.Event("input"));

// carte cliquable (échéance ≤ 30 j)
d.querySelector('[data-quick="d30"]').click();
ok(d.querySelector('[data-quick="d30"]').classList.contains("on"), "carte ≤ 30 j active comme filtre");
d.querySelector('[data-quick="d30"]').click();

// suivi : statut + note, persistance localStorage
const sel = d.querySelector("#tb-fr .status-select");
const id = sel.getAttribute("data-id");
sel.value = "Intéressant"; sel.dispatchEvent(new w.Event("change", { bubbles: true }));
d.querySelector(`[data-note="${id}"]`).click();
const saved = JSON.parse(w.localStorage.getItem("bdgs_public_procurement_tracking_v1"));
ok(saved[id] && saved[id].status === "Intéressant" && saved[id].note === "Note de test", "statut + note enregistrés");
ok(d.querySelector(`#tb-fr .status-select[data-id="${id}"]`).value === "Intéressant", "statut toujours affiché après re-rendu");

// détail du score
ok(d.querySelector("#tb-fr details.det") && d.querySelector("#tb-fr details.det").textContent.includes("Total"), "détail du score disponible");

// migration des anciens identifiants
const dom2 = new JSDOM(html, { runScripts: "dangerously", url: "https://example.org/", beforeParse(w2) {
  w2.localStorage.setItem("bdgs_public_procurement_tracking_v1", JSON.stringify({"BOAMP-26-106060": {status: "Déposé", note: "ancien"}})); } });
const migr = JSON.parse(dom2.window.localStorage.getItem("bdgs_public_procurement_tracking_v1"));
ok(migr["BOAMP:26-106060"] && migr["BOAMP:26-106060"].status === "Déposé", "reprise des statuts de l'ancienne version");

ok(errors.length === 0 || errors.every(e => e.startsWith("✗") === false && !/Error/.test(e)), "aucune erreur JavaScript");
if (errors.length) { console.log("Erreurs :", errors); process.exit(1); }
console.log("\nTableau de bord OK");
