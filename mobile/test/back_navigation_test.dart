import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/app_shell.dart';
import 'package:mobile/ui/screens/detail/note_detail_screen.dart';
import 'package:mobile/ui/screens/home/home_screen.dart';
import 'package:mobile/ui/screens/library/library_screen.dart';
import 'package:mobile/ui/screens/recall/recall_screen.dart';
import 'package:mobile/ui/screens/settings/settings_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  Future<List<Note>> searchNotes(String query) async {
    final q = query.toLowerCase();
    return inMemory.where((n) {
      return n.title.toLowerCase().contains(q) ||
          n.originalContent.toLowerCase().contains(q) ||
          (n.summary?.toLowerCase().contains(q) ?? false);
    }).toList();
  }
}

class MockAudioService extends Fake implements AudioService {
  @override
  Future<bool> isRecording() async => false;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late MockNoteRepository repo;
  late NoteProvider noteProvider;
  late MockAudioService audioService;
  late SettingsService settingsService;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    settingsService = SettingsService(prefs);
    await settingsService.setSessionToken('test-session-token');
    repo = MockNoteRepository();

    final testNote = Note(
      id: 'test-note-1',
      originalContent: 'Sample note content',
      title: 'Sample Note',
      summary: 'Summary of sample note',
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
    await repo.insertNote(testNote);

    final backendService = BackendService(settingsService);

    noteProvider = NoteProvider(
      repo,
      backendService,
      settingsService,
    );
    await noteProvider.loadNotes();
    audioService = MockAudioService();
  });

  Widget createTestWidget() {
    return MaterialApp(
      home: AppShell(
        noteProvider: noteProvider,
        audioService: audioService,
        settingsService: settingsService,
      ),
    );
  }

  testWidgets('1. Back from detail screen returns to calling screen', (
    tester,
  ) async {
    await tester.pumpWidget(createTestWidget());
    await tester.pumpAndSettle();

    // Verify initially on Home screen
    expect(find.byType(HomeScreen), findsOneWidget);
    expect(find.byType(NoteDetailScreen), findsNothing);

    // Open detail screen
    final home = tester.widget<HomeScreen>(find.byType(HomeScreen));
    home.onOpenDetail('test-note-1');
    await tester.pumpAndSettle();

    expect(find.byType(NoteDetailScreen), findsOneWidget);

    // Trigger back
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();

    // Verify detail is closed and back on Home
    expect(find.byType(NoteDetailScreen), findsNothing);
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('2. Back from settings modal/screen dismisses it', (
    tester,
  ) async {
    await tester.pumpWidget(createTestWidget());
    await tester.pumpAndSettle();

    // Tap settings icon in EchoAppBar
    expect(find.byIcon(Icons.settings_outlined), findsOneWidget);
    await tester.tap(find.byIcon(Icons.settings_outlined));
    await tester.pumpAndSettle();

    expect(find.byType(SettingsScreen), findsOneWidget);

    // Trigger back via system back
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();

    expect(find.byType(SettingsScreen), findsNothing);
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('3. Back after switching main tabs returns to previous tab', (
    tester,
  ) async {
    await tester.pumpWidget(createTestWidget());
    await tester.pumpAndSettle();

    // Initially at Home (tab 0)
    expect(find.byType(HomeScreen), findsOneWidget);

    // Tap Library tab (index 2)
    final libraryNav = find.text('Library');
    expect(libraryNav, findsOneWidget);
    await tester.tap(libraryNav);
    await tester.pumpAndSettle();

    expect(find.byType(LibraryScreen), findsOneWidget);

    // Trigger back
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    final didPopHandled = await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();

    expect(didPopHandled, isTrue);
    // Should return to Home tab
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('4. Back at root screen (Home tab) allows pop / exit', (
    tester,
  ) async {
    await tester.pumpWidget(createTestWidget());
    await tester.pumpAndSettle();

    // We are at root Home tab with empty history
    expect(find.byType(HomeScreen), findsOneWidget);

    // Check PopScope configuration
    final popScopeFinder = find.byWidgetPredicate((w) => w is PopScope);
    expect(popScopeFinder, findsOneWidget);
    final popScopeWidget = tester.widget(popScopeFinder) as dynamic;
    expect(popScopeWidget.canPop, isTrue);

    // Trigger back route
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    final result = await widgetsAppState.didPopRoute();
    // At root with canPop: true, didPopRoute returns false, allowing Android OS to exit
    expect(result, isFalse);
  });

  testWidgets(
    '5. Repeated tab switching followed by Back traverses history correctly',
    (tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.pumpAndSettle();

      // Sequence: Home(0) -> Recall(1) -> Library(2)
      await tester.tap(find.text('Recall'));
      await tester.pumpAndSettle();
      expect(find.byType(RecallScreen), findsOneWidget);

      await tester.tap(find.text('Library'));
      await tester.pumpAndSettle();
      expect(find.byType(LibraryScreen), findsOneWidget);

      final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));

      // First Back -> should go back to Recall
      await widgetsAppState.didPopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(RecallScreen), findsOneWidget);

      // Second Back -> should go back to Home
      await widgetsAppState.didPopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(HomeScreen), findsOneWidget);

      // Now at Home, popScope should allow exit
      final popScopeFinder = find.byWidgetPredicate((w) => w is PopScope);
      expect(popScopeFinder, findsOneWidget);
      final popScopeWidget = tester.widget(popScopeFinder) as dynamic;
      expect(popScopeWidget.canPop, isTrue);
    },
  );
}
