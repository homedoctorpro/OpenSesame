const form = document.getElementById("generate-form");
const urlsInput = document.getElementById("urls");
const toneSelect = document.getElementById("tone");
const depthSelect = document.getElementById("research-depth");
const charLimitInput = document.getElementById("char-limit");
const mustIncludeInput = document.getElementById("must-include");
const submitBtn = document.getElementById("submit-btn");
const progress = document.getElementById("progress");
const progressText = document.getElementById("progress-text");
const resultsSection = document.getElementById("results-section");
const resultsBody = document.getElementById("results-body");
const exportBtn = document.getElementById("export-csv");
const modal = document.getElementById("manual-modal");
const manualFields = document.getElementById("manual-fields");
const manualSubmit = document.getElementById("manual-submit");
const manualSkip = document.getElementById("manual-skip");

let currentResults = [];
let pendingRequest = null;

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const urls = urlsInput.value
        .split("\n")
        .map((u) => u.trim())
        .filter((u) => u.length > 0);

    if (urls.length === 0) return;
    if (urls.length > 10) {
        alert("Maximum 10 URLs per batch.");
        return;
    }

    await runGeneration(urls, {});
});

async function runGeneration(urls, manualProfiles) {
    submitBtn.disabled = true;
    progress.classList.remove("hidden");
    resultsSection.classList.add("hidden");
    progressText.textContent = `Processing ${urls.length} profile${urls.length > 1 ? "s" : ""}...`;

    const payload = {
        urls,
        must_include: mustIncludeInput.value.trim(),
        char_limit: parseInt(charLimitInput.value) || 300,
        tone: toneSelect.value,
        research_depth: depthSelect.value,
        manual_profiles: manualProfiles,
    };

    try {
        const resp = await fetch("/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `Server error ${resp.status}`);
        }

        const data = await resp.json();
        currentResults = data.results;

        // Check for failed scrapes that need manual input
        const failed = currentResults.filter((r) => r.scrape_tier === "failed" && !manualProfiles[r.url]);
        if (failed.length > 0) {
            pendingRequest = { urls, manualProfiles: { ...manualProfiles } };
            showManualModal(failed);
        }

        renderResults(currentResults);
    } catch (err) {
        alert("Error: " + err.message);
    } finally {
        submitBtn.disabled = false;
        progress.classList.add("hidden");
    }
}

function renderResults(results) {
    resultsBody.innerHTML = "";
    resultsSection.classList.remove("hidden");

    results.forEach((r, i) => {
        const tr = document.createElement("tr");
        if (r.error && !r.opener) {
            tr.className = "error-row";
            tr.innerHTML = `
                <td>${escapeHtml(r.name || extractSlug(r.url))}</td>
                <td>${escapeHtml(r.error)}</td>
                <td>${r.scrape_tier || "-"}</td>
                <td></td>`;
        } else {
            tr.innerHTML = `
                <td>${escapeHtml(r.name || extractSlug(r.url))}</td>
                <td>${escapeHtml(r.opener)}</td>
                <td>${r.scrape_tier || "-"}</td>
                <td><button class="copy-btn" data-index="${i}">Copy</button></td>`;
        }
        resultsBody.appendChild(tr);
    });

    // Attach copy handlers
    document.querySelectorAll(".copy-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const idx = parseInt(btn.dataset.index);
            navigator.clipboard.writeText(currentResults[idx].opener).then(() => {
                btn.textContent = "Copied!";
                btn.classList.add("copied");
                setTimeout(() => {
                    btn.textContent = "Copy";
                    btn.classList.remove("copied");
                }, 1500);
            });
        });
    });
}

function showManualModal(failedResults) {
    manualFields.innerHTML = "";
    failedResults.forEach((r) => {
        const div = document.createElement("div");
        div.className = "manual-entry";
        div.innerHTML = `
            <label>${escapeHtml(r.url)}</label>
            <textarea data-url="${escapeHtml(r.url)}" placeholder="Paste the LinkedIn profile text here (name, headline, experience, etc.)"></textarea>`;
        manualFields.appendChild(div);
    });
    modal.classList.remove("hidden");
}

manualSubmit.addEventListener("click", () => {
    if (!pendingRequest) return;
    const textareas = manualFields.querySelectorAll("textarea");
    textareas.forEach((ta) => {
        const text = ta.value.trim();
        if (text) {
            pendingRequest.manualProfiles[ta.dataset.url] = text;
        }
    });
    modal.classList.add("hidden");
    runGeneration(pendingRequest.urls, pendingRequest.manualProfiles);
    pendingRequest = null;
});

manualSkip.addEventListener("click", () => {
    modal.classList.add("hidden");
    pendingRequest = null;
});

exportBtn.addEventListener("click", () => {
    if (currentResults.length === 0) return;
    const rows = [["Name", "URL", "Opener", "Source", "Error"]];
    currentResults.forEach((r) => {
        rows.push([
            r.name || "",
            r.url,
            r.opener || "",
            r.scrape_tier || "",
            r.error || "",
        ]);
    });
    const csv = rows.map((row) => row.map(csvEscape).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "opensesame_openers.csv";
    a.click();
    URL.revokeObjectURL(a.href);
});

function csvEscape(val) {
    const str = String(val);
    if (str.includes(",") || str.includes('"') || str.includes("\n")) {
        return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function extractSlug(url) {
    const match = url.match(/linkedin\.com\/in\/([^/?]+)/);
    return match ? match[1] : url;
}
