(() => {
  const listRoots = Array.from(document.querySelectorAll("[data-client-list]"));
  if (!listRoots.length) {
    return;
  }

  const normalizeText = (value) => (value || "").toLocaleLowerCase().replace(/\s+/g, " ").trim();

  const setVisible = (element, visible) => {
    if (element.tagName === "TR") {
      element.style.display = visible ? "" : "none";
      return;
    }

    element.classList.toggle("hidden", !visible);
  };

  const buildPageSequence = (currentPage, totalPages) => {
    const pages = [];
    let last = 0;

    for (let page = 1; page <= totalPages; page += 1) {
      if (
        page <= 1 ||
        (currentPage - 2 < page && page < currentPage + 2) ||
        page > totalPages - 1
      ) {
        if (last + 1 !== page) {
          pages.push(null);
        }
        pages.push(page);
        last = page;
      }
    }

    return pages;
  };

  const createPageButtonClassName = (variant, isActive) => {
    if (isActive) {
      return "inline-flex min-w-10 items-center justify-center rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white";
    }

    if (variant === "customer") {
      return "inline-flex min-w-10 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-pink-300 hover:text-rose-600";
    }

    return "inline-flex min-w-10 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-sky-300 hover:text-sky-700";
  };

  listRoots.forEach((root) => {
    const pager = root.querySelector("[data-client-list-pager]");
    if (!pager) {
      return;
    }

    const searchInput = root.querySelector("[data-client-list-search]");
    const countChip = root.querySelector("[data-client-list-count]");
    const perPageSelect = pager.querySelector("[data-client-list-per-page]");
    const nav = pager.querySelector("[data-client-list-nav]");
    const prevButton = pager.querySelector("[data-client-list-prev]");
    const nextButton = pager.querySelector("[data-client-list-next]");
    const pagesWrap = pager.querySelector("[data-client-list-pages]");
    const startEl = pager.querySelector("[data-client-list-start]");
    const endEl = pager.querySelector("[data-client-list-end]");
    const totalEl = pager.querySelector("[data-client-list-total]");
    const variant = pager.dataset.clientListVariant || "admin";

    let currentPage = 1;
    let applyQueued = false;

    const getPerPage = () => {
      const parsed = Number.parseInt(perPageSelect?.value || "10", 10);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : 10;
    };

    const getGroupedItems = () => {
      const groups = new Map();

      root.querySelectorAll("[data-client-list-item]").forEach((item) => {
        const group = item.dataset.clientListGroup || "default";
        if (!groups.has(group)) {
          groups.set(group, []);
        }
        groups.get(group).push(item);
      });

      return groups;
    };

    const renderPageButtons = (totalPages) => {
      if (!pagesWrap) {
        return;
      }

      pagesWrap.innerHTML = "";

      buildPageSequence(currentPage, totalPages).forEach((pageNumber) => {
        if (pageNumber === null) {
          const spacer = document.createElement("span");
          spacer.className = "inline-flex min-w-10 items-center justify-center px-1 text-sm text-slate-400";
          spacer.textContent = "...";
          pagesWrap.appendChild(spacer);
          return;
        }

        if (pageNumber === currentPage) {
          const active = document.createElement("span");
          active.className = createPageButtonClassName(variant, true);
          active.textContent = String(pageNumber);
          pagesWrap.appendChild(active);
          return;
        }

        const button = document.createElement("button");
        button.type = "button";
        button.className = createPageButtonClassName(variant, false);
        button.textContent = String(pageNumber);
        button.addEventListener("click", () => {
          currentPage = pageNumber;
          apply();
        });
        pagesWrap.appendChild(button);
      });
    };

    const apply = () => {
      applyQueued = false;

      const query = normalizeText(searchInput?.value || "");
      const groupedItems = getGroupedItems();
      const filteredGroups = new Map();

      groupedItems.forEach((items, groupName) => {
        filteredGroups.set(
          groupName,
          items.filter((item) => {
            if (!query) {
              return true;
            }
            const haystack = normalizeText(item.dataset.searchText || item.textContent || "");
            return haystack.includes(query);
          }),
        );
      });

      const totalItems = Math.max(
        0,
        ...Array.from(filteredGroups.values(), (items) => items.length),
      );
      const perPage = getPerPage();
      const totalPages = Math.max(Math.ceil(totalItems / perPage), 1);
      currentPage = totalItems ? Math.min(currentPage, totalPages) : 1;

      const startIndex = totalItems ? (currentPage - 1) * perPage : 0;
      const endIndex = totalItems ? Math.min(startIndex + perPage, totalItems) : 0;

      groupedItems.forEach((items, groupName) => {
        const visibleItems = new Set(
          (filteredGroups.get(groupName) || []).slice(startIndex, endIndex),
        );

        items.forEach((item) => {
          setVisible(item, visibleItems.has(item));
        });
      });

      if (startEl) {
        startEl.textContent = totalItems ? String(startIndex + 1) : "0";
      }
      if (endEl) {
        endEl.textContent = totalItems ? String(endIndex) : "0";
      }
      if (totalEl) {
        totalEl.textContent = String(totalItems);
      }

      if (countChip) {
        const suffix = countChip.dataset.clientListCountSuffix || "";
        const visibleCount = totalItems ? endIndex - startIndex : 0;
        countChip.textContent = suffix ? `${visibleCount} ${suffix}` : String(visibleCount);
      }

      pager.classList.toggle("hidden", totalItems === 0);

      if (nav) {
        nav.classList.toggle("hidden", totalItems <= perPage);
      }

      if (prevButton) {
        prevButton.disabled = currentPage <= 1 || totalItems === 0;
      }
      if (nextButton) {
        nextButton.disabled = currentPage >= totalPages || totalItems === 0;
      }

      renderPageButtons(totalPages);
    };

    const queueApply = () => {
      if (applyQueued) {
        return;
      }
      applyQueued = true;
      window.requestAnimationFrame(apply);
    };

    searchInput?.addEventListener("input", () => {
      currentPage = 1;
      queueApply();
    });

    perPageSelect?.addEventListener("change", () => {
      currentPage = 1;
      apply();
    });

    prevButton?.addEventListener("click", () => {
      if (currentPage <= 1) {
        return;
      }
      currentPage -= 1;
      apply();
    });

    nextButton?.addEventListener("click", () => {
      currentPage += 1;
      apply();
    });

    root.querySelectorAll("tbody").forEach((tbody) => {
      const observer = new MutationObserver(() => {
        queueApply();
      });

      observer.observe(tbody, { childList: true });
    });

    apply();
  });
})();
