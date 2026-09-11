// Applied by Playwright MCP before the first navigation. The agent cannot edit this policy.
exports.default = async ({ page }) => {
  const origin = process.env.QA_BROWSER_ORIGIN;
  const context = page.context();
  await context.route('**/*', async route => {
    const request = route.request();
    let allowed = false;
    try { const target = new URL(request.url()); const figma = ['https://www.figma.com','https://figma.com'].includes(origin); const trusted = target.origin === origin || (figma && ['figma.com','figmausercontent.com','figma-alpha-api.s3.us-west-2.amazonaws.com'].some(host => target.hostname === host || target.hostname.endsWith('.' + host))); allowed = trusted && ['GET', 'HEAD', 'OPTIONS'].includes(request.method()); } catch {}
    if (!allowed) return route.abort('blockedbyclient');
    return route.continue();
  });
  // WebSocket mutations are outside an observation-only session.
  await context.routeWebSocket('**/*', socket => socket.close());
  context.on('page', popup => { if (popup !== page) popup.close().catch(() => {}); });
};
