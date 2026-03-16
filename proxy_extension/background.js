// Proxy credentials - will be replaced by Python script
const PROXY_LOGIN = "LOGIN_PLACEHOLDER";
const PROXY_PASSWORD = "PASSWORD_PLACEHOLDER";

chrome.webRequestAuthProvider.onAuthRequired.addListener(
  (details, callback) => {
    console.log("Proxy auth required:", details);
    callback({
      authCredentials: {
        username: PROXY_LOGIN,
        password: PROXY_PASSWORD
      }
    });
  },
  { urls: ["<all_urls>"] },
  ["asyncBlocking"]
);

console.log("Proxy Auto Auth extension loaded");
