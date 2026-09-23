#!/usr/bin/env python3
"""Exercise the installed image browser runtime without npx or installation."""
import subprocess
import sys

root = subprocess.check_output(['npm', 'root', '-g'], text=True, timeout=10).strip()
# Resolve the runtime bundled with the pinned MCP on Linux, not a project pin.
module = root + ('/playwright' if sys.platform == 'darwin' else '/@playwright/mcp')
script = r'''
const {createRequire} = require('module');
const path = require('path');
const local = createRequire(path.join(process.argv[1], 'package.json'));
const {chromium} = local('playwright');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    await page.goto('data:text/html,<title>pilot-accept</title><button>check</button>');
    await page.locator('button').click();
    if (await page.title() !== 'pilot-accept') throw Error('unexpected title');
    const png = await page.screenshot();
    if (png.subarray(0,8).toString('hex') !== '89504e470d0a1a0a') throw Error('invalid screenshot');
    console.log(JSON.stringify({title:await page.title(), screenshotBytes:png.length}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
subprocess.run(['node', '-e', script, module], check=True, timeout=45)
