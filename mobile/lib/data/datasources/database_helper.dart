import 'dart:async';

import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._init();
  static Database? _database;

  DatabaseHelper._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('echo_notes.db');
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    final docsDir = await getApplicationDocumentsDirectory();
    final path = join(docsDir.path, filePath);

    return await openDatabase(
      path,
      version: 2,
      onCreate: _createDB,
      onUpgrade: (db, oldVersion, newVersion) async {
        await db.execute('DROP TABLE IF EXISTS notes_fts');
        await db.execute('DROP TABLE IF EXISTS notes');
        await _createDB(db, newVersion);
      },
    );
  }

  Future<void> _createDB(Database db, int version) async {
    await db.execute('''
      CREATE TABLE notes (
        id TEXT PRIMARY KEY,
        audioPath TEXT,
        audioDurationMs INTEGER,
        originalContent TEXT NOT NULL,
        transcript TEXT,
        title TEXT NOT NULL,
        summary TEXT,
        keyFacts TEXT,
        openQuestions TEXT,
        tags TEXT,
        status TEXT NOT NULL,
        failureReason TEXT,
        createdAt TEXT NOT NULL,
        updatedAt TEXT NOT NULL
      )
    ''');

    // Create indexes for fast keyword search across key fields
    await db.execute('CREATE INDEX idx_notes_title ON notes(title)');
    await db.execute('CREATE INDEX idx_notes_created ON notes(createdAt)');
  }

  Future<void> close() async {
    final db = _database;
    if (db != null) {
      await db.close();
      _database = null;
    }
  }
}
