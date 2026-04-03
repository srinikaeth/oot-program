// ==UserScript==
// @name         Discord MULTIPLE Trade Forwarder (ScriptCat)
// @namespace    http://scriptcat.org/
// @version      1.5
// @description  Forwards Discord messages to a local Flask server with highly visible console logs
// @match        https://discord.com/channels/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    // 1. FLASK SERVER URL
    const FLASK_URL = GM_getValue('FLASK_URL', '');

    // 2. API key — must match API_SECRET_KEY in config.py
    // const API_SECRET_KEY = "fern_balloon_pad_thai_6490";
    const API_SECRET_KEY = GM_getValue('API_SECRET_KEY', '');

    // 3. Map of Discord channel ID → source name sent to the server.
    //    Use lowercase — this value is stored as-is in the trades table.
    //    Must match a value handled by normalize_source() in server.py.
    const CHANNELS = {
        "1347238168109387857": "waxui",  // OOT - Waxui
        "782068070977110027":  "zabes",  // OOT - Zabes
        "1476499168817188876": "test",   // Test server
    };

    // CSS Styles for the Console
    const styleInit    = "color: #bada55; font-size: 20px; font-weight: bold; background: #222; padding: 5px; border-radius: 5px;";
    const styleAlert   = "color: #00e5ff; font-size: 24px; font-weight: bold; background: #111; padding: 8px; border-left: 8px solid #00e5ff;";
    const styleText    = "color: #ffffff; font-size: 18px; font-style: italic; padding-left: 10px;";
    const styleSuccess = "color: #39ff14; font-size: 20px; font-weight: bold; padding: 5px;";
    const styleError   = "color: #ff0000; font-size: 24px; font-weight: bold; background: #440000; padding: 8px; border: 2px solid red;";

    const SCRIPT_START_TIME = Date.now();

    console.log("%c[TradeForwarder] 🚀 ScriptCat injected and waiting...", styleInit);

    function getCurrentChannelName() {
        for (const [id, name] of Object.entries(CHANNELS)) {
            if (window.location.href.includes(id)) return name;
        }
        return null;
    }

    function sendToFlask(channelName, author, text) {
        if (!text) return;

        GM_xmlhttpRequest({
            method: "POST",
            url: FLASK_URL,
            headers: {
                "Content-Type": "application/json",
                "X-Bot-Key": API_SECRET_KEY
            },
            // source is sent explicitly so server.py doesn't have to infer it from the title.
            data: JSON.stringify({ title: channelName, text: text, source: channelName }),
            onload: function(response) {
                console.log(`%c[TradeForwarder] ✅ Success! Server responded with: ${response.status}`, styleSuccess);
            },
            onerror: function(error) {
                console.log("%c[TradeForwarder] ❌ Connection Error: " + error, styleError);
            }
        });
    }

    const observer = new MutationObserver((mutations) => {
        const channelName = getCurrentChannelName();
        if (!channelName) return;

        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeName === "LI" && node.id && node.id.startsWith("chat-messages-")) {
                    // Extract Discord snowflake message ID and skip historical messages
                    const messageId = node.id.split("-").pop();
                    const messageTimestamp = Number(BigInt(messageId) >> 22n) + 1420070400000;
                    if (messageTimestamp < SCRIPT_START_TIME) return;

                    setTimeout(() => {
                        try {
                            const textElement = node.querySelector('[id^="message-content-"]');
                            const authorElement = node.querySelector('span[class^="username_"]');

                            const text = textElement ? textElement.innerText : "";
                            const author = authorElement ? authorElement.innerText : "Unknown";

                            if (text) {
                                console.log(`%c[TradeForwarder] 🔔 CAUGHT MESSAGE FROM ${author.toUpperCase()} (${channelName}):\n%c"${text}"`, styleAlert, styleText);
                                sendToFlask(channelName, author, text);
                            }
                        } catch (e) {
                            console.log("%c[TradeForwarder] ⚠️ Failed to parse: " + e, styleError);
                        }
                    }, 100);
                }
            });
        });
    });

    const startObserver = setInterval(() => {
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
            console.log("%c[TradeForwarder] 👁️ Successfully attached to chat.", styleInit);
            clearInterval(startObserver);
        }
    }, 2000);
})();
