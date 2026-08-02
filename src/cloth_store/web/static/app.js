const STOREFRONT_URL =
  document.documentElement.dataset.storefrontUrl || "/final_catalog/storefront.json";
const SEARCH_DEBOUNCE_MS = 280;
const CATALOGUE_SLIDE_LABEL = "Catalogue view";

const elements = {
  searchInput: document.getElementById("catalog-search"),
  roleFilters: document.querySelectorAll(".role-filter"),
  statusBanner: document.getElementById("status-banner"),
  resultsMeta: document.getElementById("results-meta"),
  catalogSections: document.getElementById("catalog-sections"),
  statePanel: document.getElementById("state-panel"),
  stateTitle: document.getElementById("state-title"),
  stateMessage: document.getElementById("state-message"),
  gridTop: document.getElementById("grid-top"),
  gridBlazer: document.getElementById("grid-blazer"),
  gridDress: document.getElementById("grid-dress"),
  gridBottom: document.getElementById("grid-bottom"),
  sectionCounts: document.querySelectorAll("[data-count-for]"),
  cardTemplate: document.getElementById("item-card-template"),
  detailModal: document.getElementById("item-detail-modal"),
  detailClose: document.querySelector(".detail-close"),
  detailTitle: document.getElementById("detail-title"),
  detailDescription: document.getElementById("detail-description"),
  detailSlideLabel: document.getElementById("detail-slide-label"),
  detailAdvice: document.getElementById("detail-advice"),
  detailAdviceHeading: document.getElementById("detail-advice-heading"),
  detailAdviceText: document.getElementById("detail-advice-text"),
  detailError: document.getElementById("detail-error"),
  detailStage: document.getElementById("detail-stage"),
  detailStageImage: document.getElementById("detail-stage-image"),
  detailStageMessage: document.getElementById("detail-stage-message"),
  detailDots: document.getElementById("detail-dots"),
  detailSlideCount: document.getElementById("detail-slide-count"),
  detailNavPrev: document.querySelector(".detail-nav-prev"),
  detailNavNext: document.querySelector(".detail-nav-next"),
  outfitGeneratorOpen: document.getElementById("outfit-generator-open"),
  outfitGeneratorModal: document.getElementById("outfit-generator-modal"),
  outfitGeneratorClose: document.querySelector(".generator-close"),
  outfitGeneratorRegenerate: document.getElementById("generator-regenerate"),
  generatorHeroStage: document.getElementById("generator-hero-stage"),
  generatorHeroImage: document.getElementById("generator-hero-image"),
  generatorStageMessage: document.getElementById("generator-stage-message"),
  generatorSummary: document.getElementById("generator-summary"),
  generatorPieces: document.getElementById("generator-pieces"),
  generatorTopImage: document.getElementById("generator-top-image"),
  generatorTopName: document.getElementById("generator-top-name"),
  generatorTopDescription: document.getElementById("generator-top-description"),
  generatorBottomImage: document.getElementById("generator-bottom-image"),
  generatorBottomName: document.getElementById("generator-bottom-name"),
  generatorBottomDescription: document.getElementById("generator-bottom-description"),
  generatorError: document.getElementById("generator-error"),
  luckyPairOpen: document.getElementById("lucky-pair-open"),
  luckyPairModal: document.getElementById("lucky-pair-modal"),
  luckyPairClose: document.querySelector(".lucky-close"),
  luckyRegenerate: document.getElementById("lucky-regenerate"),
  luckyStageMessage: document.getElementById("lucky-stage-message"),
  luckyLookType: document.getElementById("lucky-look-type"),
  luckySummary: document.getElementById("lucky-summary"),
  luckyPieces: document.getElementById("lucky-pieces"),
  luckyPieceTemplate: document.getElementById("lucky-piece-template"),
  luckyError: document.getElementById("lucky-error"),
};

const state = {
  category: "",
  query: "",
  loading: false,
  requestToken: 0,
};

const catalogItemsById = new Map();
let storefrontData = null;

const modalState = {
  catalogId: null,
  item: null,
  slides: [],
  activeIndex: 0,
  fetchToken: 0,
  lastFocusedCard: null,
};

const generatorState = {
  fetchToken: 0,
  currentFixture: null,
  totalCandidates: 0,
  lastFocusedElement: null,
};

