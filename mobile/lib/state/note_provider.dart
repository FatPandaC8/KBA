import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

/// Single source of truth for captures and their processing state.
///
/// Pipeline split (S1/S2): the app calls POST /api/stt first (stateless; the
/// server stores nothing), keeps the transcript in memory, then calls
/// POST /api/text-kb with a client-generated capture_id. Every call runs
/// work inside the request; there is no job, no queue and no polling. On any
/// failure the user taps Retry: the SAME capture_id is re-sent for Text-KB
/// (idempotent server-side) and the audio is re-sent to /api/stt only if the
/// transcript was never obtained (or the session restarted).
class NoteProvider extends ChangeNotifier {
  final NoteRepository _repository;
  final BackendService _backendService;
  final SettingsService? _settingsService;

  List<Note> _notes = [];
  bool _isLoading = false;
  String _searchQuery = '';
  List<Note> _searchResults = [];
  int _searchRequestId = 0;
  bool _resumeStarted = false;

  /// Transcripts that survive in memory after a successful STT call, keyed by
  /// note id. A Text-KB retry never re-runs STT while the transcript lives.
  final Map<String, String> _transcripts = {};
  final Set<String> _processing = {};

  NoteProvider(
    this._repository,
    this._backendService, [
    this._settingsService,
  ]) {
    loadNotes();
  }

  List<Note> get notes => _notes;
  bool get isLoading => _isLoading;
  String get searchQuery => _searchQuery;
  List<Note> get searchResults => _searchResults;
  BackendService get backendService => _backendService;
  SettingsService? get settingsService => _settingsService;

