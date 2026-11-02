# Echo Mobile (Android)

Flutter client for Echo. Android is the actively supported target; the iOS
scaffold is preserved but is not built or verified in this phase.

## Manual run

Start the PostgreSQL-backed server first; see the repository-root `README.md`.
The backend URL is a compile-time `BACKEND_URL` value, not an in-app setting.

For a USB-connected device:

```bash
adb devices
adb reverse tcp:8000 tcp:8000
cd mobile
flutter pub get
flutter run -d <android-device-id> \
  --dart-define=BACKEND_URL=http://127.0.0.1:8000
```

For an Android emulator, use the host address supported by that emulator
(commonly `http://10.0.2.2:8000`). The app signs users in through the auth
screens and stores the user's session token in secure storage. Do not put the
admin token in the app.

The capture flow is synchronous from the client's perspective:

1. Record locally.
2. Send raw audio bytes to `POST /api/stt`; the server returns a transcript
   and persists nothing.
3. Keep the transcript in memory and send it to `POST /api/text-kb` with the
   note's UUID as `capture_id`.
4. On a Text-KB retry, resend the same UUID and cached transcript. STT only
   runs again when no transcript was obtained.

The local audio remains on device because the API does not upload it. Debug
builds can use HTTP for local development. Release builds require HTTPS.

## Verify

```bash
cd mobile
flutter analyze lib test
flutter test
flutter build apk --debug \
  --dart-define=BACKEND_URL=http://127.0.0.1:8000
```

Profile build for a physical-device performance test:

```bash
flutter build apk --profile \
  --dart-define=BACKEND_URL=http://127.0.0.1:8000
```

The committed integration performance harness uses `flutter drive`; see
`integration_test/perf_test.dart` for the exact command and the required
`PERF_SESSION_TOKEN` test define.

## Signing

Release builds use `android/key.properties` and the referenced keystore only
when the owner supplies them. Otherwise they fall back to the debug key and are
not production artifacts. The application ID `dev.echo.notes.dev` is
provisional.