const luckyState = {
  fetchToken: 0,
  currentCatalogIds: [],
  totalCandidates: 0,
  lastFocusedElement: null,
};

const LUCKY_PIECE_KIND_LABELS = {
  top: "Top",
  blazer: "Blazer",
  bottom: "Bottom",
  dress: "Dress",
};

function setStatePanel({ visible, title, message }) {
  elements.statePanel.hidden = !visible;
  elements.stateTitle.textContent = title;
  elements.stateMessage.textContent = message;
}

function setStatusBanner(message) {
  if (!message) {
    elements.statusBanner.hidden = true;
    elements.statusBanner.textContent = "";
    return;
  }
  elements.statusBanner.hidden = false;
  elements.statusBanner.textContent = message;
}

function updateCategoryFilters(activeCategory) {
  elements.roleFilters.forEach((button) => {
    const isActive = button.dataset.category === activeCategory;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  });
}

function itemDisplayCategory(item) {
  return item.display_category || item.role;
}

const CATEGORY_LABELS = {
  "": "pieces",
  top: "tops",
  blazer: "blazers",
  dress: "dresses",
  bottom: "bottoms",
};

function normalizeSearchText(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function itemSearchText(item) {
  const parts = [
    item.display_name,
    item.description,
    item.role,
    item.fixture,
    item.garment_class,
    ...(item.tags || []),
    ...(item.labels || []).map((label) => `${label.kind} ${label.value}`),
  ];
  return normalizeSearchText(parts.filter(Boolean).join(" "));
}

function filterItems(items, { query, category }) {
  let filtered = items;
  if (category) {
    filtered = filtered.filter((item) => itemDisplayCategory(item) === category);
  }
  if (query) {
    const needle = normalizeSearchText(query);
    if (needle) {
      filtered = filtered.filter((item) => itemSearchText(item).includes(needle));
    }
  }
  return filtered;
}

function seededRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value = (value * 1664525 + 1013904223) >>> 0;
    return value / 0x100000000;
  };
}

function pickRandom(items, { excludeKey, excludeValue, seed } = {}) {
  if (!items.length) {
    return null;
  }
  let pool = items;
  if (excludeKey && excludeValue) {
    const filtered = items.filter((item) => item[excludeKey] !== excludeValue);
    if (filtered.length) {
      pool = filtered;
    }
  }
  const rng = seed == null ? Math.random : seededRandom(seed);
  const index = Math.floor(rng() * pool.length);
  return pool[index];
}

function pickLuckyLook({ excludeCatalogIds, seed } = {}) {
  const candidates = storefrontData?.lucky_look_candidates || [];
  if (!candidates.length) {
    return null;
  }

  let pool = candidates;
  if (excludeCatalogIds?.length) {
    const excluded = new Set(excludeCatalogIds);
    const filtered = candidates.filter((look) => {
      const ids = look.pieces.map((piece) => piece.catalog_id);
      if (ids.length !== excluded.size) {
        return true;
      }
      return !ids.every((id) => excluded.has(id));
    });
    if (filtered.length) {
      pool = filtered;
    }
  }

  const byType = {
    top_bottom: [],
    blazer_top_bottom: [],
    blazer_dress: [],
  };
  for (const look of pool) {
    if (byType[look.look_type]) {
      byType[look.look_type].push(look);
    }
  }

  const availableTypes = Object.keys(byType).filter((type) => byType[type].length);
  if (!availableTypes.length) {
    return null;
  }

  const rng = seed == null ? Math.random : seededRandom(seed);
  const typeIndex = Math.floor(rng() * availableTypes.length);
  const lookType = availableTypes[typeIndex];
  const typePool = byType[lookType];
  const lookIndex = Math.floor(rng() * typePool.length);
  return typePool[lookIndex];
}

