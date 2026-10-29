import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';

import 'support/fakes.dart';

/// End-to-end client behaviour for the M3 recording pipeline (REC-04, REC-05,
/// REC-06, NET-01, NET-02). No real network or audio hardware is involved.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;
  late Directory tempDir;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    settings = SettingsService(prefs);
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    NoteProvider.statusPollInterval = Duration.zero;
    provider = NoteProvider(repo, backend, settings);
    tempDir = await Directory.systemTemp.createTemp('echo_m3_');
  });

  tearDown(() async {
    NoteProvider.statusPollInterval = const Duration(milliseconds: 600);
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

  test('uploads are serialized one at a time (REC-04)', () async {
    backend.uploadGate = Completer<void>();

    final first = await provider.createAudioNote(
      audioPath: writeAudio('first.m4a'),
      durationMs: 1200,
    );
    final second = await provider.createAudioNote(
      audioPath: writeAudio('second.m4a'),
      durationMs: 1500,
    );

    await waitFor(
      () => backend.uploadCalls == 1,
      reason: 'the first upload should start',
    );
    // Give the queue a chance to misbehave before asserting.
    await Future<void>.delayed(const Duration(milliseconds: 60));
    expect(backend.uploadCalls, 1, reason: 'only one upload may be in flight');
    expect(provider.isUploadInFlight, isTrue);
    expect(backend.uploadedCaptureIds, isEmpty);

    backend.uploadGate!.complete();

    await waitFor(
      () => backend.uploadCalls == 2,
      reason: 'the queued upload should start after the first finishes',
    );
    await waitFor(
      () => backend.uploadedCaptureIds.length == 2,
      reason: 'both captures should have been uploaded',
    );

    expect(backend.uploadedCaptureIds, [first.id, second.id]);
    expect(provider.isUploadInFlight, isFalse);
  });

  test('local audio is deleted only after a terminal ready (REC-06)', () async {
    final path = writeAudio('ready.m4a');
    backend.knowledgeByCapture.clear();

    final note = await provider.createAudioNote(
      audioPath: path,
      durationMs: 2000,
    );

    await waitFor(
      () => noteFor(note.id).status == ProcessingStatus.ready,
      reason: 'the capture should become ready',
    );

    final ready = noteFor(note.id);
    expect(File(path).existsSync(), isFalse, reason: 'audio is redundant now');
    expect(ready.audioPath, isNull);
    expect(ready.audioOnServer, isTrue);
    expect(ready.stage, 'completed');
    expect(ready.knowledgeItemId, isNotNull);
    expect(ready.errorClass, '');
    expect(ready.failureReason, isNull);
  });

  test('audio is retained when processing fails (REC-05, REC-06)', () async {
    final path = writeAudio('failed.m4a');
    backend.terminalErrorClass = 'network_error';

    final note = await provider.createAudioNote(
      audioPath: path,
      durationMs: 2000,
    );

    await waitFor(
      () => noteFor(note.id).status == ProcessingStatus.failed,
      reason: 'the capture should fail',
    );

    final failed = noteFor(note.id);
    expect(File(path).existsSync(), isTrue, reason: 'retry needs the bytes');
    expect(failed.audioPath, path);
    expect(failed.errorClass, 'network_error');
    expect(failed.stage, 'transcribe');
    expect(failed.audioOnServer, isTrue);
    expect(failed.failureReason, contains('kept for retry'));
  });

  test('pipeline stages map to visible processing states (PRC-03)', () async {
    backend.stages = const ['transcribe', 'extract', 'save'];
    final seen = <ProcessingStatus, String>{};

    provider.addListener(() {
      for (final note in provider.notes) {
        seen[note.status] = note.stage;
      }
    });

    final note = await provider.createAudioNote(
      audioPath: writeAudio('stages.m4a'),
      durationMs: 2000,
    );

    await waitFor(() => noteFor(note.id).status == ProcessingStatus.ready);

    expect(seen.containsKey(ProcessingStatus.transcribing), isTrue);
    expect(seen.containsKey(ProcessingStatus.structuring), isTrue);
    expect(seen[ProcessingStatus.ready], 'completed');
    // Every intermediate stage came from the server, not a local guess.
    expect(
      seen[ProcessingStatus.structuring],
      anyOf('extract', 'save'),
    );
  });

  test('server error classes get actionable, honest messages', () async {
    backend.terminalErrorClass = 'invalid_input';
    backend.terminalErrorMessage = 'audio was not English';

    final note = await provider.createAudioNote(
      audioPath: writeAudio('invalid.m4a'),
      durationMs: 900,
    );

    await waitFor(() => noteFor(note.id).status == ProcessingStatus.failed);

    final failed = noteFor(note.id);
    expect(failed.errorClass, 'invalid_input');
    expect(failed.failureReason, contains('No knowledge was created'));
    expect(failed.failureReason, isNot(contains('audio was not English')));
    // The raw provider message never leaks to the user.
    expect(failed.failureReason, isNot(contains('provider')));
  });

  test('reconciliation picks up server recordings on app open (NET-02)',
      () async {
    backend.recordings.add(
      RecordingModel(
        captureId: 'server-ready',
        createdAt: '2026-02-01T10:00:00Z',
        durationMs: 4200,
        status: 'ready',
        stage: 'completed',
        hasAudio: true,
        knowledgeItemId: 'k-server-ready',
        errorMessage: null,
        errorClass: '',
        retryable: false,
      ),
    );
    backend.recordings.add(
      RecordingModel(
        captureId: 'server-failed',
        createdAt: '2026-02-01T11:00:00Z',
        durationMs: 1800,
        status: 'failed',
        stage: 'transcribe',
        hasAudio: true,
        knowledgeItemId: null,
        errorMessage: 'speech provider returned 500',
        errorClass: 'provider_failure',
        retryable: true,
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
    expect(ready.audioOnServer, isTrue);
    expect(ready.knowledgeItemId, 'k-server-ready');
    expect(ready.hasLocalAudio, isFalse);
    expect(ready.createdAt.toUtc().year, 2026);

    final failed = noteFor('server-failed');
    expect(failed.status, ProcessingStatus.failed);
    expect(failed.errorClass, 'provider_failure');
    expect(failed.stage, 'transcribe');
    expect(failed.failureReason, contains('kept'));

    // Reopening the app never creates work; it only reads.
    expect(backend.uploadCalls, 0);
  });

  test('reconciliation removes local audio the server already has (REC-06)',
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
        stage: 'transcribe',
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
      ),
    );
    await provider.loadNotes();

    backend.recordings.add(
      RecordingModel(
        captureId: 'local-capture',
        createdAt: DateTime.now().toIso8601String(),
        durationMs: 1000,
        status: 'ready',
        stage: 'completed',
        hasAudio: true,
        knowledgeItemId: 'k-local',
        errorMessage: null,
        errorClass: '',
        retryable: false,
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
    expect(File(path).existsSync(), isFalse);
    expect(note.audioPath, isNull);
    expect(note.status, ProcessingStatus.ready);
    expect(note.title, 'Local capture');
  });
}
