import 'dart:convert';

import 'package:http/http.dart' as http;

import 'settings_service.dart';

class AIStructuredOutput {
  final String title;
  final String summary;
  final List<String> keyFacts;
  final List<String> openQuestions;
  final List<String> tags;

  AIStructuredOutput({
    required this.title,
    required this.summary,
    required this.keyFacts,
    required this.openQuestions,
    required this.tags,
  });
}

class AIService {
  final SettingsService _settings;
  final http.Client _client;

  AIService(this._settings, {http.Client? client})
    : _client = client ?? http.Client();

  bool get isConfigured => _settings.apiKey.trim().isNotEmpty;

  /// Transcribe audio using Whisper-compatible endpoint
  Future<String> transcribeAudio(String audioPath) async {
    if (!isConfigured) {
      throw Exception(
        'AI API key is not configured. Please add it in Settings.',
      );
    }

    final uri = Uri.parse(
      '${_settings.baseUrl.replaceAll(RegExp(r'/+$'), '')}/audio/transcriptions',
    );
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer ${_settings.apiKey}'
      ..fields['model'] = 'whisper-1'
      ..files.add(await http.MultipartFile.fromPath('file', audioPath));

    final streamedResponse = await _client.send(request);
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode >= 200 && response.statusCode < 300) {
      final json = jsonDecode(response.body);
      return json['text'] as String? ?? '';
    } else {
      throw Exception(
        'Transcription failed (${response.statusCode}): ${response.body}',
      );
    }
  }

  /// Process text into structured knowledge: title, summary, key facts, questions, tags
  Future<AIStructuredOutput> structureKnowledge(String text) async {
    if (!isConfigured) {
      throw Exception(
        'AI API key is not configured. Please add it in Settings.',
      );
    }

    final uri = Uri.parse(
      '${_settings.baseUrl.replaceAll(RegExp(r'/+$'), '')}/chat/completions',
    );

    final systemPrompt = '''
You are an expert research knowledge assistant.
Analyze the provided thought/note and return a JSON object with this exact schema:
{
  "title": "A concise, descriptive title (maximum 6 words)",
  "summary": "A 1-2 sentence core insight or summary",
  "keyFacts": ["Bullet point fact 1", "Bullet point fact 2"],
  "openQuestions": ["Open research question 1"],
  "tags": ["tag1", "tag2"]
}
Do NOT include markdown formatting or backticks. Return valid JSON only.
''';

    final body = jsonEncode({
      'model': _settings.model,
      'messages': [
        {'role': 'system', 'content': systemPrompt},
        {'role': 'user', 'content': text},
      ],
      'temperature': 0.3,
    });

    final response = await _client.post(
      uri,
      headers: {
        'Authorization': 'Bearer ${_settings.apiKey}',
        'Content-Type': 'application/json',
      },
      body: body,
    );

    if (response.statusCode >= 200 && response.statusCode < 300) {
      final json = jsonDecode(utf8.decode(response.bodyBytes));
      final content = json['choices'][0]['message']['content'] as String;

      // Clean potential code fences
      String cleanJson = content.trim();
      if (cleanJson.startsWith('```json')) {
        cleanJson = cleanJson.substring(7);
      }
      if (cleanJson.startsWith('```')) {
        cleanJson = cleanJson.substring(3);
      }
      if (cleanJson.endsWith('```')) {
        cleanJson = cleanJson.substring(0, cleanJson.length - 3);
      }
      cleanJson = cleanJson.trim();

      final parsed = jsonDecode(cleanJson);
      return AIStructuredOutput(
        title: parsed['title'] as String? ?? 'Untitled Thought',
        summary: parsed['summary'] as String? ?? '',
        keyFacts:
            (parsed['keyFacts'] as List?)?.map((e) => e.toString()).toList() ??
            [],
        openQuestions:
            (parsed['openQuestions'] as List?)
                ?.map((e) => e.toString())
                .toList() ??
            [],
        tags:
            (parsed['tags'] as List?)?.map((e) => e.toString()).toList() ?? [],
      );
    } else {
      throw Exception(
        'Structuring failed (${response.statusCode}): ${response.body}',
      );
    }
  }
}
