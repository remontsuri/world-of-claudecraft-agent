import asyncio, json, math, sys
from puppeteer_core import connect  # fallback if import name differs

CDP = "http://127.0.0.1:9222"
async def main():
    browser = await connect(browserWSEndpoint=None, browserURL=CDP) if False else None
    # puppeteer-core uses connectOverCDP
    from puppeteer_core import connectOverCDP
    browser = await connectOverCDP(CDP)
    pages = await browser.pages()
    page = None
    for p in pages:
        url = p.url or ""
        if "worldofclaudecraft" in url:
            page = p; break
    if not page:
        print("no game tab"); return
    print("tab:", page.url)
    # focus canvas, hold W 5s
    await page.bringToFront()
    await page.keyboard.down('w')
    await asyncio.sleep(5)
    await page.keyboard.up('w')
    pos = await page.evaluate("JSON.stringify(window.__game.sim.player.pos)")
    print("pos after W:", pos)
    await browser.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
