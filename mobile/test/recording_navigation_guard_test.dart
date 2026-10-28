import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/ai_service.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/app_shell.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';

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
  TestWidgetsFlutterBinding.ensureInitialized();

  late NoteProvider provider;
  late FakeAudioService audioService;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final settings = SettingsService(prefs);
    audioService = FakeAudioService();
    provider = NoteProvider(
      FakeNoteRepository(),
      AIService(settings),
      FakeBackendService(settings),
      settings,
    );
    await provider.loadNotes();
  });

  testWidgets('tab navigation is blocked while a recording is active', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AppShell(
          noteProvider: provider,
          audioService: audioService,
          settingsService: SettingsService(
            await SharedPreferences.getInstance(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(MicHaloButton)),
    );
    await tester.pump(const Duration(milliseconds: 100));
    expect(audioService.active, isTrue);

    // Tapping Library must not leave the capture screen mid-recording.
    await tester.tap(find.text('Library'));
    await tester.pump();

    expect(find.text('Capture what matters.'), findsOneWidget);
    expect(
      find.text('Stop recording before leaving this screen.'),
      findsOneWidget,
    );

    await gesture.up();
    await tester.pumpAndSettle();
  });
}
