import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._init();

  Database? _database;
  final Future<String> Function()? _directoryOverride;

  DatabaseHelper._init() : _directoryOverride = null;

  /// Allows migration tests to run against a temporary directory instead of
  /// the user's real application documents directory.
  @visibleForTesting
  DatabaseHelper.forTesting(Future<String> Function() directoryProvider)
    : _directoryOverride = directoryProvider;

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('echo_notes.db');
    return _database!;
  }

  Future<String> _resolveDirectory() async {
    if (_directoryOverride != null) return _directoryOverride();
    return (await getApplicationDocumentsDirectory()).path;
  }

  Future<Database> _initDB(String filePath) async {
    final directory = await _resolveDirectory();
    final path = join(directory, filePath);

    return await openDatabase(
      path,
      version: 3,
      onCreate: _createDB,
      onUpgrade: _upgradeDB,
    );
  }

  Future<void> _upgradeDB(Database db, int oldVersion, int newVersion) async {
    if (oldVersion < 3) {
      await db.execute(
        'ALTER TABLE notes ADD COLUMN retryCount INTEGER NOT NULL DEFAULT 0',
      );
    }
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
        retryCount INTEGER NOT NULL DEFAULT 0,
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
