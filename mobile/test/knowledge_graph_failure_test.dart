import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/library/library_screen.dart';

import 'support/fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late SettingsService settings;
  late FakeNoteRepository repo;
  late FakeBackendService backend;
  late NoteProvider provider;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    settings = SettingsService(prefs);
    repo = FakeNoteRepository();
    backend = FakeBackendService(settings);
    provider = NoteProvider(repo, backend, settings);
    await provider.loadNotes();
  });

  Widget wrap() => MaterialApp(home: LibraryScreen(noteProvider: provider));

  testWidgets('graph load failure is visible and retryable', (tester) async {
    backend.failGraph = true;
    await tester.pumpWidget(wrap());
    await tester.pumpAndSettle();

    expect(find.text('Your graph could not be loaded.'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);

    backend.failGraph = false;
    backend.graphData = GraphDataModel(
      nodes: const [],
      edges: const [],
      clusters: const [],
    );
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();

    expect(find.text('Your graph could not be loaded.'), findsNothing);
    expect(find.text('No knowledge yet'), findsOneWidget);
  });

  testWidgets('graph canvas renders backend entities', (tester) async {
    backend.graphData = GraphDataModel(
      nodes: [
        GraphNodeModel(
          id: 'e1',
          title: 'Roadmap',
          kind: 'project',
          x: 500,
          y: 500,
          certainty: 'confirmed',
        ),
        GraphNodeModel(
          id: 'e2',
          title: 'Echo',
          kind: 'project',
          x: 620,
          y: 520,
          certainty: 'uncertain',
        ),
      ],
      edges: [
        GraphEdgeModel(
          id: 'r1',
          fromNode: 'e1',
          toNode: 'e2',
          type: 'Depends on',
          status: 'suggested',
          certainty: 'conflicting',
        ),
      ],
      clusters: [
        GraphClusterModel(
          id: 'type:project',
          label: 'Projects',
          x: 560,
          y: 510,
          size: 2,
        ),
      ],
    );

    await tester.pumpWidget(wrap());
    await tester.pumpAndSettle();

    expect(find.text('Roadmap'), findsOneWidget);
    // Uncertainty is encoded in the label, not colour alone (KG-06).
    expect(find.text('? Echo'), findsOneWidget);
    expect(find.text('Confirmed'), findsOneWidget);
    expect(find.text('Uncertain'), findsOneWidget);
    expect(find.text('Conflicting'), findsOneWidget);
  });

  testWidgets('tapping a node opens the entity detail panel', (tester) async {
    backend.graphData = GraphDataModel(
      nodes: [
        GraphNodeModel(
          id: 'e1',
          title: 'Roadmap',
          kind: 'project',
          x: 500,
          y: 500,
        ),
      ],
      edges: const [],
      clusters: const [],
    );
    backend.entityDetails['e1'] = EntityDetailModel(
      entity: EntityModel(
        id: 'e1',
        name: 'Roadmap',
        entityType: 'project',
        description: 'Quarterly plan',
        confidence: 0.9,
        certainty: 'confirmed',
        provenance: 'voice-capture',
        createdAt: '2026-01-01T00:00:00Z',
      ),
      relationships: const [],
    );

    await tester.pumpWidget(wrap());
    await tester.pumpAndSettle();

    await tester.tap(find.text('Roadmap'));
    await tester.pumpAndSettle();

    expect(find.text('Quarterly plan'), findsOneWidget);
    expect(find.text('Edit'), findsOneWidget);
    expect(find.text('RELATIONSHIPS · 0'), findsOneWidget);
  });
}
