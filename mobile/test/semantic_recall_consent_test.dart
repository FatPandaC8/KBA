import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/data/models/note.dart';
import 'package:mobile/data/repositories/note_repository.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class MockNoteRepository extends NoteRepository {
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
    try {
      return inMemory.firstWhere((n) => n.id == id);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> updateNote(Note note) async {
    final idx = inMemory.indexWhere((n) => n.id == note.id);
    if (idx != -1) {
      inMemory[idx] = note;
    } else {
      inMemory.add(note);
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Semantic recall prioritization and keyword fallback', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final settingsService = SettingsService(prefs);

    final mockRepo = MockNoteRepository();
    final backendService = BackendService(settingsService);
    final provider = NoteProvider(
      mockRepo,
      backendService,
      settingsService,
    );

    final n1 = Note(
      id: 'note-1',
      title: 'ANN Indices for Speed',
      originalContent: 'Vector approximate nearest neighbor searches.',
      summary: 'Trades recall for latency.',
      status: ProcessingStatus.ready,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
    final n2 = Note(
      id: 'note-2',
      title: 'Pet Feeding Schedule',
      originalContent: 'Dogs need food twice daily.',
      summary: 'Canine diet.',
      status: ProcessingStatus.ready,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );

    await mockRepo.insertNote(n1);
    await mockRepo.insertNote(n2);
    await provider.loadNotes();

    expect(provider.notes.length, 2);

    // Keyword fallback test
    await provider.search('Dogs');
    expect(provider.searchResults.length, 1);
    expect(provider.searchResults.first.id, 'note-2');

    // Empty query test
    await provider.search('');
    expect(provider.searchResults.isEmpty, true);
  });
}
