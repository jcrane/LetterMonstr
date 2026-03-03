import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  GoogleAuthProvider,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";
import {
  getFirestore,
  doc,
  getDoc,
  updateDoc,
  serverTimestamp,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js";

const ENV = window.LETTERMONSTR_CONFIG;
if (!ENV) {
  document.getElementById("app").innerHTML =
    '<div style="padding:40px;color:#e74c3c;">' +
    "<h2>Missing Configuration</h2>" +
    "<p>Create <code>public/env-config.js</code> from " +
    "<code>public/env-config.template.js</code> and redeploy.</p></div>";
  throw new Error("LETTERMONSTR_CONFIG not found — see env-config.template.js");
}

const FIREBASE_CONFIG = ENV.firebase;
const AUTHORIZED_EMAIL = ENV.authorizedEmail;
const FUNCTIONS_BASE = `https://${ENV.region}-${ENV.firebase.projectId}.cloudfunctions.net`;
const UPDATE_SECRETS_URL = `${FUNCTIONS_BASE}/update_secrets`;
const TRIGGER_SUMMARY_URL = `${FUNCTIONS_BASE}/trigger_summary`;

const LIST_FIELDS = new Set(["folders", "ad_keywords"]);
const INT_FIELDS = new Set([
  "imap_port", "smtp_port", "max_tokens",
  "max_links_per_email", "max_link_depth", "request_timeout",
  "initial_lookback_days",
]);
const FLOAT_FIELDS = new Set(["temperature"]);

const app = initializeApp(FIREBASE_CONFIG);
const auth = getAuth(app);
const db = getFirestore(app);
const settingsRef = doc(db, "settings", "app_config");

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// -----------------------------------------------------------------------
// Toast
// -----------------------------------------------------------------------

function showToast(message, type = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = type;
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 3000);
}

// -----------------------------------------------------------------------
// Auth
// -----------------------------------------------------------------------

$("#btn-sign-in").addEventListener("click", () => {
  signInWithPopup(auth, new GoogleAuthProvider());
});

$("#btn-sign-out").addEventListener("click", () => signOut(auth));
$("#btn-denied-sign-out")?.addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  $("#loading").hidden = true;

  if (!user) {
    $("#btn-sign-in").hidden = false;
    $("#user-info").hidden = true;
    $("#main-content").hidden = true;
    $("#access-denied").hidden = true;
    return;
  }

  $("#btn-sign-in").hidden = true;
  $("#user-email").textContent = user.email;
  $("#user-info").hidden = false;

  if (user.email !== AUTHORIZED_EMAIL) {
    $("#main-content").hidden = true;
    $("#access-denied").hidden = false;
    return;
  }

  $("#access-denied").hidden = true;
  $("#main-content").hidden = false;
  await loadSettings();
});

// -----------------------------------------------------------------------
// Load settings from Firestore
// -----------------------------------------------------------------------

async function loadSettings() {
  try {
    const snap = await getDoc(settingsRef);
    if (!snap.exists()) {
      showToast("No settings document found", "error");
      return;
    }
    const data = snap.data();
    populateForms(data);
  } catch (err) {
    console.error("Error loading settings:", err);
    showToast("Failed to load settings", "error");
  }
}

function populateForms(data) {
  for (const [section, fields] of Object.entries(data)) {
    if (typeof fields !== "object" || fields === null) continue;

    const form = document.querySelector(`form[data-section="${section}"]`);
    if (!form) continue;

    for (const [key, value] of Object.entries(fields)) {
      const input = form.querySelector(`[data-key="${key}"]`);
      if (!input) continue;

      if (input.type === "checkbox") {
        input.checked = Boolean(value);
      } else if (LIST_FIELDS.has(key) && Array.isArray(value)) {
        input.value = value.join(", ");
      } else {
        input.value = value;
      }
    }
  }

  const tempSlider = $("#llm-temperature");
  if (tempSlider) {
    $("#temp-display").textContent = tempSlider.value;
  }
}

// -----------------------------------------------------------------------
// Save settings
// -----------------------------------------------------------------------

