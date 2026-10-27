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
    } catch (e) {
      debugPrint('Background sync to server skipped or failed: $e');
    }
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

  /// Processes an audio capture via backend pipeline
  Future<void> syncCaptureToBackend(String noteId) async {
    final note = await _repository.getNoteById(noteId);
    if (note == null || note.audioPath == null) return;

    try {
      // Check backend health
      final isOnline = await _backendService.checkHealth();
      if (!isOnline) {
        throw Exception('Backend server is unreachable');
      }

      await _repository.updateNote(
        note.copyWith(
          status: ProcessingStatus.uploading,
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

      final updated = note.copyWith(
        title: result.title.isNotEmpty ? result.title : note.title,
        summary: result.coreIdea,
        transcript: result.transcript,
        keyFacts: result.concepts,
        openQuestions: result.openQuestions,
        tags: result.tags,
        status: ProcessingStatus.ready,
        failureReason: null,
        updatedAt: DateTime.now(),
      );

      await _repository.updateNote(updated);
    } catch (e) {
      debugPrint('Processing error on note $noteId: $e');
      final current = await _repository.getNoteById(noteId);
      if (current != null) {
        // Fall back to direct client AI if configured, otherwise mark failed
        if (_aiService.isConfigured) {
          await processNoteAI(noteId);
        } else {
          await _repository.updateNote(
            current.copyWith(
              status: ProcessingStatus.failed,
              failureReason: e.toString(),
              updatedAt: DateTime.now(),
            ),
          );
        }
      }
    } finally {
      await loadNotes();
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

      final updated = note.copyWith(
        transcript: transcript,
        title: structured.title.isNotEmpty ? structured.title : note.title,
        summary: structured.summary,
        keyFacts: structured.keyFacts,
        openQuestions: structured.openQuestions,
        tags: structured.tags,
        status: ProcessingStatus.ready,
        failureReason: null,
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
            failureReason: e.toString(),
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
    _syncNoteToBackend(updated);
    await loadNotes();
  }

  Future<void> deleteNote(String id) async {
    await _repository.deleteNote(id);
    try {
      await _backendService.client.delete(
        Uri.parse('${_backendService.baseUrl}/api/knowledge/$id'),
      );
    } catch (_) {}
    await loadNotes();
  }

  Future<void> search(String query) async {
    _searchQuery = query;
    if (query.trim().isEmpty) {
      _searchResults = [];
      notifyListeners();
      return;
    }

    _isLoading = true;
    notifyListeners();

    try {
      // 1. Attempt Embedding-based Semantic Recall from Backend
      final semanticMatches = await _backendService.searchSemantic(query);
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
      _searchResults = await _repository.searchNotes(query);
    } catch (e) {
      debugPrint('Semantic search error, falling back to keyword: $e');
      _searchResults = await _repository.searchNotes(query);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
