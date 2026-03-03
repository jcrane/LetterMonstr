// Copy this file to env-config.js and fill in your deployment values.
// env-config.js is gitignored and must be created before deploying.
//
// To get your Firebase config values, run:
//   firebase apps:sdkconfig web --project YOUR_PROJECT_ID

window.LETTERMONSTR_CONFIG = {
  firebase: {
    apiKey: "YOUR_API_KEY",
    authDomain: "YOUR_PROJECT.firebaseapp.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT.firebasestorage.app",
    messagingSenderId: "YOUR_SENDER_ID",
    appId: "YOUR_APP_ID",
  },
  authorizedEmail: "you@example.com",
  region: "us-central1",
};
