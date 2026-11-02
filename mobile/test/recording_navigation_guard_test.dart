import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/app_shell.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';
import 'package:mobile/ui/widgets/echo_bottom_nav.dart';

import 'support/fakes.dart';

class FakeAudioService extends Fake implements AudioService {
  bool active = false;

  @override
  Future<bool> checkPermission() async => true;

  @override
  Future<bool> requestPermission() async => true;

  @override
  Future<void> startRecording() async {
    active = true;
  }

  @override
  Future<({String path, int durationMs})?> stopRecording() async {
    if (!active) return null;
    active = false;
    return (path: '/tmp/guard-test.m4a', durationMs: 1500);
  }

  @override
  Future<void> cancelRecording() async {
    active = false;
  }

  @override
  Future<bool> isRecording() async => active;
}

void main() {
  late NoteProvider provider;
  late FakeAudioService audioService;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
final settings = SettingsService();
    await settings.setSessionToken('test-session-token');
    audioService = FakeAudioService();
    provider = NoteProvider(
      FakeNoteRepository(),
      FakeBackendService(settings),
      settings,
    );
    await provider.loadNotes();
  });

  testWidgets('tab navigation is blocked while a recording is active', (
    tester,
  ) async {
    final shellSettings = SettingsService();
    await shellSettings.setSessionToken('test-session-token');
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          noteProvider: provider,
          audioService: audioService,
          settingsService: shellSettings,
        ),
      ),
    );
    // The mic button pulses forever, so pumpAndSettle never returns; pump a
    // bounded number of frames instead.
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(MicHaloButton)),
    );
    await tester.pump(const Duration(milliseconds: 100));
    expect(audioService.active, isTrue);

    // Tapping another tab must not leave the capture screen mid-recording.
    await tester.tap(
      find.descendant(
        of: find.byType(EchoBottomNav),
        matching: find.text('Graph'),
      ),
    );
    await tester.pump();
    await tester.pump();

    // The user stays on the Record tab (app_shell keeps both tabs mounted,
    // so assert on the active index instead of a hero string).
    final bottomNav = tester.widget<EchoBottomNav>(
      find.byType(EchoBottomNav),
    );
    expect(bottomNav.currentIndex, 0);
    expect(
      find.text('Stop recording before leaving this screen.'),
      findsOneWidget,
    );

    await gesture.up();
    // Bounded pumps again: the pipeline runs inside the (fake) requests and
    // the mic animation never settles by itself.
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  });
}
