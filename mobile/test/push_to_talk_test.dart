import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/home/home_screen.dart';
import 'package:mobile/ui/screens/home/widgets/mic_halo_button.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'support/fakes.dart';

class MockNoteRepository extends NoteRepository {
  final List<Note> inMemory = [];

  @override
  Future<List<Note>> getAllNotes() async => List.unmodifiable(inMemory);

  @override
  Future<void> insertNote(Note note) async {
    inMemory.removeWhere((n) => n.id == note.id);
    inMemory.add(note);
  }

  @override
  Future<Note?> getNoteById(String id) async {
    try {
      return inMemory.firstWhere((n) => n.id == id);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> updateNote(Note note) async {
    final idx = inMemory.indexWhere((n) => n.id == note.id);
    if (idx != -1) {
      inMemory[idx] = note;
    } else {
      inMemory.add(note);
    }
  }

  @override
  Future<void> deleteNote(String id) async {
    inMemory.removeWhere((n) => n.id == id);
  }

  @override
  Future<List<Note>> searchNotes(String query) async => [];
}

class TestableAudioService extends Fake implements AudioService {
  bool permissionGranted = true;
  bool isRecordingActive = false;
  int startCallCount = 0;
  int stopCallCount = 0;
  int cancelCallCount = 0;

  @override
  Future<bool> checkPermission() async => permissionGranted;

  @override
  Future<bool> requestPermission() async => permissionGranted;

  @override
  Future<void> startRecording() async {
    if (!permissionGranted) throw Exception('Permission denied');
    isRecordingActive = true;
    startCallCount++;
  }

  @override
  Future<({String path, int durationMs})?> stopRecording() async {
    if (!isRecordingActive) return null;
    isRecordingActive = false;
    stopCallCount++;
    return (path: '/mock/path/test_capture.m4a', durationMs: 1500);
  }

  @override
  Future<void> cancelRecording() async {
    isRecordingActive = false;
    cancelCallCount++;
  }

  @override
  Future<bool> isRecording() async => isRecordingActive;
}

void main() {
  late MockNoteRepository repo;
  late NoteProvider noteProvider;
  late TestableAudioService audioService;
  late SettingsService settingsService;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
settingsService = SettingsService();
    repo = MockNoteRepository();
    final backendService = BackendService(settingsService);

    noteProvider = NoteProvider(repo, backendService, settingsService);
    await noteProvider.loadNotes();
    audioService = TestableAudioService();
  });

  Widget createHomeScreen() {
    return MaterialApp(
      home: HomeScreen(
        noteProvider: noteProvider,
        audioService: audioService,
        onOpenDetail: (_) {},
        onOpenSettings: () {},
        onOpenLibrary: () {},
        onOpenRecordings: () {},
      ),
    );
  }

  testWidgets(
    '1. Press and hold starts recording; release stops and submits note',
    (tester) async {
      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);
      expect(micFinder, findsOneWidget);

      // Initial idle state
      expect(find.text('Hold to talk · Release to save'), findsOneWidget);
      expect(audioService.startCallCount, 0);

      // Press down
      final gesture = await tester.startGesture(tester.getCenter(micFinder));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(audioService.startCallCount, 1);
      expect(find.text('RECORDING'), findsOneWidget);
      expect(find.text('Listening… Release to save'), findsOneWidget);

      // Hold for 1 second (exceeds minRecordingMs threshold)
      await tester.pump(const Duration(seconds: 1));

      // Release gesture
      await gesture.up();
      await tester.pumpAndSettle();

      expect(audioService.stopCallCount, 1);
      // The capture is submitted and the banner reports the real outcome; it
      // never keeps claiming work is running after the job has settled.
      expect(find.text('Thought captured! Organizing…'), findsNothing);
      expect(find.textContaining('could not be processed'), findsOneWidget);
      expect(repo.inMemory.length, 1);
    },
  );

  testWidgets(
    '2. Brief press shows short recording feedback without submitting',
    (tester) async {
      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);

      // Tap quickly (200ms < minRecordingMs)
      final gesture = await tester.startGesture(tester.getCenter(micFinder));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      await gesture.up();
      await tester.pumpAndSettle();

      expect(audioService.startCallCount, 1);
      expect(audioService.stopCallCount, 0); // Not submitted
      expect(audioService.cancelCallCount, 1); // Cancelled
      expect(
        find.text('Recording too short. Hold the button while speaking.'),
        findsOneWidget,
      );
      expect(repo.inMemory.isEmpty, isTrue);
    },
  );

  testWidgets(
    '3. Maximum duration auto-stops and submits while button is held',
    (tester) async {
      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);
      final gesture = await tester.startGesture(tester.getCenter(micFinder));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(audioService.startCallCount, 1);

      // Advance past the 120 second ceiling while holding
      await tester.pump(const Duration(seconds: 121));
      await tester.pumpAndSettle();

      // Auto-submitted upon hitting the 2 minute limit
      expect(audioService.stopCallCount, 1);
      expect(repo.inMemory.length, 1);

      // Clean up gesture
      await gesture.up();
      await tester.pumpAndSettle();
    },
  );

  testWidgets(
    '4. Pointer cancellation (e.g. pan/cancel) cancels recording cleanly',
    (tester) async {
      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);
      final gesture = await tester.startGesture(tester.getCenter(micFinder));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(audioService.startCallCount, 1);

      // Cancel gesture (simulates interrupt/system cancel)
      await gesture.cancel();
      await tester.pumpAndSettle();

      expect(audioService.cancelCallCount, 1);
      expect(audioService.isRecordingActive, isFalse);
      expect(find.text('RECORDING'), findsNothing);
    },
  );

  testWidgets(
    '5. Permission denial displays clear error message and prevents recording',
    (tester) async {
      audioService.permissionGranted = false;

      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);
      final gesture = await tester.startGesture(tester.getCenter(micFinder));
      await tester.pump();
      await tester.pumpAndSettle();
      await gesture.up();
      await tester.pumpAndSettle();

      expect(audioService.startCallCount, 0);
      expect(
        find.textContaining('Microphone permission was denied'),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    '6. Prevents duplicate submissions and concurrent recording sessions',
    (tester) async {
      await tester.pumpWidget(createHomeScreen());
      await tester.pumpAndSettle();

      final micFinder = find.byType(MicHaloButton);
      final gesture1 = await tester.startGesture(
        tester.getCenter(micFinder),
        pointer: 1,
      );
      await tester.pump(const Duration(milliseconds: 100));

      expect(audioService.startCallCount, 1);

      // Second pointer attempting to start concurrently
      final gesture2 = await tester.startGesture(
        tester.getCenter(micFinder),
        pointer: 2,
      );
      await tester.pump(const Duration(milliseconds: 100));

      // Still only 1 start call
      expect(audioService.startCallCount, 1);

      await gesture1.up();
      await gesture2.up();
      await tester.pumpAndSettle();
    },
  );
}
