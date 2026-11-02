import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/backend_service.dart';

/// Mocks the flutter_secure_storage method channel so tests never settle on a
/// missing platform plugin (a read/write future would otherwise never
/// complete and the test hangs). Values are held in a memory map.
///
/// Returns the map so a test can inspect or change the stored session token.
Map<String, String> installSecureStorageMock(TestWidgetsFlutterBinding binding) {
  final store = <String, String>{};
  const channel = MethodChannel(
    'plugins.it_nomads.com/flutter_secure_storage',
  );
  binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
    call,
  ) async {
    switch (call.method) {
      case 'read':
      case 'readAll':
        final arguments = (call.arguments as Map?)?.cast<String, Object?>() ??
            const <String, Object?>{};
        final key = arguments['key'] as String?;
        if (call.method == 'read') {
          return store[key];
        }
        return store;
      case 'write':
        final arguments = (call.arguments as Map?)?.cast<String, Object?>() ??
            const <String, Object?>{};
        final key = arguments['key'] as String?;
        final value = arguments['value'] as String?;
        if (key != null && value != null) store[key] = value;
        return null;
      case 'delete':
        final arguments = (call.arguments as Map?)?.cast<String, Object?>() ??
            const <String, Object?>{};
        store.remove(arguments['key'] as String?);
        return null;
      case 'deleteAll':
        store.clear();
        return null;
      case 'containsKey':
        final arguments = (call.arguments as Map?)?.cast<String, Object?>() ??
            const <String, Object?>{};
        return store.containsKey(arguments['key'] as String?);
      default:
        return null;
    }
  });
  return store;
}

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
/// It models the pipeline split (S1/S2): a successful [transcribe] call
/// yields a transcript; [ingestText] runs the synchronous text-kb ingest and
/// is idempotent per capture_id unless [failIn] is set.
class FakeBackendService extends BackendService {
  FakeBackendService(super.settings);

  bool healthy = true;
  bool failStt = false;
  bool failIngest = false;
  bool failDelete = false;
  bool failGraph = false;
  bool failSearch = false;
  bool failAuth = false;
  bool hasNewGraphData = false;

  int transcribeCalls = 0;
  int ingestCalls = 0;
  int healthCalls = 0;
  int loginCalls = 0;
  int signupCalls = 0;
  int consentCalls = 0;
  int logoutCalls = 0;
  int deleteAccountCalls = 0;
  int testConnectionCalls = 0;
  int getConsentCalls = 0;
  int knowledgeCalls = 0;
  int graphCalls = 0;
  int deleteCalls = 0;
  int searchCalls = 0;

  /// Capture ids in ingest order.
  final List<String> ingestedCaptureIds = [];

  /// When set, ingest waits until the completer is completed.
  Completer<void>? ingestGate;

  SttResult sttResult = SttResult(
    transcript: 'I met Anna at the cafe yesterday.',
    language: 'en',
    provider: 'fake-whisper',
  );

  IngestResultModel ingestResult = IngestResultModel(
    captureId: '',
    knowledgeItemId: '',
    entitiesAdded: 1,
    relationshipsAdded: 1,
    provider: 'extraction_local',
  );

  /// Knowledge returned for ready captures.
  Map<String, KnowledgeSnapshot> knowledgeByCapture = {};

  final List<RecordingModel> recordings = [];

  GraphDataModel graphData = GraphDataModel(
    nodes: const [],
    edges: const [],
    clusters: const [],
  );
  GraphDataModel? nextGraphData;
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
  Future<SttResult> transcribe({
    required String audioPath,
    required int durationMs,
  }) async {
    transcribeCalls++;
    if (failStt) {
      throw BackendException(
        'Audio is too small or corrupted (<100 bytes)',
        statusCode: 400,
        errorClass: 'invalid_input',
      );
    }
    return sttResult;
  }

  @override
  Future<IngestResultModel> ingestText({
    required String captureId,
    required String text,
  }) async {
    ingestCalls++;
    if (ingestGate != null) {
      await ingestGate!.future;
    }
    if (failAuth) {
      throw BackendException(
        'AI processing consent is required before recording.',
        statusCode: 403,
        errorClass: 'consent_required',
      );
    }
    if (failIngest) {
      throw BackendException(
        'Text-KB ingest failed.',
        statusCode: 500,
        errorClass: 'server_error',
      );
    }
    ingestedCaptureIds.add(captureId);
    return IngestResultModel(
      captureId: captureId,
      knowledgeItemId: 'knowledge-$captureId',
      entitiesAdded: ingestResult.entitiesAdded,
      relationshipsAdded: ingestResult.relationshipsAdded,
      provider: ingestResult.provider,
      elapsedMs: ingestResult.elapsedMs,
    );
  }

  @override
  Future<KnowledgeSnapshot?> fetchKnowledgeForCapture(String captureId) async {
    knowledgeCalls++;
    return knowledgeByCapture[captureId] ??
        KnowledgeSnapshot(
          knowledgeItemId: 'knowledge-$captureId',
          title: 'Voice Thought',
          coreIdea: 'Organized knowledge',
          concepts: const ['Echo'],
          tags: const ['concept'],
          openQuestions: const [],
        );
  }

  @override
  Future<List<RecordingModel>> fetchRecordings() async {
    return List.unmodifiable(recordings);
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
    if (nextGraphData != null) {
      final data = nextGraphData!;
      nextGraphData = null;
      return data;
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
