(() => {
  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getUnitLabel(unit, unitNames) {
    const name = unitNames && unitNames[unit] ? unitNames[unit] : '';
    return name ? `${unit} - ${name}` : unit;
  }

  function resolveAllCount(counts, allValue) {
    if (typeof counts[allValue] === 'number') return counts[allValue];
    if (typeof counts.__ALL__ === 'number') return counts.__ALL__;
    if (typeof counts.all === 'number') return counts.all;
    if (typeof counts[''] === 'number') return counts[''];
    return 0;
  }

  function render(containerId, options) {
    const container = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!container) return;

    const opts = options || {};
    const units = opts.units || [];
    const unitNames = opts.unitNames || {};
    const counts = opts.counts || {};
    const currentUnit = typeof opts.currentUnit === 'undefined' ? '' : opts.currentUnit;
    const includeAll = opts.includeAll !== false;
    const allValue = typeof opts.allValue === 'undefined' ? '__ALL__' : opts.allValue;
    const allLabel = opts.allLabel || '全部';

    const buttons = [];
    if (includeAll) {
      buttons.push({
        value: allValue,
        label: allLabel,
        count: resolveAllCount(counts, allValue)
      });
    }

    units.forEach((unit) => {
      buttons.push({
        value: unit,
        label: getUnitLabel(unit, unitNames),
        count: typeof counts[unit] === 'number' ? counts[unit] : 0
      });
    });

    container.innerHTML = buttons.map((btn) => {
      const isActive = btn.value === currentUnit;
      const label = escapeHtml(btn.label || '');
      const count = typeof btn.count === 'number' ? ` (${btn.count})` : '';
      return `<button type="button" class="tab ${isActive ? 'active' : ''}" data-unit="${escapeHtml(btn.value)}">${label}${count}</button>`;
    }).join('');

    if (typeof opts.onChange === 'function') {
      container.querySelectorAll('button[data-unit]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const value = btn.getAttribute('data-unit');
          opts.onChange(value);
        });
      });
    }
  }

  window.ELUnitTabs = { render };
})();
