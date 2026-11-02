import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
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
  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
    settings = SettingsService();
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    provider = NoteProvider(repo, backend, settings);
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

  test('concurrent retries run the ingest only once', () async {
    final note = _note();
    repo.inMemory.add(note);
    await provider.loadNotes();

    backend.ingestGate = Completer<void>();
    final first = provider.retryNote(note.id);
    final second = provider.retryNote(note.id);
    backend.ingestGate!.complete();
    await Future.wait([first, second]);
    await pumpEventQueue();

    expect(backend.ingestCalls, 1);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.ready);
  });

  test('restart resumes eligible failed work through the split pipeline',
      () async {
    final note = _note();
    repo.inMemory.add(note);
    await provider.loadNotes();

    await provider.retryPendingWork();
    await pumpEventQueue();

    expect(backend.transcribeCalls, 1);
    expect(backend.ingestCalls, 1);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.ready);
  });

  test('restart never re-ingests a failed note without audio or transcript',
      () async {
    final note = _note(audioPath: null);
    repo.inMemory.add(note);
    await provider.loadNotes();

    await provider.retryPendingWork();
    await pumpEventQueue();

    expect(backend.transcribeCalls, 0);
    expect(backend.ingestCalls, 0);
    final saved = await repo.getNoteById(note.id);
    expect(saved!.status, ProcessingStatus.failed);
  });

  test(
    'a Text-KB failure keeps the transcript: Retry re-sends the SAME '
    'capture_id without running STT again',
    () async {
      backend.failIngest = true;
      final note = await provider.createAudioNote(
        audioPath: '/tmp/echo-test.m4a',
        durationMs: 1200,
      );
      await pumpEventQueue();

      final failed = await repo.getNoteById(note.id);
      expect(failed!.status, ProcessingStatus.failed);
      expect(backend.transcribeCalls, 1);
      expect(backend.ingestCalls, 1);

      // The user fixes the condition and taps Retry: the transcript is in
      // memory, so only Text-KB runs again with the same capture_id.
      backend.failIngest = false;
      await provider.retryNote(note.id);
      await pumpEventQueue();

      expect(backend.transcribeCalls, 1,
          reason: 'STT must NOT run twice for one capture');
      expect(backend.ingestCalls, 2);
      expect(backend.ingestedCaptureIds, everyElement(note.id),
          reason: 'retries re-send the SAME capture_id (idempotent)');
      final saved = await repo.getNoteById(note.id);
      expect(saved!.status, ProcessingStatus.ready);
    },
  );

  test(
    'a failed ingest records a typed, visible failure reason',
    () async {
      backend.failIngest = true;

      final note = await provider.createAudioNote(
        audioPath: '/tmp/echo-test.m4a',
        durationMs: 1200,
      );
      await pumpEventQueue();

      final saved = await repo.getNoteById(note.id);
      expect(saved!.status, ProcessingStatus.failed);
      expect(saved.failureReason, isNotNull);
    },
  );
}

