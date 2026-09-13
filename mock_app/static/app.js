"use strict";

const loading = document.querySelector("[data-retry-ms]");
if (loading) {
  const delay = Number(loading.dataset.retryMs);
  if (Number.isFinite(delay) && delay >= 100 && delay <= 2000) {
    window.setTimeout(() => window.location.reload(), delay);
  }
}

const review = document.querySelector(".review-dialog");
if (review && typeof review.showModal === "function") {
  review.close();
  review.showModal();
  // Leaving requires an explicit choice. No account data is in the blocked page.
  review.addEventListener("cancel", (event) => event.preventDefault());
}
