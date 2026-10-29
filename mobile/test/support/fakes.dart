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
          (n.summary?.toLowerCase().contains(query) ?? false);
    }).toList();
  }
}

/// Controllable backend double. No real network calls are made.
class FakeBackendService extends BackendService {
  FakeBackendService(super.settings);

  bool healthy = true;
  bool failUpload = false;
  bool failDelete = false;
  bool failGraph = false;
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

  /// When set, uploads wait until the completer is completed.
  Completer<void>? uploadGate;

  BackendSyncResult uploadResult = BackendSyncResult(
    captureId: 'capture',
    status: 'ready',
    title: 'Processed title',
    coreIdea: 'Processed summary',
    concepts: const ['concept'],
    tags: const ['tag'],
    openQuestions: const ['question'],
  );

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
    if (failUpload) {
      throw BackendException('upload failed', statusCode: 500);
    }
    return BackendSyncResult(
      captureId: captureId,
      status: uploadResult.status,
      title: uploadResult.title,
      coreIdea: uploadResult.coreIdea,
      concepts: uploadResult.concepts,
      tags: uploadResult.tags,
      openQuestions: uploadResult.openQuestions,
    );
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
    return {'granted': consentGranted, 'version': '2026-10-29-v1', 'providers': <Map>[]};
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
    return const BackendConnectionResult(ok: true, message: 'Connected and authenticated.');
  }
}
