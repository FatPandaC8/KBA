import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/ai_service.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

class NoteProvider extends ChangeNotifier {
  final NoteRepository _repository;
  final AIService _aiService;
  final BackendService _backendService;
  final SettingsService? _settingsService;

  List<Note> _notes = [];
  bool _isLoading = false;
  String _searchQuery = '';
  List<Note> _searchResults = [];
  int _searchRequestId = 0;
  final Set<String> _syncInFlight = {};
  bool _resumeStarted = false;

  static const int maxRetryAttempts = 3;
  static const Duration retryBaseDelay = Duration(seconds: 2);

  NoteProvider(
    this._repository,
    this._aiService,
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

  /// Create a direct text note
  Future<Note> createTextNote(String text) async {
    final now = DateTime.now();
    final firstLine = text.trim().split('\n').first;
    final initialTitle = firstLine.length > 40
        ? '${firstLine.substring(0, 37)}...'
        : (firstLine.isEmpty ? 'Untitled Note' : firstLine);

    final note = Note(
      id: const Uuid().v4(),
      originalContent: text,
      title: initialTitle,
      status: _aiService.isConfigured
          ? ProcessingStatus.pending
          : ProcessingStatus.rawOnly,
      createdAt: now,
      updatedAt: now,
    );

    await _repository.insertNote(note);
    await loadNotes();

    // Sync to backend so graph and server knowledge remain identical
    _syncNoteToBackend(note);

    if (_aiService.isConfigured) {
      processNoteAI(note.id);
    }

    return note;
  }

  Future<void> _syncNoteToBackend(Note note) async {
    try {
      await _backendService.syncKnowledgeItem(
        id: note.id,
        captureId: note.id,
        title: note.title,
        coreIdea: note.summary ?? note.originalContent,
        details: note.originalContent,
        transcript: note.transcript ?? note.originalContent,
        concepts: note.keyFacts,
        tags: note.tags,
        openQuestions: note.openQuestions,
      );
      final current = await _repository.getNoteById(note.id);
      if (current != null && current.failureReason != null) {
        await _repository.updateNote(
          current.copyWith(failureReason: null, updatedAt: DateTime.now()),
        );
        await loadNotes();
      }
    } catch (e) {
      final current = await _repository.getNoteById(note.id);
      if (current != null) {
        await _repository.updateNote(
          current.copyWith(
            failureReason: 'Server sync failed: ${_friendlyError(e)}',
            updatedAt: DateTime.now(),
          ),
        );
        await loadNotes();
      }
    }
  }

  String _friendlyError(Object error) {
    final text = error.toString().replaceFirst('Exception: ', '');
    return text.length > 180 ? '${text.substring(0, 180)}…' : text;
  }

  /// Create an audio note with persistent queue and automatic server sync
  Future<Note> createAudioNote({
    required String audioPath,
    required int durationMs,
  }) async {
    final now = DateTime.now();
    final noteId = const Uuid().v4();

    // 1. Persist locally first as 'queued'
    final note = Note(
      id: noteId,
      audioPath: audioPath,
      audioDurationMs: durationMs,
      originalContent: '[Short Voice Capture]',
      title: 'Voice Thought',
      status: ProcessingStatus.queued,
      createdAt: now,
      updatedAt: now,
    );

    await _repository.insertNote(note);
    await loadNotes();

    // 2. Trigger asynchronous sync/pipeline
    syncCaptureToBackend(note.id);

    return note;
  }

  /// Processes an audio capture via backend pipeline.
  ///
  /// Retries are guarded so a note is never processed twice concurrently.
  Future<void> syncCaptureToBackend(String noteId) async {
    if (_syncInFlight.contains(noteId)) return;
    _syncInFlight.add(noteId);
    try {
      final note = await _repository.getNoteById(noteId);
      if (note == null || note.audioPath == null || note.audioPath!.isEmpty) {
        return;
      }

      try {
        final isOnline = await _backendService.checkHealth();
        if (!isOnline) {
          throw BackendException(
            'Backend server is unreachable. Check the server URL in Settings.',
          );
        }

        await _repository.updateNote(
          note.copyWith(
            status: ProcessingStatus.uploading,
            failureReason: null,
            updatedAt: DateTime.now(),
          ),
        );
        await loadNotes();

        final consentGiven = _settingsService?.evalConsent ?? false;

        final result = await _backendService.uploadCapture(
          captureId: note.id,
          idempotencyKey: note.id,
          audioPath: note.audioPath!,
          durationMs: note.audioDurationMs ?? 0,
          consentGiven: consentGiven,
        );

        final current = await _repository.getNoteById(noteId) ?? note;
        final updated = current.copyWith(
          title: result.title.isNotEmpty ? result.title : current.title,
          summary: result.coreIdea,
          transcript: result.transcript,
          keyFacts: result.concepts,
          openQuestions: result.openQuestions,
          tags: result.tags,
          status: ProcessingStatus.ready,
          failureReason: null,
          retryCount: 0,
          updatedAt: DateTime.now(),
        );

        await _repository.updateNote(updated);
      } catch (e) {
        debugPrint('Processing error on note $noteId: $e');
        final current = await _repository.getNoteById(noteId);
        if (current != null) {
          if (_aiService.isConfigured && current.retryCount == 0) {
            await processNoteAI(noteId);
          } else {
            await _repository.updateNote(
              current.copyWith(
                status: ProcessingStatus.failed,
                failureReason: _friendlyError(e),
                retryCount: current.retryCount + 1,
                updatedAt: DateTime.now(),
              ),
            );
          }
        }
      }
    } finally {
      _syncInFlight.remove(noteId);
      await loadNotes();
    }
  }

  /// Resumes eligible captures after app start without duplicating work.
  Future<void> retryPendingWork() async {
    if (_resumeStarted) return;
    _resumeStarted = true;
    final candidates = _notes.where((note) {
      if (note.audioPath == null || note.audioPath!.isEmpty) return false;
      if (note.retryCount >= maxRetryAttempts) return false;
      return note.status == ProcessingStatus.queued ||
          note.status == ProcessingStatus.uploading ||
          note.status == ProcessingStatus.failed;
    }).toList();

    for (var i = 0; i < candidates.length; i++) {
      final note = candidates[i];
      if (i > 0) {
        await Future<void>.delayed(retryBaseDelay);
      }
      syncCaptureToBackend(note.id);
    }
  }

  /// User-triggered retry. Resets the attempt budget for an explicit action.
  Future<void> retryNote(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null) return;
    final reset = note.copyWith(
      retryCount: 0,
      failureReason: null,
      status: note.audioPath == null || note.audioPath!.isEmpty
          ? note.status
          : ProcessingStatus.queued,
      updatedAt: DateTime.now(),
    );
    await _repository.updateNote(reset);
    await loadNotes();
    if (reset.audioPath != null && reset.audioPath!.isNotEmpty) {
      await syncCaptureToBackend(noteId);
    } else if (_aiService.isConfigured) {
      await processNoteAI(noteId);
    } else {
      await _syncNoteToBackend(reset);
    }
  }

