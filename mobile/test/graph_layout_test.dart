import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/ui/screens/library/widgets/graph_layout_engine.dart';

void main() {
  test('DeterministicGraphLayout computes valid positions with zero overlaps', () {
    final nodes = [
      GraphNodeModel(id: 'node-1', title: 'Idea 1', kind: 'capture', x: 0, y: 0),
      GraphNodeModel(id: 'node-2', title: 'Idea 2', kind: 'idea', x: 0, y: 0),
      GraphNodeModel(id: 'node-3', title: 'Idea 3', kind: 'idea', x: 0, y: 0),
      GraphNodeModel(id: 'node-4', title: 'Isolated Node', kind: 'capture', x: 0, y: 0),
    ];

    final edges = [
      GraphEdgeModel(id: 'e1', fromNode: 'node-1', toNode: 'node-2', type: 'Supports', status: 'confirmed'),
      GraphEdgeModel(id: 'e2', fromNode: 'node-2', toNode: 'node-3', type: 'Related to', status: 'suggested'),
    ];

    final layout = DeterministicGraphLayout.computeLayout(nodes: nodes, edges: edges);

    expect(layout.length, 4);
    expect(layout.containsKey('node-1'), isTrue);
    expect(layout.containsKey('node-2'), isTrue);
    expect(layout.containsKey('node-3'), isTrue);
    expect(layout.containsKey('node-4'), isTrue);

    // Verify determinism: running again yields exact same coordinates
    final layout2 = DeterministicGraphLayout.computeLayout(nodes: nodes, edges: edges);
    for (final id in layout.keys) {
      expect(layout[id]!.position.dx, equals(layout2[id]!.position.dx));
      expect(layout[id]!.position.dy, equals(layout2[id]!.position.dy));
    }

    // Verify no two node bounding boxes intersect
    final positionedNodes = layout.values.toList();
    for (int i = 0; i < positionedNodes.length; i++) {
      for (int j = i + 1; j < positionedNodes.length; j++) {
        final rectA = positionedNodes[i].rect;
        final rectB = positionedNodes[j].rect;
        expect(rectA.overlaps(rectB), isFalse,
            reason: 'Nodes ${positionedNodes[i].model.id} and ${positionedNodes[j].model.id} overlap');
      }
    }
  });
}
