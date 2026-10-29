import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

/// Single source of truth for captures and Ask AI conversations.
///
/// Audio uploads are strictly serialized (REC-04): only one upload request is
/// sent at a time, but the mic is never gated by in-flight uploads or
/// processing — a new recording can start while the previous one is still on
/// the server (owner decision, 2026-10-29). The local audio file is deleted as
/// soon as the backend answers 202, because that response only returns after
/// the server has written the file and committed the database row; retry then
/// works from the server-side copy (REC-06).
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

  final List<String> _uploadQueue = [];
  final Set<String> _processing = {};
  final Set<String> _uploadingIds = {};
  final Map<String, Completer<void>> _uploadCompleters = {};
  bool _draining = false;

  List<ConversationSummaryModel> _conversations = [];
  String? _activeConversationId;
  List<AskMessageModel> _messages = [];
  bool _isAsking = false;
  String? _askError;

  static const int maxRetryAttempts = 3;
  static const Duration retryBaseDelay = Duration(seconds: 2);

  /// Poll cadence for asynchronous processing status. Mutable so tests can run
  /// the pipeline without real waiting.
  static Duration statusPollInterval = const Duration(milliseconds: 600);
  static const int maxStatusPolls = 500;

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
  bool get isUploadInFlight => _uploadingIds.isNotEmpty;

  List<ConversationSummaryModel> get conversations => _conversations;
  String? get activeConversationId => _activeConversationId;
  List<AskMessageModel> get messages => _messages;
  bool get isAsking => _isAsking;
  String? get askError => _askError;

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

  /// Create an audio note with a persistent queue and serialized server sync.
  /// Text-only capture is removed per PRD v2 (text capture is backlogged).
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
      status: ProcessingStatus.queued,
      stage: 'upload',
      createdAt: now,
      updatedAt: now,
    );

    await _repository.insertNote(note);
    await loadNotes();

    // Queue without awaiting: the capture screen returns immediately and the
    // processor works through the queue one upload at a time.
    unawaited(syncCaptureToBackend(note.id));

    return note;
  }

  /// Queues a capture for upload and processing.
  ///
  /// Concurrent calls for the same capture join the same future, so retries can
  /// never produce two uploads for one record.
  Future<void> syncCaptureToBackend(String noteId) {
    final completer = _uploadCompleters.putIfAbsent(
      noteId,
      () => Completer<void>(),
    );
    if (_processing.contains(noteId) || _uploadQueue.contains(noteId)) {
      return completer.future;
    }
    _uploadQueue.add(noteId);
    _drainQueue();
    return completer.future;
  }

  Future<void> _drainQueue() async {
    if (_draining) return;
    _draining = true;
    try {
      while (_uploadQueue.isNotEmpty) {
        final noteId = _uploadQueue.removeAt(0);
        if (_processing.contains(noteId)) continue;
        _processing.add(noteId);
        try {
          await _processNote(noteId);
        } catch (e) {
          debugPrint('Processing error on note $noteId: $e');
        } finally {
          _processing.remove(noteId);
          _uploadingIds.remove(noteId);
          notifyListeners();
          final completer = _uploadCompleters.remove(noteId);
          if (completer != null && !completer.isCompleted) {
            completer.complete();
          }
        }
        await loadNotes();
      }
    } finally {
      _draining = false;
    }
  }

  Future<void> _processNote(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null) return;
    if (!note.hasLocalAudio && !note.audioOnServer) return;

    try {
      if (note.hasLocalAudio) {
        final isOnline = await _backendService.checkHealth();
        if (!isOnline) {
          throw BackendException(
            'Backend server is unreachable. Check the server URL in Settings.',
          );
        }

        await _save(
          note.copyWith(
            status: ProcessingStatus.uploading,
            stage: 'upload',
            failureReason: null,
            errorClass: null,
            updatedAt: DateTime.now(),
          ),
        );

        _uploadingIds.add(noteId);
        notifyListeners();
        try {
          await _backendService.uploadCapture(
            captureId: note.id,
            idempotencyKey: note.id,
            audioPath: note.audioPath!,
            durationMs: note.audioDurationMs ?? 0,
          );
        } finally {
          _uploadingIds.remove(noteId);
          notifyListeners();
        }

        final uploaded = await _repository.getNoteById(noteId) ?? note;
        // REC-04/REC-06 (owner decision 2026-10-29): a successful upload means
        // the server confirmed receipt and durable storage, so the local copy
        // is redundant and is deleted right away. Retries use the server-side
        // audio via /recordings/{id}/retry.
        final removed = await _deleteLocalAudio(uploaded.audioPath);
        await _save(
          uploaded.copyWith(
            status: ProcessingStatus.pending,
            stage: 'upload',
            audioPath: removed ? null : uploaded.audioPath,
            // The server has the bytes now, so retry can work without the
            // local file even before extraction completes.
            audioOnServer: true,
            failureReason: null,
            errorClass: null,
            updatedAt: DateTime.now(),
          ),
        );
      } else {
        await _save(
          note.copyWith(
            status: ProcessingStatus.pending,
            stage: note.stage.isEmpty ? 'upload' : note.stage,
            failureReason: null,
            errorClass: null,
            updatedAt: DateTime.now(),
          ),
        );
      }

      await _pollUntilTerminal(noteId);
    } catch (e) {
      final current = await _repository.getNoteById(noteId);
      if (current == null) return;
      final errorClass = _errorClassFor(e);
      await _save(
        current.copyWith(
          status: ProcessingStatus.failed,
          errorClass: errorClass,
          failureReason: _friendlyError(e, errorClass),
          retryCount: current.retryCount + 1,
          updatedAt: DateTime.now(),
        ),
      );
    }
  }

  Future<void> _pollUntilTerminal(String noteId) async {
    for (var poll = 0; poll < maxStatusPolls; poll++) {
      final status = await _backendService.fetchRecordingStatus(noteId);
      final current = await _repository.getNoteById(noteId);
      if (current == null) return;

      if (status.status == 'ready') {
        final knowledge = await _backendService.fetchKnowledgeForCapture(
          noteId,
        );
        await _markReady(current, knowledge);
        return;
      }

      if (status.status == 'failed') {
        await _markFailed(
          current,
          status.errorClass,
          status.errorMessage,
          status.attempt,
          status.stage,
        );
        return;
      }

      await _save(
        current.copyWith(
          status: _mapStage(status.stage),
          stage: status.stage,
          retryCount: status.attempt,
          audioOnServer: true,
          failureReason: null,
          errorClass: null,
          updatedAt: DateTime.now(),
        ),
      );
      await Future<void>.delayed(statusPollInterval);
    }

    final current = await _repository.getNoteById(noteId);
    if (current != null) {
      await _markFailed(
        current,
        'provider_failure',
        'Processing did not finish in time.',
        current.retryCount,
        current.stage,
      );
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
    // REC-06: post-upload deletion is the primary path; this only catches the
    // rare case where deletion failed during upload or the state was rebuilt
    // through reconciliation.
    if (note.hasLocalAudio) {
      await _deleteLocalAudio(note.audioPath);
    }

    await _save(
      note.copyWith(
        audioPath: null,
        audioOnServer: true,
        title: (knowledge != null && knowledge.title.isNotEmpty)
            ? knowledge.title
            : note.title,
        summary: knowledge?.coreIdea ?? note.summary,
        keyFacts: knowledge?.concepts ?? note.keyFacts,
        tags: knowledge?.tags ?? note.tags,
        openQuestions: knowledge?.openQuestions ?? note.openQuestions,
        knowledgeItemId: knowledge?.knowledgeItemId ?? note.knowledgeItemId,
        status: ProcessingStatus.ready,
        stage: 'completed',
        failureReason: null,
        errorClass: null,
        retryCount: 0,
        updatedAt: DateTime.now(),
      ),
    );
  }

  Future<void> _markFailed(
    Note note,
    String errorClass,
    String? rawMessage,
    int attempt,
    String stage,
  ) async {
    await _save(
      note.copyWith(
        status: ProcessingStatus.failed,
        stage: stage,
        errorClass: errorClass,
        failureReason: _friendlyErrorClass(errorClass, rawMessage),
        retryCount: attempt,
        updatedAt: DateTime.now(),
      ),
    );
  }

  ProcessingStatus _mapStage(String stage) {
    switch (stage) {
      case 'upload':
        return ProcessingStatus.uploading;
      case 'transcribe':
        return ProcessingStatus.transcribing;
      case 'extract':
      case 'save':
        return ProcessingStatus.structuring;
      case 'completed':
        return ProcessingStatus.ready;
      default:
        return ProcessingStatus.pending;
    }
  }

  ProcessingStatus _mapServerStatus(String status, String stage) {
    if (status == 'ready') return ProcessingStatus.ready;
    if (status == 'failed') return ProcessingStatus.failed;
    return _mapStage(stage);
  }

  String _errorClassFor(Object error) {
    if (error is BackendException) {
      if (error.statusCode == 401 || error.statusCode == 403) return 'auth';
      if (error.statusCode == 422) return 'invalid_input';
      if (error.statusCode == 429) return 'quota_exhausted';
      if (error.statusCode != null && error.statusCode! >= 500) {
        return 'provider_failure';
      }
    }
    final text = error.toString().toLowerCase();
    if (text.contains('socket') ||
        text.contains('timeout') ||
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
      default:
        final text = (rawMessage ?? '').trim();
        if (text.isEmpty) {
          return 'Processing failed. Your recording is kept for retry.';
        }
        return text.length > 180 ? '${text.substring(0, 180)}…' : text;
    }
  }

  /// Rebuilds local processing state from the backend on app open (NET-02).
  /// Reopening the app never creates a job; it only reads and reconciles.
  Future<void> reconcileWithBackend() async {
    List<RecordingModel> recordings;
    try {
      recordings = await _backendService.fetchRecordings();
    } catch (e) {
      debugPrint('Could not reconcile recordings: $e');
      return;
    }

    final existing = {for (final note in await _repository.getAllNotes()) note.id: note};

    for (final recording in recordings) {
      final local = existing[recording.captureId];
      if (local == null) {
        KnowledgeSnapshot? knowledge;
        if (recording.status == 'ready') {
          knowledge = await _backendService.fetchKnowledgeForCapture(
            recording.captureId,
          );
        }
        final createdAt =
            DateTime.tryParse(recording.createdAt) ?? DateTime.now();
        final note = Note(
          id: recording.captureId,
          audioPath: null,
          audioDurationMs: recording.durationMs,
          originalContent: '[Voice recording]',
          title: (knowledge != null && knowledge.title.isNotEmpty)
              ? knowledge.title
              : 'Voice recording',
          summary: knowledge?.coreIdea,
          keyFacts: knowledge?.concepts ?? const [],
          openQuestions: knowledge?.openQuestions ?? const [],
          tags: knowledge?.tags ?? const [],
          status: _mapServerStatus(recording.status, recording.stage),
          stage: recording.stage,
          audioOnServer: recording.hasAudio,
          knowledgeItemId:
              recording.knowledgeItemId ?? knowledge?.knowledgeItemId,
          failureReason: recording.status == 'failed'
              ? _friendlyErrorClass(
                  recording.errorClass,
                  recording.errorMessage,
                )
              : null,
          errorClass: recording.errorClass,
          createdAt: createdAt,
          updatedAt: DateTime.now(),
        );
        await _repository.insertNote(note);
        continue;
      }

      if (_processing.contains(local.id) || _uploadQueue.contains(local.id)) {
        continue;
      }

      KnowledgeSnapshot? knowledge;
      if (recording.status == 'ready' && local.knowledgeItemId == null) {
        knowledge = await _backendService.fetchKnowledgeForCapture(
          recording.captureId,
        );
      }

      var updated = local.copyWith(
        status: _mapServerStatus(recording.status, recording.stage),
        stage: recording.stage,
        audioOnServer: local.audioOnServer || recording.hasAudio,
        errorClass: recording.errorClass,
        knowledgeItemId: local.knowledgeItemId ?? knowledge?.knowledgeItemId,
        failureReason: recording.status == 'failed'
            ? _friendlyErrorClass(recording.errorClass, recording.errorMessage)
            : null,
        retryCount: recording.status == 'failed'
            ? local.retryCount
            : local.retryCount,
        title: (knowledge != null && knowledge.title.isNotEmpty)
            ? knowledge.title
            : local.title,
        summary: knowledge?.coreIdea ?? local.summary,
        keyFacts: knowledge?.concepts ?? local.keyFacts,
        openQuestions: knowledge?.openQuestions ?? local.openQuestions,
        tags: knowledge?.tags ?? local.tags,
        updatedAt: DateTime.now(),
      );

      // A server-confirmed ready recording means the local file is redundant.
      if (recording.status == 'ready' && updated.hasLocalAudio) {
        try {
          final file = File(updated.audioPath!);
          if (await file.exists()) await file.delete();
        } catch (e) {
          debugPrint('Could not delete reconciled local audio: $e');
        }
        updated = updated.copyWith(audioPath: null);
      }

      await _repository.updateNote(updated);
    }

    await loadNotes();
  }

  /// Resumes eligible local captures after app start without duplicating work.
  Future<void> retryPendingWork() async {
    if (_resumeStarted) return;
    _resumeStarted = true;

    await reconcileWithBackend();

    final candidates = _notes.where((note) {
      if (!note.hasLocalAudio) return false;
      if (note.retryCount >= maxRetryAttempts) return false;
      return note.status == ProcessingStatus.queued ||
          note.status == ProcessingStatus.uploading ||
          note.status == ProcessingStatus.pending ||
          note.status == ProcessingStatus.transcribing ||
          note.status == ProcessingStatus.structuring ||
          note.status == ProcessingStatus.failed;
    }).toList();

    for (final note in candidates) {
      unawaited(syncCaptureToBackend(note.id));
    }
  }

  /// User-triggered retry. Resets the attempt budget for an explicit action.
  Future<void> retryNote(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null) return;

    final reset = note.copyWith(
      retryCount: 0,
      failureReason: null,
      errorClass: null,
      status: ProcessingStatus.queued,
      updatedAt: DateTime.now(),
    );
    await _repository.updateNote(reset);
    await loadNotes();

    if (reset.hasLocalAudio) {
      await syncCaptureToBackend(noteId);
      return;
    }

    if (reset.audioOnServer) {
      try {
        await _backendService.retryRecording(noteId);
      } catch (e) {
        await _save(
          reset.copyWith(
            status: ProcessingStatus.failed,
            failureReason: _friendlyError(e, _errorClassFor(e)),
            errorClass: _errorClassFor(e),
            updatedAt: DateTime.now(),
          ),
        );
        rethrow;
      }
      await syncCaptureToBackend(noteId);
      return;
    }

    throw Exception('This recording has no audio available for retry.');
  }

  String _friendlyErrorText(Object error) {
    final text = error.toString().replaceFirst('Exception: ', '');
    return text.length > 180 ? '${text.substring(0, 180)}…' : text;
  }

  /// Updates an existing note in the local repository and refreshes the list.
  Future<void> updateNote(Note note) async {
    final updated = note.copyWith(updatedAt: DateTime.now());
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
    await _repository.deleteNote(id);
    await loadNotes();
  }

  Future<void> _save(Note note) async {
    await _repository.updateNote(note);
    await loadNotes();
  }

  // ------------------------------------------------------------------ Ask AI
  Future<void> loadConversations() async {
    try {
      _conversations = await _backendService.fetchConversations();
      notifyListeners();
    } catch (e) {
      _askError = _friendlyErrorText(e);
      notifyListeners();
    }
  }

  Future<void> openConversation(String conversationId) async {
    _askError = null;
    try {
      final conversation = await _backendService.fetchConversation(
        conversationId,
      );
      _activeConversationId = conversation.id;
      _messages = conversation.messages;
    } catch (e) {
      _askError = _friendlyErrorText(e);
    }
    notifyListeners();
  }

  void startNewConversation() {
    _activeConversationId = null;
    _messages = [];
    _askError = null;
    notifyListeners();
  }

  Future<void> askQuestion(String question) async {
    final trimmed = question.trim();
    if (trimmed.isEmpty || _isAsking) return;

    _isAsking = true;
    _askError = null;
    final optimistic = AskMessageModel(
      id: 'local-${DateTime.now().microsecondsSinceEpoch}',
      role: 'user',
      content: trimmed,
      status: 'ready',
      errorClass: '',
      errorMessage: '',
      createdAt: DateTime.now().toIso8601String(),
      citations: const [],
    );
    _messages = [..._messages, optimistic];
    notifyListeners();

    try {
      final result = await _backendService.ask(
        trimmed,
        conversationId: _activeConversationId,
      );
      _activeConversationId = result.conversationId;
      _messages = [..._messages, result.message];
      await loadConversations();
    } catch (e) {
      _askError = _friendlyErrorText(e);
    } finally {
      _isAsking = false;
      notifyListeners();
    }
  }

  Future<void> deleteConversation(String conversationId) async {
    try {
      await _backendService.deleteConversation(conversationId);
      if (_activeConversationId == conversationId) {
        startNewConversation();
      }
      await loadConversations();
    } catch (e) {
      _askError = _friendlyErrorText(e);
      notifyListeners();
    }
  }

  void clearAskError() {
    _askError = null;
    notifyListeners();
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
