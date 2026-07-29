# NOIR — Expo React Native

A standalone Expo implementation of the four-screen NOIR nightlife experience:

- Cinematic access screen
- London venue discovery
- Aether Lounge VIP package details
- Reservation confirmation and wallet-pass interaction

## Run it

```bash
npm install
npm start
```

Then press `i` for the iOS Simulator, `a` for Android, or scan the QR code with Expo Go.

## Project structure

```text
App.tsx                  Screen flow
src/components.tsx       Reusable controls and bottom navigation
src/theme.ts             Color and typography tokens
src/screens/             Four app screens
assets/                  Bundled local nightlife photography
```

The project uses local image assets and does not rely on expiring Figma or image-host URLs.
