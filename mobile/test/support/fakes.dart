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
///
/// It models the M3 asynchronous pipeline: an upload queues a job, status polls
/// walk through [stages] and then report `ready`, unless [terminalErrorClass]
/// makes the job fail with that class.
class FakeBackendService extends BackendService {
  FakeBackendService(super.settings);

  bool healthy = true;
  bool failUpload = false;
  bool failDelete = false;
  bool failGraph = false;
  bool failSearch = false;
  bool failAuth = false;

  int uploadCalls = 0;
  int deleteCalls = 0;
  int healthCalls = 0;
  int loginCalls = 0;
  int signupCalls = 0;
  int consentCalls = 0;
  int logoutCalls = 0;
  int deleteAccountCalls = 0;
  int testConnectionCalls = 0;
  int getConsentCalls = 0;
  int statusCalls = 0;
  int knowledgeCalls = 0;
  int retryCalls = 0;
  int graphCalls = 0;
  int searchCalls = 0;

  /// Capture ids in upload order, used to prove uploads are serialized.
  final List<String> uploadedCaptureIds = [];

  /// When set, uploads wait until the completer is completed.
  Completer<void>? uploadGate;

  /// Stages reported before the job becomes `ready`. Empty means the first
  /// status poll already reports `ready`.
  List<String> stages = const [];

  /// When set, the job fails with this error class.
  String? terminalErrorClass;
  String? terminalErrorMessage;

  final Map<String, int> _polls = {};

  BackendSyncResult uploadResult = BackendSyncResult(
    captureId: 'capture',
    status: 'queued',
    title: '',
    coreIdea: '',
    concepts: const [],
    tags: const [],
    openQuestions: const [],
  );

  /// Knowledge returned once a capture is ready.
  Map<String, KnowledgeSnapshot> knowledgeByCapture = {};

  final List<RecordingModel> recordings = [];

  GraphDataModel graphData = GraphDataModel(
    nodes: const [],
    edges: const [],
    clusters: const [],
  );
  GraphSearchResult searchResult = GraphSearchResult(
    entities: const [],
    relationships: const [],
  );
  final Map<String, EntityDetailModel> entityDetails = {};

