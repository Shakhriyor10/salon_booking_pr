document.addEventListener('DOMContentLoaded', () => {
    let dynamicRoot = document.querySelector('[data-dynamic-container]');

    if (!dynamicRoot) {
        return;
    }

    const pendingFormTimeouts = new Map();

    const clearPendingTimeout = (form) => {
        const timeoutId = pendingFormTimeouts.get(form);
        if (timeoutId) {
            clearTimeout(timeoutId);
            pendingFormTimeouts.delete(form);
        }
    };

    const setPendingTimeout = (form, delay, callback) => {
        clearPendingTimeout(form);
        const timeoutId = window.setTimeout(() => {
            pendingFormTimeouts.delete(form);
            callback();
        }, delay);
        pendingFormTimeouts.set(form, timeoutId);
    };

    async function loadAndSwap(url) {
        if (!dynamicRoot) {
            return;
        }

        dynamicRoot.classList.add('is-loading');

        try {
            const response = await fetch(url.toString(), {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`Network response was not ok: ${response.status}`);
            }

            const text = await response.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString(text, 'text/html');
            const newRoot = doc.querySelector('[data-dynamic-container]');
            const newTitle = doc.querySelector('title');

            if (!newRoot) {
                window.location.href = url.toString();
                return;
            }

            dynamicRoot.replaceWith(newRoot);
            dynamicRoot = newRoot;

            if (newTitle) {
                document.title = newTitle.textContent;
            }

            window.history.replaceState({}, document.title, url.pathname + url.search);
        } catch (error) {
            console.error('Ошибка при обновлении страницы', error);
            window.location.href = url.toString();
        } finally {
            dynamicRoot = document.querySelector('[data-dynamic-container]');
            if (dynamicRoot) {
                dynamicRoot.classList.remove('is-loading');
            }
        }
    }

    const buildFormUrl = (form) => {
        const action = form.getAttribute('action') || window.location.pathname;
        const url = new URL(action, window.location.origin);
        const formData = new FormData(form);

        for (const [key, value] of formData.entries()) {
            if (value === '') {
                continue;
            }
            url.searchParams.append(key, value);
        }

        return url;
    };

    const submitAjaxForm = async (form) => {
        const url = buildFormUrl(form);
        await loadAndSwap(url);
    };

    document.addEventListener('submit', (event) => {
        const form = event.target;

        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        if (!form.matches('[data-dynamic-form]')) {
            return;
        }

        if ((form.method || 'get').toLowerCase() !== 'get') {
            return;
        }

        event.preventDefault();
        clearPendingTimeout(form);
        submitAjaxForm(form);
    });

    document.addEventListener('change', (event) => {
        const target = event.target;

        if (!(target instanceof HTMLElement)) {
            return;
        }

        if (!target.matches('[data-auto-submit]')) {
            return;
        }

        const form = target.closest('form[data-dynamic-form]');

        if (!form) {
            return;
        }

        const delayAttr = target.dataset.autoSubmitDelay || form.dataset.autoSubmitDelay;
        const delay = delayAttr ? parseInt(delayAttr, 10) : 0;

        const triggerSubmit = () => {
            submitAjaxForm(form);
        };

        if (delay && !Number.isNaN(delay) && delay > 0) {
            setPendingTimeout(form, delay, triggerSubmit);
        } else {
            triggerSubmit();
        }
    });

    document.addEventListener('click', (event) => {
        const link = event.target instanceof Element ? event.target.closest('[data-dynamic-link]') : null;

        if (!link) {
            return;
        }

        const href = link.getAttribute('href');

        if (!href) {
            return;
        }

        event.preventDefault();
        const url = new URL(href, window.location.href);
        loadAndSwap(url);
    });
});
