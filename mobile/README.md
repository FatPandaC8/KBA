# Echo Mobile (Android)

Flutter client for Echo. Android is the actively supported target; the iOS
scaffold is preserved but not built or verified in this phase.

## Run

```bash
flutter pub get
flutter run -d <android-device-id>
```

The backend must be running and protected by `ECHO_CLIENT_TOKEN`. In the app,
open **Settings**, set the backend URL, enter the client token, and use
**Test connection**.

For USB development the default URL `http://127.0.0.1:8000` requires:

```bash
adb reverse tcp:8000 tcp:8000
```

Debug builds allow cleartext HTTP for local development. Release builds keep
Android's secure default and require HTTPS.

## Verify

```bash
flutter analyze
flutter test
flutter build apk --debug
```

## Signing

Release builds use `android/key.properties` and the referenced keystore only
when the owner supplies them. Otherwise they fall back to the debug key and are
not production artifacts. The application ID `dev.echo.notes.dev` is
provisional.
