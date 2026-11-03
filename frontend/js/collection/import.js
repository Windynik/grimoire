// Import screen: upload a ManaBox CSV, process it, and download the result.

import { navigate } from "../app/router.js";
import { h } from "../shared/dom.js";
import { setActiveCollection, setViewerSource } from "../shared/session.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";

const $ = (id) => document.getElementById(id);

let resultJobId = null; // the job of the results on view

function handleFileSelect(e) {
  const file = e.target.files[0];
  if (file) handleFile(file);
}

async function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    showToast("Please select a CSV file", "error");
    return;
  }

  $("upload-zone").style.display = "none";
  $("processing-display").style.display = "block";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(`${API_BASE}/process`, {
      method: "POST",
      body: formData,
    });

    const result = await response.json();

    if (response.ok) {
      resultJobId = result.job_id;
      setActiveCollection(result.job_id);
      // A fresh import becomes the viewer's collection again
      setViewerSource(null);
      displayResults(result);
    } else {
      showToast("Error processing CSV: " + result.detail, "error");
      resetUploadUI();
    }
  } catch (error) {
    showToast("Error uploading file", "error");
    resetUploadUI();
  }
}

function displayResults(result) {
  $("processing-display").style.display = "none";
  $("results-display").style.display = "block";

  $("total-processed").textContent = result.total_processed;
  $("success-count").textContent = result.success_count;
  $("final-error-count").textContent = result.error_count;

  // Add the View Collection button once.
  if (!$("view-collection-btn")) {
    const actions = $("results-display").querySelector(".actions");
    actions.prepend(h("button", {
      id: "view-collection-btn",
      class: "btn btn-secondary",
      onclick: () => navigate("#collection"),
    }, "View Collection"));
  }
}

function resetUploadUI() {
  $("upload-zone").style.display = "block";
  $("processing-display").style.display = "none";
  $("results-display").style.display = "none";
  $("file-input").value = "";
  resultJobId = null;
}

function downloadProcessedFile() {
  if (resultJobId) {
    window.location.href = `${API_BASE}/download/${resultJobId}`;
  }
}

function init() {
  const uploadZone = $("upload-zone");
  const fileInput = $("file-input");

  uploadZone.addEventListener("click", () => fileInput.click());
  uploadZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", handleFileSelect);
  $("process-another").addEventListener("click", resetUploadUI);
  $("download-result").addEventListener("click", downloadProcessedFile);

  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("dragover");
  });
  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("dragover");
  });
  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
  });
}

/** Show the screen. It keeps the last upload state. */
export function open() {}

init();
