(() => {
  const iconYes = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="9" fill="#07a86c"/><path d="M5 10.5l3 3 7-7" stroke="white" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>');
  const iconNo = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="9" fill="#e5484d"/><path d="M6.2 6.2l7.6 7.6M13.8 6.2l-7.6 7.6" stroke="white" stroke-width="2.2" fill="none" stroke-linecap="round"/></svg>');
  const iconWarn = 'data:image/svg+xml;utf8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="9" fill="#f59e0b"/><path d="M10 5v6" stroke="white" stroke-width="2.2" stroke-linecap="round"/><circle cx="10" cy="15" r="1.4" fill="white"/></svg>');

  function escapeHtml(value) {
    return String(value || '').replace(/</g, '&lt;');
  }

  function buildNoteText(noteRaw, consistencyOk, highlightWarning = true) {
    let noteText = escapeHtml(noteRaw || '');
    if (consistencyOk === false) {
      const warningText = '识别不一致，请检查图片';
      const warningHtml = highlightWarning
        ? `<span class="note-warning">${warningText}</span>`
        : escapeHtml(warningText);
      noteText = noteText ? `${noteText}；${warningHtml}` : warningHtml;
    }
    return noteText || '';
  }

  function formatLlmText(rawText, refAnswer, noteRaw, sectionType, isCorrect) {
    let formatted = escapeHtml(rawText || '');
    const hasSpellingError = (noteRaw || '').includes('拼写');
    const secType = sectionType || '';
    if (hasSpellingError && !isCorrect && (secType === 'PHRASE' || secType === 'SENTENCE') && rawText) {
      const wrongWords = new Set();
      const arrowPattern = /(\w+)\s*(?:→|->)\s*(\w+)/g;
      let match;
      while ((match = arrowPattern.exec(noteRaw || '')) !== null) {
        wrongWords.add(match[1].toLowerCase());
      }

      const parenPattern = /拼写错误[^(]*[（(]([^)）]+)[)）]/;
      const parenMatch = (noteRaw || '').match(parenPattern);
      if (parenMatch) {
        const words = parenMatch[1].split(/[，,、\s]+/);
        words.forEach(w => {
          const cleaned = w.trim().toLowerCase();
          if (cleaned) wrongWords.add(cleaned);
        });
      }

      if (refAnswer && wrongWords.size === 0) {
        const studentWords = String(rawText || '').split(/\s+/);
        const refWords = String(refAnswer || '').split(/\s+/);
        for (let i = 0; i < Math.min(studentWords.length, refWords.length); i++) {
          const studentWord = studentWords[i] || '';
          const refWord = refWords[i] || '';
          const studentWordClean = studentWord.replace(/[^\w]/g, '');
          const refWordClean = refWord.replace(/[^\w]/g, '');
          if (studentWordClean && refWordClean &&
              studentWordClean.toLowerCase() !== refWordClean.toLowerCase()) {
            wrongWords.add(studentWordClean.toLowerCase());
          }
        }
      }

      if (wrongWords.size > 0) {
        let highlighted = formatted;
        wrongWords.forEach(wrongWord => {
          const escapedWord = wrongWord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          const regex = new RegExp(`\\b${escapedWord}\\w*\\b`, 'gi');
          highlighted = highlighted.replace(regex, (matched) => {
            if (matched.toLowerCase().startsWith(wrongWord)) {
              return `<span style="color:#e5484d;font-weight:500">${matched}</span>`;
            }
            return matched;
          });
        });
        formatted = highlighted;
      }
    }
    return formatted;
  }

  function getMarkIcons() {
    return {iconYes, iconNo, iconWarn};
  }

  function initImageModal(options = {}) {
    const modalId = options.modalId || 'imgModal';
    const imgId = options.imgId || 'imgModalPic';
    const modal = document.getElementById(modalId);
    const modalPic = document.getElementById(imgId);
    if (!modal || !modalPic) return null;
    if (modal.dataset && modal.dataset.bound === '1') return null;

    const padding = Number(options.padding || 10);
    const preferCenter = options.center === true;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let imgStartLeft = 0;
    let imgStartTop = 0;

    function resetPosition() {
      modalPic.style.left = 'auto';
      modalPic.style.top = 'auto';
      modalPic.style.right = 'auto';
      modalPic.style.bottom = 'auto';
      modalPic.style.transform = '';
    }

    function clampPos(left, top, width, height) {
      const maxLeft = Math.max(padding, window.innerWidth - width - padding);
      const maxTop = Math.max(padding, window.innerHeight - height - padding);
      return {
        left: Math.min(Math.max(padding, left), maxLeft),
        top: Math.min(Math.max(padding, top), maxTop),
      };
    }

    function positionAt(anchorX, anchorY) {
      const imgWidth = modalPic.offsetWidth || modalPic.naturalWidth || 0;
      const imgHeight = modalPic.offsetHeight || modalPic.naturalHeight || 0;
      let leftPos = anchorX - imgWidth;
      let topPos = anchorY - imgHeight;
      const pos = clampPos(leftPos, topPos, imgWidth, imgHeight);
      modalPic.style.left = pos.left + 'px';
      modalPic.style.top = pos.top + 'px';
      modalPic.style.right = 'auto';
      modalPic.style.bottom = 'auto';
    }

    function positionCenter() {
      const imgWidth = modalPic.offsetWidth || modalPic.naturalWidth || 0;
      const imgHeight = modalPic.offsetHeight || modalPic.naturalHeight || 0;
      let leftPos = (window.innerWidth - imgWidth) / 2;
      let topPos = (window.innerHeight - imgHeight) / 2;
      const pos = clampPos(leftPos, topPos, imgWidth, imgHeight);
      modalPic.style.left = pos.left + 'px';
      modalPic.style.top = pos.top + 'px';
      modalPic.style.right = 'auto';
      modalPic.style.bottom = 'auto';
    }

    function openImage(src, evt) {
      if (!src || src === window.location.href) return;
      resetPosition();
      modal.style.display = 'block';
      modalPic.onload = () => {
        if (preferCenter || !evt) {
          positionCenter();
        } else {
          positionAt(evt.clientX, evt.clientY);
        }
      };
      modalPic.src = src;
    }

    document.body.addEventListener('click', (e) => {
      const base = (e.target && e.target.closest) ? e.target : e.target.parentElement;
      if (!base) return;
      const link = base.closest('.page-link');
      if (link) {
        e.preventDefault();
        openImage(link.getAttribute('data-page-url'), e);
        return;
      }
      const img = base.closest('img.zoomable, img.crop-thumb');
      if (img) {
        openImage(img.getAttribute('src'), e);
      }
    });

    modalPic.addEventListener('mousedown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      isDragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      const rect = modalPic.getBoundingClientRect();
      imgStartLeft = rect.left;
      imgStartTop = rect.top;
      modalPic.style.cursor = 'grabbing';
      modal.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const deltaX = e.clientX - dragStartX;
      const deltaY = e.clientY - dragStartY;
      const newLeft = imgStartLeft + deltaX;
      const newTop = imgStartTop + deltaY;
      modalPic.style.left = newLeft + 'px';
      modalPic.style.top = newTop + 'px';
      modalPic.style.right = 'auto';
      modalPic.style.bottom = 'auto';
    });

    document.addEventListener('mouseup', () => {
      if (isDragging) {
        isDragging = false;
        modalPic.style.cursor = 'grab';
        modal.style.cursor = 'pointer';
      }
    });

    modal.addEventListener('click', (e) => {
      if (e.target === modal && !isDragging) {
        modal.style.display = 'none';
        modalPic.src = '';
        modalPic.style.transform = '';
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        modal.style.display = 'none';
        modalPic.src = '';
        modalPic.style.transform = '';
      }
    });

    if (modal.dataset) {
      modal.dataset.bound = '1';
    }

    return {openImage};
  }

  window.ELGrading = {
    escapeHtml,
    buildNoteText,
    formatLlmText,
    getMarkIcons,
    initImageModal
  };
})();
