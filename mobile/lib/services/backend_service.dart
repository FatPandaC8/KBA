import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'settings_service.dart';

class GraphNodeModel {
  final String id;
  final String title;
  final String kind;
  final double x;
  final double y;
  final String clusterId;
  final String certainty;
  final double confidence;
  final int degree;
  final bool isSelf;

  GraphNodeModel({
    required this.id,
    required this.title,
    required this.kind,
    required this.x,
    required this.y,
    this.clusterId = '',
    this.certainty = 'confirmed',
    this.confidence = 0.5,
    this.degree = 0,
    this.isSelf = false,
  });

  factory GraphNodeModel.fromJson(Map<String, dynamic> json) {
    return GraphNodeModel(
      id: json['id'] as String,
      title: json['title'] as String,
      kind: json['kind'] as String,
      x: (json['x'] as num).toDouble(),
      y: (json['y'] as num).toDouble(),
      clusterId: (json['cluster_id'] as String?) ?? '',
      certainty: (json['certainty'] as String?) ?? 'confirmed',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.5,
      degree: (json['degree'] as num?)?.toInt() ?? 0,
      isSelf: (json['is_self'] as bool?) ?? false,
    );
  }
}

class GraphEdgeModel {
  final String id;
  final String fromNode;
  final String toNode;
  final String type;
  final String status;
  final String certainty;

  GraphEdgeModel({
    required this.id,
    required this.fromNode,
    required this.toNode,
    required this.type,
    required this.status,
    this.certainty = 'confirmed',
  });

  factory GraphEdgeModel.fromJson(Map<String, dynamic> json) {
    return GraphEdgeModel(
      id: json['id'] as String,
      fromNode: json['from_node'] as String,
      toNode: json['to_node'] as String,
      type: json['type'] as String,
      status: json['status'] as String,
      certainty: (json['certainty'] as String?) ?? 'confirmed',
    );
  }
}

class GraphClusterModel {
  final String id;
  final String label;
  final double x;
  final double y;
  final int size;

  GraphClusterModel({
    required this.id,
    required this.label,
    required this.x,
    required this.y,
    required this.size,
  });

  factory GraphClusterModel.fromJson(Map<String, dynamic> json) {
    return GraphClusterModel(
      id: json['id'] as String,
      label: json['label'] as String,
      x: (json['x'] as num).toDouble(),
      y: (json['y'] as num).toDouble(),
      size: (json['size'] as num).toInt(),
    );
  }
}

class GraphDataModel {
  final List<GraphNodeModel> nodes;
  final List<GraphEdgeModel> edges;
  final List<GraphClusterModel> clusters;

  GraphDataModel({
    required this.nodes,
    required this.edges,
    required this.clusters,
  });
}

class EntityModel {
  final String id;
  final String name;
  final String entityType;
  final String description;
  final double confidence;
  final String certainty;
  final String provenance;
  final String createdAt;

  EntityModel({
    required this.id,
    required this.name,
    required this.entityType,
    required this.description,
    required this.confidence,
    required this.certainty,
    required this.provenance,
    required this.createdAt,
  });

  factory EntityModel.fromJson(Map<String, dynamic> json) {
    return EntityModel(
      id: json['id'] as String,
      name: json['name'] as String,
      entityType: (json['entity_type'] as String?) ?? 'concept',
      description: (json['description'] as String?) ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.5,
      certainty: (json['certainty'] as String?) ?? 'confirmed',
      provenance: (json['provenance'] as String?) ?? '',
      createdAt: (json['created_at'] as String?) ?? '',
    );
  }
}

class EntityRelationshipModel {
  final String id;
  final String fromId;
  final String toId;
  final String fromName;
  final String toName;
  final String relationType;
  final String status;
  final String certainty;

  EntityRelationshipModel({
    required this.id,
    required this.fromId,
    required this.toId,
    required this.fromName,
    required this.toName,
    required this.relationType,
    required this.status,
    required this.certainty,
  });

