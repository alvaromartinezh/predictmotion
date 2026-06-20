/* ──────────────────────────────────────────────────────────────────────────
   Configuración centralizada de anuncios (Adsterra "highperformanceformat").
   ÚNICA fuente de las keys y dimensiones — no repartir keys por el código.
   Cambia ENABLED a false para desactivar TODOS los anuncios de golpe.
   ────────────────────────────────────────────────────────────────────────── */
window.PM_ADS = {
  // Interruptor global. Con false no se carga ningún script de Adsterra.
  ENABLED: true,

  // Punto de corte escritorio/móvil (debe coincidir con assets/ads.css).
  MOBILE_BREAKPOINT: 768,

  // Banners disponibles (solo display, nunca pop-unders).
  FORMATS: {
    leaderboard: { key: 'ecb1461a8d8a1b4e590f7031a157aec3', width: 728, height: 90  },
    rectangle:   { key: 'f024231c8ea422b73db8cc2dd0bcaf02', width: 300, height: 250 },
    mobile:      { key: 'c39c86922c9ec6323fd572f191ea14a3', width: 320, height: 50  },
  },

  // Qué formato usa cada slot según el viewport. El marcado solo pone
  // <div data-ad-slot="top|mid">; el componente elige el banner correcto y
  // nunca carga el de escritorio en móvil ni al revés.
  SLOTS: {
    top: { desktop: 'leaderboard', mobile: 'mobile' },     // debajo de la cabecera
    mid: { desktop: 'rectangle',   mobile: 'rectangle' },  // dentro del contenido
  },
};
