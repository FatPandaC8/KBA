import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/ai_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'support/fakes.dart';

Note _note({
  String id = 'note-1',
  ProcessingStatus status = ProcessingStatus.failed,
  int retryCount = 0,
  String? audioPath = '/tmp/echo-test.m4a',
}) {
  final now = DateTime.utc(2026, 1, 1);
  return Note(
    id: id,
    audioPath: audioPath,
    audioDurationMs: 1200,
    originalContent: 'Original content',
    title: 'Original title',
    status: status,
    retryCount: retryCount,
    createdAt: now,
    updatedAt: now,
  );
}

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
    provider = NoteProvider(repo, AIService(settings), backend, settings);
  });

  test(
    'delete is server-first and keeps the note when cleanup fails',
    () async {
      final note = _note(status: ProcessingStatus.ready);
      repo.inMemory.add(note);
      await provider.loadNotes();

      backend.failDelete = true;
      await expectLater(
        provider.deleteNote(note.id),
        throwsA(isA<Exception>()),
      );
      expect(repo.inMemory, hasLength(1));

      backend.failDelete = false;
      await provider.deleteNote(note.id);
      expect(repo.inMemory, isEmpty);
      expect(backend.deleteCalls, 2);
    },
  );

  test('concurrent retries upload a capture only once', () async {
    final note = _note();
    repo.inMemory.add(note);
    await provider.loadNotes();

    backend.uploadGate = Completer<void>();
    final first = provider.syncCaptureToBackend(note.id);
    final second = provider.syncCaptureToBackend(note.id);
    backend.uploadGate!.complete();
    await Future.wait([first, second]);
    await pumpEventQueue();

    expect(backend.uploadCalls, 1);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.ready);
    expect(saved.retryCount, 0);
  });

  test('restart resumes eligible failed work', () async {
    final note = _note(retryCount: 1);
    repo.inMemory.add(note);
    await provider.loadNotes();

    await provider.retryPendingWork();
    await pumpEventQueue();

    expect(backend.uploadCalls, 1);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.ready);
  });

  test('restart does not exceed the bounded retry budget', () async {
    final note = _note(retryCount: NoteProvider.maxRetryAttempts);
    repo.inMemory.add(note);
    await provider.loadNotes();

    await provider.retryPendingWork();
    await pumpEventQueue();

    expect(backend.uploadCalls, 0);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.failed);
    expect(saved.retryCount, NoteProvider.maxRetryAttempts);
  });

  test(
    'failed upload records a visible failure and increments retryCount',
    () async {
      final note = _note(retryCount: 0);
      repo.inMemory.add(note);
      await provider.loadNotes();
      backend.failUpload = true;

      await provider.syncCaptureToBackend(note.id);
      await pumpEventQueue();

      final saved = await repo.getNoteById(note.id);
      expect(saved!.status, ProcessingStatus.failed);
      expect(saved.failureReason, isNotNull);
      expect(saved.retryCount, 1);
    },
  );
}
