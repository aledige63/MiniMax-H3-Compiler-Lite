import { t } from "./i18n.js";

// Identifica il comando HTTP, non i Subject/Picture assegnati dal server.
// randomUUID può mancare su HTTP LAN; getRandomValues è disponibile anche lì.
export function newCommandId(cryptoApi = globalThis.crypto) {
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error(t("Il browser non supporta la generazione degli identificativi. Usa un browser aggiornato."));
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // UUID versione 4.
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // Variante RFC 9562.
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}
