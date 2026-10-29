import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/screens/library/library_screen.dart';
import 'package:mobile/ui/screens/recall/recall_screen.dart';

import 'support/fakes.dart';

/// Ask AI and graph-search behaviour (QA-01, QA-04, QA-05, D13, SRCH-01..03).
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

  Widget recallScreen() => MaterialApp(
    home: RecallScreen(noteProvider: provider, onOpenDetail: (_) {}),
  );

  Widget graphScreen() =>
      MaterialApp(home: LibraryScreen(noteProvider: provider));

  AskResultModel answer({
    required String content,
    List<CitationModel> citations = const [],
    bool refused = false,
    String status = 'ready',
    String errorClass = '',
  }) {
    return AskResultModel(
      conversationId: 'conversation-1',
      message: AskMessageModel(
        id: 'assistant-1',
        role: 'assistant',
        content: content,
        status: status,
        errorClass: errorClass,
        errorMessage: '',
        createdAt: '2026-10-29T10:00:00Z',
        citations: citations,
      ),
      facts: const [],
      inferences: const [],
      contradictions: const [],
      refused: refused,
      refusalReason: refused ? 'insufficient_evidence' : '',
    );
  }

  testWidgets('source chips are display-only and never navigable (D13, QA-04)',
      (tester) async {
    backend.askHandler = (question, conversationId) => answer(
      content: 'You planned to ship the MVP in the third quarter.',
      citations: [
        CitationModel(
          id: 'citation-1',
          kind: 'entity',
          targetId: 'entity-1',
          name: 'Quarterly plan',
          deleted: false,
        ),
        CitationModel(
          id: 'citation-2',
          kind: 'entity',
          targetId: 'entity-2',
          name: 'Old roadmap',
          deleted: true,
        ),
      ],
    );

    await tester.pumpWidget(recallScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'When will we ship?');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();

    expect(
      find.text('You planned to ship the MVP in the third quarter.'),
      findsOneWidget,
    );
    expect(find.text('Quarterly plan'), findsOneWidget);
    // Deleted sources stay visible but are marked as removed (QA-04).
    expect(find.text('Old roadmap (deleted)'), findsOneWidget);

    // A citation is a label, not a control: no tap target wraps it.
    expect(
      find.ancestor(
        of: find.text('Quarterly plan'),
        matching: find.byType(InkWell),
      ),
      findsNothing,
    );
    expect(
      find.ancestor(
        of: find.text('Quarterly plan'),
        matching: find.byType(GestureDetector),
      ),
      findsNothing,
    );

    // Tapping it does nothing at all — no sheet, no route change.
    await tester.tap(find.text('Quarterly plan'));
    await tester.pumpAndSettle();
    expect(find.text('Quarterly plan'), findsOneWidget);
    expect(find.byType(RecallScreen), findsOneWidget);
  });

  testWidgets('insufficient evidence is refused instead of invented (QA-02)',
      (tester) async {
    backend.askHandler = (question, conversationId) => answer(
      content:
          'I could not find enough in your knowledge to answer that. '
          'Try recording more about it.',
      refused: true,
    );

    await tester.pumpWidget(recallScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'What is my blood type?');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('could not find enough in your knowledge'),
      findsOneWidget,
    );
    // A refusal carries no fabricated sources.
    expect(find.text('Quarterly plan'), findsNothing);
    expect(provider.messages, hasLength(2));
    expect(provider.isAsking, isFalse);
  });

  testWidgets('provider failures surface a distinct state and never retry '
      'on a paid provider (QA-05, NET-01)', (tester) async {
    backend.askHandler = (question, conversationId) => answer(
      content: 'Free quota exhausted. Retry later.',
      status: 'failed',
      errorClass: 'quota_exhausted',
    );

    await tester.pumpWidget(recallScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'Summarise my week');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();

    expect(find.text('Free quota exhausted'), findsOneWidget);
    expect(find.text('Free quota exhausted. Retry later.'), findsOneWidget);

    // The question stays in the transcript so the user can send it again.
    expect(provider.messages.first.content, 'Summarise my week');
    expect(backend.askCalls, 1);
  });

  testWidgets('graph search is debounced and focuses the entity (SRCH-01/02)',
      (tester) async {
    backend.graphData = GraphDataModel(
      nodes: [
        GraphNodeModel(
          id: 'e1',
          title: 'Roadmap',
          kind: 'project',
          x: 500,
          y: 500,
        ),
        GraphNodeModel(
          id: 'e2',
          title: 'Echo',
          kind: 'project',
          x: 640,
          y: 520,
        ),
      ],
      edges: [
        GraphEdgeModel(
          id: 'r1',
          fromNode: 'e1',
          toNode: 'e2',
          type: 'Depends on',
          status: 'suggested',
          certainty: 'uncertain',
        ),
      ],
      clusters: const [],
    );
    backend.searchResult = GraphSearchResult(
      entities: [
        GraphSearchEntity(
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
          score: 0.92,
        ),
      ],
      relationships: const [],
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

    await tester.pumpWidget(graphScreen());
    await tester.pumpAndSettle();

    // Typing in bursts must produce one request, not one per keystroke.
    await tester.enterText(find.byType(TextField), 'r');
    await tester.pump(const Duration(milliseconds: 100));
    await tester.enterText(find.byType(TextField), 'road');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();

    expect(backend.searchCalls, 1);
    final result = find.widgetWithText(ListTile, 'Roadmap');
    expect(result, findsOneWidget);
    expect(find.text('project · Quarterly plan'), findsOneWidget);

    await tester.tap(result);
    await tester.pumpAndSettle();

    // The canvas focuses the node and opens its detail panel.
    expect(find.text('Quarterly plan'), findsWidgets);
    expect(find.text('RELATIONSHIPS · 0'), findsOneWidget);
  });

  testWidgets('searching a relationship opens the relationship panel (SRCH-03)',
      (tester) async {
    backend.graphData = GraphDataModel(
      nodes: [
        GraphNodeModel(
          id: 'e1',
          title: 'Roadmap',
          kind: 'project',
          x: 500,
          y: 500,
        ),
        GraphNodeModel(
          id: 'e2',
          title: 'Echo',
          kind: 'project',
          x: 640,
          y: 520,
        ),
      ],
      edges: [
        GraphEdgeModel(
          id: 'r1',
          fromNode: 'e1',
          toNode: 'e2',
          type: 'Depends on',
          status: 'suggested',
          certainty: 'uncertain',
        ),
      ],
      clusters: const [],
    );
    backend.searchResult = GraphSearchResult(
      entities: const [],
      relationships: [
        EntityRelationshipModel(
          id: 'r1',
          fromId: 'e1',
          toId: 'e2',
          fromName: '',
          toName: '',
          relationType: 'Depends on',
          status: 'suggested',
          certainty: 'uncertain',
        ),
      ],
    );

    await tester.pumpWidget(graphScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'depends');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();

    // Names are resolved from the canvas, not echoed from the server.
    final row = find.widgetWithText(ListTile, 'Roadmap → Echo');
    expect(row, findsOneWidget);
    await tester.tap(row);
    await tester.pumpAndSettle();

    expect(find.text('Depends on'), findsOneWidget);
    expect(find.text('suggested'), findsOneWidget);
    expect(find.text('Uncertain'), findsOneWidget);
    // The edge's endpoints are shown by name.
    expect(find.text('Roadmap'), findsWidgets);
    expect(find.text('Echo'), findsWidgets);
  });

  testWidgets('clearing the query removes results without a new request',
      (tester) async {
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
    backend.searchResult = GraphSearchResult(
      entities: [
        GraphSearchEntity(
          entity: EntityModel(
            id: 'e1',
            name: 'Roadmap',
            entityType: 'project',
            description: '',
            confidence: 0.9,
            certainty: 'confirmed',
            provenance: 'voice-capture',
            createdAt: '2026-01-01T00:00:00Z',
          ),
          score: 0.8,
        ),
      ],
      relationships: const [],
    );

    await tester.pumpWidget(graphScreen());
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'road');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(backend.searchCalls, 1);
    expect(find.byType(ListTile), findsOneWidget);

    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();

    expect(find.byType(ListTile), findsNothing);
    expect(backend.searchCalls, 1);
  });
}
