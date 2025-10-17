(function () {
  const listEl = document.getElementById('support-thread-list');
  const messagesEl = document.getElementById('support-thread-messages');
  const titleEl = document.getElementById('support-thread-title');
  const emailEl = document.getElementById('support-thread-email');
  const form = document.getElementById('support-staff-form');
  const statusEl = document.getElementById('support-thread-status');
  const noticeEl = document.getElementById('support-thread-notice');
  const messageInput = form ? form.querySelector('textarea[name="message"]') : null;
  const attachmentInput = form ? form.querySelector('input[name="attachment"]') : null;
  const submitButton = form ? form.querySelector('button[type="submit"]') : null;
  const attachmentTrigger = document.getElementById('support-attachment-trigger');
  const attachmentIndicator = document.getElementById('support-attachment-indicator');
  const closeButton = document.getElementById('support-thread-close');

  if (!listEl || !form) {
    return;
  }

  let activeThreadId = null;

  function updateAttachmentIndicator() {
    if (!attachmentIndicator || !attachmentInput) {
      return;
    }
    const file = attachmentInput.files && attachmentInput.files[0];
    if (file) {
      attachmentIndicator.innerText = 'Вложение: ' + file.name;
      attachmentIndicator.classList.remove('d-none');
    } else {
      attachmentIndicator.innerText = '';
      attachmentIndicator.classList.add('d-none');
    }
  }

  function getCsrfToken() {
    const input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function setFormAvailability(canReply) {
    const disabled = !canReply;
    if (messageInput) {
      messageInput.disabled = disabled;
    }
    if (attachmentInput) {
      attachmentInput.disabled = disabled;
    }
    if (attachmentTrigger) {
      attachmentTrigger.disabled = disabled;
    }
    if (submitButton) {
      submitButton.disabled = disabled;
    }
    if (disabled) {
      if (attachmentInput) {
        attachmentInput.value = '';
      }
      updateAttachmentIndicator();
    }
  }

  function applyThreadMeta(meta) {
    if (statusEl) {
      statusEl.className = 'badge rounded-pill';
      if (meta && meta.status_badge) {
        statusEl.className += ' ' + meta.status_badge;
      }
      if (meta && meta.status) {
        statusEl.innerText = meta.status;
        statusEl.classList.remove('d-none');
      } else {
        statusEl.innerText = '—';
        statusEl.classList.add('d-none');
      }
    }

    if (noticeEl) {
      noticeEl.innerText = '';
      noticeEl.className = 'alert d-none mb-3';
      if (meta && meta.notice) {
        const level = meta.notice_level || 'info';
        noticeEl.className = 'alert alert-' + level + ' mb-3';
        noticeEl.innerText = meta.notice;
        noticeEl.classList.remove('d-none');
      }
    }

    setFormAvailability(meta ? meta.can_reply : false);

    if (closeButton) {
      const canClose = !!(meta && meta.can_close);
      closeButton.classList.toggle('d-none', !canClose);
      closeButton.disabled = !canClose;
    }
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
      item.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-start';
      if (activeThreadId === thread.id) {
        item.classList.add('active');
      }
      if (thread.assigned_to_me) {
        item.classList.add('border', 'border-2', 'border-primary');
      }
      item.dataset.threadId = thread.id;

      const content = document.createElement('div');
      content.innerHTML = '<div class="fw-semibold">' + thread.display_name + '</div>' +
        '<div class="small text-muted">' + (thread.last_message || 'Нет сообщений') + '</div>' +
        '<div class="small text-muted">' + thread.updated_at + '</div>';

      const badge = document.createElement('span');
      badge.className = 'badge rounded-pill ' + (thread.status_badge || 'bg-secondary');
      badge.innerText = thread.status;

      item.appendChild(content);
      item.appendChild(badge);

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
        applyThreadMeta(data.thread);
        renderMessages(data.messages);
      })
      .catch(() => {
        messagesEl.innerHTML = '<p class="text-danger">Не удалось загрузить сообщения.</p>';
        applyThreadMeta(null);
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
      .then(data => {
        if (messageInput) {
          messageInput.value = '';
        }
        if (attachmentInput) {
          attachmentInput.value = '';
        }
        updateAttachmentIndicator();
        if (noticeEl) {
          noticeEl.className = 'alert d-none mb-3';
          noticeEl.innerText = '';
        }
        if (data.thread) {
          applyThreadMeta(data.thread);
        }
        selectThread(activeThreadId);
        refreshThreads();
      })
      .catch(error => {
        if (error && error.thread) {
          applyThreadMeta(error.thread);
        }
        if (error && error.errors) {
          const message = Object.values(error.errors).flat().join(' ');
          if (noticeEl) {
            noticeEl.className = 'alert alert-warning mb-3';
            noticeEl.innerText = message;
            noticeEl.classList.remove('d-none');
          } else {
            messagesEl.innerHTML += '<p class="text-danger">' + message + '</p>';
          }
        } else {
          if (noticeEl) {
            noticeEl.className = 'alert alert-danger mb-3';
            noticeEl.innerText = 'Не удалось отправить сообщение.';
            noticeEl.classList.remove('d-none');
          } else {
            messagesEl.innerHTML += '<p class="text-danger">Не удалось отправить сообщение.</p>';
          }
        }
      });
  });

  if (attachmentTrigger && attachmentInput) {
    attachmentTrigger.addEventListener('click', () => {
      if (!attachmentTrigger.disabled) {
        attachmentInput.click();
      }
    });
  }

  if (attachmentInput) {
    attachmentInput.addEventListener('change', () => {
      updateAttachmentIndicator();
    });
  }

  if (closeButton) {
    closeButton.addEventListener('click', () => {
      if (!activeThreadId || closeButton.disabled) {
        return;
      }
      const closeUrl = window.supportInboxConfig.closeUrlTemplate.replace('00000000-0000-0000-0000-000000000000', activeThreadId);
      closeButton.disabled = true;
      fetch(closeUrl, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken(),
        },
        credentials: 'include',
      })
        .then(response => {
          if (!response.ok) {
            return response.json().then(data => { throw data; });
          }
          return response.json();
        })
        .then(data => {
          if (data.thread) {
            applyThreadMeta(data.thread);
          }
          selectThread(activeThreadId);
          refreshThreads();
          if (noticeEl) {
            noticeEl.className = 'alert alert-secondary mb-3';
            noticeEl.innerText = 'Обращение закрыто.';
            noticeEl.classList.remove('d-none');
          }
        })
        .catch(error => {
          if (error && error.thread) {
            applyThreadMeta(error.thread);
          }
          if (noticeEl) {
            const message = (error && error.errors && Object.values(error.errors).flat().join(' '))
              || 'Не удалось закрыть обращение.';
            noticeEl.className = 'alert alert-warning mb-3';
            noticeEl.innerText = message;
            noticeEl.classList.remove('d-none');
          }
          if ((!error || !error.thread) && closeButton) {
            closeButton.disabled = false;
          }
        });
    });
  }

  if (attachmentInput) {
    updateAttachmentIndicator();
  }

  applyThreadMeta(null);
  refreshThreads();
  setInterval(refreshThreads, window.supportInboxConfig.refreshInterval);
})();
