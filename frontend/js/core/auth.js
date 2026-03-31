// Shared auth/session helpers used by dashboard scripts.
(function () {
  function getExistingToken() {
    return sessionStorage.getItem('authToken') || localStorage.getItem('deviceToken');
  }

  function setupAuthHeaders(token) {
    if (!token) return;
    window.__authToken = token;
    const originalFetch = window.fetch;

    if (originalFetch.__bhWrapped) {
      return;
    }

    const wrappedFetch = function (resource, config = {}) {
      if (typeof resource === 'string' && (resource.startsWith('/') || resource.startsWith('http'))) {
        config.headers = config.headers || {};
        config.headers['Authorization'] = 'Bearer ' + window.__authToken;
      }
      return originalFetch.call(this, resource, config);
    };
    wrappedFetch.__bhWrapped = true;
    window.fetch = wrappedFetch;
  }

  window.DashboardAuth = {
    getExistingToken,
    setupAuthHeaders,
  };
})();
