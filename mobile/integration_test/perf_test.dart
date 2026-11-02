// E2E perf harness (test-only): drives the REAL app on a real device in
// profile mode and reports FrameTiming stats over 3 x 20 s scripted pan/zoom
// passes on the seeded knowledge graph (task Step 5).
//
// Run from the mobile/ directory (device must be attached):
//   flutter drive \
//     --driver=test_driver/perf_driver.dart \
//     --target=integration_test/perf_test.dart \
//     --profile \
//     --dart-define=BACKEND_URL=http://127.0.0.1:8000 \
//     --dart-define=PERF_SESSION_TOKEN=<session token>
//
// Backend-session note: the test injects the session token of the seeded
// e2e account through SettingsService before rendering the app shell. This
// mirrors the app's own login flow (server round-trip, secure storage) and
// was chosen because on this device in-memory UI login is not reachable via
// the integration-test IME bridge (tester.enterText is a no-op in the live
// binding; see e2e report). The token is created through the normal
// /api/auth/login flow by the e2e driver outside the test.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:mobile/main.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/state/note_provider.dart';

const _sessionToken = String.fromEnvironment(
  'PERF_SESSION_TOKEN',
  defaultValue: 'hFKOTa1-LyEqKh5WQuuQH9wn1R-NQMkdsT0pvI8xa9E',
);

Future<void> main() async {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('graph pan/zoom frame performance (3 x 20s)', (tester) async {
    final settingsService = await SettingsService.init();
    // The keystore read in SettingsService._loadSessionToken fails (err 7) and
    // resets _sessionToken='' some time after init(); set/retry the token
    // until the in-memory state stays (e2e report, Keystore err 7).
    await Future<void>.delayed(const Duration(milliseconds: 250));

    final noteProvider = NoteProvider(
      NoteRepository(),
      BackendService(settingsService),
      settingsService,
    );
    final audioService = AudioService();

    await tester.pumpWidget(
      EchoApp(
        noteProvider: noteProvider,
        audioService: audioService,
        settingsService: settingsService,
      ),
    );
    await tester.pump(const Duration(seconds: 3));

    for (var attempt = 0; attempt < 6; attempt++) {
      if (settingsService.isAuthenticated) break;
      await settingsService.setSessionToken(_sessionToken);
      await Future<void>.delayed(const Duration(milliseconds: 300));
      await tester.pump(const Duration(seconds: 1));
    }
    debugPrint(
      'HARNESS sessionTokenLen=${settingsService.sessionToken.length} '
      'isAuth=${settingsService.isAuthenticated}',
    );

    // wait for the tab shell (isAuthenticated) instead of the auth gate
    final graphTab = find.text('Graph');
    for (var i = 0; i < 15 && graphTab.evaluate().isEmpty; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    if (graphTab.evaluate().isEmpty) {
      fail('app did not reach the tab shell (session token rejected?)');
    }

    await tester.tap(graphTab.last);
    await tester.pump(const Duration(seconds: 2));

    // Wait for the seeded graph to render (the seeded "Echo" node appears).
    final seedNode = find.textContaining('Echo');
    for (var i = 0; i < 30; i++) {
      if (seedNode.evaluate().isNotEmpty) break;
      await tester.pump(const Duration(seconds: 1));
    }

    if (seedNode.evaluate().isEmpty) {
      fail('seeded graph did not load (no Echo node found)');
    }
    await tester.pump(const Duration(seconds: 1));

    final zoomIn = find.byTooltip('Zoom in');
    final zoomOut = find.byTooltip('Zoom out');
    final fit = find.byTooltip('Fit graph');

    for (var run = 1; run <= 3; run++) {
      await binding.watchPerformance(
        () => _scriptedPass(tester, zoomIn, zoomOut, fit),
        reportKey: 'perf_run$run',
      );
      // flush FrameTimings between runs
      await Future<void>.delayed(const Duration(seconds: 2));
    }

    debugPrint(
      'PERF_JSON ${_compact(binding.reportData ?? <String, dynamic>{})}',
    );
  }, timeout: const Timeout(Duration(minutes: 8)));
}

Future<void> _scriptedPass(
  WidgetTester tester,
  Finder zoomIn,
  Finder zoomOut,
  Finder fit,
) async {
  final screen = tester.view.physicalSize;
  final canvasCenter = Offset(
    screen.width.toDouble() / 2,
    screen.height.toDouble() * 0.45,
  );
  const int steps = 8;

  Future<void> drag(Offset delta) async {
    final gesture = await tester.startGesture(canvasCenter);
    for (var i = 0; i < steps; i++) {
      await gesture.moveBy(Offset(delta.dx / steps, delta.dy / steps));
      await tester.pump(const Duration(milliseconds: 60));
    }
    await gesture.up();
    await tester.pump(const Duration(milliseconds: 120));
  }

  for (var i = 0; i < 4; i++) {
    await drag(const Offset(-180.0, 120.0));
    await drag(const Offset(180.0, -120.0));
  }
  await Future<void>.delayed(const Duration(seconds: 3));
  for (var i = 0; i < 3; i++) {
    await tester.tap(zoomIn, warnIfMissed: false);
    await tester.pump(const Duration(milliseconds: 700));
  }
  for (var i = 0; i < 3; i++) {
    await tester.tap(zoomOut, warnIfMissed: false);
    await tester.pump(const Duration(milliseconds: 700));
  }
  await tester.tap(fit, warnIfMissed: false);
  await tester.pump(const Duration(milliseconds: 700));
  for (var i = 0; i < 6; i++) {
    await drag(const Offset(-120.0, 200.0));
    await drag(const Offset(120.0, -200.0));
  }
}

String _compact(Map<String, dynamic> report) {
  final buf = StringBuffer('{');
  report.forEach((key, value) {
    if (value is Map) {
      buf.write('"$key":$value,');
    } else {
      buf.write('"$key":"$value",');
    }
  });
  buf.write('}');
  return buf.toString();
}
