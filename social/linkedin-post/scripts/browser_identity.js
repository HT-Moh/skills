// Present the user's own browser identity (from browser_identity.py) on a Puppeteer page.
//
// Without it the headless browser sends "HeadlessChrome/<n>", its own client-hint brands and
// navigator.webdriver=true, while the login cookie was made in the user's browser. LinkedIn
// treats that cookie as stolen and signs the session out.

async function applyIdentity(page, identity) {
  if (!identity) return;
  const major = identity.userAgent.match(/Chrome\/(\d+)/)[1];
  await page.setUserAgent({
    userAgent: identity.userAgent,
    userAgentMetadata: {
      brands: identity.brands,
      fullVersion: `${major}.0.0.0`,
      platform: identity.platform,
      platformVersion: '',
      architecture: 'x86',
      model: '',
      mobile: false,
    },
  });
  await page.setExtraHTTPHeaders({ 'Accept-Language': identity.acceptLanguage });
  const languages = identity.acceptLanguage.split(',').map((part) => part.split(';')[0].trim());
  await page.evaluateOnNewDocument((langs) => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'languages', { get: () => langs });
  }, languages);
}

module.exports = { applyIdentity };
