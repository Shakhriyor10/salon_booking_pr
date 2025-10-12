(function () {
  const CART_STORAGE_KEY = 'salonCarts';
  const CART_TTL_MS = 30 * 60 * 1000; // 30 minutes

  function createEmptyStorage() {
    return { salons: {} };
  }

  function loadStorage() {
    try {
      const raw = localStorage.getItem(CART_STORAGE_KEY);
      if (!raw) {
        return createEmptyStorage();
      }

      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') {
        return createEmptyStorage();
      }

      if (!parsed.salons || typeof parsed.salons !== 'object') {
        parsed.salons = {};
      }

      return { salons: parsed.salons };
    } catch (error) {
      return createEmptyStorage();
    }
  }

  function saveStorage(storage) {
    try {
      localStorage.setItem(CART_STORAGE_KEY, JSON.stringify({ salons: storage.salons || {} }));
    } catch (error) {
      // Ignore write errors (e.g. storage quota exceeded)
    }
  }

  function normalizeItems(items) {
    if (!Array.isArray(items)) {
      return [];
    }

    const unique = [];
    const seen = new Set();

    items.forEach((value) => {
      const number = Number(value);
      if (Number.isNaN(number) || seen.has(number)) {
        return;
      }
      seen.add(number);
      unique.push(number);
    });

    return unique;
  }

  function cleanupExpired(storage) {
    const now = Date.now();
    const cleaned = {};
    let changed = false;

    Object.entries(storage.salons || {}).forEach(([salonId, entry]) => {
      if (!entry || typeof entry !== 'object') {
        changed = true;
        return;
      }

      const items = normalizeItems(entry.items);
      const updatedAt = Number(entry.updatedAt);

      if (!items.length) {
        changed = true;
        return;
      }

      if (!Number.isFinite(updatedAt) || now - updatedAt > CART_TTL_MS) {
        changed = true;
        return;
      }

      cleaned[salonId] = { items, updatedAt };
    });

    if (Object.keys(cleaned).length !== Object.keys(storage.salons || {}).length) {
      changed = true;
    }

    const cleanedStorage = { salons: cleaned };

    if (changed) {
      saveStorage(cleanedStorage);
    }

    return cleanedStorage;
  }

  function readStylistsMap(elementId) {
    const element = document.getElementById(elementId);
    if (!element) {
      return {};
    }

    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      return {};
    }
  }

  function normalizeStylistsMap(rawMap) {
    if (!rawMap || typeof rawMap !== 'object') {
      return {};
    }

    const normalized = {};
    Object.entries(rawMap).forEach(([serviceId, stylists]) => {
      const numericId = Number(serviceId);
      if (Number.isNaN(numericId) || !Array.isArray(stylists)) {
        return;
      }

      const uniqueStylists = normalizeItems(stylists);
      if (uniqueStylists.length) {
        normalized[numericId] = uniqueStylists;
      }
    });

    return normalized;
  }

  function migrateLegacyCart(defaultSalonId) {
    const legacyCartRaw = localStorage.getItem('cart');

    if (!legacyCartRaw) {
      localStorage.removeItem('cartTimestamp');
      localStorage.removeItem('currentSalonId');
      return;
    }

    let items;
    try {
      items = JSON.parse(legacyCartRaw);
    } catch (error) {
      items = [];
    }

    items = normalizeItems(items);
    const now = Date.now();

    let updatedAt = Number.parseInt(localStorage.getItem('cartTimestamp') || '', 10);
    if (!Number.isFinite(updatedAt)) {
      updatedAt = now;
    }

    const salonId = localStorage.getItem('currentSalonId') || defaultSalonId;
    const storage = loadStorage();

    if (items.length && now - updatedAt <= CART_TTL_MS) {
      storage.salons[String(salonId)] = { items, updatedAt };
      saveStorage(storage);
    }

    localStorage.removeItem('cart');
    localStorage.removeItem('cartTimestamp');
    localStorage.removeItem('currentSalonId');
  }

  window.initSalonCart = function initSalonCart(options) {
    if (!options || typeof options.salonId === 'undefined' || options.salonId === null) {
      return;
    }

    const salonKey = String(options.salonId);

    migrateLegacyCart(salonKey);

    let storage = cleanupExpired(loadStorage());

    function getItems() {
      storage = cleanupExpired(loadStorage());
      const entry = storage.salons[salonKey];
      if (!entry) {
        return [];
      }
      return normalizeItems(entry.items);
    }

    function saveItems(items) {
      storage = cleanupExpired(loadStorage());
      if (!items.length) {
        if (Object.prototype.hasOwnProperty.call(storage.salons, salonKey)) {
          delete storage.salons[salonKey];
          saveStorage(storage);
        }
        return;
      }

      storage.salons[salonKey] = {
        items: normalizeItems(items),
        updatedAt: Date.now(),
      };
      saveStorage(storage);
    }

    function clearItems() {
      saveItems([]);
    }

    const stylistsMap = normalizeStylistsMap(
      options.stylistsMap || readStylistsMap(options.stylistsMapElementId || 'service-stylists-map')
    );

    function getCommonStylists(serviceIds) {
      if (!serviceIds.length) {
        return [];
      }

      const [firstService, ...restServices] = serviceIds;
      const firstStylists = new Set(stylistsMap[firstService] || []);

      if (!firstStylists.size) {
        return [];
      }

      restServices.forEach((serviceId) => {
        const stylistsForService = new Set(stylistsMap[serviceId] || []);
        firstStylists.forEach((stylistId) => {
          if (!stylistsForService.has(stylistId)) {
            firstStylists.delete(stylistId);
          }
        });
      });

      return Array.from(firstStylists);
    }

    function hasCommonStylists(serviceIds) {
      if (!serviceIds.length) {
        return true;
      }

      return getCommonStylists(serviceIds).length > 0;
    }

    const addToCartButtons = Array.from(document.querySelectorAll('.add-to-cart'));
    const floatingCart = document.getElementById('floating-cart-button');
    const bookingButton = document.getElementById('go-to-booking');
    const warning = document.getElementById('cart-warning');
    const cartCount = document.getElementById('cart-count');
    const clearCartButton = document.getElementById('clear-cart');

    if (!floatingCart || !bookingButton || !cartCount) {
      return;
    }

    function updateCartUI() {
      const cartItems = getItems();
      const count = cartItems.length;
      const commonAvailable = hasCommonStylists(cartItems);

      cartCount.textContent = String(count);
      bookingButton.disabled = count === 0 || !commonAvailable;
      bookingButton.title = count > 0 && !commonAvailable
        ? 'Нет мастеров, выполняющих все выбранные услуги'
        : '';

      if (count > 0) {
        floatingCart.classList.remove('d-none');
        floatingCart.classList.add('show');
      } else {
        floatingCart.classList.remove('show');
        floatingCart.classList.add('d-none');
      }

      if (warning) {
        if (count > 0 && !commonAvailable) {
          warning.classList.remove('d-none');
        } else {
          warning.classList.add('d-none');
        }
      }

      addToCartButtons.forEach((button) => {
        const serviceId = Number(button.dataset.serviceId);
        if (Number.isNaN(serviceId)) {
          return;
        }

        if (cartItems.includes(serviceId)) {
          button.classList.add('added');
          button.textContent = '✅ Добавлено (нажмите, чтобы удалить)';
        } else {
          button.classList.remove('added');
          button.textContent = '➕ Добавить услугу';
        }
      });
    }

    addToCartButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const serviceId = Number(button.dataset.serviceId);
        if (Number.isNaN(serviceId)) {
          return;
        }

        const currentItems = getItems();

        if (currentItems.includes(serviceId)) {
          saveItems(currentItems.filter((id) => id !== serviceId));
          updateCartUI();
          return;
        }

        const updatedItems = [...currentItems, serviceId];
        if (!hasCommonStylists(updatedItems)) {
          alert('К сожалению, нет мастера, который выполняет все выбранные услуги.');
          return;
        }

        saveItems(updatedItems);
        updateCartUI();
      });
    });

    if (clearCartButton) {
      clearCartButton.addEventListener('click', () => {
        clearItems();
        updateCartUI();
      });
    }

    bookingButton.addEventListener('click', (event) => {
      const cartItems = getItems();
      if (!cartItems.length) {
        return;
      }

      if (!hasCommonStylists(cartItems)) {
        alert('К сожалению, нет мастера, который выполняет все выбранные услуги.');
        return;
      }

      const salonId = bookingButton.dataset.salonId || event.target.dataset.salonId;
      if (!salonId) {
        alert('Ошибка: salon ID не найден');
        return;
      }

      const params = new URLSearchParams();
      params.append('salon', salonId);
      cartItems.forEach((id) => params.append('services', id));

      window.location.href = `/booking/?${params.toString()}`;
    });

    window.addEventListener('storage', (event) => {
      if (!event || !event.key || event.key === CART_STORAGE_KEY) {
        updateCartUI();
      }
    });

    window.addEventListener('pageshow', () => {
      updateCartUI();
    });

    updateCartUI();
  };
})();