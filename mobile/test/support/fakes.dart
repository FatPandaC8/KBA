import 'dart:async';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/backend_service.dart';

/// In-memory repository used by widget and provider regression tests.
class FakeNoteRepository extends NoteRepository {
  final List<Note> inMemory = [];

  @override
  Future<List<Note>> getAllNotes() async => List.unmodifiable(inMemory);

  @override
  Future<void> insertNote(Note note) async {
    inMemory.removeWhere((n) => n.id == note.id);
    inMemory.add(note);
  }

  @override
  Future<Note?> getNoteById(String id) async {
    for (final note in inMemory) {
      if (note.id == id) return note;
    }
    return null;
  }

  @override
  Future<void> updateNote(Note note) async {
    final index = inMemory.indexWhere((n) => n.id == note.id);
    if (index == -1) {
      inMemory.add(note);
    } else {
      inMemory[index] = note;
    }
  }

  @override
  Future<void> deleteNote(String id) async {
    inMemory.removeWhere((n) => n.id == id);
  }

  @override
  Future<List<Note>> searchNotes(String query) async {
    final q = query.toLowerCase();
    return inMemory.where((n) {
      return n.title.toLowerCase().contains(q) ||
          n.originalContent.toLowerCase().contains(q) ||
          (n.summary?.toLowerCase().contains(q) ?? false);
    }).toList();
  }
}

/// Controllable backend double. No real network calls are made.
class FakeBackendService extends BackendService {
  FakeBackendService(super.settings);

  bool healthy = true;
  bool failUpload = false;
  bool failSync = false;
  bool failDelete = false;
  bool failGraph = false;

  int uploadCalls = 0;
  int syncCalls = 0;
  int deleteCalls = 0;
  int healthCalls = 0;

  /// When set, uploads wait until the completer is completed.
  Completer<void>? uploadGate;

  BackendSyncResult uploadResult = BackendSyncResult(
    captureId: 'capture',
    status: 'ready',
    title: 'Processed title',
    coreIdea: 'Processed summary',
    transcript: 'Processed transcript',
    concepts: const ['concept'],
    tags: const ['tag'],
    openQuestions: const ['question'],
  );

  @override
  Future<bool> checkHealth() async {
    healthCalls++;
    return healthy;
  }

  @override
  Future<BackendSyncResult> uploadCapture({
    required String captureId,
    required String idempotencyKey,
    required String audioPath,
    required int durationMs,
    bool consentGiven = false,
  }) async {
    uploadCalls++;
    if (uploadGate != null) {
      await uploadGate!.future;
    }
    if (failUpload) {
      throw BackendException('upload failed', statusCode: 500);
    }
    return BackendSyncResult(
      captureId: captureId,
      status: uploadResult.status,
      title: uploadResult.title,
      coreIdea: uploadResult.coreIdea,
      transcript: uploadResult.transcript,
      concepts: uploadResult.concepts,
      tags: uploadResult.tags,
      openQuestions: uploadResult.openQuestions,
    );
  }

  @override
  Future<void> syncKnowledgeItem({
    required String id,
    required String captureId,
    required String title,
    required String coreIdea,
    String details = '',
    String transcript = '',
    List<String> concepts = const [],
    List<String> tags = const [],
    List<String> openQuestions = const [],
  }) async {
    syncCalls++;
    if (failSync) {
      throw BackendException('sync failed', statusCode: 500);
    }
  }

  @override
  Future<void> deleteCapture(String captureId) async {
    deleteCalls++;
    if (failDelete) {
      throw BackendException('delete failed', statusCode: 500);
    }
  }

  @override
  Future<List<({String id, double score})>> searchSemantic(
    String query, {
    int limit = 20,
  }) async => const [];

  @override
  Future<({List<GraphNodeModel> nodes, List<GraphEdgeModel> edges})>
  fetchGraph() async {
    if (failGraph) {
      throw BackendException('graph failed', statusCode: 500);
    }
    return (nodes: <GraphNodeModel>[], edges: <GraphEdgeModel>[]);
  }

  @override
  Future<List<GraphEdgeModel>> fetchAllRelationships() async {
    if (failGraph) {
      throw BackendException('relationships failed', statusCode: 500);
    }
    return const [];
  }
}