  bool consentGranted = false;

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
  }) async {
    uploadCalls++;
    if (uploadGate != null) {
      await uploadGate!.future;
    }
    if (failAuth) {
      throw BackendException(
        'AI provider consent is required before recording.',
        statusCode: 403,
      );
    }
    if (failUpload) {
      throw BackendException('upload failed', statusCode: 500);
    }
    uploadedCaptureIds.add(captureId);
    _polls[captureId] = 0;
    return BackendSyncResult(
      captureId: captureId,
      status: 'queued',
      title: uploadResult.title,
      coreIdea: uploadResult.coreIdea,
      concepts: uploadResult.concepts,
      tags: uploadResult.tags,
      openQuestions: uploadResult.openQuestions,
    );
  }

  @override
  Future<RecordingStatusModel> fetchRecordingStatus(String captureId) async {
    statusCalls++;
    if (terminalErrorClass != null) {
      return RecordingStatusModel(
        captureId: captureId,
        stage: 'transcribe',
        status: 'failed',
        attempt: 1,
        errorClass: terminalErrorClass!,
        errorMessage: terminalErrorMessage,
      );
    }

    final poll = (_polls[captureId] ?? 0) + 1;
    _polls[captureId] = poll;

    if (poll <= stages.length) {
      return RecordingStatusModel(
        captureId: captureId,
        stage: stages[poll - 1],
        status: 'processing',
        attempt: 0,
        errorClass: '',
        errorMessage: null,
      );
    }

    return RecordingStatusModel(
      captureId: captureId,
      stage: 'completed',
      status: 'ready',
      attempt: 0,
      errorClass: '',
      errorMessage: null,
    );
  }

  @override
  Future<KnowledgeSnapshot?> fetchKnowledgeForCapture(String captureId) async {
    knowledgeCalls++;
    return knowledgeByCapture[captureId] ??
        KnowledgeSnapshot(
          knowledgeItemId: 'knowledge-$captureId',
          title: uploadResult.title.isEmpty
              ? 'Voice Thought'
              : uploadResult.title,
          coreIdea: uploadResult.coreIdea,
          concepts: uploadResult.concepts,
          tags: uploadResult.tags,
          openQuestions: uploadResult.openQuestions,
        );
  }

  @override
  Future<List<RecordingModel>> fetchRecordings() async {
    return List.unmodifiable(recordings);
  }

  @override
  Future<void> retryRecording(String captureId) async {
    retryCalls++;
    _polls[captureId] = 0;
    terminalErrorClass = null;
  }

  @override
  Future<void> deleteCapture(String captureId) async {
    deleteCalls++;
    if (failDelete) {
      throw BackendException('delete failed', statusCode: 500);
    }
    recordings.removeWhere((r) => r.captureId == captureId);
  }

  @override
  Future<List<({String id, double score})>> searchSemantic(
    String query, {
    int limit = 20,
  }) async => const [];

  // ----------------------------------------------------------------- graph
  @override
  Future<GraphDataModel> fetchGraph() async {
    graphCalls++;
    if (failGraph) {
      throw BackendException('graph failed', statusCode: 500);
    }
    return graphData;
  }

  @override
  Future<GraphSearchResult> searchGraph(String query, {int limit = 20}) async {
    searchCalls++;
    if (failSearch) {
      throw BackendException('search failed', statusCode: 500);
    }
    if (query.trim().isEmpty) {
      return GraphSearchResult(entities: const [], relationships: const []);
    }
    return searchResult;
  }

  @override
  Future<EntityDetailModel> fetchEntityDetail(String entityId) async {
    final detail = entityDetails[entityId];
    if (detail == null) {
      throw BackendException('entity not found', statusCode: 404);
    }
    return detail;
  }

  @override
  Future<EntityModel> updateEntity(
    String entityId, {
    String? name,
    String? description,
  }) async {
    final detail = entityDetails[entityId];
    if (detail == null) {
      throw BackendException('entity not found', statusCode: 404);
    }
    final updated = EntityModel(
      id: detail.entity.id,
      name: name ?? detail.entity.name,
      entityType: detail.entity.entityType,
      description: description ?? detail.entity.description,
      confidence: detail.entity.confidence,
      certainty: detail.entity.certainty,
      provenance: detail.entity.provenance,
      createdAt: detail.entity.createdAt,
    );
    entityDetails[entityId] = EntityDetailModel(
      entity: updated,
      relationships: detail.relationships,
    );
    return updated;
  }

  @override
  Future<void> deleteEntity(String entityId) async {
    entityDetails.remove(entityId);
    graphData = GraphDataModel(
      nodes: graphData.nodes.where((n) => n.id != entityId).toList(),
      edges: graphData.edges
          .where((e) => e.fromNode != entityId && e.toNode != entityId)
          .toList(),
      clusters: graphData.clusters,
    );
  }

  @override
  Future<void> updateRelationship(
    String relId,
    String status, {
    String? relationType,
  }) async {
    graphData = GraphDataModel(
      nodes: graphData.nodes,
      edges: graphData.edges.map((edge) {
        if (edge.id != relId) return edge;
        return GraphEdgeModel(
          id: edge.id,
          fromNode: edge.fromNode,
          toNode: edge.toNode,
          type: relationType ?? edge.type,
          status: status,
          certainty: edge.certainty,
        );
      }).toList(),
      clusters: graphData.clusters,
    );
  }

  @override
  Future<List<GraphEdgeModel>> fetchAllRelationships() async {
    if (failGraph) {
      throw BackendException('relationships failed', statusCode: 500);
    }
    return graphData.edges;
  }

  @override
  Future<void> deleteRelationship(String relId) async {
    graphData = GraphDataModel(
      nodes: graphData.nodes,
      edges: graphData.edges.where((e) => e.id != relId).toList(),
      clusters: graphData.clusters,
    );
    for (final entry in entityDetails.entries.toList()) {
      entityDetails[entry.key] = EntityDetailModel(
        entity: entry.value.entity,
        relationships: entry.value.relationships
            .where((r) => r.id != relId)
            .toList(),
      );
    }
  }

  // ------------------------------------------------------------------ auth
  @override
  Future<Map<String, dynamic>> signup(String email, String password) async {
    signupCalls++;
    if (failAuth) {
      throw BackendException('signup failed', statusCode: 500);
    }
    return {
      'verification_required': true,
      'email': email,
      'dev_verification_token': 'dev-verify-token',
    };
  }

  @override
  Future<Map<String, dynamic>> login(String email, String password) async {
    loginCalls++;
    if (failAuth) {
      throw BackendException('login failed', statusCode: 401);
    }
    return {
      'token': 'session-token-123',
      'user': {
        'id': 'user-1',
        'email': email,
        'email_verified': true,
        'created_at': '2026-01-01T00:00:00Z',
      },
    };
  }

  @override
  Future<void> verifyEmail(String token) async {
    if (failAuth) {
      throw BackendException('verify failed', statusCode: 401);
    }
  }

  @override
  Future<void> updateConsent(bool granted) async {
    consentCalls++;
    if (failAuth) {
      throw BackendException('consent failed', statusCode: 500);
    }
    consentGranted = granted;
  }

  @override
  Future<Map<String, dynamic>> getConsent() async {
    getConsentCalls++;
    return {
      'granted': consentGranted,
      'version': '2026-10-29-v1',
      'providers': <Map>[],
    };
  }

  @override
  Future<void> logout() async {
    logoutCalls++;
  }

  @override
  Future<Map<String, dynamic>> deleteAccount() async {
    deleteAccountCalls++;
    return {'deleted': true, 'sessions_revoked': 1};
  }

  @override
  Future<BackendConnectionResult> testConnection() async {
    testConnectionCalls++;
    if (!healthy) {
      return const BackendConnectionResult(
        ok: false,
        message: 'Could not reach server.',
      );
    }
    return const BackendConnectionResult(
      ok: true,
      message: 'Connected and authenticated.',
    );
  }
}