  /// Direct client AI processing fallback
  Future<void> processNoteAI(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null) return;

    try {
      String contentToStructure = note.originalContent;
      String? transcript = note.transcript;

      if (note.audioPath != null && note.audioPath!.isNotEmpty) {
        await _repository.updateNote(
          note.copyWith(
            status: ProcessingStatus.transcribing,
            updatedAt: DateTime.now(),
          ),
        );
        await loadNotes();

        transcript = await _aiService.transcribeAudio(note.audioPath!);
        contentToStructure = transcript;
      }

      await _repository.updateNote(
        note.copyWith(
          transcript: transcript,
          status: ProcessingStatus.structuring,
          updatedAt: DateTime.now(),
        ),
      );
      await loadNotes();

      final structured = await _aiService.structureKnowledge(
        contentToStructure,
      );

      final current = await _repository.getNoteById(noteId) ?? note;
      final updated = current.copyWith(
        transcript: transcript,
        title: structured.title.isNotEmpty ? structured.title : current.title,
        summary: structured.summary,
        keyFacts: structured.keyFacts,
        openQuestions: structured.openQuestions,
        tags: structured.tags,
        status: ProcessingStatus.ready,
        failureReason: null,
        retryCount: 0,
        updatedAt: DateTime.now(),
      );

      await _repository.updateNote(updated);
    } catch (e) {
      debugPrint('AI Processing error on note $noteId: $e');
      final current = await _repository.getNoteById(noteId);
      if (current != null) {
        await _repository.updateNote(
          current.copyWith(
            status: ProcessingStatus.failed,
            failureReason: _friendlyError(e),
            retryCount: current.retryCount + 1,
            updatedAt: DateTime.now(),
          ),
        );
      }
    } finally {
      await loadNotes();
    }
  }

  Future<void> updateNote(Note note) async {
    final updated = note.copyWith(updatedAt: DateTime.now());
    await _repository.updateNote(updated);
    await loadNotes();
    await _syncNoteToBackend(updated);
  }

  /// Deletes locally only after the server confirmed the full capture cleanup.
  /// A server failure keeps the note so the user can retry rather than being
  /// told deletion succeeded when retained data still exists.
  Future<void> deleteNote(String id) async {
    try {
      await _backendService.deleteCapture(id);
    } catch (e) {
      throw Exception('Could not delete from server: ${_friendlyError(e)}');
    }
    await _repository.deleteNote(id);
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
