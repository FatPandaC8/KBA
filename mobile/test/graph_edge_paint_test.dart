import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';

import 'package:mobile/services/backend_service.dart';
import 'package:mobile/ui/screens/library/widgets/knowledge_graph_widget.dart';

GraphDataModel _smallGraph() {
  GraphNodeModel n(String id, String title, double x, double y) =>
      GraphNodeModel(id: id, title: title, kind: 'concept', x: x, y: y);
  GraphEdgeModel e(String id, String from, String to, String type) =>
      GraphEdgeModel(
        id: id,
        fromNode: from,
        toNode: to,
        type: type,
        status: 'suggested',
      );
  return GraphDataModel(
    nodes: [
      n('me', 'Me', 200, 200),
      n('anna', 'Anna', 500, 200),
      n('echo', 'Echo', 350, 430),
    ],
    clusters: const [],
    edges: [
      e('e1', 'me', 'anna', 'Met'),
      e('e2', 'me', 'echo', 'Related to'),
      e('e3', 'anna', 'echo', 'Supports'),
      // A dangling edge: the API guarantee is that this never happens, but
      // the painter must degrade instead of painting a stray line.
      e('e-ghost', 'me', 'ghost-id', 'Broken'),
    ],
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('paintGraphEdges draws every resolvable edge of a known graph', () {
    final graph = _smallGraph();
    final centers = {
      for (final node in graph.nodes) node.id: Offset(node.x, node.y),
    };

    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    final drawn = paintGraphEdges(
      canvas,
      centers: centers,
      origin: Offset.zero,
      edges: graph.edges,
    );
    recorder.endRecording();

    expect(drawn, 3, reason: 'the three resolvable edges must paint; the '
        'dangling edge must be skipped, not painted as a stray line');
  });

  test('paintGraphEdges returns zero for an empty edge list', () {
    final recorder = ui.PictureRecorder();
    final canvas = ui.Canvas(recorder);
    final drawn = paintGraphEdges(
      canvas,
      centers: const {'me': Offset(0, 0)},
      origin: Offset.zero,
      edges: const [],
    );
    recorder.endRecording();
    expect(drawn, 0);
  });
}
