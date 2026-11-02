import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/detail/note_detail_screen.dart';

import 'support/fakes.dart';

void main() {
  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;
  late Note note;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
    settings = SettingsService();
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    final now = DateTime.utc(2026, 1, 1);
    note = Note(
      id: 'edit-race-note',
      originalContent: 'Original capture',
      transcript: 'Original capture',
      title: 'AI title',
      summary: 'AI summary',
      status: ProcessingStatus.ready,
      createdAt: now,
      updatedAt: now,
    );
    repo.inMemory.add(note);
    provider = NoteProvider(repo, backend, settings);
    await provider.loadNotes();
  });

  Widget screen() => MaterialApp(
    home: NoteDetailScreen(
      noteId: note.id,
      noteProvider: provider,
      onBack: () {},
    ),
  );

  testWidgets('displayed note updates when processing finishes', (
    tester,
  ) async {
    await tester.pumpWidget(screen());
    expect(find.text('AI title'), findsOneWidget);

    await repo.updateNote(
      note.copyWith(title: 'Fresh AI title', summary: 'Fresh summary'),
    );
    await provider.loadNotes();
    await tester.pump();

    expect(find.text('Fresh AI title'), findsOneWidget);
  });

  testWidgets('user draft is preserved when an AI update arrives mid-edit', (
    tester,
  ) async {
    await tester.pumpWidget(screen());
    await tester.tap(find.text('Edit organized ideas'));
    await tester.pumpAndSettle();

    final titleField = find.byType(TextField).first;
    await tester.enterText(titleField, 'My unsaved draft');
    await tester.pump();

    await repo.updateNote(
      note.copyWith(title: 'AI overwrite attempt', summary: 'New AI summary'),
    );
    await provider.loadNotes();
    await tester.pump();

    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.controller!.text, 'My unsaved draft');

    await tester.ensureVisible(find.text('Save changes'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save changes'));
    await tester.pumpAndSettle();

    final saved = await repo.getNoteById(note.id);
    expect(saved!.title, 'My unsaved draft');
  });
}
