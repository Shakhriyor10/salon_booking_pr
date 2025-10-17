(function () {
  const root = document.getElementById('support-chat-root');
  if (!root) {
    return;
  }

  const toggleButton = document.getElementById('support-chat-toggle');
  const windowEl = document.getElementById('support-chat-window');
  const form = document.getElementById('support-chat-form');
  const messagesEl = document.getElementById('support-chat-messages');
  const nameFieldRow = document.getElementById('support-chat-name-row');
  const emailFieldRow = document.getElementById('support-chat-email-row');
  const threadTitle = document.getElementById('support-chat-title');
  const errorEl = document.getElementById('support-chat-error');
  const messageField = form.querySelector('textarea[name="message"]');
  const submitButton = form.querySelector('button[type="submit"]');
  const attachmentInput = form.querySelector('input[name="attachment"]');

  let threadId = null;

  function getCsrfToken() {
    const cookie = document.cookie.match(/csrftoken=([^;]+)/);
    if (cookie) {
      return cookie[1];
    }
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return csrfInput ? csrfInput.value : '';
  }

  function renderMessage(message) {
    if (messagesEl.firstElementChild && !messagesEl.firstElementChild.dataset.messageId) {
      messagesEl.innerHTML = '';
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'support-chat__message ' + (message.is_from_staff ? 'support-chat__message--staff' : 'support-chat__message--user');
    wrapper.dataset.messageId = message.id;
    const bubble = document.createElement('div');
    bubble.className = 'support-chat__bubble';

    if (message.body) {
      const textEl = document.createElement('p');
      textEl.className = 'support-chat__text';
      textEl.innerText = message.body;
      bubble.appendChild(textEl);
    }

    if (message.attachment) {
      const attachmentWrapper = document.createElement('div');
      attachmentWrapper.className = 'support-chat__attachment';
      const img = document.createElement('img');
      img.src = message.attachment.url;
      img.alt = message.attachment.name || 'Вложение';
      img.loading = 'lazy';
      attachmentWrapper.appendChild(img);
      bubble.appendChild(attachmentWrapper);
    }

    if (!message.body && !message.attachment) {
      bubble.innerText = '[Пустое сообщение]';
    }

    const meta = document.createElement('div');
    meta.className = 'support-chat__meta';
    meta.innerText = message.created_at;

    wrapper.appendChild(bubble);
    wrapper.appendChild(meta);
    messagesEl.appendChild(wrapper);
  }

  function clearMessages() {
    while (messagesEl.firstChild) {
      messagesEl.removeChild(messagesEl.firstChild);
    }
  }

  function loadState() {
    fetch(window.supportWidgetConfig.stateUrl, {
      credentials: 'include'
    })
      .then(response => response.json())
      .then(data => {
        if (!data.thread) {
          threadId = null;
          clearMessages();
          messagesEl.innerHTML = '<p class="text-muted small mb-0">Напишите нам, и мы ответим.</p>';
          threadTitle.innerText = 'Онлайн-поддержка';
          messageField.disabled = false;
          submitButton.disabled = false;
          if (attachmentInput) {
            attachmentInput.disabled = false;
            attachmentInput.value = '';
          }
          errorEl.classList.add('d-none');
          nameFieldRow.classList.remove('d-none');
          emailFieldRow.classList.remove('d-none');
        } else {
          threadId = data.thread.id;
          clearMessages();
          threadTitle.innerText = 'Чат с поддержкой';
          if (data.messages.length === 0) {
            messagesEl.innerHTML = '<p class="text-muted small mb-0">Диалог пока пуст.</p>';
          } else {
            data.messages.forEach(renderMessage);
            messagesEl.scrollTop = messagesEl.scrollHeight;
          }
          if (data.thread.is_closed) {
            messageField.disabled = true;
            submitButton.disabled = true;
            if (attachmentInput) {
              attachmentInput.disabled = true;
            }
            errorEl.classList.remove('d-none');
            errorEl.innerText = 'Диалог закрыт. Создайте новое обращение, чтобы продолжить.';
          } else {
            messageField.disabled = false;
            submitButton.disabled = false;
            if (attachmentInput) {
              attachmentInput.disabled = false;
            }
            errorEl.classList.add('d-none');
          }
          if (data.thread.contact_name) {
            nameFieldRow.classList.add('d-none');
          }
          if (data.thread.contact_email) {
            emailFieldRow.classList.add('d-none');
          }
        }
      })
      .catch(() => {
        errorEl.innerText = 'Не удалось загрузить чат. Попробуйте обновить страницу.';
        errorEl.classList.remove('d-none');
      });
  }

  function pollMessages() {
    if (!windowEl.classList.contains('show')) {
      setTimeout(pollMessages, window.supportWidgetConfig.pollInterval);
      return;
    }
    fetch(window.supportWidgetConfig.stateUrl, { credentials: 'include' })
      .then(response => response.json())
      .then(data => {
        if (!data.thread) {
          return;
        }
        clearMessages();
        if (data.messages.length === 0) {
          messagesEl.innerHTML = '<p class="text-muted small mb-0">Диалог пока пуст.</p>';
        } else {
          data.messages.forEach(renderMessage);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
        if (data.thread.is_closed) {
          messageField.disabled = true;
          submitButton.disabled = true;
          if (attachmentInput) {
            attachmentInput.disabled = true;
          }
          errorEl.classList.remove('d-none');
          errorEl.innerText = 'Диалог закрыт. Создайте новое обращение, чтобы продолжить.';
        } else {
          messageField.disabled = false;
          submitButton.disabled = false;
          if (attachmentInput) {
            attachmentInput.disabled = false;
          }
          if (!errorEl.classList.contains('d-none') && errorEl.innerText.includes('Диалог закрыт')) {
            errorEl.classList.add('d-none');
          }
        }
      })
      .finally(() => {
        setTimeout(pollMessages, window.supportWidgetConfig.pollInterval);
      });
  }

  toggleButton.addEventListener('click', () => {
    const isOpen = windowEl.classList.toggle('show');
    windowEl.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
    toggleButton.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) {
      loadState();
    }
  });

  form.addEventListener('submit', event => {
    event.preventDefault();
    errorEl.classList.add('d-none');
    const formData = new FormData(form);
    if (threadId) {
      formData.append('thread_id', threadId);
    }
    fetch(window.supportWidgetConfig.sendUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken()
      },
      body: formData,
      credentials: 'include'
    })
      .then(response => {
        if (!response.ok) {
          return response.json().then(data => {
            throw data;
          });
        }
        return response.json();
      })
      .then(data => {
        if (data.thread_id) {
          threadId = data.thread_id;
        }
        if (nameFieldRow && !nameFieldRow.classList.contains('d-none')) {
          nameFieldRow.classList.add('d-none');
        }
        if (emailFieldRow && !emailFieldRow.classList.contains('d-none')) {
          emailFieldRow.classList.add('d-none');
        }
        form.querySelector('textarea[name="message"]').value = '';
        if (attachmentInput) {
          attachmentInput.value = '';
        }
        renderMessage(data.message);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      })
      .catch(data => {
        if (data && data.errors) {
          errorEl.innerText = Object.values(data.errors).flat().join(' ');
        } else {
          errorEl.innerText = 'Не удалось отправить сообщение. Попробуйте позже.';
        }
        errorEl.classList.remove('d-none');
      });
  });

  loadState();
  setTimeout(pollMessages, window.supportWidgetConfig.pollInterval);
})();
