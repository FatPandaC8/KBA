import 'dart:convert';

import 'package:http/http.dart' as http;

import 'settings_service.dart';

class GraphNodeModel {
  final String id;
  final String title;
  final String kind;
  final double x;
  final double y;

  GraphNodeModel({
    required this.id,
    required this.title,
    required this.kind,
    required this.x,
    required this.y,
  });

  factory GraphNodeModel.fromJson(Map<String, dynamic> json) {
    return GraphNodeModel(
      id: json['id'] as String,
      title: json['title'] as String,
      kind: json['kind'] as String,
      x: (json['x'] as num).toDouble(),
      y: (json['y'] as num).toDouble(),
    );
  }
}

class GraphEdgeModel {
  final String id;
  final String fromNode;
  final String toNode;
  final String type;
  final String status;

  GraphEdgeModel({
    required this.id,
    required this.fromNode,
    required this.toNode,
    required this.type,
    required this.status,
  });

  factory GraphEdgeModel.fromJson(Map<String, dynamic> json) {
    return GraphEdgeModel(
      id: json['id'] as String,
      fromNode: json['from_node'] as String,
      toNode: json['to_node'] as String,
      type: json['type'] as String,
      status: json['status'] as String,
    );
  }
}

class BackendSyncResult {
  final String captureId;
  final String status;
  final String title;
  final String coreIdea;
  final String transcript;
  final List<String> concepts;
  final List<String> tags;
  final List<String> openQuestions;

  BackendSyncResult({
    required this.captureId,
    required this.status,
    required this.title,
    required this.coreIdea,
    required this.transcript,
    required this.concepts,
    required this.tags,
    required this.openQuestions,
  });
}

class BackendService {
  final SettingsService _settings;
  final http.Client _client;

  BackendService(this._settings, {http.Client? client})
    : _client = client ?? http.Client();

  http.Client get client => _client;
  String get baseUrl => _settings.serverUrl.replaceAll(RegExp(r'/+$'), '');

  Future<bool> checkHealth() async {
    try {
      final res = await _client
          .get(Uri.parse('$baseUrl/api/health'))
          .timeout(const Duration(seconds: 3));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<BackendSyncResult> uploadCapture({
    required String captureId,
    required String idempotencyKey,
    required String audioPath,
    required int durationMs,
    bool consentGiven = false,
  }) async {
    final uri = Uri.parse('$baseUrl/api/captures/upload');
    final request = http.MultipartRequest('POST', uri)
      ..fields['capture_id'] = captureId
      ..fields['idempotency_key'] = idempotencyKey
      ..fields['duration_ms'] = durationMs.toString()
      ..fields['consent_given'] = consentGiven ? 'true' : 'false'
      ..files.add(await http.MultipartFile.fromPath('file', audioPath));

    final streamedRes = await _client.send(request);
    final res = await http.Response.fromStream(streamedRes);

    if (res.statusCode >= 200 && res.statusCode < 300) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      final item = data['knowledge_item'] as Map<String, dynamic>? ?? {};
      return BackendSyncResult(
        captureId: data['capture_id'] ?? captureId,
        status: data['status'] ?? 'ready',
        title: item['title'] ?? 'Captured Idea',
        coreIdea: item['core_idea'] ?? '',
        transcript: item['transcript'] ?? '',
        concepts:
            (item['concepts'] as List?)?.map((e) => e.toString()).toList() ??
            [],
        tags: (item['tags'] as List?)?.map((e) => e.toString()).toList() ?? [],
        openQuestions:
            (item['open_questions'] as List?)
                ?.map((e) => e.toString())
                .toList() ??
            [],
      );
    } else {
      throw Exception('Server upload failed (${res.statusCode}): ${res.body}');
    }
  }

  Future<List<({String id, double score})>> searchSemantic(
    String query, {
    int limit = 20,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/api/knowledge/semantic-search?q=${Uri.encodeComponent(query)}&limit=$limit',
    );
    final res = await _client.get(uri);
    if (res.statusCode == 200) {
      final List data = jsonDecode(utf8.decode(res.bodyBytes));
      return data.map((entry) {
        final item = entry['item'] as Map<String, dynamic>;
        final score = (entry['similarity_score'] as num).toDouble();
        return (id: item['id'] as String, score: score);
      }).toList();
    }
    return [];
  }

  Future<void> updateConsent(bool consentGiven) async {
    final uri = Uri.parse('$baseUrl/api/eval/consent');
    await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'consent_given': consentGiven}),
    );
  }

  Future<({List<GraphNodeModel> nodes, List<GraphEdgeModel> edges})>
  fetchGraph() async {
    final uri = Uri.parse('$baseUrl/api/graph');
    final res = await _client.get(uri);
    if (res.statusCode == 200) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      final nodes = (data['nodes'] as List)
          .map((n) => GraphNodeModel.fromJson(n))
          .toList();
      final edges = (data['edges'] as List)
          .map((e) => GraphEdgeModel.fromJson(e))
          .toList();
      return (nodes: nodes, edges: edges);
    }
    throw Exception('Failed to fetch graph (${res.statusCode})');
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
    await _client.patch(Uri.parse(url));
  }

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
    final uri = Uri.parse('$baseUrl/api/knowledge');
    final payload = jsonEncode({
      'id': id,
      'capture_id': captureId,
      'title': title,
      'core_idea': coreIdea,
      'details': details,
      'transcript': transcript,
      'concepts': concepts,
      'tags': tags,
      'open_questions': openQuestions,
      'provenance': 'mobile-sync',
    });
    await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: payload,
    );
  }

  Future<List<GraphEdgeModel>> fetchAllRelationships() async {
    final uri = Uri.parse('$baseUrl/api/graph');
    final res = await _client.get(uri);
    if (res.statusCode == 200) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      return (data['edges'] as List)
          .map((e) => GraphEdgeModel.fromJson(e))
          .toList();
    }
    return [];
  }

  Future<void> deleteRelationship(String relId) async {
    await _client.delete(Uri.parse('$baseUrl/api/relationships/$relId'));
  }
}
