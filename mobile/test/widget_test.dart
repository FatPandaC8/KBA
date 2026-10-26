import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/models/note.dart';

void main() {
  test('Note model serialization and deserialization', () {
    final now = DateTime.now();
    final note = Note(
      id: 'test-uuid-123',
      originalContent: 'Vector search trade-offs',
      title: 'Vector Search',
      summary: 'ANN methods gain speed for slight recall loss.',
      keyFacts: ['Fast query', 'Memory footprint'],
      openQuestions: ['How to handle memory?'],
      tags: ['search', 'ai'],
      status: ProcessingStatus.ready,
      createdAt: now,
      updatedAt: now,
    );

    final map = note.toMap();
    expect(map['id'], 'test-uuid-123');
    expect(map['title'], 'Vector Search');
    expect(map['status'], 'ready');

    final reconstructed = Note.fromMap(map);
    expect(reconstructed.id, note.id);
    expect(reconstructed.title, note.title);
    expect(reconstructed.summary, note.summary);
    expect(reconstructed.keyFacts.length, 2);
    expect(reconstructed.tags, ['search', 'ai']);
    expect(reconstructed.status, ProcessingStatus.ready);
  });
}
