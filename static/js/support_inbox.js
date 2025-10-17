(function () {
  const listEl = document.getElementById('support-thread-list');
  const messagesEl = document.getElementById('support-thread-messages');
  const titleEl = document.getElementById('support-thread-title');
  const emailEl = document.getElementById('support-thread-email');
  const form = document.getElementById('support-staff-form');

  if (!listEl || !form) {
    return;
  }

  let activeThreadId = null;

  function getCsrfToken() {
    const input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function renderThreads(threads) {
    listEl.innerHTML = '';
    if (threads.length === 0) {
      listEl.innerHTML = '<div class="list-group-item text-muted small">Нет открытых обращений</div>';
      return;
    }
    threads.forEach(thread => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'list-group-item list-group-item-action';
      if (activeThreadId === thread.id) {
        item.classList.add('active');
      }
      item.dataset.threadId = thread.id;
      item.innerHTML = '<div class="fw-semibold">' + thread.display_name + '</div>' +
        '<div class="small text-muted">' + (thread.last_message || 'Нет сообщений') + '</div>' +
        '<div class="small text-muted">' + thread.updated_at + '</div>';
      item.addEventListener('click', () => selectThread(thread.id));
      listEl.appendChild(item);
    });
  }

  function renderMessages(messages) {
    messagesEl.innerHTML = '';
    if (messages.length === 0) {
      messagesEl.innerHTML = '<p class="text-muted">Сообщений пока нет.</p>';
      return;
    }
    messages.forEach(message => {
      const wrapper = document.createElement('div');
      wrapper.className = 'mb-3';

      const timeEl = document.createElement('div');
      timeEl.className = 'small text-muted';
      timeEl.innerText = message.created_at;
      wrapper.appendChild(timeEl);

      const bodyEl = document.createElement('div');
      bodyEl.className = 'p-3 rounded ' + (message.is_from_staff ? 'bg-light' : 'bg-dark text-white');

      if (message.body) {
        const textEl = document.createElement('p');
        textEl.className = 'mb-2';
        textEl.innerText = message.body;
        bodyEl.appendChild(textEl);
      }

      if (message.attachment) {
        const link = document.createElement('a');
        link.href = message.attachment.url;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = message.attachment.url;
        img.alt = message.attachment.name || 'Вложение';
        img.className = 'img-fluid rounded';
        link.appendChild(img);
        bodyEl.appendChild(link);
      }

      if (!message.body && !message.attachment) {
        bodyEl.innerText = '[Пустое сообщение]';
      }

      wrapper.appendChild(bodyEl);
      messagesEl.appendChild(wrapper);
    });
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function refreshThreads() {
    fetch(window.supportInboxConfig.threadsUrl, { credentials: 'include' })
      .then(response => {
        if (!response.ok) {
          throw new Error('network');
        }
        return response.json();
      })
      .then(data => {
        renderThreads(data.threads);
      })
      .catch(() => {
        listEl.innerHTML = '<div class="list-group-item text-danger small">Не удалось загрузить обращения</div>';
      });
  }

  function selectThread(threadId) {
    activeThreadId = threadId;
    Array.from(listEl.querySelectorAll('.list-group-item')).forEach(item => {
      item.classList.toggle('active', item.dataset.threadId === threadId);
    });
    const messageUrl = window.supportInboxConfig.messagesUrlTemplate.replace('00000000-0000-0000-0000-000000000000', threadId);
    fetch(messageUrl, { credentials: 'include' })
      .then(response => {
        if (!response.ok) {
          throw new Error('network');
        }
        return response.json();
      })
      .then(data => {
        titleEl.innerText = data.thread.display_name;
        emailEl.innerText = data.thread.contact_email || '';
        renderMessages(data.messages);
      })
      .catch(() => {
        messagesEl.innerHTML = '<p class="text-danger">Не удалось загрузить сообщения.</p>';
      });
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!activeThreadId) {
      return;
    }
    const formData = new FormData(form);
    const sendUrl = window.supportInboxConfig.sendUrlTemplate.replace('00000000-0000-0000-0000-000000000000', activeThreadId);
    fetch(sendUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken()
      },
      body: formData,
      credentials: 'include'
    })
      .then(response => {
        if (!response.ok) {
          return response.json().then(data => { throw data; });
        }
        return response.json();
      })
      .then(() => {
        form.querySelector('textarea[name="message"]').value = '';
        const attachmentInput = form.querySelector('input[name="attachment"]');
        if (attachmentInput) {
          attachmentInput.value = '';
        }
        selectThread(activeThreadId);
      })
      .catch(error => {
        if (error && error.errors) {
          messagesEl.innerHTML += '<p class="text-danger">' + Object.values(error.errors).flat().join(' ') + '</p>';
        } else {
          messagesEl.innerHTML += '<p class="text-danger">Не удалось отправить сообщение.</p>';
        }
      });
  });

  refreshThreads();
  setInterval(refreshThreads, window.supportInboxConfig.refreshInterval);
})();
