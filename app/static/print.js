document.getElementById("print").addEventListener("click", () => window.print());

Promise.all([import("./appearance.js"), import("./i18n.js")]).then(([appearance, i18n]) => {
  const { language } = appearance.readAppearance(window);
  document.documentElement.lang = language;
  i18n.setUiLanguage(language);
  for (const node of document.querySelectorAll("nav button, nav p, header p, article > h2, article > p, aside > h3")) {
    node.textContent = i18n.diagnostic(node.textContent);
  }
});
