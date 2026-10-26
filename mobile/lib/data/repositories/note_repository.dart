import 'dart:io';

import '../datasources/database_helper.dart';
import '../models/note.dart';

class NoteRepository {
  final DatabaseHelper _dbHelper;

  NoteRepository({DatabaseHelper? dbHelper})
    : _dbHelper = dbHelper ?? DatabaseHelper.instance;

  Future<void> insertNote(Note note) async {
    final db = await _dbHelper.database;
    await db.insert('notes', note.toMap());
  }

  Future<void> updateNote(Note note) async {
    final db = await _dbHelper.database;
    await db.update(
      'notes',
      note.toMap(),
      where: 'id = ?',
      whereArgs: [note.id],
    );
  }

  Future<void> deleteNote(String id) async {
    final db = await _dbHelper.database;
    // Find audio file if exists to delete
    final maps = await db.query('notes', where: 'id = ?', whereArgs: [id]);
    if (maps.isNotEmpty) {
      final note = Note.fromMap(maps.first);
      if (note.audioPath != null && note.audioPath!.isNotEmpty) {
        try {
          final file = File(note.audioPath!);
          if (await file.exists()) {
            await file.delete();
          }
        } catch (_) {}
      }
    }

    await db.delete('notes', where: 'id = ?', whereArgs: [id]);
  }

  Future<Note?> getNoteById(String id) async {
    final db = await _dbHelper.database;
    final maps = await db.query('notes', where: 'id = ?', whereArgs: [id]);
    if (maps.isNotEmpty) {
      return Note.fromMap(maps.first);
    }
    return null;
  }

  Future<List<Note>> getAllNotes() async {
    final db = await _dbHelper.database;
    final maps = await db.query('notes', orderBy: 'createdAt DESC');
    return maps.map((m) => Note.fromMap(m)).toList();
  }

  Future<List<Note>> searchNotes(String query) async {
    if (query.trim().isEmpty) {
      return getAllNotes();
    }
    final db = await _dbHelper.database;

    // Sanitize query for FTS5 (escape special chars)
    final sanitized = query.replaceAll(RegExp(r'[^\w\s]'), '').trim();
    if (sanitized.isEmpty) {
      return [];
    }

    final likePattern = '%$query%';
    final results = await db.query(
      'notes',
      where: 'title LIKE ? OR originalContent LIKE ? OR transcript LIKE ? OR summary LIKE ?',
      whereArgs: [likePattern, likePattern, likePattern, likePattern],
      orderBy: 'createdAt DESC',
    );
    return results.map((m) => Note.fromMap(m)).toList();
  }
}
