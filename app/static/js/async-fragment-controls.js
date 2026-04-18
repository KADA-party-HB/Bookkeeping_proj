(() => {
  const fragmentRoots = Array.from(document.querySelectorAll("[data-async-fragment]"));
  if (!fragmentRoots.length || typeof window.fetch !== "function") {
    return;
  }

  const activeRequests = new WeakMap();

  const buildFetchUrl = (baseUrl, partial) => {
    const url = new URL(baseUrl, window.location.href);
    url.searchParams.set("partial", partial);
    return url;
  };

  const publicUrl = (urlLike) => {
    const url = new URL(urlLike, window.location.href);
    url.searchParams.delete("partial");
    return url;
  };

  const renderError = (root, baseUrl) => {
    root.innerHTML = `
      <div class="rounded-[1.5rem] border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-900">
        <div>Could not load this section.</div>
        <button
          type="button"
          class="mt-3 inline-flex items-center justify-center rounded-xl border border-rose-300 bg-white px-3 py-2 text-sm font-medium text-rose-800 transition hover:bg-rose-100"
          data-async-fragment-retry
        >
          Retry
        </button>
      </div>
    `;

    root.querySelector("[data-async-fragment-retry]")?.addEventListener("click", () => {
      loadRoot(root, baseUrl);
    });
  };

  const loadRoot = async (root, baseUrl) => {
    const partial = root.dataset.asyncFragment;
    if (!partial) {
      return;
    }

    activeRequests.get(root)?.abort();
    const controller = new AbortController();
    activeRequests.set(root, controller);
    root.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(buildFetchUrl(baseUrl, partial), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Request failed with ${response.status}`);
      }

      const html = await response.text();
      if (controller.signal.aborted) {
        return;
      }

      root.innerHTML = html;
      root.removeAttribute("aria-busy");
      document.dispatchEvent(
        new CustomEvent("async-fragment:rendered", {
          detail: { partial, root },
        }),
      );
    } catch (error) {
      if (controller.signal.aborted || error?.name === "AbortError") {
        return;
      }

      root.removeAttribute("aria-busy");
      renderError(root, baseUrl);
      console.error(error);
    }
  };

  const reloadAll = (baseUrl) => Promise.all(
    fragmentRoots.map((root) => loadRoot(root, baseUrl)),
  );

  const navigate = (nextUrl, { replace = false } = {}) => {
    const cleanUrl = publicUrl(nextUrl);
    if (replace) {
      window.history.replaceState({}, "", cleanUrl.toString());
    } else {
      window.history.pushState({}, "", cleanUrl.toString());
    }
    reloadAll(cleanUrl);
  };

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-async-nav]");
    if (!link || !link.closest("[data-async-fragment]")) {
      return;
    }

    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (link.target && link.target !== "_self") ||
      link.hasAttribute("download")
    ) {
      return;
    }

    event.preventDefault();
    navigate(link.href);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (
      !(form instanceof HTMLFormElement) ||
      !form.matches("form[data-async-nav]") ||
      !form.closest("[data-async-fragment]")
    ) {
      return;
    }

    if ((form.method || "get").toUpperCase() !== "GET") {
      return;
    }

    event.preventDefault();

    const url = new URL(form.action || window.location.href, window.location.href);
    url.search = "";

    const formData = new FormData(form);
    for (const [key, value] of formData.entries()) {
      if (typeof value === "string" && value !== "") {
        url.searchParams.append(key, value);
      }
    }

    navigate(url);
  });

  window.addEventListener("popstate", () => {
    reloadAll(publicUrl(window.location.href));
  });

  reloadAll(publicUrl(window.location.href));
})();
