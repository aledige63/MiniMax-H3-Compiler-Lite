export function serviceFor(model = "") { return model.startsWith("openai::") ? "openai" : "ollama"; }
export function modelLabel(model) { return `${model.service === "openai" || serviceFor(model.name) === "openai" ? "OpenAI" : "Ollama"} · ${model.label || model.name.replace(/^openai::/, "")}`; }
export function eligibleModels(models, service, capability) { return models.filter(m => serviceFor(m.name) === service && m.capabilities.includes(capability)); }

export function createUserSettings(document, { request, commandId, reloadModels, accessChanged }) {
  const $ = id => document.getElementById(id);
  let saved = null, access = null, saving = false, trialRunning = false;
  const status = (id, text, error = false) => { $(id).textContent = text; $(id).classList.toggle("error", error); };
  function renderKeyStatus(config) {
    $("openai-key-state").textContent = config.openai_key_set
      ? t("Chiave salvata nel servizio. Lascia vuoto per conservarla.")
      : t("Nessuna chiave salvata.");
  }
  function renderAccessStatus(policy) {
    $("password-policy").textContent = policy.enabled ? policy.protect_all
      ? t("Password attiva per tutti gli accessi, anche da questo computer.")
      : t("Protezione LAN esistente conservata. Applicando una password sarà protetto anche l’accesso locale.")
      : t("Accesso senza password. Puoi attivare la protezione per questo unico account.");
    $("access-urls").textContent = policy.lan_urls?.length
      ? t("Indirizzi del compilatore sulla LAN: ") + policy.lan_urls.join(" · ") : "";
  }
  async function load(accessOnly = false) {
    const [config, policy] = await Promise.all([request("/api/connections"), request("/api/access/status")]);
    access = policy;
    if (!accessOnly) {
      saved = config;
      $("ollama-url").value = config.ollama_url;
      $("llm-timeout").value = config.timeout_s;
      $("openai-key").value = "";
      $("remove-openai-key").checked = false;
      renderKeyStatus(config);
    }
    $("access-enabled").checked = policy.enabled;
    $("current-password").value = ""; $("new-password").value = ""; $("confirm-password").value = "";
    $("current-password").disabled = !policy.configured;
    renderAccessStatus(policy);
    $("initial-password-wrap").hidden = true;
    if (policy.local && !policy.protect_all) {
      const initial = await request("/api/access/bootstrap");
      if (initial.password) { $("initial-password").value = initial.password; $("initial-password-wrap").hidden = false; }
    }
    passwordFields();
  }
  function passwordFields() {
    const enabled = $("access-enabled").checked;
    $("new-password").disabled = !enabled;
    $("confirm-password").disabled = !enabled;
  }
  async function saveConnections() {
    if (!saved) throw new Error(t("Carica prima le impostazioni."));
    const body = { command_id: commandId(), expected_revision: saved.revision,
      ollama_url: $("ollama-url").value.trim(), timeout_s: Number($("llm-timeout").value),
      remove_api_key: $("remove-openai-key").checked };
    if ($("openai-key").value.trim()) body.api_key = $("openai-key").value.trim();
    if (body.api_key && body.remove_api_key) throw new Error(t("Scegli se sostituire o rimuovere la chiave API."));
    saved = await request("/api/connections", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    $("openai-key").value = ""; $("remove-openai-key").checked = false;
    renderKeyStatus(saved);
    return saved;
  }
  async function connectionAction(service = null) {
    if (saving) return;
    saving = true;
    for (const id of ["save-connections", "connect-ollama", "connect-openai"]) $(id).disabled = true;
    status("connections-status", service ? t("Salvataggio e connessione in corso…") : t("Salvataggio in corso…"));
    let didSave = false;
    try {
      await saveConnections();
      didSave = true;
      if (service) {
        const models = await request(`/api/connections/models/${service}`);
        status("connections-status", tr`${service === "ollama" ? "Ollama" : "OpenAI"}: connessione riuscita, ${models.length} modelli disponibili. Nessuna inferenza eseguita.`);
      } else status("connections-status", t("Connessioni salvate. Nessuna inferenza eseguita."));
    } catch (error) { status("connections-status", error.message, true); }
    finally {
      if (didSave) { try { await reloadModels(); } catch (error) { status('connections-status', error.message, true); } }
      saving = false; for (const id of ["save-connections", "connect-ollama", "connect-openai"]) $(id).disabled = false;
    }
  }
  async function trial(kind, model) {
    if (trialRunning || !model) return;
    trialRunning = true;
    $("test-vision").disabled = true; $("test-text").disabled = true;
    status("trial-status", t("Verifica in coda… La prova usa soltanto dati sintetici."));
    try {
      let job = await request("/api/connections/trials", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, model }) });
      while (["queued", "running"].includes(job.status)) {
        await new Promise(resolve => setTimeout(resolve, 700));
        job = await request(`/api/connections/trials/${job.id}`);
        status("trial-status", job.status === "running" ? t("Verifica in corso…") : t("Verifica in coda…"));
      }
      status("trial-status", `${kind === "vision" ? "Vision" : t("Testo")}: ${diagnostic(job.message)}`, job.status !== "succeeded");
      await reloadModels();
    } catch (error) { status("trial-status", error.message, true); }
    finally { trialRunning = false; $("test-text").disabled = false; $("test-vision").disabled = false; }
  }
  $("save-connections").onclick = () => connectionAction();
  $("connect-ollama").onclick = () => connectionAction("ollama");
  $("connect-openai").onclick = () => connectionAction("openai");
  $("access-enabled").onchange = passwordFields;
  $("save-access").onclick = async () => {
    const enabled = $("access-enabled").checked;
    if (enabled && $("new-password").value !== $("confirm-password").value) { status("access-status", t("Le nuove password non coincidono."), true); return; }
    if (enabled && $("new-password").value.length < 12) { status("access-status", t("Usa una password di almeno 12 caratteri."), true); return; }
    $("save-access").disabled = true;
    status("access-status", t("Aggiornamento dell’accesso…"));
    try {
      const value = await request("/api/access/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled,
        current_password: $("current-password").value, password: enabled ? $("new-password").value : "" }) });
      await accessChanged(value);
      await load(true);
      status("access-status", enabled ? t("Password aggiornata. Le altre sessioni sono state chiuse.") : t("Protezione con password disattivata."));
    } catch (error) { status("access-status", error.message, true); }
    finally { $("save-access").disabled = false; }
  };
  function refreshLanguage() {
    if (saved) renderKeyStatus(saved);
    if (access) renderAccessStatus(access);
    if (!saving) status("connections-status", "");
    if (!trialRunning) status("trial-status", "");
    status("access-status", "");
  }
  return { load, trial, refreshLanguage };
}
import { diagnostic, t, tr } from "./i18n.js";
