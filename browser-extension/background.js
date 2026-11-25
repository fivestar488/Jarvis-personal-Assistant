"use strict";
// Right-click menu: "Ask Jarvis about this" on highlighted text, "Summarise this page with Jarvis" anywhere.
// The answer appears (and is spoken) in the Jarvis HUD.
importScripts("shared.js");

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "selection", title: "Ask Jarvis about this", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "page", title: "Summarise this page with Jarvis", contexts: ["page"] });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    const page = await readTab(tab);
    if (info.menuItemId === "selection") {
      page.selection = info.selectionText || page.selection;
      page.text = "";
      await askJarvis(page, "Explain what I highlighted.");
    } else {
      await askJarvis(page, "Summarise this page.");
    }
  } catch (e) {
    // No popup to show it in: put the problem on the extension's badge instead
    chrome.action.setBadgeText({ text: "!", tabId: tab.id });
    chrome.action.setTitle({ title: `Jarvis: ${e.message || e}`, tabId: tab.id });
  }
});