$$("form[data-section]").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const section = form.dataset.section;
    const updates = {};

    form.querySelectorAll("[data-key]").forEach((input) => {
      const key = input.dataset.key;
      let value;

      if (input.type === "checkbox") {
        value = input.checked;
      } else if (LIST_FIELDS.has(key)) {
        value = input.value.split(",").map((s) => s.trim()).filter(Boolean);
      } else if (INT_FIELDS.has(key)) {
        value = parseInt(input.value, 10) || 0;
      } else if (FLOAT_FIELDS.has(key)) {
        value = parseFloat(input.value) || 0;
      } else {
        value = input.value;
      }

      updates[`${section}.${key}`] = value;
    });

    updates["updated_at"] = serverTimestamp();

    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Saving...";

    try {
      await updateDoc(settingsRef, updates);
      showToast(`${section} settings saved`);
    } catch (err) {
      console.error("Save error:", err);
      showToast("Failed to save settings", "error");
    } finally {
      btn.disabled = false;
      btn.textContent = btn.textContent.replace("Saving...", `Save ${section} Settings`);
      btn.textContent = `Save ${section.charAt(0).toUpperCase() + section.slice(1)} Settings`;
    }
  });
});

// -----------------------------------------------------------------------
// Temperature slider live display
// -----------------------------------------------------------------------

const tempSlider = $("#llm-temperature");
if (tempSlider) {
  tempSlider.addEventListener("input", () => {
    $("#temp-display").textContent = tempSlider.value;
  });
}

// -----------------------------------------------------------------------
// Secret updates
// -----------------------------------------------------------------------

// -----------------------------------------------------------------------
// Manual summary trigger
// -----------------------------------------------------------------------

const triggerBtn = $("#btn-trigger-summary");
const triggerStatus = $("#trigger-status");

if (triggerBtn) {
  triggerBtn.addEventListener("click", async () => {
    const user = auth.currentUser;
    if (!user) {
      showToast("Not signed in", "error");
      return;
    }

    triggerBtn.disabled = true;
    triggerBtn.textContent = "Generating...";
    triggerStatus.hidden = false;
    triggerStatus.textContent = "This may take a minute or two. Please wait...";

    try {
      const token = await user.getIdToken();
      const resp = await fetch(TRIGGER_SUMMARY_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      });

      const result = await resp.json();
      if (!resp.ok) throw new Error(result.error || "Request failed");

      if (result.status === "no_content") {
        triggerStatus.textContent = "No unsummarized content available.";
        showToast("No new content to summarize", "error");
      } else if (result.status === "all_filtered") {
        triggerStatus.textContent = "All content already summarized.";
        showToast("Nothing new to summarize", "error");
      } else if (result.email_sent) {
        triggerStatus.textContent =
          `Summary sent! ${result.items_summarized} items summarized.`;
        showToast("Summary email sent!");
      } else {
        triggerStatus.textContent =
          "Summary generated but email failed to send.";
        showToast("Email send failed", "error");
      }
    } catch (err) {
      console.error("Trigger summary error:", err);
      triggerStatus.textContent = `Error: ${err.message}`;
      showToast(`Failed: ${err.message}`, "error");
    } finally {
      triggerBtn.disabled = false;
      triggerBtn.textContent = "Send Summary Now";
    }
  });
}

// -----------------------------------------------------------------------
// Secret updates
// -----------------------------------------------------------------------

$$("[data-secret]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const secretId = btn.dataset.secret;
    const input = btn.previousElementSibling || btn.parentElement.querySelector("input");
    const value = input?.value?.trim();

    if (!value) {
      showToast("Enter a value first", "error");
      return;
    }

    btn.disabled = true;
    btn.textContent = "Updating...";

    try {
      const user = auth.currentUser;
      if (!user) throw new Error("Not signed in");

      const token = await user.getIdToken();
      const resp = await fetch(UPDATE_SECRETS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ secret_id: secretId, value }),
      });

      const result = await resp.json();
      if (!resp.ok) throw new Error(result.error || "Request failed");

      input.value = "";
      showToast(`Secret updated: ${secretId}`);
    } catch (err) {
      console.error("Secret update error:", err);
      showToast(`Failed: ${err.message}`, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Update";
    }
  });
});
