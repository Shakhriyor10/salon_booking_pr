(function () {
  const SNOWFLAKE_COUNT = 90;

  function createSnowflake(index) {
    const flake = document.createElement('div');
    flake.className = 'snowflake';
    flake.textContent = Math.random() > 0.5 ? '❄' : '✶';

    const size = (Math.random() * 0.8 + 0.6).toFixed(2);
    const startX = Math.random() * 100;
    const endX = (Math.random() * 20 - 10).toFixed(2);
    const duration = (Math.random() * 8 + 10).toFixed(2);
    const delay = (Math.random() * 10).toFixed(2);
    const opacity = (Math.random() * 0.35 + 0.55).toFixed(2);

    flake.style.setProperty('--size', `${size}rem`);
    flake.style.setProperty('--start-x', `${startX}vw`);
    flake.style.setProperty('--end-x', `${endX}vw`);
    flake.style.setProperty('--fall-duration', `${duration}s`);
    flake.style.setProperty('--fall-delay', `${delay}s`);
    flake.style.setProperty('--flake-opacity', opacity);

    return flake;
  }

  function initSnow() {
    const container = document.querySelector('.snow-container');
    if (!container) return;

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < SNOWFLAKE_COUNT; i += 1) {
      fragment.appendChild(createSnowflake(i));
    }
    container.appendChild(fragment);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSnow);
  } else {
    initSnow();
  }
})();
