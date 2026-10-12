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
  const exactName = String(info.name || info.id || "").trim().toLowerCase();
  const label = String(info.label || "").trim().replace(/[*:]+$/, "").trim().toLowerCase();
  // Never infer answers to sensitive screening or employer declarations.
  if (/(salary|compensation|pay range|visa|work authorization|sponsor|citizenship|citizen|eligib|relocat|notice period|start date|consent|privacy|gdpr|gender|race|ethnic|disability|veteran)/i.test(text)) return null;
  if (info.type === "hidden" || info.type === "password" ||
      info.type === "checkbox" || info.type === "radio" || info.type === "file" ||
      (info.tag === "select" && !/(country|location|land|nation|stadt)/.test(text))) return null;
  if ((exactName === "name" || exactName === "fullname" || label === "name") &&
      info.tag !== "select" && info.type !== "file") {
    return {key:"fullName",value:String(profile.fullName || "").trim()};
  }
  if (/(your location|current location|present location|wohnort|current city)/.test(text) &&
      !/(work location preference|preferred location)/.test(text)) {
    return {key:"location",value:[profile.city,profile.country].filter(Boolean).join(", ")};
  }
  const tests = [
    [/(first\s*name|given\s*name|vorname|fname)/, "firstName"],
    [/(last\s*name|family\s*name|surname|nachname|lname)/, "lastName"],
    [/(full\s*name|your\s*name|applicant\s*name|candidate\s*name)/, "fullName"],
    [/^(name|name required|name \*|name:|applicant|candidate)$/,"fullName"],
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
const ATS_HOSTS = [
  "ashbyhq.com", "greenhouse.io", "greenhouse.com", "lever.co",
  "smartrecruiters.com", "workdayjobs.com", "myworkdayjobs.com",
  "workable.com", "personio.de", "recruitee.com", "bamboohr.com",
  "teamtailor.com", "jobvite.com", "icims.com"
];
function isAtsUrl(raw) {
  if (!safeApplicationUrl(raw)) return false;
  const host = new URL(raw).hostname.toLowerCase();
  return ATS_HOSTS.some(ats => host === ats || host.endsWith("." + ats));
}
function applicationLinks(links, currentUrl) {
  const current = new URL(currentUrl).hostname.toLowerCase();
  const seen = new Set(), result = [];
  for (const item of links) {
    const url = String(item.href || "");
    if (!safeApplicationUrl(url) || seen.has(url)) continue;
    const title = String(item.text || "").trim().slice(0, 140);
    const host = new URL(url).hostname.toLowerCase();
    const external = host !== current;
    const action = /\b(apply|application|bewerben|bewerbung|jetzt bewerben|apply now)\b/i.test(title);
    if (!action && !isAtsUrl(url)) continue;
    if (!external && !/\b(apply|bewerben|bewerbung)\b/i.test(title)) continue;
    if (/\b(sign in|log in|privacy|cookie|newsletter|advertise)\b/i.test(title)) continue;
    seen.add(url);
    result.push({url, title:title || "Employer application", external, ats:isAtsUrl(url)});
  }
  return result.sort((a,b)=>Number(b.ats)-Number(a.ats)).slice(0,8);
}

/**
 * Ashby may upload the file asynchronously and clear the native input after
 * showing an attached-file chip. The native FileList alone is not sufficient.
 * Only accept scoped visual evidence of the exact CV the applicant selected.
 */
function uploadFieldComplete(field, documents = {}) {
  if (field.type !== "file") return Boolean(field.filled);
  if (field.filled) return true; // Browser still has a real FileList.
  const kind = documentKind(field);
  const document = kind && documents[kind];
  const filename = document && document.name;
  // Ashby may expose the same attached-file chip through its input's label.
  // In that case the field label includes the exact filename and "Replace".
  const text = String(field.attachmentText || field.label || "").toLowerCase();
  if (!filename || !text || text.length > 1000) return false;
  if (!text.includes(String(filename).toLowerCase())) return false;
  if (/uploading|processing|upload failed|error uploading/.test(text)) return false;
  // "Replace" or "Remove" is a strong signal the upload UI now holds a file.
  return /replace|remove|delete|attached|uploaded|ersetzen|entfernen/i.test(text);
}
function requiredFieldsMissing(fields, documents = {}) {
  return fields.filter(field => field.required && !uploadFieldComplete(field, documents));
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
module.exports = {safeApplicationUrl,fieldValue,documentKind,submissionLabel,nextLabel,isAtsUrl,applicationLinks,uploadFieldComplete,requiredFieldsMissing};
