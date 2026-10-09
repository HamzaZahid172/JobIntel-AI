"use strict";

// Pure helpers kept separate so they can be tested without launching Chromium.
const net = require("node:net");
function safeApplicationUrl(raw) {
  let url;
  try { url = new URL(raw); } catch { return false; }
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return false;
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal")) return false;
  if (net.isIP(host)) {
    if (net.isIP(host) === 6) return false;
    const parts = host.split(".").map(Number);
    if (parts[0] === 10 || parts[0] === 127 || parts[0] === 0 || parts[0] >= 224 ||
        (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
        (parts[0] === 192 && parts[1] === 168) ||
        (parts[0] === 169 && parts[1] === 254)) return false;
  }
  return true;
}

function fieldValue(info, profile) {
  const text = [info.name, info.id, info.placeholder, info.label, info.autocomplete]
    .filter(Boolean).join(" ").toLowerCase().replace(/[_-]/g, " ");
  if (info.type === "hidden" || info.type === "password" ||
      info.type === "checkbox" || info.type === "radio" || info.type === "file" ||
      info.tag === "select") return null;
  const tests = [
    [/(first\s*name|given\s*name|vorname|fname)/, "firstName"],
    [/(last\s*name|family\s*name|surname|nachname|lname)/, "lastName"],
    [/(full\s*name|your\s*name|applicant\s*name|candidate\s*name)/, "fullName"],
    [/(e\s*mail|email)/, "email"],
    [/(phone|mobile|telephone|telefon)/, "phone"],
    [/(linkedin)/, "linkedin"],
    [/(github)/, "github"],
    [/(portfolio|personal\s*website|website\s*url)/, "portfolio"],
    [/(city|stadt|wohnort)/, "city"],
    [/(country|land|nation)/, "country"],
  ];
  for (const [pattern, key] of tests) {
    if (pattern.test(text)) return {key, value: String(profile[key] || "").trim()};
  }
  return null;
}
function documentKind(info) {
  const text = [info.name, info.id, info.label, info.accept]
    .filter(Boolean).join(" ").toLowerCase();
  if (/cover|anschreiben|motivation/.test(text)) return "cover";
  if (/experience|employment\s*letter|reference|arbeitszeugnis|certificate/.test(text)) return "experience";
  if (/resume|résumé|curriculum|cv|lebenslauf/.test(text)) return "cv";
  return null;
}
function submissionLabel(text) {
  const normalized = String(text || "").trim().toLowerCase();
  return /^(submit( application)?|send application|apply now|bewerbung absenden|jetzt bewerben|send bewerbung|submit and apply)(\s*[→›])?$/.test(normalized);
}
function nextLabel(text) {
  const normalized = String(text || "").trim().toLowerCase();
  return /^(apply|apply for this job|apply now|start application|continue|next|weiter|bewerben|zur bewerbung)(\s*[→›])?$/.test(normalized)
    && !submissionLabel(normalized);
}
module.exports = {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel};