  factory EntityRelationshipModel.fromJson(Map<String, dynamic> json) {
    return EntityRelationshipModel(
      id: json['id'] as String,
      fromId: (json['from_id'] as String?) ?? '',
      toId: (json['to_id'] as String?) ?? '',
      fromName: (json['from_name'] as String?) ?? '',
      toName: (json['to_name'] as String?) ?? '',
      relationType: (json['relation_type'] as String?) ?? '',
      status: (json['status'] as String?) ?? 'suggested',
      certainty: (json['certainty'] as String?) ?? 'confirmed',
    );
  }
}

class EntityDetailModel {
  final EntityModel entity;
  final List<EntityRelationshipModel> relationships;

  EntityDetailModel({required this.entity, required this.relationships});
}

class GraphSearchEntity {
  final EntityModel entity;
  final double score;

  GraphSearchEntity({required this.entity, required this.score});
}

class GraphSearchResult {
  final List<GraphSearchEntity> entities;
  final List<EntityRelationshipModel> relationships;

  GraphSearchResult({required this.entities, required this.relationships});
}

class CitationModel {
  final String id;
  final String kind;
  final String targetId;
  final String name;
  final bool deleted;

  CitationModel({
    required this.id,
    required this.kind,
    required this.targetId,
    required this.name,
    required this.deleted,
  });

  factory CitationModel.fromJson(Map<String, dynamic> json) {
    return CitationModel(
      id: json['id'] as String,
      kind: (json['kind'] as String?) ?? '',
      targetId: (json['target_id'] as String?) ?? '',
      name: (json['name'] as String?) ?? '',
      deleted: (json['deleted'] as bool?) ?? false,
    );
  }
}

class ProviderInfoModel {
  final String id;
  final String name;
  final String kind;
  final List<String> receives;
  final bool trainsOnData;
  final bool available;
  final String detail;

  ProviderInfoModel({
    required this.id,
    required this.name,
    required this.kind,
    required this.receives,
    required this.trainsOnData,
    required this.available,
    required this.detail,
  });

