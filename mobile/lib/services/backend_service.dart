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

/// Client-facing capture result. Transcripts are deliberately absent: the
/// server never returns transcripts to ordinary users (PRD C3/D5).
class BackendSyncResult {
  final String captureId;
  final String status;
  final String title;
  final String coreIdea;
  final List<String> concepts;
  final List<String> tags;
  final List<String> openQuestions;

  BackendSyncResult({
    required this.captureId,
    required this.status,
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

  BackendException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class BackendService {
  static const Duration _readTimeout = Duration(seconds: 45);
  static const Duration _uploadTimeout = Duration(seconds: 120);

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

  Future<void> logout() async {
    await _client
        .post(
          Uri.parse('$baseUrl/api/auth/logout'),
          headers: _authHeaders,
        )
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
          message:
              'Server reachable, but you are not signed in. Sign in on the Settings screen.',
        );
      }
      if (auth.statusCode == 403) {
        return const BackendConnectionResult(
          ok: false,
          message:
              'Server reachable, but AI-provider consent is required. Grant consent on the Settings screen.',
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

  // ---------------------------------------------------------------- capture
  Future<BackendSyncResult> uploadCapture({
    required String captureId,
    required String idempotencyKey,
    required String audioPath,
    required int durationMs,
  }) async {
    final uri = Uri.parse('$baseUrl/api/captures/upload');
    final request = http.MultipartRequest('POST', uri)
      ..headers.addAll(_authHeaders)
      ..fields['capture_id'] = captureId
      ..fields['idempotency_key'] = idempotencyKey
      ..fields['duration_ms'] = durationMs.toString()
      ..files.add(await http.MultipartFile.fromPath('file', audioPath));

    final streamedRes = await _client.send(request).timeout(_uploadTimeout);
    final res = await http.Response.fromStream(streamedRes)
        .timeout(_uploadTimeout);

    if (res.statusCode >= 200 && res.statusCode < 300) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      final item = data['knowledge_item'] as Map<String, dynamic>? ?? {};
      return BackendSyncResult(
        captureId: data['capture_id'] ?? captureId,
        status: data['status'] ?? 'ready',
        title: item['title'] ?? 'Captured Idea',
        coreIdea: item['core_idea'] ?? '',
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
    }
    throw BackendException(
      _serverMessage(res, 'Server upload failed'),
      statusCode: res.statusCode,
    );
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
  Future<({List<GraphNodeModel> nodes, List<GraphEdgeModel> edges})>
  fetchGraph() async {
    final res = await _client
        .get(Uri.parse('$baseUrl/api/graph'), headers: _authHeaders)
        .timeout(_readTimeout);
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
    throw BackendException(
      _serverMessage(res, 'Failed to fetch graph'),
      statusCode: res.statusCode,
    );
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
    final res = await _client
        .get(Uri.parse('$baseUrl/api/graph'), headers: _authHeaders)
        .timeout(_readTimeout);
    if (res.statusCode == 200) {
      final data = jsonDecode(utf8.decode(res.bodyBytes));
      return (data['edges'] as List)
          .map((e) => GraphEdgeModel.fromJson(e))
          .toList();
    }
    throw BackendException(
      _serverMessage(res, 'Failed to load relationships'),
      statusCode: res.statusCode,
    );
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

  String _serverMessage(http.Response res, String fallback) {
    try {
      final decoded = jsonDecode(utf8.decode(res.bodyBytes));
      if (decoded is Map && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } catch (_) {}
    return '$fallback (HTTP ${res.statusCode}).';
  }
}
