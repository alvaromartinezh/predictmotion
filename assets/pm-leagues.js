/* PM_LEAGUES — catálogo de competiciones en cliente (fuente única del shell y del
 * feed). Debe casar con seo/config.py → LEAGUES y con el array COMPS de index.html;
 * a UNIFICAR en una fase posterior (hoy: mínimo viable, mismos 15 slugs).
 * code = código de liga ESPN. logo = leaguelogo dark de ESPN. */
(function () {
  'use strict';
  window.PM_LEAGUES = {
    laliga:       { name: 'LaLiga',          code: 'esp.1',            country: 'España',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/15.png' },
    hypermotion:  { name: 'Hypermotion',     code: 'esp.2',            country: 'España',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/1868.png' },
    premier:      { name: 'Premier League',  code: 'eng.1',            country: 'Inglaterra',   logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/23.png' },
    championship: { name: 'Championship',    code: 'eng.2',            country: 'Inglaterra',   logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/24.png' },
    seriea:       { name: 'Serie A',         code: 'ita.1',            country: 'Italia',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/12.png' },
    serieb:       { name: 'Serie B',         code: 'ita.2',            country: 'Italia',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/13.png' },
    bundesliga:   { name: 'Bundesliga',      code: 'ger.1',            country: 'Alemania',     logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/10.png' },
    bundesliga2:  { name: '2. Bundesliga',   code: 'ger.2',            country: 'Alemania',     logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/3521.png' },
    ligue1:       { name: 'Ligue 1',         code: 'fra.1',            country: 'Francia',      logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/9.png' },
    ligue2:       { name: 'Ligue 2',         code: 'fra.2',            country: 'Francia',      logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/96.png' },
    primeira:     { name: 'Primeira Liga',   code: 'por.1',            country: 'Portugal',     logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/14.png' },
    eredivisie:   { name: 'Eredivisie',      code: 'ned.1',            country: 'Países Bajos', logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/11.png' },
    champions:    { name: 'Champions',       code: 'uefa.champions',   country: 'Europa',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2.png' },
    europa:       { name: 'Europa League',   code: 'uefa.europa',      country: 'Europa',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/2310.png' },
    conference:   { name: 'Conference',      code: 'uefa.europa.conf', country: 'Europa',       logo: 'https://a.espncdn.com/i/leaguelogos/soccer/500-dark/20296.png' }
  };
  window.PM_LEAGUES_ORDER = ['laliga','hypermotion','premier','seriea','bundesliga','ligue1','primeira','eredivisie','championship','serieb','bundesliga2','ligue2','champions','europa','conference'];
})();