  factory ProviderInfoModel.fromJson(Map<String, dynamic> json) {
    return ProviderInfoModel(
      id: json['id'] as String,
      name: (json['name'] as String?) ?? '',
      kind: (json['kind'] as String?) ?? '',
      receives: ((json['receives'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList(),
      trainsOnData: (json['trains_on_data'] as bool?) ?? false,
      available: (json['available'] as bool?) ?? false,
      detail: (json['detail'] as String?) ?? '',
    );
  }
}

/// STT result (pipeline split, S1): one audio blob in, one transcript out.
/// The server persists NOTHING; the client keeps or discards the audio.
class SttResult {
  final String transcript;
  final String? language;
  final String provider;

  SttResult({required this.transcript, this.language, required this.provider});

  factory SttResult.fromJson(Map<String, dynamic> json) {
    return SttResult(
      transcript: (json['transcript'] as String?) ?? '',
      language: json['language'] as String?,
      provider: (json['provider'] as String?) ?? '',
    );
  }
}

/// Knowledge-ingest result (pipeline split, S1): POST /api/text-kb ran the
/// one-UoW ingest for capture_id. Retries re-send the SAME capture_id.
class IngestResultModel {
  final String captureId;
  final String knowledgeItemId;
  final int entitiesAdded;
  final int relationshipsAdded;
  final String provider;
  final int elapsedMs;

  IngestResultModel({
    required this.captureId,
    required this.knowledgeItemId,
    required this.entitiesAdded,
    required this.relationshipsAdded,
    required this.provider,
    this.elapsedMs = 0,
  });

  factory IngestResultModel.fromJson(Map<String, dynamic> json) {
    return IngestResultModel(
      captureId: (json['capture_id'] as String?) ?? '',
      knowledgeItemId: (json['knowledge_item_id'] as String?) ?? '',
      entitiesAdded: (json['entities_added'] as num?)?.toInt() ?? 0,
      relationshipsAdded:
          (json['relationships_added'] as num?)?.toInt() ?? 0,
      provider: (json['provider'] as String?) ?? '',
      elapsedMs: (json['elapsed_ms'] as num?)?.toInt() ?? 0,
    );
  }
}

/// Capture journal row (pipeline split, S2): capture truth only — created_at,
/// whether the knowledge item exists, and the last ingest error if one is
/// stored. There is no stage/status/attempt any more.
class RecordingModel {
  final String captureId;
  final String createdAt;
  final bool hasKnowledgeItem;
  final String? lastError;

  RecordingModel({
    required this.captureId,
    required this.createdAt,
    required this.hasKnowledgeItem,
    required this.lastError,
  });

  factory RecordingModel.fromJson(Map<String, dynamic> json) {
    return RecordingModel(
      captureId: json['capture_id'] as String,
      createdAt: (json['created_at'] as String?) ?? '',
      hasKnowledgeItem: (json['has_knowledge_item'] as bool?) ?? false,
      lastError: json['last_error'] as String?,
    );
  }
}

/// Knowledge derived from one recording. This is the only text the client is
/// allowed to display; transcripts and raw audio content are never included.
class KnowledgeSnapshot {
  final String knowledgeItemId;
  final String title;
  final String coreIdea;
  final List<String> concepts;
  final List<String> tags;
  final List<String> openQuestions;

  KnowledgeSnapshot({
    required this.knowledgeItemId,
    required this.title,
    required this.coreIdea,
    required this.concepts,
    required this.tags,
    required this.openQuestions,
  });
}

class BackendConnectionResult {
  final bool ok;
  final String message;

  const BackendConnectionResult({required this.ok, required this.message});
}

class BackendException implements Exception {
  final int? statusCode;
  final String message;
  /// Typed error class from the split endpoints ({class, message} bodies):
  /// invalid_input, unsupported_language, conflict, quota_exhausted,
  /// timeout, network_error, provider_failure, server_error...
  final String errorClass;

  BackendException(this.message, {this.statusCode, this.errorClass = ''});

  @override
  String toString() => message;
}

class BackendService {
  static const Duration _readTimeout = Duration(seconds: 45);
  // Pipeline split (S2): both endpoints run work inside the request, so the
  // client timeout must cover the full server-side work:
  //  - /api/stt  : local faster-whisper decode+transcribe (measured ~0.5-2 s
  //    for a short capture on the dev machine; 120 s covers a full 120 s note).
  //  - /api/text-kb : extraction + graph commit (measured ~0.5-3 s; 90 s
  //    covers long texts near the 20k-char limit and provider hiccups).
  static const Duration _sttTimeout = Duration(seconds: 120);
  static const Duration _textKbTimeout = Duration(seconds: 90);

  final SettingsService _settings;
  final http.Client _client;

  BackendService(SettingsService settings, {http.Client? client})
    : _settings = settings,
      _client = client ?? http.Client();

  String get baseUrl => _settings.serverUrl.replaceAll(RegExp(r'/+$'), '');

  /// Bearer session auth. Returns no headers when not signed in so unauthenticated
  /// requests fail closed with 401 from the server.
  Map<String, String> get _authHeaders {
    final token = _settings.sessionToken.trim();
    if (token.isEmpty) return const {};
    return {'Authorization': 'Bearer $token'};
  }

  Map<String, String> get _jsonHeaders => {
    ..._authHeaders,
    'Content-Type': 'application/json',
  };

  // ------------------------------------------------------------------ auth
  Future<Map<String, dynamic>> signup(String email, String password) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/auth/signup'),
          headers: _jsonHeaders,
          body: jsonEncode({'email': email, 'password': password}),
        )
        .timeout(_readTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    }
    throw BackendException(
      _serverMessage(res, 'Sign-up failed'),
      statusCode: res.statusCode,
    );
  }

  Future<Map<String, dynamic>> login(String email, String password) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/auth/login'),
          headers: _jsonHeaders,
          body: jsonEncode({'email': email, 'password': password}),
        )
        .timeout(_readTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    }
    throw BackendException(
      _serverMessage(res, 'Log-in failed'),
      statusCode: res.statusCode,
    );
  }

  Future<void> verifyEmail(String token) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/auth/verify-email'),
          headers: _jsonHeaders,
          body: jsonEncode({'token': token}),
        )
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Verification failed'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<void> updateConsent(bool granted) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/consent'),
          headers: _jsonHeaders,
          body: jsonEncode({'granted': granted}),
        )
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Consent update failed'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<Map<String, dynamic>> getConsent() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/consent'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    }
    throw BackendException(
      _serverMessage(res, 'Failed to load consent'),
      statusCode: res.statusCode,
    );
  }

  /// Echo's core workflow requires AI processing. Keep the server-side
  /// consent record current without exposing it as an end-user opt-in.
  Future<void> ensureConsent() async {
    final consent = await getConsent();
    final granted = consent['granted'] as bool? ?? false;
    final version = consent['version'] as String?;
    final recordedVersion = consent['recorded_version'] as String?;
    if (!granted || version == null || recordedVersion != version) {
      await updateConsent(true);
    }
  }

  Future<void> logout() async {
    await _client
        .post(Uri.parse('$baseUrl/api/auth/logout'), headers: _authHeaders)
        .timeout(_readTimeout);
  }

  Future<Map<String, dynamic>> deleteAccount() async {
    final res = await _client
        .delete(
          Uri.parse('$baseUrl/api/account?confirm=DELETE'),
          headers: _authHeaders,
        )
        .timeout(_readTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    }
    throw BackendException(
      _serverMessage(res, 'Account deletion failed'),
      statusCode: res.statusCode,
    );
  }

  // ------------------------------------------------------------------ health
  Future<bool> checkHealth() async {
    try {
      final res = await _client
          .get(Uri.parse('$baseUrl/api/health'))
          .timeout(const Duration(seconds: 4));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Verifies reachability and that a session is accepted by the server.
  Future<BackendConnectionResult> testConnection() async {
    final uri = Uri.tryParse(baseUrl);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return const BackendConnectionResult(
        ok: false,
        message: 'Enter a valid server URL, including http:// or https://.',
      );
    }
    try {
      final health = await _client
          .get(Uri.parse('$baseUrl/api/health'))
          .timeout(const Duration(seconds: 5));
      if (health.statusCode != 200) {
        return BackendConnectionResult(
          ok: false,
          message: 'Server responded with HTTP ${health.statusCode}.',
        );
      }
      final auth = await _client
          .get(Uri.parse('$baseUrl/api/knowledge'), headers: _authHeaders)
          .timeout(const Duration(seconds: 5));
      if (auth.statusCode == 401) {
        return const BackendConnectionResult(
          ok: false,
          message: 'Server reachable, but you are not signed in. Sign in on the Settings screen.',
        );
      }
      if (auth.statusCode == 403) {
        return const BackendConnectionResult(
          ok: false,
          message: 'Server reachable, but AI processing setup is incomplete. Try again shortly.',
        );
      }
      if (auth.statusCode != 200) {
        return BackendConnectionResult(
          ok: false,
          message:
              'Server reachable, but API returned HTTP ${auth.statusCode}.',
        );
      }
      return const BackendConnectionResult(
        ok: true,
        message: 'Connected and authenticated.',
      );
    } catch (e) {
      return BackendConnectionResult(
        ok: false,
        message: 'Could not reach server: ${_shortError(e)}',
      );
    }
  }

  String _shortError(Object error) {
    final text = error.toString();
    return text.length > 160 ? '${text.substring(0, 160)}…' : text;
  }

  // --------------------------------------------------------------- capture
  /// POST /api/stt (auth only): a stateless transcription. The server persists
  /// NOTHING, so the local audio remains the only copy; the caller decides
  /// whether to keep it for playback or delete it (S2/S4b).
  Future<SttResult> transcribe({
    required String audioPath,
    required int durationMs,
  }) async {
    final bytes = await File(audioPath).readAsBytes();
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/stt'),
          headers: {
            ..._authHeaders,
            'Content-Type': 'audio/mp4',
            'Content-Length': '${bytes.length}',
          },
          body: bytes,
        )
        .timeout(_sttTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return SttResult.fromJson(
        jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>,
      );
    }
    throw BackendException(
      _typedMessage(res, 'Transcription failed'),
      statusCode: res.statusCode,
      errorClass: _typedClass(res),
    );
  }

  /// POST /api/text-kb (auth + consent): one synchronous ingest of `text`
  /// under `captureId`. Idempotent on capture_id — a retry re-sends the SAME
  /// id and the server returns the existing result without creating anything.
  Future<IngestResultModel> ingestText({
    required String captureId,
    required String text,
  }) async {
    await ensureConsent();
    final res = await _client
        .post(
          Uri.parse('$baseUrl/api/text-kb'),
          headers: _jsonHeaders,
          body: jsonEncode({'capture_id': captureId, 'text': text}),
        )
        .timeout(_textKbTimeout);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return IngestResultModel.fromJson(
        jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>,
      );
    }
    throw BackendException(
      _typedMessage(res, 'Knowledge processing failed'),
      statusCode: res.statusCode,
      errorClass: _typedClass(res),
    );
  }

  Future<List<RecordingModel>> fetchRecordings() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/recordings'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode != 200) {
      throw BackendException(
        _serverMessage(res, 'Failed to load recordings'),
        statusCode: res.statusCode,
      );
    }
    final list = jsonDecode(utf8.decode(res.bodyBytes)) as List;
    return list
        .map((e) => RecordingModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// Returns the knowledge produced for one recording, or null when the
  /// backend has not finished extraction. Transcripts are never returned.
  Future<KnowledgeSnapshot?> fetchKnowledgeForCapture(String captureId) async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/knowledge'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode != 200) return null;
    final list = jsonDecode(utf8.decode(res.bodyBytes)) as List;
    for (final entry in list) {
      final item = entry as Map<String, dynamic>;
      if (item['capture_id'] != captureId) continue;
      return KnowledgeSnapshot(
        knowledgeItemId: (item['id'] as String?) ?? '',
        title: (item['title'] as String?) ?? '',
        coreIdea: (item['core_idea'] as String?) ?? '',
        concepts: ((item['concepts'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        tags: ((item['tags'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
        openQuestions: ((item['open_questions'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
      );
    }
    return null;
  }

  // ---------------------------------------------------------------- search
  Future<List<({String id, double score})>> searchSemantic(
    String query, {
    int limit = 20,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/api/knowledge/semantic-search?q=${Uri.encodeComponent(query)}&limit=$limit',
    );
    final res = await _client
        .get(uri, headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode == 200) {
      final List data = jsonDecode(utf8.decode(res.bodyBytes));
      return data.map((entry) {
        final item = entry['item'] as Map<String, dynamic>;
        final score = (entry['similarity_score'] as num).toDouble();
        return (id: item['id'] as String, score: score);
      }).toList();
    }
    if (res.statusCode == 401 || res.statusCode == 503) {
      throw BackendException(
        _serverMessage(res, 'Server authentication failed'),
        statusCode: res.statusCode,
      );
    }
    return [];
  }

  // ----------------------------------------------------------------- graph
  Future<GraphDataModel> fetchGraph() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/graph'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode == 200) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      return GraphDataModel(
        nodes: ((data['nodes'] as List?) ?? const [])
            .map((n) => GraphNodeModel.fromJson(n as Map<String, dynamic>))
            .toList(),
        edges: ((data['edges'] as List?) ?? const [])
            .map((e) => GraphEdgeModel.fromJson(e as Map<String, dynamic>))
            .toList(),
        clusters: ((data['clusters'] as List?) ?? const [])
            .map((c) => GraphClusterModel.fromJson(c as Map<String, dynamic>))
            .toList(),
      );
    }
    throw BackendException(
      _serverMessage(res, 'Failed to fetch graph'),
      statusCode: res.statusCode,
    );
  }

  Future<GraphSearchResult> searchGraph(String query, {int limit = 20}) async {
    final uri = Uri.parse(
      '$baseUrl/api/graph/search?q=${Uri.encodeComponent(query)}&limit=$limit',
    );
    final res = await _client
        .get(uri, headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode != 200) {
      throw BackendException(
        _serverMessage(res, 'Search failed'),
        statusCode: res.statusCode,
      );
    }
    final data = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    return GraphSearchResult(
      entities: ((data['entities'] as List?) ?? const []).map((entry) {
        final map = entry as Map<String, dynamic>;
        return GraphSearchEntity(
          entity: EntityModel.fromJson(map['entity'] as Map<String, dynamic>),
          score: (map['score'] as num?)?.toDouble() ?? 0,
        );
      }).toList(),
      relationships: ((data['relationships'] as List?) ?? const [])
          .map(
            (e) => EntityRelationshipModel.fromJson(e as Map<String, dynamic>),
          )
          .toList(),
    );
  }

  Future<EntityDetailModel> fetchEntityDetail(String entityId) async {
    final res = await _client
        .get(
          Uri.parse('$baseUrl/api/graph/entities/$entityId'),
          headers: _authHeaders,
        )
        .timeout(_readTimeout);
    if (res.statusCode == 200) {
      final data =
          jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      return EntityDetailModel(
        entity: EntityModel.fromJson(data['entity'] as Map<String, dynamic>),
        relationships: ((data['relationships'] as List?) ?? const [])
            .map(
              (e) =>
                  EntityRelationshipModel.fromJson(e as Map<String, dynamic>),
            )
            .toList(),
      );
    }
    throw BackendException(
      _serverMessage(res, 'Entity not found'),
      statusCode: res.statusCode,
    );
  }

  Future<EntityModel> updateEntity(
    String entityId, {
    String? name,
    String? description,
  }) async {
    final res = await _client
        .patch(
          Uri.parse('$baseUrl/api/graph/entities/$entityId'),
          headers: _jsonHeaders,
          body: jsonEncode({'name': ?name, 'description': ?description}),
        )
        .timeout(_readTimeout);
    if (res.statusCode == 200) {
      return EntityModel.fromJson(
        jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>,
      );
    }
    throw BackendException(
      _serverMessage(res, 'Could not update entity'),
      statusCode: res.statusCode,
    );
  }

  Future<void> deleteEntity(String entityId) async {
    final res = await _client
        .delete(
          Uri.parse('$baseUrl/api/graph/entities/$entityId'),
          headers: _authHeaders,
        )
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Could not delete entity'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<void> updateRelationship(
    String relId,
    String status, {
    String? relationType,
  }) async {
    var url = '$baseUrl/api/relationships/$relId?status=$status';
    if (relationType != null) {
      url += '&relation_type=${Uri.encodeComponent(relationType)}';
    }
    final res = await _client
        .patch(Uri.parse(url), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Failed to update relationship'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<List<GraphEdgeModel>> fetchAllRelationships() async {
    final graph = await fetchGraph();
    return graph.edges;
  }

  Future<void> deleteRelationship(String relId) async {
    final res = await _client
        .delete(
          Uri.parse('$baseUrl/api/relationships/$relId'),
          headers: _authHeaders,
        )
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Failed to delete relationship'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<void> deleteCapture(String captureId) async {
    final res = await _client
        .delete(
          Uri.parse('$baseUrl/api/captures/$captureId'),
          headers: _authHeaders,
        )
        .timeout(_readTimeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw BackendException(
        _serverMessage(res, 'Server deletion failed'),
        statusCode: res.statusCode,
      );
    }
  }

  Future<List<ProviderInfoModel>> fetchProviders() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/providers'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode != 200) {
      throw BackendException(
        _serverMessage(res, 'Could not load providers'),
        statusCode: res.statusCode,
      );
    }
    final list = jsonDecode(utf8.decode(res.bodyBytes)) as List;
    return list
        .map((e) => ProviderInfoModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  String _serverMessage(http.Response res, String fallback) {
    return _typedMessage(res, fallback);
  }

  /// Reads the typed error body of the split endpoints:
  /// `{"detail": {"class": "...", "message": "..."}}`. Plain `detail` strings
  /// (legacy routes) still work.
  String _typedMessage(http.Response res, String fallback) {
    try {
      final decoded = jsonDecode(utf8.decode(res.bodyBytes));
      if (decoded is Map) {
        final detail = decoded['detail'];
        if (detail is Map) {
          final message = (detail['message'] as String?) ?? '';
          if (message.isNotEmpty) return message;
        }
        if (detail is String && detail.isNotEmpty) return detail;
      }
    } catch (_) {}
    return '$fallback (HTTP ${res.statusCode}).';
  }

  String _typedClass(http.Response res) {
    try {
      final decoded = jsonDecode(utf8.decode(res.bodyBytes));
      if (decoded is Map && decoded['detail'] is Map) {
        return ((decoded['detail'] as Map)['class'] as String?) ?? '';
      }
    } catch (_) {}
    return '';
  }
}
