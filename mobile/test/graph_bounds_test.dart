import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/ui/screens/library/widgets/graph_layout_engine.dart';

void main() {
  test('wrapping every node stays inside computed bounds', () {
    final nodes = List.generate(
      12,
      (i) => GraphNodeModel(
        id: 'node-$i',
        title: 'Idea $i',
        kind: i.isEven ? 'capture' : 'idea',
        x: 0,
        y: 0,
      ),
    );
    final edges = List.generate(
      10,
      (i) => GraphEdgeModel(
        id: 'edge-$i',
        fromNode: 'node-$i',
        toNode: 'node-${i + 1}',
        type: 'Related to',
        status: 'suggested',
      ),
    );

    final layout = DeterministicGraphLayout.computeLayout(
      nodes: nodes,
      edges: edges,
    );
    final bounds = DeterministicGraphLayout.computeBounds(layout);

    expect(bounds.width, greaterThan(0));
    expect(bounds.height, greaterThan(0));
    for (final node in layout.values) {
      expect(
        bounds.contains(node.rect.topLeft) &&
            bounds.contains(node.rect.bottomRight),
        isTrue,
        reason: '${node.model.id} is outside the computed graph bounds',
      );
    }
  });

  test('empty layout returns a non-degenerate bounds rectangle', () {
    final bounds = DeterministicGraphLayout.computeBounds({});
    expect(bounds.width, greaterThan(0));
    expect(bounds.height, greaterThan(0));
  });
}
