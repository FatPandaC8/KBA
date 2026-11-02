import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/audio_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/app_shell.dart';
import 'package:mobile/ui/screens/detail/note_detail_screen.dart';
import 'package:mobile/ui/screens/home/home_screen.dart';
import 'package:mobile/ui/screens/library/library_screen.dart';
import 'package:mobile/ui/screens/recordings/recordings_screen.dart';
import 'package:mobile/ui/screens/settings/settings_screen.dart';
import 'package:mobile/ui/widgets/echo_bottom_nav.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fakes.dart';

class MockAudioService extends Fake implements AudioService {
  @override
  Future<bool> isRecording() async => false;
}

void main() {
  late FakeNoteRepository repo;
  late NoteProvider noteProvider;
  late MockAudioService audioService;
  late SettingsService settingsService;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
    settingsService = SettingsService();
    await settingsService.setSessionToken('test-session-token');
    repo = FakeNoteRepository();

    final testNote = Note(
      id: 'test-note-1',
      originalContent: 'Sample note content',
      title: 'Sample Note',
      summary: 'Summary of sample note',
      status: ProcessingStatus.ready,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
    await repo.insertNote(testNote);

    noteProvider = NoteProvider(
      repo,
      FakeBackendService(settingsService),
      settingsService,
    );
    await noteProvider.loadNotes();
    audioService = MockAudioService();
  });

  Finder navItem(String label) => find.descendant(
    of: find.byType(EchoBottomNav),
    matching: find.text(label),
  );

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

    // Verify initially on the Record tab
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

    // Verify detail is closed and back on the Record tab
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

    // Initially on the Record tab
    expect(find.byType(HomeScreen), findsOneWidget);

    // Tap the Graph tab (index 1)
    await tester.tap(navItem('Graph'));
    await tester.pumpAndSettle();

    expect(find.byType(LibraryScreen), findsOneWidget);

    // Trigger back
    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    final didPopHandled = await widgetsAppState.didPopRoute();
    await tester.pumpAndSettle();

    expect(didPopHandled, isTrue);
    // Should return to the Record tab
    expect(find.byType(HomeScreen), findsOneWidget);
  });

  testWidgets('4. Back at root screen (Record tab) allows pop / exit', (
    tester,
  ) async {
    await tester.pumpWidget(createTestWidget());
    await tester.pumpAndSettle();

    expect(find.byType(HomeScreen), findsOneWidget);

    // Check PopScope configuration
    final popScopeFinder = find.byWidgetPredicate((w) => w is PopScope);
    expect(popScopeFinder, findsOneWidget);
    final popScopeWidget = tester.widget(popScopeFinder) as dynamic;
    expect(popScopeWidget.canPop, isTrue);

    final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));
    final result = await widgetsAppState.didPopRoute();
    expect(result, isFalse);
  });

  testWidgets(
    '5. Repeated tab switching followed by Back traverses history correctly',
    (tester) async {
      await tester.pumpWidget(createTestWidget());
      await tester.pumpAndSettle();

      // Sequence: Record(0) -> Graph(1) -> Record(0) -> Graph(1)
      await tester.tap(navItem('Graph'));
      await tester.pumpAndSettle();
      expect(find.byType(LibraryScreen), findsOneWidget);

      await tester.tap(navItem('Record'));
      await tester.pumpAndSettle();
      expect(find.byType(HomeScreen), findsOneWidget);

      // Back through the tab history: Graph, Record, then exit is allowed.
      final dynamic widgetsAppState = tester.state(find.byType(WidgetsApp));

      // First Back -> should go back to Graph
      await widgetsAppState.didPopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(LibraryScreen), findsOneWidget);

      // Second Back -> should go back to Record
      await widgetsAppState.didPopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(HomeScreen), findsOneWidget);

      final popScopeFinder = find.byWidgetPredicate((w) => w is PopScope);
      final popScopeWidget = tester.widget(popScopeFinder) as dynamic;
      expect(popScopeWidget.canPop, isTrue);
    },
  );


}
