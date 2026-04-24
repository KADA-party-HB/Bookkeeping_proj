(() => {
  const modal = document.querySelector("[data-price-sync-modal]");
  if (!modal) {
    return;
  }

  const openButtons = Array.from(document.querySelectorAll("[data-price-sync-open]"));
  const closeButtons = Array.from(document.querySelectorAll("[data-price-sync-close]"));
  const pickButton = modal.querySelector("[data-price-sync-pick]");
  const form = modal.querySelector("[data-price-sync-form]");
  const fileInput = modal.querySelector("[data-price-sync-input]");
  const dropzone = modal.querySelector("[data-price-sync-dropzone]");
  const fileLabel = modal.querySelector("[data-price-sync-file-label]");
  const submitButton = modal.querySelector("[data-price-sync-submit]");
  const body = document.body;

  if (!form || !fileInput || !dropzone || !fileLabel || !submitButton) {
    return;
  }

  const setOpen = (isOpen) => {
    modal.classList.toggle("hidden", !isOpen);
    modal.classList.toggle("flex", isOpen);
    modal.setAttribute("aria-hidden", isOpen ? "false" : "true");
    body.classList.toggle("overflow-hidden", isOpen);

    if (isOpen) {
      dropzone.focus();
    }
  };

  const updateSelectedFileState = () => {
    const selectedFile = fileInput.files && fileInput.files[0];
    const hasFile = Boolean(selectedFile);

    fileLabel.textContent = hasFile
      ? `Selected file: ${selectedFile.name}`
      : "No file selected yet.";
    submitButton.disabled = !hasFile;
  };

  const assignFiles = (files) => {
    if (!files || !files.length) {
      return;
    }

    const transfer = new DataTransfer();
    Array.from(files).forEach((file) => transfer.items.add(file));
    fileInput.files = transfer.files;
    updateSelectedFileState();
  };

  openButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setOpen(true);
      const details = button.closest("details");
      if (details) {
        details.open = false;
      }
    });
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setOpen(false);
    });
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      setOpen(false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal.getAttribute("aria-hidden") === "false") {
      setOpen(false);
    }
  });

  pickButton?.addEventListener("click", () => {
    fileInput.click();
  });

  dropzone.addEventListener("click", () => {
    fileInput.click();
  });

  dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", updateSelectedFileState);

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("border-amber-500", "bg-amber-50");
    });
  });

  ["dragleave", "dragend", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("border-amber-500", "bg-amber-50");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    const droppedFiles = event.dataTransfer?.files;
    if (!droppedFiles || !droppedFiles.length) {
      return;
    }

    assignFiles(droppedFiles);
  });

  form.addEventListener("submit", () => {
    submitButton.disabled = true;
    submitButton.textContent = "Uploading...";
  });

  updateSelectedFileState();
})();