  Future<void> loadNotes() async {
    _isLoading = true;
    notifyListeners();

    try {
      _notes = await _repository.getAllNotes();
    } catch (e) {
      debugPrint('Error loading notes: $e');
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Create an audio note and run the synchronous split pipeline for it.
  /// The screen returns immediately; the processing update stream drives the
  /// progress states (transcribing -> structuring -> ready/failed).
  Future<Note> createAudioNote({
    required String audioPath,
    required int durationMs,
  }) async {
    final now = DateTime.now();
    final noteId = const Uuid().v4();

    final note = Note(
      id: noteId,
      audioPath: audioPath,
      audioDurationMs: durationMs,
      originalContent: '[Voice recording]',
      title: 'Voice Thought',
      status: ProcessingStatus.transcribing,
      createdAt: now,
      updatedAt: now,
    );

    await _repository.insertNote(note);
    await loadNotes();

    // Fire-and-forget: the capture screen returns immediately.
    unawaited(_ingestNote(noteId));

    return note;
  }

  /// Runs the two-API pipeline for one note: STT (unless the transcript is
  /// already known) then Text-KB, updating the note between stages.
  Future<void> _ingestNote(String noteId) async {
    if (_processing.contains(noteId)) return;
    _processing.add(noteId);
    try {
      var note = await _repository.getNoteById(noteId);
      if (note == null) return;

      final transcript = _transcripts[noteId] ?? await _transcribe(noteId, note);
      if (transcript == null) return; // failed & marked by _transcribe

      note = await _repository.getNoteById(noteId);
      if (note == null) return;

      await _save(
        note.copyWith(
          status: ProcessingStatus.structuring,
          failureReason: null,
          errorClass: null,
          updatedAt: DateTime.now(),
        ),
      );

      final result = await _backendService.ingestText(
        captureId: noteId, // re-sends the SAME id on retry (idempotent, S4a)
        text: transcript,
      );
      _transcripts[noteId] = transcript;
      debugPrint(
        'text-kb ok capture_id=$noteId entities=${result.entitiesAdded} '
        'relationships=${result.relationshipsAdded} '
        'provider=${result.provider} elapsed_ms=${result.elapsedMs}',
      );

      final knowledge = await _backendService.fetchKnowledgeForCapture(noteId);
      await _markReady(
        (await _repository.getNoteById(noteId)) ?? note,
        knowledge,
      );
    } catch (e) {
      final current = await _repository.getNoteById(noteId);
      if (current == null) return;
      final errorClass = _errorClassFor(e);
      await _save(
        current.copyWith(
          status: ProcessingStatus.failed,
          errorClass: errorClass,
          failureReason: _friendlyError(e, errorClass),
          updatedAt: DateTime.now(),
        ),
      );
    } finally {
      _processing.remove(noteId);
      notifyListeners();
    }
  }

  /// POST /api/stt. Returns the transcript on success, or null after marking
  /// the note failed. The transcript is remembered in memory so a Text-KB
  /// retry never runs STT again.
  Future<String?> _transcribe(String noteId, Note note) async {
    if (note.audioPath == null || note.audioPath!.isEmpty) {
      return null;
    }
    final isOnline = await _backendService.checkHealth();
    if (!isOnline) {
      await _save(
        note.copyWith(
          status: ProcessingStatus.failed,
          errorClass: 'network_error',
          failureReason:
              'Backend server is unreachable. Check the server URL in Settings.',
          updatedAt: DateTime.now(),
        ),
      );
      return null;
    }

    await _save(
      note.copyWith(
        status: ProcessingStatus.transcribing,
        failureReason: null,
        errorClass: null,
        updatedAt: DateTime.now(),
      ),
    );

    try {
      final stt = await _backendService.transcribe(
        audioPath: note.audioPath!,
        durationMs: note.audioDurationMs ?? 0,
      );
      _transcripts[noteId] = stt.transcript;
      debugPrint('stt ok capture_id=$noteId provider=${stt.provider} '
          'language=${stt.language ?? "-"}');
      return stt.transcript;
    } catch (e) {
      final current = await _repository.getNoteById(noteId);
      if (current != null) {
        final errorClass = _errorClassFor(e);
        await _save(
          current.copyWith(
            status: ProcessingStatus.failed,
            errorClass: errorClass,
            failureReason: _friendlyError(e, errorClass),
            updatedAt: DateTime.now(),
          ),
        );
      }
      return null;
    }
  }

  /// Deletes a local audio file best effort. Returns true when the file is
  /// gone (or was never readable); false when deletion failed and the record
  /// must keep pointing at the local copy until retry or reconciliation.
  /// Synchronous FS calls are deliberate: an awaited dart:io future would
  /// never settle inside a widget-test fake-async zone and could stall the
  /// pipeline; a stat/delete is fast enough to run inline.
  Future<bool> _deleteLocalAudio(String? path) async {
    if (path == null || path.isEmpty) return true;
    try {
      final file = File(path);
      if (file.existsSync()) file.deleteSync();
      return true;
    } catch (e) {
      debugPrint('Could not delete local audio for $path: $e');
      return false;
    }
  }

  Future<void> _markReady(Note note, KnowledgeSnapshot? knowledge) async {
    await _save(
      note.copyWith(
        // Local audio stays: the split pipeline stores nothing server-side
        // (S4b), so this device holds the only playable copy (VR-02).
        // Local wins (U3): a user-edited title/summary is never overwritten
        // by server-derived text; unedited fields keep following the server.
        title:
            (!note.userEditedTitle &&
                knowledge != null &&
                knowledge.title.isNotEmpty)
            ? knowledge.title
            : note.title,
        summary: !note.userEditedSummary
            ? (knowledge?.coreIdea ?? note.summary)
            : note.summary,
        keyFacts: knowledge?.concepts ?? note.keyFacts,
        tags: knowledge?.tags ?? note.tags,
        openQuestions: knowledge?.openQuestions ?? note.openQuestions,
        knowledgeItemId: knowledge?.knowledgeItemId ?? note.knowledgeItemId,
        status: ProcessingStatus.ready,
        failureReason: null,
        errorClass: null,
        updatedAt: DateTime.now(),
      ),
    );
  }

  String _errorClassFor(Object error) {
    if (error is BackendException) {
      if (error.errorClass.isNotEmpty) return error.errorClass;
      if (error.statusCode == 401) return 'auth';
      if (error.statusCode == 403) {
        final message = error.message.toLowerCase();
        if (message.contains('consent')) return 'consent_required';
        if (message.contains('verify')) return 'verification_required';
        return 'forbidden';
      }
      if (error.statusCode == 409) return 'conflict';
      if (error.statusCode == 422) return 'invalid_input';
      if (error.statusCode == 413) return 'too_large';
      if (error.statusCode == 429) return 'quota_exhausted';
      if (error.statusCode != null && error.statusCode! >= 500) {
        return 'provider_failure';
      }
    }
    final text = error.toString().toLowerCase();
    if (text.contains('socket') ||
        text.contains('timeout') ||
        text.contains('timed out') ||
        text.contains('network') ||
        text.contains('unreachable') ||
        text.contains('connection')) {
      return 'network_error';
    }
    return 'provider_failure';
  }

  String _friendlyError(Object error, String errorClass) {
    if (errorClass == 'auth') {
      return 'Your session is no longer valid. Sign in again; the recording is kept on this device.';
    }
    if (errorClass == 'consent_required') {
      return 'AI processing is not ready yet. Try recording again in a moment.';
    }
    if (errorClass == 'verification_required') {
      return 'Verify your email before recording. Your capture is kept on this device.';
    }
    if (errorClass == 'forbidden') {
      return 'The server rejected this recording request. Your capture is kept on this device.';
    }
    if (errorClass == 'invalid_input') {
      return 'This recording could not be processed. It may be silent, corrupted, or not in English. No knowledge was created.';
    }
    if (errorClass == 'quota_exhausted') {
      return 'Free processing quota is exhausted. Retry later. No paid provider will be used.';
    }
    if (errorClass == 'network_error') {
      return 'Network problem while uploading. Your recording is kept for retry.';
    }
    return _friendlyErrorClass(errorClass, error.toString());
  }

  String _friendlyErrorClass(String errorClass, String? rawMessage) {
    switch (errorClass) {
      case 'quota_exhausted':
        return 'Free processing quota is exhausted. Retry later. No paid provider will be used.';
      case 'network_error':
        return 'Network error while processing. Your recording is kept for retry.';
      case 'provider_failure':
        return 'A processing component failed. Your recording is kept; retry when the server is available.';
      case 'invalid_input':
        return 'This recording could not be processed. It may be silent, corrupted, or not in English. No knowledge was created.';
      case 'auth':
        return 'Your session is no longer valid. Sign in again; the recording is kept on this device.';
      case 'consent_required':
        return 'AI processing is not ready yet. Try recording again in a moment.';
      case 'verification_required':
        return 'Verify your email before recording. Your capture is kept on this device.';
      case 'forbidden':
        return 'The server rejected this recording request. Your capture is kept on this device.';
      default:
        final text = (rawMessage ?? '').trim();
        if (text.isEmpty) {
          return 'Processing failed. Your recording is kept for retry.';
        }
        return text.length > 180 ? '${text.substring(0, 180)}…' : text;
    }
  }

  /// Rebuilds local processing state from the backend on app open (NET-02).
  /// Reads the capture journal (capture truth only) — never creates work and
  /// never polls; missing knowledge items are fetched once.
  Future<void> reconcileWithBackend() async {
    List<RecordingModel> recordings;
    try {
      recordings = await _backendService.fetchRecordings();
    } catch (e) {
      debugPrint('Could not reconcile recordings: $e');
      return;
    }

    final existing = {
      for (final note in await _repository.getAllNotes()) note.id: note,
    };

    for (final recording in recordings) {
      final local = existing[recording.captureId];
      if (local == null) {
        KnowledgeSnapshot? knowledge;
        if (recording.hasKnowledgeItem) {
          knowledge = await _backendService.fetchKnowledgeForCapture(
            recording.captureId,
          );
        }
        final createdAt =
            DateTime.tryParse(recording.createdAt) ?? DateTime.now();
        final note = Note(
          id: recording.captureId,
          audioPath: null,
          originalContent: '[Voice recording]',
          title: (knowledge != null && knowledge.title.isNotEmpty)
              ? knowledge.title
              : 'Voice recording',
          summary: knowledge?.coreIdea,
          keyFacts: knowledge?.concepts ?? const [],
          openQuestions: knowledge?.openQuestions ?? const [],
          tags: knowledge?.tags ?? const [],
          status: recording.hasKnowledgeItem
              ? ProcessingStatus.ready
              : ProcessingStatus.failed,
          knowledgeItemId: knowledge?.knowledgeItemId,
          failureReason: recording.hasKnowledgeItem
              ? null
              : _friendlyErrorClass('provider_failure', recording.lastError),
          errorClass: recording.hasKnowledgeItem ? '' : 'provider_failure',
          createdAt: createdAt,
          updatedAt: DateTime.now(),
        );
        await _repository.insertNote(note);
        continue;
      }

      if (_processing.contains(local.id)) {
        continue;
      }

      KnowledgeSnapshot? knowledge;
      if (recording.hasKnowledgeItem && local.knowledgeItemId == null) {
        knowledge = await _backendService.fetchKnowledgeForCapture(
          recording.captureId,
        );
      }

      final ready = recording.hasKnowledgeItem;
      final updated = local.copyWith(
        status: ready ? ProcessingStatus.ready : local.status,
        knowledgeItemId: local.knowledgeItemId ?? knowledge?.knowledgeItemId,
        failureReason: ready
            ? null
            : (local.failureReason ??
                _friendlyErrorClass('provider_failure', recording.lastError)),
        errorClass: ready ? '' : (local.errorClass.isEmpty
            ? 'provider_failure'
            : local.errorClass),
        // Local wins (U3): user-edited fields are preserved as-is across
        // reconciliation; unedited fields keep syncing from the server.
        title:
            (!local.userEditedTitle &&
                knowledge != null &&
                knowledge.title.isNotEmpty)
            ? knowledge.title
            : local.title,
        summary: !local.userEditedSummary
            ? (knowledge?.coreIdea ?? local.summary)
            : local.summary,
        keyFacts: knowledge?.concepts ?? local.keyFacts,
        openQuestions: knowledge?.openQuestions ?? local.openQuestions,
        tags: knowledge?.tags ?? local.tags,
        updatedAt: DateTime.now(),
      );

      await _repository.updateNote(updated);
    }

    await loadNotes();
  }

  /// Resumes eligible local captures after app start without duplicating work.
  /// A note whose transcript is still in memory goes straight to Text-KB;
  /// otherwise the audio is re-sent to /api/stt.
  Future<void> retryPendingWork() async {
    if (_resumeStarted) return;
    _resumeStarted = true;

    await reconcileWithBackend();

    final candidates = _notes.where((note) {
      return _transcripts.containsKey(note.id) ||
          (note.status == ProcessingStatus.failed &&
              note.hasLocalAudio) ||
          note.status == ProcessingStatus.transcribing ||
          note.status == ProcessingStatus.structuring;
    }).toList();

    for (final note in candidates) {
      unawaited(_ingestNote(note.id));
    }
  }

  /// User-triggered retry. Re-sends the SAME capture_id for Text-KB
  /// (idempotent, S4a); STT only re-runs when no transcript is held in
  /// memory.
  Future<void> retryNote(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null) return;

    final hasTranscript = _transcripts.containsKey(noteId) ||
        (note.knowledgeItemId != null && note.knowledgeItemId!.isNotEmpty);
    if (!hasTranscript && !note.hasLocalAudio) {
      throw Exception('This recording has no audio available for retry.');
    }

    await _repository.updateNote(
      note.copyWith(
        failureReason: null,
        errorClass: null,
        status: ProcessingStatus.transcribing,
        updatedAt: DateTime.now(),
      ),
    );
    await loadNotes();

    await _ingestNote(noteId);
  }

  String _friendlyErrorText(Object error) {
    final text = error.toString().replaceFirst('Exception: ', '');
    return text.length > 180 ? '${text.substring(0, 180)}…' : text;
  }

  /// Updates an existing note in the local repository and refreshes the list.
  ///
  /// Local wins (U3): any changed title or summary marks that field as
  /// user-edited locally; sync afterwards never overwrites it. Edits are not
  /// written back to the server.
  Future<void> updateNote(Note note) async {
    final existing = await _repository.getNoteById(note.id);
    final titleChanged =
        note.userEditedTitle ||
        (existing != null && note.title != existing.title);
    final summaryChanged =
        note.userEditedSummary ||
        (existing != null && (note.summary ?? '') != (existing.summary ?? ''));
    final updated = note.copyWith(
      updatedAt: DateTime.now(),
      userEditedTitle: titleChanged,
      userEditedSummary: summaryChanged,
    );
    await _repository.updateNote(updated);
    await loadNotes();
  }

  /// Deletes locally only after the server confirmed the full capture cleanup.
  /// A server failure keeps the note so the user can retry rather than being
  /// told deletion succeeded when retained data still exists.
  Future<void> deleteNote(String id) async {
    try {
      await _backendService.deleteCapture(id);
    } catch (e) {
      throw Exception('Could not delete from server: ${_friendlyErrorText(e)}');
    }
    final note = await _repository.getNoteById(id);
    if (note != null) {
      // The local audio is the only copy (S4b); delete it with the record.
      await _deleteLocalAudio(note.audioPath);
    }
    _transcripts.remove(id);
    await _repository.deleteNote(id);
    await loadNotes();
  }

  Future<void> _save(Note note) async {
    await _repository.updateNote(note);
    await loadNotes();
  }

  /// Clears every locally cached note (and its audio) so nothing user-specific
  /// survives in echo_notes.db after logout.
  Future<void> clearLocalNotes() async {
    for (final note in _notes) {
      await _deleteLocalAudio(note.audioPath);
    }
    _transcripts.clear();
    await _repository.clearAllNotes();
    await loadNotes();
  }

  Future<void> search(String query) async {
    _searchQuery = query;
    final requestId = ++_searchRequestId;

    if (query.trim().isEmpty) {
      _searchResults = [];
      _isLoading = false;
      notifyListeners();
      return;
    }

    _isLoading = true;
    notifyListeners();

    try {
      // 1. Attempt Embedding-based Semantic Recall from Backend
      final semanticMatches = await _backendService.searchSemantic(query);
      if (requestId != _searchRequestId) return;
      if (semanticMatches.isNotEmpty) {
        final Map<String, Note> noteMap = {for (final n in _notes) n.id: n};
        final List<Note> ranked = [];
        for (final match in semanticMatches) {
          final note = noteMap[match.id];
          if (note != null) {
            ranked.add(note);
          }
        }
        if (ranked.isNotEmpty) {
          _searchResults = ranked;
          return;
        }
      }

      // 2. Fallback to Local Substring Keyword Search if offline or no semantic match
      final local = await _repository.searchNotes(query);
      if (requestId != _searchRequestId) return;
      _searchResults = local;
    } catch (e) {
      debugPrint('Semantic search error, falling back to keyword: $e');
      final local = await _repository.searchNotes(query);
      if (requestId != _searchRequestId) return;
      _searchResults = local;
    } finally {
      if (requestId == _searchRequestId) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }
}
