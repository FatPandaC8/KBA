import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'package:mobile/data/datasources/database_helper.dart';

const _v2Schema = '''
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
''';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tempDir;

  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('echo_migration_');
  });

  tearDown(() async {
    if (await tempDir.exists()) {
      await tempDir.delete(recursive: true);
    }
  });

  test(
    'v2 → v5 migration preserves existing notes and adds M3/U3 columns',
    () async {
      final dbPath = p.join(tempDir.path, 'echo_notes.db');
      final legacy = await databaseFactory.openDatabase(
        dbPath,
        options: OpenDatabaseOptions(
          version: 2,
          onCreate: (db, version) async {
            await db.execute(_v2Schema);
            await db.execute('CREATE INDEX idx_notes_title ON notes(title)');
            await db.execute(
              'CREATE INDEX idx_notes_created ON notes(createdAt)',
            );
          },
        ),
      );

      await legacy.insert('notes', {
        'id': 'existing-note',
        'audioPath': '/tmp/audio.m4a',
        'audioDurationMs': 1200,
        'originalContent': 'User content that must survive',
        'transcript': 'spoken words',
        'title': 'Existing note',
        'summary': 'Existing summary',
        'keyFacts': '["fact"]',
        'openQuestions': '[]',
        'tags': '["tag"]',
        'status': 'ready',
        'failureReason': null,
        'createdAt': '2026-01-01T00:00:00.000Z',
        'updatedAt': '2026-01-01T00:00:00.000Z',
      });
      await legacy.close();

      final helper = DatabaseHelper.forTesting(() async => tempDir.path);
      final db = await helper.database;

      final rows = await db.query('notes');
      expect(rows, hasLength(1));
      final row = rows.single;
      expect(row['id'], 'existing-note');
      expect(row['title'], 'Existing note');
      expect(row['originalContent'], 'User content that must survive');
      expect(row['transcript'], 'spoken words');
      expect(row['status'], 'ready');
      expect(row['retryCount'], 0);
      // M3 columns are additive and must not disturb legacy rows.
      expect(row['errorClass'], isNull);
      expect(row['stage'], '');
      expect(row['audioOnServer'], 0);
      expect(row['knowledgeItemId'], isNull);
      // U3 local-wins flags default to unedited for migrated notes.
      expect(row['userEditedTitle'], 0);
      expect(row['userEditedSummary'], 0);

      await helper.close();
    },
  );

  test('fresh database creates the v5 schema', () async {
    final helper = DatabaseHelper.forTesting(() async => tempDir.path);
    final db = await helper.database;
    final columns = await db.rawQuery('PRAGMA table_info(notes)');
    final names = columns.map((c) => c['name']).toSet();
    expect(names, contains('retryCount'));
    expect(names, contains('failureReason'));
    expect(names, contains('errorClass'));
    expect(names, contains('stage'));
    expect(names, contains('audioOnServer'));
    expect(names, contains('knowledgeItemId'));
    // U3 local-wins flags exist in the fresh schema.
    expect(names, contains('userEditedTitle'));
    expect(names, contains('userEditedSummary'));

    await db.insert('notes', {
      'id': 'new-note',
      'originalContent': 'hello',
      'title': 'Hello',
      'status': 'rawOnly',
      'createdAt': '2026-01-01T00:00:00.000Z',
      'updatedAt': '2026-01-01T00:00:00.000Z',
    });
    final row = (await db.query('notes')).single;
    expect(row['retryCount'], 0);
    expect(row['errorClass'], isNull);
    expect(row['stage'], '');
    expect(row['audioOnServer'], 0);
    expect(row['knowledgeItemId'], isNull);
    expect(row['userEditedTitle'], 0);
    expect(row['userEditedSummary'], 0);

    await helper.close();
  });
}
