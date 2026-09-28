"use strict";

// ------------------------------------------------------------------ arranque

function iniciarTema() {
  const guardado = (() => { try { return localStorage.getItem("tema"); } catch { return null; } })();
  if (guardado) document.documentElement.dataset.theme = guardado;
  $("#toggleTema").addEventListener("click", () => {
    const oscuroAhora = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const nuevo = oscuroAhora ? "light" : "dark";
    document.documentElement.dataset.theme = nuevo;
    try { localStorage.setItem("tema", nuevo); } catch { /* sin almacenamiento */ }
  });
}

// ------------------------------------------------------------------ móvil

function abrirHoja() {
  $("#hojaMas").classList.add("abierta");
  $("#hojaFondo").classList.add("abierto");
  $("#botonMas").setAttribute("aria-expanded", "true");
}
function cerrarHoja() {
  $("#hojaMas").classList.remove("abierta");
  $("#hojaFondo").classList.remove("abierto");
  $("#botonMas").setAttribute("aria-expanded", "false");
}

function iniciarMovil() {
  $("#botonMas").addEventListener("click", () => ($("#hojaMas").classList.contains("abierta") ? cerrarHoja() : abrirHoja()));
  $("#hojaFondo").addEventListener("click", cerrarHoja);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarHoja(); });
  // Tooltips táctiles: se van al tocar fuera (antes de que el nuevo toque abra otro) o al desplazarse.
  document.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse") quitarTipTactil(); }, true);
  window.addEventListener("scroll", quitarTipTactil, { passive: true });
  // Al pasar de móvil a escritorio (o al girar el teléfono) se redibuja la vista con el nuevo tamaño.
  const redibujar = () => { estadoRuta.clave = ""; render(); };
  MQ_MOVIL.addEventListener("change", () => {
    document.documentElement.classList.toggle("movil", esMovil());
    cerrarHoja();
    redibujar();
  });
  let ancho = window.innerWidth, espera = null;
  window.addEventListener("resize", () => {
    clearTimeout(espera);
    espera = setTimeout(() => {
      if (esMovil() && Math.abs(window.innerWidth - ancho) > 60) redibujar();
      ancho = window.innerWidth;
    }, 300);
  });
}

(async function () {
  iniciarTema();
  $("#vista").replaceChildren(el("div", { class: "vacio" }, "Abriendo la base de datos SQLite…"));
  try {
    const avisar = (texto) => $("#vista").replaceChildren(el("div", { class: "vacio" }, texto));
    await abrirCatalogo();
    const { clave, elegido } = ambitoInicial();
    await cambiarAmbito(clave, avisar, elegido);
  } catch (e) {
    $("#vista").replaceChildren(el("div", { class: "vacio" }, "No se pudo abrir la base de datos: " + e.message));
    return;
  }
  $("#panelFondo").addEventListener("click", cerrarPanel);
  // Los selectores múltiples se cierran (y se aplican) al pulsar fuera o con Escape.
  document.addEventListener("click", (e) => {
    for (const d of document.querySelectorAll("details.ms[open]")) if (!d.contains(e.target)) d.open = false;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") for (const d of document.querySelectorAll("details.ms[open]")) d.open = false;
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && leerRuta().q.ver) cerrarPanel(); });
  iniciarMovil();
  $("#botonAmbito").addEventListener("click", abrirSelectorAmbito);
  window.addEventListener("hashchange", async () => { cerrarHoja(); await aplicarAmbitoDeRuta(); render(); });
  render();
})();
