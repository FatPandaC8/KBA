import 'dart:convert';

enum ProcessingStatus {
  rawOnly,
  queued,
  uploading,
  pending,
  transcribing,
  structuring,
  ready,
  failed,
}

class Note {
  final String id;
  final String? audioPath;
  final int? audioDurationMs;
  final String originalContent;
  final String? transcript;
  final String title;
  final String? summary;
  final List<String> keyFacts;
  final List<String> openQuestions;
  final List<String> tags;
  final ProcessingStatus status;
  final String? failureReason;
  final DateTime createdAt;
  final DateTime updatedAt;

  Note({
    required this.id,
    this.audioPath,
    this.audioDurationMs,
    required this.originalContent,
    this.transcript,
    required this.title,
    this.summary,
    this.keyFacts = const [],
    this.openQuestions = const [],
    this.tags = const [],
    this.status = ProcessingStatus.rawOnly,
    this.failureReason,
    required this.createdAt,
    required this.updatedAt,
  });

  Note copyWith({
    String? id,
    String? audioPath,
    int? audioDurationMs,
    String? originalContent,
    String? transcript,
    String? title,
    String? summary,
    List<String>? keyFacts,
    List<String>? openQuestions,
    List<String>? tags,
    ProcessingStatus? status,
    String? failureReason,
    DateTime? createdAt,
    DateTime? updatedAt,
  }) {
    return Note(
      id: id ?? this.id,
      audioPath: audioPath ?? this.audioPath,
      audioDurationMs: audioDurationMs ?? this.audioDurationMs,
      originalContent: originalContent ?? this.originalContent,
      transcript: transcript ?? this.transcript,
      title: title ?? this.title,
      summary: summary ?? this.summary,
      keyFacts: keyFacts ?? this.keyFacts,
      openQuestions: openQuestions ?? this.openQuestions,
      tags: tags ?? this.tags,
      status: status ?? this.status,
      failureReason: failureReason ?? this.failureReason,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'audioPath': audioPath,
      'audioDurationMs': audioDurationMs,
      'originalContent': originalContent,
      'transcript': transcript,
      'title': title,
      'summary': summary,
      'keyFacts': jsonEncode(keyFacts),
      'openQuestions': jsonEncode(openQuestions),
      'tags': jsonEncode(tags),
      'status': status.name,
      'failureReason': failureReason,
      'createdAt': createdAt.toIso8601String(),
      'updatedAt': updatedAt.toIso8601String(),
    };
  }

  factory Note.fromMap(Map<String, dynamic> map) {
    List<String> parseList(dynamic val) {
      if (val == null) return [];
      if (val is List) return val.map((e) => e.toString()).toList();
      try {
        final decoded = jsonDecode(val.toString());
        if (decoded is List) {
          return decoded.map((e) => e.toString()).toList();
        }
      } catch (_) {}
      return [];
    }

    return Note(
      id: map['id'] as String,
      audioPath: map['audioPath'] as String?,
      audioDurationMs: map['audioDurationMs'] as int?,
      originalContent: (map['originalContent'] as String?) ?? '',
      transcript: map['transcript'] as String?,
      title: (map['title'] as String?) ?? 'Untitled Note',
      summary: map['summary'] as String?,
      keyFacts: parseList(map['keyFacts']),
      openQuestions: parseList(map['openQuestions']),
      tags: parseList(map['tags']),
      status: ProcessingStatus.values.firstWhere(
        (e) => e.name == map['status'],
        orElse: () => ProcessingStatus.rawOnly,
      ),
      failureReason: map['failureReason'] as String?,
      createdAt:
          DateTime.tryParse(map['createdAt'] as String? ?? '') ??
          DateTime.now(),
      updatedAt:
          DateTime.tryParse(map['updatedAt'] as String? ?? '') ??
          DateTime.now(),
    );
  }
}
