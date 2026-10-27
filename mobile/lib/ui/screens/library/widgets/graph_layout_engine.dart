import 'dart:math';

import 'package:flutter/material.dart';
import 'package:mobile/services/backend_service.dart';

class PositionedNode {
  final GraphNodeModel model;
  final Offset position;
  final double width;
  final double height;
  final int componentIndex;

  PositionedNode({
    required this.model,
    required this.position,
    required this.width,
    required this.height,
    required this.componentIndex,
  });

  Rect get rect => Rect.fromLTWH(position.dx, position.dy, width, height);
  Offset get center =>
      Offset(position.dx + width / 2, position.dy + height / 2);
}

class DeterministicGraphLayout {
  static const double nodeWidth = 96.0;
  static const double nodeHeight = 52.0;
  static const double minNodePadding = 24.0;

  /// Calculates deterministic, aesthetic non-overlapping coordinates for all nodes.
  static Map<String, PositionedNode> computeLayout({
    required List<GraphNodeModel> nodes,
    required List<GraphEdgeModel> edges,
  }) {
    if (nodes.isEmpty) return {};

    // 1. Build adjacency list
    final Map<String, Set<String>> adj = {};
    for (final node in nodes) {
      adj[node.id] = <String>{};
    }
    final nodeIds = adj.keys.toSet();

    for (final edge in edges) {
      if (nodeIds.contains(edge.fromNode) && nodeIds.contains(edge.toNode)) {
        adj[edge.fromNode]!.add(edge.toNode);
        adj[edge.toNode]!.add(edge.fromNode);
      }
    }

    // 2. Partition into connected components (Breadth-First Search)
    final visited = <String>{};
    final components = <List<String>>[];

    // Sort nodes deterministically by ID so layout is invariant
    final sortedNodes = List<GraphNodeModel>.from(nodes)
      ..sort((a, b) => a.id.compareTo(b.id));

    for (final node in sortedNodes) {
      if (!visited.contains(node.id)) {
        final comp = <String>[];
        final queue = <String>[node.id];
        visited.add(node.id);

        while (queue.isNotEmpty) {
          final curr = queue.removeAt(0);
          comp.add(curr);

          final neighbors = adj[curr] ?? {};
          final sortedNeighbors = neighbors.toList()..sort();
          for (final nbr in sortedNeighbors) {
            if (!visited.contains(nbr)) {
              visited.add(nbr);
              queue.add(nbr);
            }
          }
        }
        components.add(comp);
      }
    }

    // Sort components: largest connected components first
    components.sort((a, b) => b.length.compareTo(a.length));

    final Map<String, PositionedNode> resultMap = {};
    final nodeModelMap = {for (final n in nodes) n.id: n};

    // 3. Layout each component in a distinct cluster grid
    // We space components across horizontal or vertical bands
    double currentClusterY = 30.0;

    for (int compIdx = 0; compIdx < components.length; compIdx++) {
      final compNodeIds = components[compIdx];

      if (compNodeIds.length == 1) {
        // Single isolated node
        final id = compNodeIds.first;
        final model = nodeModelMap[id]!;
        resultMap[id] = PositionedNode(
          model: model,
          position: Offset(130.0, currentClusterY),
          width: nodeWidth,
          height: nodeHeight,
          componentIndex: compIdx,
        );
        currentClusterY += nodeHeight + 40.0;
        continue;
      }

      if (compNodeIds.length == 2) {
        // Pair: place side by side
        final id1 = compNodeIds[0];
        final id2 = compNodeIds[1];
        resultMap[id1] = PositionedNode(
          model: nodeModelMap[id1]!,
          position: Offset(40.0, currentClusterY),
          width: nodeWidth,
          height: nodeHeight,
          componentIndex: compIdx,
        );
        resultMap[id2] = PositionedNode(
          model: nodeModelMap[id2]!,
          position: Offset(200.0, currentClusterY),
          width: nodeWidth,
          height: nodeHeight,
          componentIndex: compIdx,
        );
        currentClusterY += nodeHeight + 48.0;
        continue;
      }

      // For larger components: Seeded Circular / Force-directed layout
      final count = compNodeIds.length;
      final radius = max(110.0, count * 36.0);
      final center = Offset(170.0, currentClusterY + radius);

      // Distribute nodes in a deterministic circle initially
      final Map<String, Offset> positions = {};
      for (int i = 0; i < count; i++) {
        final angle = (2 * pi * i / count) - (pi / 2);
        positions[compNodeIds[i]] = Offset(
          center.dx + radius * cos(angle) - (nodeWidth / 2),
          center.dy + radius * sin(angle) - (nodeHeight / 2),
        );
      }

      // 4. Force-directed relaxation step (50 iterations) to minimize edge crossings & node overlaps
      for (int step = 0; step < 40; step++) {
        final Map<String, Offset> forces = {
          for (final id in compNodeIds) id: Offset.zero,
        };

        // Repulsion between all nodes in component
        for (int i = 0; i < count; i++) {
          final idA = compNodeIds[i];
          final posA = positions[idA]!;

          for (int j = i + 1; j < count; j++) {
            final idB = compNodeIds[j];
            final posB = positions[idB]!;

            final dx = posA.dx - posB.dx;
            final dy = posA.dy - posB.dy;
            final distSq = dx * dx + dy * dy;
            final dist = max(sqrt(distSq), 1.0);

            // Strong repulsive force if too close
            final repulse = 18000.0 / (distSq + 200.0);
            final fx = (dx / dist) * repulse;
            final fy = (dy / dist) * repulse;

            forces[idA] = forces[idA]! + Offset(fx, fy);
            forces[idB] = forces[idB]! - Offset(fx, fy);
          }
        }

        // Attraction along connected edges
        for (final idA in compNodeIds) {
          final nbrs = adj[idA] ?? {};
          final posA = positions[idA]!;

          for (final idB in nbrs) {
            if (!compNodeIds.contains(idB)) continue;
            final posB = positions[idB]!;

            final dx = posB.dx - posA.dx;
            final dy = posB.dy - posA.dy;
            final dist = max(sqrt(dx * dx + dy * dy), 1.0);

            // Hooke's spring attraction toward ideal distance (130px)
            final idealDist = 130.0;
            final attract = 0.04 * (dist - idealDist);
            final fx = (dx / dist) * attract;
            final fy = (dy / dist) * attract;

            forces[idA] = forces[idA]! + Offset(fx, fy);
          }
        }

        // Apply forces with damping
        final temp = 0.85;
        for (final id in compNodeIds) {
          final f = forces[id]!;
          final clampedX = f.dx.clamp(-12.0, 12.0) * temp;
          final clampedY = f.dy.clamp(-12.0, 12.0) * temp;
          positions[id] = positions[id]! + Offset(clampedX, clampedY);
        }
      }

      // Add to result
      double maxComponentY = currentClusterY;
      for (final id in compNodeIds) {
        final pos = positions[id]!;
        maxComponentY = max(maxComponentY, pos.dy + nodeHeight);
        resultMap[id] = PositionedNode(
          model: nodeModelMap[id]!,
          position: pos,
          width: nodeWidth,
          height: nodeHeight,
          componentIndex: compIdx,
        );
      }

      currentClusterY = maxComponentY + 60.0;
    }

    return resultMap;
  }
}
