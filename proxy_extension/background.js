// Proxy credentials - will be replaced by Python script
const PROXY_LOGIN = "LOGIN_PLACEHOLDER";
const PROXY_PASSWORD = "PASSWORD_PLACEHOLDER";

console.log("=== Proxy Auto Auth Extension Loading ===");
console.log("Login:", PROXY_LOGIN);
console.log("Password length:", PROXY_PASSWORD ? PROXY_PASSWORD.length : 0);

// Listen for authentication requests
chrome.webRequestAuthProvider.onAuthRequired.addListener(
  (details, callback) => {
    console.log("=== Auth Required Event ===");
    console.log("Request ID:", details.requestId);
    console.log("URL:", details.url);
    console.log("Proxy:", details.proxy ? `${details.proxy.host}:${details.proxy.port}` : 'unknown');
    console.log("Realm:", details.realm);
    console.log("IsProxy:", details.isProxy);
    
    // Provide credentials
    const credentials = {
      authCredentials: {
        username: PROXY_LOGIN,
        password: PROXY_PASSWORD
      }
    };
    
    console.log("Providing credentials:", credentials.authCredentials.username);
    callback(credentials);
  },
  { urls: ["<all_urls>"] }
);

console.log("=== Extension Listener Registered ===");
