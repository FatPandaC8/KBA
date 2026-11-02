import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'support/fakes.dart';

/// End-to-end client behaviour for the pipeline split (S1/S2): record ->
/// POST /api/stt -> keep transcript -> POST /api/text-kb (same capture_id on
/// retry) -> graph update. No real network or audio hardware is involved.
void main() {
  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;
  late Directory tempDir;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    installSecureStorageMock(TestWidgetsFlutterBinding.ensureInitialized());
    settings = SettingsService();
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    provider = NoteProvider(repo, backend, settings);
    tempDir = await Directory.systemTemp.createTemp('echo_m3_');
  });

  tearDown(() async {
    if (await tempDir.exists()) await tempDir.delete(recursive: true);
  });

  String writeAudio(String name) {
    final file = File('${tempDir.path}/$name');
    file.writeAsBytesSync(const [1, 2, 3, 4]);
    return file.path;
  }

  Future<void> waitFor(bool Function() condition, {String? reason}) async {
    for (var i = 0; i < 400; i++) {
      if (condition()) return;
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
    fail(reason ?? 'condition not met in time');
  }

  Note noteFor(String id) => provider.notes.firstWhere((n) => n.id == id);

  test('record runs STT then Text-KB and reaches ready without polling',
      () async {
    final note = await provider.createAudioNote(
      audioPath: writeAudio('ready.m4a'),
      durationMs: 2000,
    );

    await waitFor(
      () => noteFor(note.id).status == ProcessingStatus.ready,
      reason: 'the synchronous pipeline finishes inside the requests',
    );

    expect(backend.transcribeCalls, 1);
    expect(backend.ingestCalls, 1);
    expect(backend.ingestedCaptureIds, [note.id],
        reason: 'the client-generated capture_id is used for Text-KB');
    final ready = noteFor(note.id);
    expect(ready.knowledgeItemId, isNotNull);
    expect(ready.errorClass, '');
    expect(ready.failureReason, isNull);
    // The server stores nothing: the local file is the only copy.
    expect(File('${tempDir.path}/ready.m4a').existsSync(), isTrue);
  });

  test(
    'local audio is retained when STT fails (retry needs the bytes)',
    () async {
      final path = writeAudio('stt-failed.m4a');
      backend.failStt = true;

      final note = await provider.createAudioNote(
        audioPath: path,
        durationMs: 2000,
      );

      await waitFor(
        () => noteFor(note.id).status == ProcessingStatus.failed,
        reason: 'STT failure must surface immediately',
      );

      final failed = noteFor(note.id);
      // The split pipeline stores no audio server-side, so the local bytes
      // are the only copy and must be kept.
      expect(
        File(path).existsSync(),
        isTrue,
        reason: 'the next STT attempt re-sends this audio',
      );
      expect(failed.audioPath, path);
      expect(failed.errorClass, 'invalid_input');
      expect(failed.failureReason, isNotNull);
    },
  );

  test('consent rejection is not reported as an invalid session', () async {
    backend.failAuth = true;

    final note = await provider.createAudioNote(
      audioPath: writeAudio('consent-required.m4a'),
      durationMs: 2000,
    );

    await waitFor(() => noteFor(note.id).status == ProcessingStatus.failed);

    final failed = noteFor(note.id);
    expect(failed.errorClass, 'consent_required');
    expect(failed.failureReason, contains('AI processing'));
    expect(failed.failureReason, isNot(contains('session')));
  });

  test('visible processing states: transcribing -> structuring -> ready',
      () async {
    backend.ingestGate = Completer<void>();
    final seen = <ProcessingStatus>[];

    provider.addListener(() {
      if (provider.notes.isEmpty) return;
      seen.add(provider.notes.first.status);
    });

    final note = await provider.createAudioNote(
      audioPath: writeAudio('states.m4a'),
      durationMs: 2000,
    );

    await waitFor(
      () => seen.contains(ProcessingStatus.structuring),
      reason: 'the app shows a progress state while Text-KB is waiting',
    );
    backend.ingestGate!.complete();

    await waitFor(() => noteFor(note.id).status == ProcessingStatus.ready);
    expect(seen, containsAllInOrder([
      ProcessingStatus.transcribing,
      ProcessingStatus.structuring,
    ]));
  });

  test('server error classes get actionable, honest messages', () async {
    backend.failIngest = true;

    final note = await provider.createAudioNote(
      audioPath: writeAudio('invalid.m4a'),
      durationMs: 900,
    );

    await waitFor(() => noteFor(note.id).status == ProcessingStatus.failed);

    final failed = noteFor(note.id);
    expect(failed.errorClass, 'server_error');
    expect(failed.failureReason, isNotNull);
  });

  test(
    'reconciliation picks up server recordings on app open (NET-02)',
    () async {
      backend.recordings.add(
        RecordingModel(
          captureId: 'server-ready',
          createdAt: '2026-02-01T10:00:00Z',
          hasKnowledgeItem: true,
          lastError: null,
        ),
      );
      backend.recordings.add(
        RecordingModel(
          captureId: 'server-failed',
          createdAt: '2026-02-01T11:00:00Z',
          hasKnowledgeItem: false,
          lastError: 'text-kb ingest failed (provider schema)',
        ),
      );
      backend.knowledgeByCapture['server-ready'] = KnowledgeSnapshot(
        knowledgeItemId: 'k-server-ready',
        title: 'Quarterly plan',
        coreIdea: 'Ship the Android MVP',
        concepts: const ['MVP'],
        tags: const ['work'],
        openQuestions: const [],
      );

      await provider.reconcileWithBackend();

      final ready = noteFor('server-ready');
      expect(ready.status, ProcessingStatus.ready);
      expect(ready.title, 'Quarterly plan');
      expect(ready.summary, 'Ship the Android MVP');
      expect(ready.knowledgeItemId, 'k-server-ready');
      expect(ready.hasLocalAudio, isFalse);
      expect(ready.createdAt.toUtc().year, 2026);

      final failed = noteFor('server-failed');
      expect(failed.status, ProcessingStatus.failed);
      expect(failed.failureReason, isNotNull);

      // Reopening the app never creates work; it only reads.
      expect(backend.transcribeCalls, 0);
      expect(backend.ingestCalls, 0);
    },
  );

  test(
    'reconciliation marks an existing local capture ready from the journal',
    () async {
      final path = writeAudio('reconciled.m4a');
      await repo.insertNote(
        Note(
          id: 'local-capture',
          audioPath: path,
          audioDurationMs: 1000,
          originalContent: '[Voice recording]',
          title: 'Voice Thought',
          status: ProcessingStatus.transcribing,
          createdAt: DateTime.now(),
          updatedAt: DateTime.now(),
        ),
      );
      await provider.loadNotes();

      backend.recordings.add(
        RecordingModel(
          captureId: 'local-capture',
          createdAt: DateTime.now().toIso8601String(),
          hasKnowledgeItem: true,
          lastError: null,
        ),
      );
      backend.knowledgeByCapture['local-capture'] = KnowledgeSnapshot(
        knowledgeItemId: 'k-local',
        title: 'Local capture',
        coreIdea: 'Recovered knowledge',
        concepts: const [],
        tags: const [],
        openQuestions: const [],
      );

      await provider.reconcileWithBackend();

      final note = noteFor('local-capture');
      // The local audio stays: nothing is stored server-side (S4b).
      expect(File(path).existsSync(), isTrue);
      expect(note.audioPath, path);
      expect(note.status, ProcessingStatus.ready);
      expect(note.title, 'Local capture');
    },
  );
}
