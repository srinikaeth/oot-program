// ==UserScript==
// @name         Discord Trade Forwarder (ScriptCat) - BIG LOGS
// @namespace    http://scriptcat.org/
// @version      1.4
// @description  Forwards Discord messages to a local Flask server with highly visible console logs
// @match        https://discord.com/channels/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    // 1. REPLACE THIS WITH YOUR FLASK SERVER URL
    const FLASK_URL = GM_getValue('FLASK_URL', '');
    
    // 2. REPLACE THIS WITH YOUR COPIED CHANNEL ID
    const TARGET_CHANNEL_ID = "1347238168109387857";  // OOT
    // const TARGET_CHANNEL_ID = "1476499168817188876"; // Test server

    //3. API key for sending requests correctly
    const API_SECRET_KEY = GM_getValue('API_SECRET_KEY', '');

    // 4. Source name sent to the server — stored in the trades table to identify
    //    which trader this signal came from. Change this if you switch channels.
    const SOURCE = "waxui";

    // CSS Styles for the Console
    const styleInit = "color: #bada55; font-size: 20px; font-weight: bold; background: #222; padding: 5px; border-radius: 5px;";
    const styleAlert = "color: #00e5ff; font-size: 24px; font-weight: bold; background: #111; padding: 8px; border-left: 8px solid #00e5ff;";
    const styleText = "color: #ffffff; font-size: 18px; font-style: italic; padding-left: 10px;";
    const styleSuccess = "color: #39ff14; font-size: 20px; font-weight: bold; padding: 5px;";
    const styleError = "color: #ff0000; font-size: 24px; font-weight: bold; background: #440000; padding: 8px; border: 2px solid red;";

    console.log("%c[TradeForwarder] 🚀 ScriptCat injected and waiting...", styleInit);

    function sendToFlask(author, text) {
        if (!text) return;
        
        GM_xmlhttpRequest({
            method: "POST",
            url: FLASK_URL,
            headers: {
                "Content-Type": "application/json",
                "X-Bot-Key": API_SECRET_KEY
            },
            data: JSON.stringify({ title: author, text: text, source: SOURCE }),
            onload: function(response) {
                console.log(`%c[TradeForwarder] ✅ Success! Server responded with: ${response.status}`, styleSuccess);
            },
            onerror: function(error) {
                console.log("%c[TradeForwarder] ❌ Connection Error: " + error, styleError);
            }
        });
    }

    const observer = new MutationObserver((mutations) => {
        if (!window.location.href.includes(TARGET_CHANNEL_ID)) return;

        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeName === "LI" && node.id && node.id.startsWith("chat-messages-")) {
                    
                    setTimeout(() => {
                        try {
                            const textElement = node.querySelector('[id^="message-content-"]');
                            const authorElement = node.querySelector('span[class^="username_"]');
                            
                            const text = textElement ? textElement.innerText : "";
                            const author = authorElement ? authorElement.innerText : "Unknown";

                            if (text) {
                                // This prints the giant cyan header, followed by the actual message text
                                console.log(`%c[TradeForwarder] 🔔 CAUGHT MESSAGE FROM ${author.toUpperCase()}:\n%c"${text}"`, styleAlert, styleText);
                                sendToFlask(author, text);
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