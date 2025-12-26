(function () {
  const DEFAULT_COUNTRY_CODE = '+998';

  const cleanDigits = (value) => (value || '').replace(/\D/g, '');

  const normalizeValue = (rawValue, defaultCode = DEFAULT_COUNTRY_CODE) => {
    const trimmed = (rawValue || '').trim();
    const digits = cleanDigits(trimmed);

    if (!digits) {
      return '';
    }

    if (trimmed.startsWith('+')) {
      return `+${digits}`;
    }

    if (digits.length <= 9) {
      const defaultDigits = cleanDigits(defaultCode) || cleanDigits(DEFAULT_COUNTRY_CODE);
      return `+${defaultDigits}${digits}`;
    }

    return `+${digits}`;
  };

  const formatNumber = (normalized) => {
    const digits = cleanDigits(normalized);
    if (!digits) {
      return '';
    }

    if (digits.startsWith('998') && digits.length >= 9) {
      const body = digits.slice(-9);
      return `+998 ${body.slice(0, 2)} ${body.slice(2, 5)} ${body.slice(5, 7)} ${body.slice(7)}`.trim();
    }

    if (digits.length > 10) {
      const country = digits.slice(0, digits.length - 10);
      const body = digits.slice(-10);
      return `+${country} ${body.slice(0, 3)} ${body.slice(3, 6)} ${body.slice(6, 10)}`.trim();
    }

    if (digits.length > 7) {
      const country = digits.slice(0, digits.length - 7);
      const body = digits.slice(-7);
      return `+${country} ${body.slice(0, 3)} ${body.slice(3, 5)} ${body.slice(5)}`.trim();
    }

    return `+${digits}`;
  };

  const enhanceInput = (input) => {
    if (!input || input.dataset.phoneEnhancementApplied === 'true') {
      return;
    }

    input.dataset.phoneEnhancementApplied = 'true';
    const defaultCode = input.dataset.defaultCountryCode || DEFAULT_COUNTRY_CODE;

    if (!input.placeholder) {
      input.placeholder = `${defaultCode.startsWith('+') ? defaultCode : `+${defaultCode}`} 90 123 45 67`;
    }

    const syncValue = () => {
      const normalized = normalizeValue(input.value, defaultCode);
      input.value = normalized ? formatNumber(normalized) : '';
    };

    syncValue();
    input.addEventListener('blur', syncValue);
    input.addEventListener('change', syncValue);
  };

  const scanForInputs = (root = document) => {
    const selector = '[data-uzbek-phone-input], [data-phone-input]';
    if (root instanceof Element && root.matches(selector)) {
      enhanceInput(root);
    }

    const candidates = root.querySelectorAll ? root.querySelectorAll(selector) : [];
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
