import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/home/home_screen.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';

import 'support/fakes.dart';

class _RecordingAudioService extends Fake implements AudioService {
  bool _active = false;

  @override
  Future<bool> checkPermission() async => true;

  @override
  Future<bool> requestPermission() async => true;

  @override
  Future<void> startRecording() async => _active = true;

  @override
  Future<({String path, int durationMs})?> stopRecording() async {
    if (!_active) return null;
    _active = false;
    return (path: '/mock/path/failed_capture.m4a', durationMs: 1800);
  }

  @override
  Future<void> cancelRecording() async => _active = false;

  @override
  Future<bool> isRecording() async => _active;
}

/// PRC-01 / PRC-05 feedback: the "Organizing…" banner must not outlive the
/// job. When processing fails, the user is told so instead of being left with
/// a spinner-style message that never resolves.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    settings = SettingsService();
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    NoteProvider.statusPollInterval = Duration.zero;
    provider = NoteProvider(repo, backend, settings);
    await provider.loadNotes();
  });

  tearDown(() {
    NoteProvider.statusPollInterval = const Duration(milliseconds: 600);
  });

  testWidgets('a failed capture replaces the organizing banner', (
    tester,
  ) async {
    backend.terminalErrorClass = 'invalid_input';

    await tester.pumpWidget(
      MaterialApp(
        home: HomeScreen(
          noteProvider: provider,
          audioService: _RecordingAudioService(),
          onOpenDetail: (_) {},
          onOpenSettings: () {},
          onOpenLibrary: () {},
          onOpenRecordings: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    final mic = find.byType(MicHaloButton);
    final gesture = await tester.startGesture(tester.getCenter(mic));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1200));
    await gesture.up();
    await tester.pumpAndSettle();

    expect(repo.inMemory, hasLength(1));
    expect(repo.inMemory.single.status.name, 'failed');

    // The stale banner is gone...
    expect(find.text('Thought captured! Organizing…'), findsNothing);
    // ...and the real outcome is shown.
    expect(find.textContaining('could not be processed'), findsOneWidget);

    // The outcome banner must also expire instead of pinning itself to the
    // screen (SnackBars with an action persist by default in current Flutter).
    await tester.pump(const Duration(seconds: 7));
    await tester.pumpAndSettle();
    expect(find.textContaining('could not be processed'), findsNothing);
  });
}
