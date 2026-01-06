(function () {
  const GROUP_SIZES = [2, 3, 2, 2];
  const MAX_DIGITS = GROUP_SIZES.reduce((sum, size) => sum + size, 0);

  const formatDigits = (digits) => {
    const clean = (digits || '').replace(/\D/g, '').slice(0, MAX_DIGITS);
    const parts = [];
    let index = 0;

    for (const size of GROUP_SIZES) {
      if (clean.length > index) {
        const nextIndex = index + size;
        parts.push(clean.slice(index, nextIndex));
      }
      index += size;
    }

    return parts.join('-');
  };

  const applyMask = (input) => {
    if (!input) {
      return;
    }

    const formatted = formatDigits(input.value);
    if (input.value !== formatted) {
      input.value = formatted;
    }
    return formatted;
  };

  const handleInput = (event) => {
    const input = event.target;
    const formatted = formatDigits(input.value);
    if (input.value !== formatted) {
      const selectionPosition = formatted.length;
      input.value = formatted;

      if (document.activeElement === input && typeof input.setSelectionRange === 'function') {
        try {
          input.setSelectionRange(selectionPosition, selectionPosition);
        } catch (error) {
          // Ignore browsers that do not support selection updates on this input type.
        }
      }
    }
  };

  const enhanceInput = (input) => {
    if (!input || input.dataset.uzbekPhoneMaskApplied === 'true') {
      return;
    }

    input.dataset.uzbekPhoneMaskApplied = 'true';
    applyMask(input);

    input.addEventListener('input', handleInput);
    input.addEventListener('blur', () => applyMask(input));
    input.addEventListener('focus', () => applyMask(input));
  };

  const scanForInputs = (root = document) => {
    if (!root) {
      return;
    }

    if (root instanceof Element && root.matches('[data-uzbek-phone-input]')) {
      enhanceInput(root);
    }

    const candidates = root.querySelectorAll ? root.querySelectorAll('[data-uzbek-phone-input]') : [];
    candidates.forEach(enhanceInput);
  };

  document.addEventListener('DOMContentLoaded', () => {
    scanForInputs();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === Node.ELEMENT_NODE) {
            scanForInputs(node);
          }
        });
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  });
})();