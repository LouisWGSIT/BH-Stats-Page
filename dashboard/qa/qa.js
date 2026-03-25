// QA-specific loader/stub placed in dashboard/qa/ for organization.
(function(){
  // Reuse the implementation from dashboard/qa.js — expose the same `window` APIs.
  window.qaTopFlipIntervalId = null;
  window.qaRotatorIntervalId = null;
  window.metricsFlipIntervalId = null;

  window.formatQaName = window.formatQaName || function(rawName){ if(!rawName) return ''; const name = rawName.toString().trim(); const withoutDomain = name.replace(/@.*$/, '').replace(/[._-]+/g,' ').trim(); const parts = withoutDomain.split(/\s+/).filter(Boolean); if(parts.length===0) return name; if(parts.length===1) return parts[0].charAt(0).toUpperCase()+parts[0].slice(1); const first = parts[0]; const lastInitial = parts[parts.length-1][0]; return `${first.charAt(0).toUpperCase()+first.slice(1)} ${lastInitial.toUpperCase()}`; };

  window.getQaInitials = window.getQaInitials || function(displayName){ if(!displayName) return ''; const cleaned = displayName.replace(/[^a-zA-Z\s]/g,'').trim(); const parts = cleaned.split(/\s+/).filter(Boolean); if(parts.length>=2) return `${parts[0][0]}${parts[parts.length-1][0]}`.toUpperCase(); return cleaned.slice(0,2).toUpperCase(); };

  // Do not override a full QA implementation if present (avoid recursion).
  // Only set helpers here; `dashboard/qa.js` provides the full `loadQADashboard` implementation.

  // mark ready
  try { window.__dashboardQAReady = true; } catch(e){}

})();

// Add Impl aliases for QA helpers
(function ensureQaImplAliases() {
  const names = ['formatQaName','getQaInitials','loadQADashboard','startQARotator','populateQACard','populateQAAppCard','populateMetricsCard','showQAError'];
  try {
    names.forEach(n => {
      if (typeof window[n] === 'function' && typeof window[n + 'Impl'] !== 'function') {
        window[n + 'Impl'] = window[n];
      }
    });
  } catch (e) {}
})();
