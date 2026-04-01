// Keep-screen-alive and nightly reload behavior extracted from app.js.
(function () {
  function createApi() {
    let wakeLock = null;
    let audioCtx = null;
    let silentOsc = null;
    let keepAliveVideo = null;

    async function requestWakeLock() {
      if (!('wakeLock' in navigator)) return;
      try {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => {
          wakeLock = null;
        });
      } catch (err) {
        console.warn('Wake lock request failed', err);
      }
    }

    function ensureSilentAudio() {
      // Very quiet oscillator to count as activity and keep Fire Stick awake.
      try {
        if (silentOsc && audioCtx && audioCtx.state !== 'closed') {
          if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
          return;
        }
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        audioCtx = new Ctx();
        if (audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        gain.gain.value = 0.0001;
        osc.connect(gain).connect(audioCtx.destination);
        osc.start();
        silentOsc = osc;
      } catch (err) {
        console.warn('Silent audio keep-alive failed', err);
      }
    }

    function startKeepAliveVideo() {
      // Hidden muted looping video to keep media session active on devices that permit autoplay.
      try {
        if (keepAliveVideo && keepAliveVideo.readyState > 0) {
          keepAliveVideo.play().catch(() => {});
          return;
        }
        const vid = document.createElement('video');
        vid.muted = true;
        vid.loop = true;
        vid.playsInline = true;
        vid.autoplay = true;
        vid.setAttribute('playsinline', '');
        vid.style.position = 'fixed';
        vid.style.width = '1px';
        vid.style.height = '1px';
        vid.style.opacity = '0.001';
        vid.style.bottom = '0';
        vid.style.left = '0';
        vid.style.pointerEvents = 'none';
        vid.src = 'data:video/webm;base64,GkXfo59ChoEBQveBAULygQRC9+BBQvWBAULpgQRC8YEEQvGBAAAB9uWdlYm0BVmVyc2lvbj4xAAAAAAoAAABHYXZrVjkAAAAAAAAD6aNjYWI9AAAZY2FkYwEAAAAAAAAAAAAAAAAAAAAAAAACdC9hAAAAAAACAAEAAQAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';
        document.body.appendChild(vid);
        keepAliveVideo = vid;
        vid.play().catch(() => {});
      } catch (err) {
        console.warn('Keep-alive video failed', err);
      }
    }

    function ping() {
      if (document.hidden) return;
      requestWakeLock();
      ensureSilentAudio();
      startKeepAliveVideo();
      document.body.style.opacity = '0.999';
      setTimeout(() => {
        document.body.style.opacity = '1';
      }, 80);
    }

    function scheduleNightlyReload() {
      const now = new Date();
      const reloadTime = new Date();
      reloadTime.setHours(2, 0, 0, 0);

      if (now > reloadTime) {
        reloadTime.setDate(reloadTime.getDate() + 1);
      }

      const msUntilReload = reloadTime - now;
      setTimeout(() => {
        location.reload();
        scheduleNightlyReload();
      }, msUntilReload);
    }

    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        ping();
      }
    });

    setInterval(ping, 2 * 60 * 1000);
    ping();
    scheduleNightlyReload();

    return { ping };
  }

  window.DisplayKeepAlive = {
    init() {
      return createApi();
    },
  };
})();
