import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/library/widgets/knowledge_graph_widget.dart';

import 'support/fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    settings = SettingsService(prefs);
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    final now = DateTime.utc(2026, 1, 1);
    repo.inMemory.add(
      Note(
        id: 'graph-note',
        originalContent: 'Graph content',
        title: 'Graph note',
        status: ProcessingStatus.ready,
        createdAt: now,
        updatedAt: now,
      ),
    );
    provider = NoteProvider(repo, backend, settings);
    await provider.loadNotes();
  });

  testWidgets('relationship failure is visible and retryable', (tester) async {
    backend.failGraph = true;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: KnowledgeGraphWidget(
            noteProvider: provider,
            onOpenDetail: (_) {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Connections could not be loaded'),
      findsOneWidget,
    );
    expect(find.text('Retry'), findsOneWidget);

    backend.failGraph = false;
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Connections could not be loaded'),
      findsNothing,
    );
  });
}