async function loadStorefront() {
  const embedded = document.getElementById("storefront-data");
  if (embedded?.textContent?.trim()) {
    return JSON.parse(embedded.textContent);
  }
  const response = await fetch(STOREFRONT_URL);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Storefront request failed (${response.status})`);
  }
  return response.json();
}

function buildCard(item) {
  const fragment = elements.cardTemplate.content.cloneNode(true);
  const card = fragment.querySelector(".item-card");
  const image = fragment.querySelector(".item-image");
  const title = fragment.querySelector(".item-title");
  const description = fragment.querySelector(".item-description");

  card.dataset.catalogId = item.catalog_id;
  card.setAttribute("aria-label", `View details for ${item.display_name}`);
  image.src = item.image_url;
  image.alt = item.display_name;
  title.textContent = item.display_name;
  description.textContent = item.description;

  catalogItemsById.set(item.catalog_id, item);
  card.addEventListener("click", () => {
    openDetailModal(item.catalog_id, card);
  });

  return card;
}

function renderItems(items, activeCategory) {
  catalogItemsById.clear();

  const tops = items.filter((item) => itemDisplayCategory(item) === "top");
  const blazers = items.filter((item) => itemDisplayCategory(item) === "blazer");
  const dresses = items.filter((item) => item.role === "dress");
  const bottoms = items.filter((item) => item.role === "bottom");

  elements.gridTop.replaceChildren(...tops.map(buildCard));
  elements.gridBlazer.replaceChildren(...blazers.map(buildCard));
  elements.gridDress.replaceChildren(...dresses.map(buildCard));
  elements.gridBottom.replaceChildren(...bottoms.map(buildCard));

  document.querySelector('[data-section="top"]').dataset.empty = String(tops.length === 0);
  document.querySelector('[data-section="blazer"]').dataset.empty = String(blazers.length === 0);
  document.querySelector('[data-section="dress"]').dataset.empty = String(dresses.length === 0);
  document.querySelector('[data-section="bottom"]').dataset.empty = String(bottoms.length === 0);

  elements.sectionCounts.forEach((node) => {
    const category = node.dataset.countFor;
    const counts = {
      top: tops.length,
      blazer: blazers.length,
      dress: dresses.length,
      bottom: bottoms.length,
    };
    const count = counts[category] ?? 0;
    node.textContent = `${count} piece${count === 1 ? "" : "s"}`;
  });

  const showSections = items.length > 0;
  elements.catalogSections.hidden = !showSections;

  if (!showSections) {
    const emptyTitle = state.query ? "No matching pieces" : "Nothing to show yet";
    const emptyMessage = state.query
      ? "Try a broader colour, fabric, or silhouette — or clear the search to browse the full edit."
      : "The catalogue index is empty for the current filters.";
    setStatePanel({ visible: true, title: emptyTitle, message: emptyMessage });
    elements.resultsMeta.textContent = "";
    return;
  }

  setStatePanel({ visible: false, title: "", message: "" });

  const categoryLabel = CATEGORY_LABELS[activeCategory] || "pieces";
  const queryLabel = state.query ? ` for “${state.query}”` : "";
  elements.resultsMeta.textContent = `Showing ${items.length} ${categoryLabel}${queryLabel}`;
}

function buildDetailSlides(item, styling) {
  const slides = [
    {
      kind: "catalog",
      imageUrl: item.image_url,
      slideLabel: CATALOGUE_SLIDE_LABEL,
      alt: item.display_name,
      isSquare: true,
    },
  ];

  for (const association of styling.associations || []) {
    const selfie = association.selfie;
    if (!selfie?.available || !selfie.image_url) {
      continue;
    }
    const adviceText = association.advice_text || association.caption || "";
    slides.push({
      kind: "selfie",
      imageUrl: selfie.image_url,
      adviceTitle: association.advice_title || "Fashion Advice",
      adviceText,
      alt: adviceText,
      isSquare: false,
    });
  }

  return slides;
}

function hideDetailAdvicePanel() {
  elements.detailAdvice.hidden = true;
  elements.detailAdviceHeading.textContent = "";
  elements.detailAdviceText.textContent = "";
  elements.detailSlideLabel.hidden = true;
  elements.detailSlideLabel.textContent = "";
}

function renderDetailAdvicePanel(slide) {
  hideDetailAdvicePanel();

  if (slide.kind === "catalog") {
    elements.detailSlideLabel.hidden = false;
    elements.detailSlideLabel.textContent = slide.slideLabel;
    return;
  }

  if (slide.adviceText) {
    elements.detailAdvice.hidden = false;
    elements.detailAdviceHeading.textContent = slide.adviceTitle;
    elements.detailAdviceText.textContent = slide.adviceText;
  }
}

function setDetailLoading(item) {
  elements.detailTitle.textContent = item.display_name;
  elements.detailDescription.textContent = item.description;
  hideDetailAdvicePanel();
  elements.detailError.hidden = true;
  elements.detailError.textContent = "";

  elements.detailStageImage.hidden = true;
  elements.detailStageImage.removeAttribute("src");
  elements.detailStageMessage.hidden = false;
  elements.detailStageMessage.textContent = "Loading styling…";

  elements.detailDots.replaceChildren();
  elements.detailSlideCount.textContent = "";
  elements.detailNavPrev.disabled = true;
  elements.detailNavNext.disabled = true;
}

function setDetailError(message) {
  elements.detailStageImage.hidden = true;
  elements.detailStageMessage.hidden = false;
  elements.detailStageMessage.textContent = "Unable to load this piece.";
  elements.detailError.hidden = false;
  elements.detailError.textContent = message;
  hideDetailAdvicePanel();
  elements.detailDots.replaceChildren();
  elements.detailSlideCount.textContent = "";
  elements.detailNavPrev.disabled = true;
  elements.detailNavNext.disabled = true;
}

function renderDetailDots() {
  elements.detailDots.replaceChildren();

  modalState.slides.forEach((slide, index) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "detail-dot";
    dot.setAttribute("role", "tab");
    dot.setAttribute("aria-label", `Show image ${index + 1} of ${modalState.slides.length}`);
    dot.setAttribute("aria-selected", String(index === modalState.activeIndex));
    dot.addEventListener("click", () => {
      setActiveSlide(index);
    });
    elements.detailDots.appendChild(dot);
  });
}

function updateCarouselControls() {
  const total = modalState.slides.length;
  const index = modalState.activeIndex;
  const hasMultiple = total > 1;

  elements.detailNavPrev.disabled = !hasMultiple || index === 0;
  elements.detailNavNext.disabled = !hasMultiple || index === total - 1;
  elements.detailSlideCount.textContent = total > 0 ? `${index + 1} / ${total}` : "";

  elements.detailDots.querySelectorAll(".detail-dot").forEach((dot, dotIndex) => {
    dot.setAttribute("aria-selected", String(dotIndex === index));
  });
}

function setActiveSlide(index) {
  if (index < 0 || index >= modalState.slides.length) {
    return;
  }

  modalState.activeIndex = index;
  const slide = modalState.slides[index];

  elements.detailStageMessage.hidden = true;
  elements.detailStageImage.hidden = false;
  elements.detailStageImage.src = slide.imageUrl;
  elements.detailStageImage.alt = slide.alt;
  elements.detailStageImage.classList.toggle("is-catalog", slide.isSquare);
  elements.detailStageImage.classList.toggle("is-selfie", !slide.isSquare);

  renderDetailAdvicePanel(slide);
  updateCarouselControls();
}

function renderDetailContent(item, styling) {
  modalState.slides = buildDetailSlides(item, styling);
  modalState.activeIndex = 0;

  elements.detailTitle.textContent = styling.display_name || item.display_name;
  elements.detailDescription.textContent = styling.description || item.description;
  elements.detailError.hidden = true;
  elements.detailError.textContent = "";

  if (modalState.slides.length === 0) {
    setDetailError("No images are available for this piece.");
    return;
  }

  renderDetailDots();
  setActiveSlide(0);
}

function resetDetailModalState() {
  modalState.catalogId = null;
  modalState.item = null;
  modalState.slides = [];
  modalState.activeIndex = 0;
}

async function openDetailModal(catalogId, cardElement) {
  const item = catalogItemsById.get(catalogId);
  if (!item || !elements.detailModal) {
    return;
  }

  modalState.lastFocusedCard = cardElement;
  modalState.catalogId = catalogId;
  modalState.item = item;
  modalState.fetchToken += 1;
  const token = modalState.fetchToken;

  setDetailLoading(item);
  elements.detailModal.showModal();
  elements.detailClose.focus();

  const styling = storefrontData?.styling?.[catalogId];
  if (token !== modalState.fetchToken) {
    return;
  }
  if (!styling) {
    setDetailError("We couldn't load styling details for this piece.");
    return;
  }
  renderDetailContent(item, styling);
}

function closeDetailModal() {
  if (!elements.detailModal.open) {
    return;
  }

  const card = modalState.lastFocusedCard;
  elements.detailModal.close();
  resetDetailModalState();

  if (card) {
    card.focus();
  }
}

function showPreviousSlide() {
  if (modalState.activeIndex > 0) {
    setActiveSlide(modalState.activeIndex - 1);
  }
}

function showNextSlide() {
  if (modalState.activeIndex < modalState.slides.length - 1) {
    setActiveSlide(modalState.activeIndex + 1);
  }
}

function setGeneratorLoading() {
  elements.generatorHeroImage.hidden = true;
  elements.generatorHeroImage.removeAttribute("src");
  elements.generatorStageMessage.hidden = false;
  elements.generatorStageMessage.textContent = "Composing your look…";

  elements.generatorSummary.hidden = true;
  elements.generatorSummary.textContent = "";
  elements.generatorPieces.hidden = true;
  elements.generatorError.hidden = true;
  elements.generatorError.textContent = "";
  elements.outfitGeneratorRegenerate.disabled = true;
}

function setGeneratorError(message) {
  elements.generatorHeroImage.hidden = true;
  elements.generatorStageMessage.hidden = false;
  elements.generatorStageMessage.textContent = "Unable to generate an outfit.";
  elements.generatorSummary.hidden = true;
  elements.generatorPieces.hidden = true;
  elements.generatorError.hidden = false;
  elements.generatorError.textContent = message;
  elements.outfitGeneratorRegenerate.disabled = generatorState.totalCandidates > 1;
}

function renderGeneratorCandidate(candidate) {
  generatorState.totalCandidates = storefrontData?.outfit_candidates?.length || 0;

  if (!candidate) {
    setGeneratorError("No complete outfit pairs are available right now.");
    generatorState.currentFixture = null;
    return;
  }

  generatorState.currentFixture = candidate.fixture;

  elements.generatorStageMessage.hidden = true;
  elements.generatorHeroImage.hidden = false;
  elements.generatorHeroImage.src = candidate.selfie.image_url;
  elements.generatorHeroImage.alt = `Mirror selfie wearing ${candidate.top.display_name} and ${candidate.bottom.display_name}`;

  elements.generatorSummary.hidden = false;
  elements.generatorSummary.textContent = `${candidate.top.display_name} with ${candidate.bottom.display_name.toLowerCase()}.`;

  elements.generatorPieces.hidden = false;
  elements.generatorTopImage.src = candidate.top.image_url;
  elements.generatorTopImage.alt = candidate.top.display_name;
  elements.generatorTopName.textContent = candidate.top.display_name;
  elements.generatorTopDescription.textContent = candidate.top.description;

  elements.generatorBottomImage.src = candidate.bottom.image_url;
  elements.generatorBottomImage.alt = candidate.bottom.display_name;
  elements.generatorBottomName.textContent = candidate.bottom.display_name;
  elements.generatorBottomDescription.textContent = candidate.bottom.description;

  elements.generatorError.hidden = true;
  elements.generatorError.textContent = "";
  elements.outfitGeneratorRegenerate.disabled = generatorState.totalCandidates <= 1;
}

function resetGeneratorState() {
  generatorState.fetchToken += 1;
  generatorState.currentFixture = null;
  generatorState.totalCandidates = 0;
}

function loadGeneratedOutfit({ excludeFixture, seed } = {}) {
  const token = ++generatorState.fetchToken;
  setGeneratorLoading();

  const candidate = pickRandom(storefrontData?.outfit_candidates || [], {
    excludeKey: "fixture",
    excludeValue: excludeFixture,
    seed,
  });
  if (token !== generatorState.fetchToken) {
    return;
  }
  renderGeneratorCandidate(candidate);
}

function openOutfitGeneratorModal() {
  if (!elements.outfitGeneratorModal) {
    return;
  }

  generatorState.lastFocusedElement = document.activeElement;
  resetGeneratorState();
  elements.outfitGeneratorModal.showModal();
  elements.outfitGeneratorClose.focus();
  loadGeneratedOutfit();
}

function closeOutfitGeneratorModal() {
  if (!elements.outfitGeneratorModal?.open) {
    return;
  }

  const restoreFocus = generatorState.lastFocusedElement;
  elements.outfitGeneratorModal.close();
  resetGeneratorState();

  if (restoreFocus && typeof restoreFocus.focus === "function") {
    restoreFocus.focus();
  }
}

function regenerateOutfit() {
  loadGeneratedOutfit({ excludeFixture: generatorState.currentFixture });
}

function buildLuckyPieceCard(piece) {
  const fragment = elements.luckyPieceTemplate.content.cloneNode(true);
  const card = fragment.querySelector(".lucky-piece-card");
  const image = fragment.querySelector(".lucky-piece-image");
  const label = fragment.querySelector(".generator-piece-label");
  const name = fragment.querySelector(".generator-piece-name");
  const description = fragment.querySelector(".generator-piece-description");

  const kindLabel = LUCKY_PIECE_KIND_LABELS[piece.kind] || piece.kind;
  card.setAttribute("aria-labelledby", `lucky-piece-${piece.catalog_id}`);
  name.id = `lucky-piece-${piece.catalog_id}`;
  label.textContent = kindLabel;
  image.src = piece.image_url;
  image.alt = piece.display_name;
  name.textContent = piece.display_name;
  description.textContent = piece.description;

  return card;
}

function setLuckyLoading() {
  elements.luckyStageMessage.hidden = false;
  elements.luckyStageMessage.textContent = "Finding a new pairing…";
  elements.luckyLookType.hidden = true;
  elements.luckyLookType.textContent = "";
  elements.luckySummary.hidden = true;
  elements.luckySummary.textContent = "";
  elements.luckyPieces.hidden = true;
  elements.luckyPieces.replaceChildren();
  elements.luckyError.hidden = true;
  elements.luckyError.textContent = "";
  elements.luckyRegenerate.disabled = true;
}

function setLuckyError(message) {
  elements.luckyStageMessage.hidden = false;
  elements.luckyStageMessage.textContent = "Unable to suggest a pairing.";
  elements.luckyLookType.hidden = true;
  elements.luckySummary.hidden = true;
  elements.luckyPieces.hidden = true;
  elements.luckyPieces.replaceChildren();
  elements.luckyError.hidden = true;
  elements.luckyError.textContent = message;
  elements.luckyRegenerate.disabled = luckyState.totalCandidates > 1;
}

function renderLuckyLook(look) {
  luckyState.totalCandidates = storefrontData?.lucky_look_candidates?.length || 0;

  if (!look) {
    setLuckyError("No new catalogue pairings are available right now.");
    luckyState.currentCatalogIds = [];
    return;
  }

  luckyState.currentCatalogIds = look.pieces.map((piece) => piece.catalog_id);

  elements.luckyStageMessage.hidden = true;

  elements.luckyLookType.hidden = false;
  elements.luckyLookType.textContent = look.look_type_label || look.look_type;

  elements.luckySummary.hidden = false;
  elements.luckySummary.textContent =
    look.summary ||
    look.pieces.map((piece) => piece.display_name).join(" with ");

  elements.luckyPieces.hidden = false;
  elements.luckyPieces.dataset.pieceCount = String(look.pieces.length);
  elements.luckyPieces.replaceChildren(...look.pieces.map(buildLuckyPieceCard));

  elements.luckyError.hidden = true;
  elements.luckyError.textContent = "";
  elements.luckyRegenerate.disabled = luckyState.totalCandidates <= 1;
}

function resetLuckyState() {
  luckyState.fetchToken += 1;
  luckyState.currentCatalogIds = [];
  luckyState.totalCandidates = 0;
}

function loadLuckyLook({ excludeCatalogIds, seed } = {}) {
  const token = ++luckyState.fetchToken;
  setLuckyLoading();

  const look = pickLuckyLook({ excludeCatalogIds, seed });
  if (token !== luckyState.fetchToken) {
    return;
  }
  renderLuckyLook(look);
}

function openLuckyPairModal() {
  if (!elements.luckyPairModal) {
    return;
  }

  luckyState.lastFocusedElement = document.activeElement;
  resetLuckyState();
  elements.luckyPairModal.showModal();
  elements.luckyPairClose.focus();
  loadLuckyLook();
}

function closeLuckyPairModal() {
  if (!elements.luckyPairModal?.open) {
    return;
  }

  const restoreFocus = luckyState.lastFocusedElement;
  elements.luckyPairModal.close();
  resetLuckyState();

  if (restoreFocus && typeof restoreFocus.focus === "function") {
    restoreFocus.focus();
  }
}

function regenerateLuckyPair() {
  loadLuckyLook({
    excludeCatalogIds: luckyState.currentCatalogIds,
  });
}

async function loadCatalog() {
  const token = ++state.requestToken;
  state.loading = true;
  setStatusBanner("");
  setStatePanel({
    visible: true,
    title: "Loading pieces…",
    message: "Gathering the latest edit from the catalogue.",
  });
  elements.catalogSections.hidden = true;

  try {
    if (!storefrontData) {
      storefrontData = await loadStorefront();
    }
    if (token !== state.requestToken) {
      return;
    }
    const items = filterItems(storefrontData.items || [], {
      query: state.query,
      category: state.category,
    });
    renderItems(items, state.category);
  } catch (error) {
    if (token !== state.requestToken) {
      return;
    }
    setStatePanel({
      visible: true,
      title: "Catalogue unavailable",
      message: "We couldn't load the catalogue data. Refresh to try again.",
    });
    setStatusBanner(error.message);
    elements.catalogSections.hidden = true;
    elements.resultsMeta.textContent = "";
  } finally {
    if (token === state.requestToken) {
      state.loading = false;
    }
  }
}

let searchTimer;
function scheduleSearch() {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.query = elements.searchInput.value.trim();
    loadCatalog();
  }, SEARCH_DEBOUNCE_MS);
}

elements.searchInput.addEventListener("input", scheduleSearch);

elements.roleFilters.forEach((button) => {
  button.addEventListener("click", () => {
    const category = button.dataset.category || "";
    state.category = category;
    updateCategoryFilters(category);
    loadCatalog();
  });
});

if (elements.detailModal) {
  elements.detailClose.addEventListener("click", closeDetailModal);
  elements.detailNavPrev.addEventListener("click", showPreviousSlide);
  elements.detailNavNext.addEventListener("click", showNextSlide);

  elements.detailModal.addEventListener("click", (event) => {
    if (event.target === elements.detailModal) {
      closeDetailModal();
    }
  });

  elements.detailModal.addEventListener("cancel", () => {
    const card = modalState.lastFocusedCard;
    resetDetailModalState();
    if (card) {
      window.setTimeout(() => card.focus(), 0);
    }
  });

  elements.detailModal.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      showPreviousSlide();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      showNextSlide();
    }
  });
}

if (elements.outfitGeneratorModal) {
  elements.outfitGeneratorOpen?.addEventListener("click", openOutfitGeneratorModal);
  elements.outfitGeneratorClose?.addEventListener("click", closeOutfitGeneratorModal);
  elements.outfitGeneratorRegenerate?.addEventListener("click", regenerateOutfit);

  elements.outfitGeneratorModal.addEventListener("click", (event) => {
    if (event.target === elements.outfitGeneratorModal) {
      closeOutfitGeneratorModal();
    }
  });

  elements.outfitGeneratorModal.addEventListener("cancel", () => {
    const restoreFocus = generatorState.lastFocusedElement;
    resetGeneratorState();
    if (restoreFocus && typeof restoreFocus.focus === "function") {
      window.setTimeout(() => restoreFocus.focus(), 0);
    }
  });
}

if (elements.luckyPairModal) {
  elements.luckyPairOpen?.addEventListener("click", openLuckyPairModal);
  elements.luckyPairClose?.addEventListener("click", closeLuckyPairModal);
  elements.luckyRegenerate?.addEventListener("click", regenerateLuckyPair);

  elements.luckyPairModal.addEventListener("click", (event) => {
    if (event.target === elements.luckyPairModal) {
      closeLuckyPairModal();
    }
  });

  elements.luckyPairModal.addEventListener("cancel", () => {
    const restoreFocus = luckyState.lastFocusedElement;
    resetLuckyState();
    if (restoreFocus && typeof restoreFocus.focus === "function") {
      window.setTimeout(() => restoreFocus.focus(), 0);
    }
  });
}

loadCatalog();
