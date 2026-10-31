import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';

import 'graph_detail_sheets.dart';
import 'graph_layout_engine.dart';

/// Requests a focus change on the canvas. [sequence] makes repeated taps on the
/// same search result act again (SRCH-02).
class GraphFocusRequest {
  final String? entityId;
  final String? relationshipId;
  final int sequence;

  const GraphFocusRequest({
    this.entityId,
    this.relationshipId,
    required this.sequence,
  });

  bool get isEmpty => entityId == null && relationshipId == null;
}

/// Zoom/pan clustered canvas (KG-04, KG-05, KG-06) with level-of-detail
/// cluster collapsing when zoomed out.
///
/// Coordinates, communities and the cluster labels are produced by the backend;
/// the client only renders them. When a backend returns a degenerate layout
/// (every node on the same point) the deterministic local engine is used as a
/// fallback so a broken layout never produces an unusable canvas.
class KnowledgeGraphWidget extends StatefulWidget {
  final GraphDataModel graph;
  final BackendService backend;
  final GraphFocusRequest? focus;
  final Future<void> Function() onGraphMutated;

  const KnowledgeGraphWidget({
    super.key,
    required this.graph,
    required this.backend,
    required this.onGraphMutated,
    this.focus,
  });

  @override
  State<KnowledgeGraphWidget> createState() => _KnowledgeGraphWidgetState();
}

class _KnowledgeGraphWidgetState extends State<KnowledgeGraphWidget> {
  static const double _nodeWidth = 88;
  static const double _nodeHeight = 40;
  static const double _paintPadding = 70;
  static const double _collapsedAtScale = 0.55;

  final TransformationController _transform = TransformationController();

  Size _viewport = Size.zero;
  double _scale = 1;
  bool _fitted = false;
  Rect _bounds = const Rect.fromLTWH(0, 0, 1, 1);
  String? _selectedEntityId;
  String? _focusedEdgeId;
  bool _detailOpen = false;
  int _appliedFocusSequence = -1;

  bool get _collapsed => _scale < _collapsedAtScale;

  @override
  void initState() {
    super.initState();
    _transform.addListener(_onTransformChanged);
    _scheduleFocus();
  }

  @override
  void didUpdateWidget(KnowledgeGraphWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.graph, widget.graph)) {
      _fitted = false;
      if (_selectedEntityId != null &&
          !widget.graph.nodes.any((node) => node.id == _selectedEntityId)) {
        _selectedEntityId = null;
      }
      if (_focusedEdgeId != null &&
          !widget.graph.edges.any((edge) => edge.id == _focusedEdgeId)) {
        _focusedEdgeId = null;
      }
    }
    if (oldWidget.graph != widget.graph ||
        oldWidget.focus?.sequence != widget.focus?.sequence) {
      _scheduleFocus();
    }
  }

  @override
  void dispose() {
    _transform.removeListener(_onTransformChanged);
    _transform.dispose();
    super.dispose();
  }

  void _onTransformChanged() {
    final scale = _transform.value.getMaxScaleOnAxis();
    if ((scale - _scale).abs() < 0.01) return;
    setState(() => _scale = scale);
  }

  void _scheduleFocus() {
    final focus = widget.focus;
    if (focus == null || focus.isEmpty) return;
    if (focus.sequence == _appliedFocusSequence) return;
    _appliedFocusSequence = focus.sequence;
    WidgetsBinding.instance.addPostFrameCallback((_) => _applyFocus(focus));
  }

  Future<void> _applyFocus(GraphFocusRequest focus) async {
    if (!mounted || _viewport.isEmpty) return;
    final centers = _centersFor(widget.graph);
    final entityId = focus.entityId;
    if (entityId != null) {
      final center = centers[entityId];
      if (center != null) {
        _focusPoint(center);
      }
      await _openEntityDetail(entityId);
      return;
    }

    final relationshipId = focus.relationshipId;
    if (relationshipId == null) return;
    GraphEdgeModel? edge;
    for (final candidate in widget.graph.edges) {
      if (candidate.id == relationshipId) {
        edge = candidate;
        break;
      }
    }
    if (edge == null) return;
    final resolved = edge;
    setState(() => _focusedEdgeId = resolved.id);
    final from = centers[resolved.fromNode];
    final to = centers[resolved.toNode];
    if (from != null && to != null) {
      _focusPoint(Offset((from.dx + to.dx) / 2, (from.dy + to.dy) / 2));
    }
    await _openRelationshipDetail(resolved);
  }

  /// Centres the canvas on a point given in graph coordinates. The child of the
  /// [InteractiveViewer] is translated by `_bounds.topLeft`, so graph points
  /// must be converted into child space before building the matrix.
  void _focusPoint(Offset graphPoint) {
    if (_viewport.isEmpty) return;
    final target = _scale < 0.85 ? 0.9 : _scale;
    _transform.value = _matrixFor(graphPoint - _bounds.topLeft, target);
  }

  Matrix4 _matrixFor(Offset contentPoint, double scale) {
    final tx = _viewport.width / 2 - contentPoint.dx * scale;
    final ty = _viewport.height / 2 - contentPoint.dy * scale;
    return Matrix4.identity()
      ..setEntry(0, 0, scale)
      ..setEntry(1, 1, scale)
      ..setEntry(0, 3, tx)
      ..setEntry(1, 3, ty);
  }

  void _zoomBy(double factor) {
    if (_viewport.isEmpty) return;
    final current = _transform.value.getMaxScaleOnAxis();
    final target = (current * factor).clamp(0.04, 4.0);
    final tx = _transform.value.storage[12];
    final ty = _transform.value.storage[13];
    final cx = _viewport.width / 2;
    final cy = _viewport.height / 2;
    final contentX = (cx - tx) / current;
    final contentY = (cy - ty) / current;
    _transform.value = _matrixFor(Offset(contentX, contentY), target);
  }

  void _scheduleFit() {
    WidgetsBinding.instance.addPostFrameCallback((_) => _fitToView());
  }

  void _fitToView() {
    if (!mounted || _viewport.isEmpty) return;
    if (_bounds.width <= 0 || _bounds.height <= 0) return;
    final scale = math
        .min(_viewport.width / _bounds.width, _viewport.height / _bounds.height)
        .clamp(0.04, 1.4);
    // The child spans `_bounds.size` starting at the origin, so its centre is
    // half its size — not `_bounds.center` in graph coordinates.
    _transform.value = _matrixFor(_bounds.size.center(Offset.zero), scale);
  }

  Future<void> _openEntityDetail(String entityId) async {
    if (_detailOpen) return;
    _detailOpen = true;
    if (mounted) setState(() => _selectedEntityId = entityId);
    try {
      final detail = await widget.backend.fetchEntityDetail(entityId);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (_) => EntityDetailSheet(
          detail: detail,
          backend: widget.backend,
          onChanged: widget.onGraphMutated,
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('This entity could not be loaded. Try again.'),
          ),
        );
      }
    } finally {
      _detailOpen = false;
    }
  }

  Future<void> _openRelationshipDetail(GraphEdgeModel edge) async {
    if (_detailOpen) return;
    _detailOpen = true;
    final titles = {for (final node in widget.graph.nodes) node.id: node.title};
    final relationship = EntityRelationshipModel(
      id: edge.id,
      fromId: edge.fromNode,
      toId: edge.toNode,
      fromName: titles[edge.fromNode] ?? '',
      toName: titles[edge.toNode] ?? '',
      relationType: edge.type,
      status: edge.status,
      certainty: edge.certainty,
    );
    try {
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (_) => _RelationshipSheet(
          relationship: relationship,
          backend: widget.backend,
          onChanged: widget.onGraphMutated,
        ),
      );
    } finally {
      _detailOpen = false;
    }
  }

  /// Node centres in graph coordinates.
  Map<String, Offset> _centersFor(GraphDataModel graph) {
    if (graph.nodes.isEmpty) return const {};
    final distinct = graph.nodes
        .map((node) => '${node.x},${node.y}')
        .toSet()
        .length;
    if (graph.nodes.length > 1 && distinct == 1) {
      final layout = DeterministicGraphLayout.computeLayout(
        nodes: graph.nodes,
        edges: _validEdges(graph),
      );
      return {
        for (final entry in layout.entries) entry.key: entry.value.center,
      };
    }
    return {for (final node in graph.nodes) node.id: Offset(node.x, node.y)};
  }

  List<GraphEdgeModel> _validEdges(GraphDataModel graph) {
    final ids = graph.nodes.map((node) => node.id).toSet();
    return graph.edges
        .where(
          (edge) => ids.contains(edge.fromNode) && ids.contains(edge.toNode),
        )
        .toList();
  }

  Rect _boundsFor(Map<String, Offset> centers, GraphDataModel graph) {
    if (centers.isEmpty) return const Rect.fromLTWH(0, 0, 1, 1);
    var minX = double.infinity;
    var minY = double.infinity;
    var maxX = -double.infinity;
    var maxY = -double.infinity;
    for (final center in centers.values) {
      minX = math.min(minX, center.dx - _nodeWidth / 2);
      minY = math.min(minY, center.dy - _nodeHeight / 2);
      maxX = math.max(maxX, center.dx + _nodeWidth / 2);
      maxY = math.max(maxY, center.dy + _nodeHeight / 2);
    }
    for (final cluster in graph.clusters) {
      minX = math.min(minX, cluster.x - 40);
      minY = math.min(minY, cluster.y - 24);
      maxX = math.max(maxX, cluster.x + 40);
      maxY = math.max(maxY, cluster.y + 24);
    }
    return Rect.fromLTRB(minX, minY, maxX, maxY).inflate(_paintPadding);
  }

  @override
  Widget build(BuildContext context) {
    final graph = widget.graph;
    if (graph.nodes.isEmpty) {
      return _EmptyGraph();
    }

    final centers = _centersFor(graph);
    _bounds = _boundsFor(centers, graph);
    final edges = _validEdges(graph);

    final neighbours = <String>{};
    if (_selectedEntityId != null) {
      for (final edge in edges) {
        if (edge.fromNode == _selectedEntityId) neighbours.add(edge.toNode);
        if (edge.toNode == _selectedEntityId) neighbours.add(edge.fromNode);
      }
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        _viewport = Size(constraints.maxWidth, constraints.maxHeight);
        if (!_fitted && !_viewport.isEmpty) {
          _fitted = true;
          _scheduleFit();
        }

        return Container(
          decoration: BoxDecoration(
            color: const Color(0xFFF1F3EE),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: EchoColors.border),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            children: [
              Positioned.fill(
                child: InteractiveViewer(
                  transformationController: _transform,
                  constrained: false,
                  minScale: 0.04,
                  maxScale: 4.0,
                  boundaryMargin: const EdgeInsets.all(900),
                  child: SizedBox(
                    width: _bounds.width,
                    height: _bounds.height,
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        if (!_collapsed)
                          Positioned.fill(
                            child: CustomPaint(
                              painter: _GraphEdgePainter(
                                centers: centers,
                                origin: _bounds.topLeft,
                                edges: edges,
                                selectedNodeId: _selectedEntityId,
                                focusedEdgeId: _focusedEdgeId,
                              ),
                            ),
                          ),
                        if (!_collapsed)
                          ...graph.nodes.map(
                            (node) => _nodeWidget(node, centers, neighbours),
                          ),
                        if (_collapsed)
                          ...graph.clusters.map(
                            (cluster) => _clusterWidget(cluster),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
              Positioned(top: 10, right: 10, child: _zoomControls()),
              Positioned(left: 10, bottom: 10, child: _legend()),
              if (_collapsed)
                Positioned(
                  left: 10,
                  right: 46,
                  top: 10,
                  child: IgnorePointer(
                    child: Text(
                      'Zoomed out · ${graph.clusters.length} clusters',
                      style: const TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                        color: EchoColors.muted,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _nodeWidget(
    GraphNodeModel node,
    Map<String, Offset> centers,
    Set<String> neighbours,
  ) {
    final center = centers[node.id];
    if (center == null) return const SizedBox.shrink();

    final isSelected = node.id == _selectedEntityId;
    final dimmed =
        _selectedEntityId != null &&
        !isSelected &&
        !neighbours.contains(node.id);
    final marker = switch (node.certainty) {
      'uncertain' => '? ',
      'conflicting' => '! ',
      _ => '',
    };
    final borderColor = switch (node.certainty) {
      'conflicting' => EchoColors.danger,
      'uncertain' => const Color(0xFF8A7A4A),
      _ => EchoColors.sage,
    };

    return Positioned(
      left: center.dx - _bounds.left - _nodeWidth / 2,
      top: center.dy - _bounds.top - _nodeHeight / 2,
      child: Opacity(
        opacity: dimmed ? 0.4 : 1,
        child: GestureDetector(
          onTap: () => _openEntityDetail(node.id),
          child: Container(
            width: _nodeWidth,
            height: _nodeHeight,
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
            decoration: BoxDecoration(
              color: isSelected ? EchoColors.forest : Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: isSelected ? EchoColors.forest : borderColor,
                width: isSelected ? 2.4 : 1.2,
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color.fromRGBO(35, 42, 37, 0.08),
                  blurRadius: isSelected ? 10 : 5,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            alignment: Alignment.center,
            child: Text(
              '$marker${node.title}',
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 9.5,
                height: 1.15,
                fontWeight: FontWeight.w600,
                color: isSelected ? Colors.white : EchoColors.ink,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _clusterWidget(GraphClusterModel cluster) {
    final lod = _scale.clamp(0.35, 1.0);
    final width = (88 + 9 * math.sqrt(cluster.size)) / lod;
    final height = 46 / lod;
    final left = cluster.x - _bounds.left - width / 2;
    final top = cluster.y - _bounds.top - height / 2;

    return Positioned(
      left: left,
      top: top,
      child: GestureDetector(
        onTap: () => _focusPoint(Offset(cluster.x, cluster.y)),
        child: Container(
          width: width,
          height: height,
          padding: EdgeInsets.symmetric(horizontal: 8 / lod),
          decoration: BoxDecoration(
            color: EchoColors.sageSoft,
            borderRadius: BorderRadius.circular(14 / lod),
            border: Border.all(color: EchoColors.forest, width: 1.2 / lod),
          ),
          alignment: Alignment.center,
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              '${cluster.label} · ${cluster.size}',
              style: TextStyle(
                fontSize: 11 / lod,
                fontWeight: FontWeight.w700,
                color: EchoColors.forest,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _zoomControls() {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: EchoColors.border),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Tooltip(
            message: 'Zoom in',
            child: IconButton(
              icon: const Icon(Icons.add, size: 18, color: EchoColors.forest),
              onPressed: () => _zoomBy(1.3),
              constraints: const BoxConstraints(minWidth: 34, minHeight: 34),
              padding: EdgeInsets.zero,
            ),
          ),
          const Divider(height: 1, color: EchoColors.border),
          Tooltip(
            message: 'Zoom out',
            child: IconButton(
              icon: const Icon(
                Icons.remove,
                size: 18,
                color: EchoColors.forest,
              ),
              onPressed: () => _zoomBy(1 / 1.3),
              constraints: const BoxConstraints(minWidth: 34, minHeight: 34),
              padding: EdgeInsets.zero,
            ),
          ),
          const Divider(height: 1, color: EchoColors.border),
          Tooltip(
            message: 'Fit graph',
            child: IconButton(
              icon: const Icon(
                Icons.center_focus_strong_outlined,
                size: 18,
                color: EchoColors.forest,
              ),
              onPressed: _fitToView,
              constraints: const BoxConstraints(minWidth: 34, minHeight: 34),
              padding: EdgeInsets.zero,
            ),
          ),
        ],
      ),
    );
  }

  Widget _legend() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: EchoColors.border),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _LineSample(pattern: 'solid', label: 'Confirmed'),
          SizedBox(width: 10),
          _LineSample(pattern: 'dashed', label: 'Uncertain'),
          SizedBox(width: 10),
          _LineSample(pattern: 'dotted', label: 'Conflicting'),
        ],
      ),
    );
  }
}

class _LineSample extends StatelessWidget {
  final String pattern;
  final String label;

  const _LineSample({required this.pattern, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 16,
          height: 6,
          child: CustomPaint(painter: _LineSamplePainter(pattern)),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: const TextStyle(fontSize: 9, color: EchoColors.muted),
        ),
      ],
    );
  }
}

class _LineSamplePainter extends CustomPainter {
  final String pattern;

  _LineSamplePainter(this.pattern);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = EchoColors.forest
      ..strokeWidth = 1.4
      ..style = PaintingStyle.stroke;
    final path = Path()
      ..moveTo(0, size.height / 2)
      ..lineTo(size.width, size.height / 2);
    drawPatternedPath(canvas, path, paint, pattern);
  }

  @override
  bool shouldRepaint(covariant _LineSamplePainter oldDelegate) =>
      oldDelegate.pattern != pattern;
}

class _EmptyGraph extends StatelessWidget {
  const _EmptyGraph();

  @override
  Widget build(BuildContext context) {
    return Container(
      alignment: Alignment.center,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFFF1F3EE),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: EchoColors.border),
      ),
      child: const Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.hub_outlined, color: EchoColors.forest, size: 30),
          SizedBox(height: 12),
          Text(
            'No knowledge yet',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: EchoColors.ink,
            ),
          ),
          SizedBox(height: 6),
          Text(
            'Record a thought. Echo turns what you said into entities and '
            'relationships you can explore here.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: EchoColors.muted),
          ),
        ],
      ),
    );
  }
}

class _RelationshipSheet extends StatefulWidget {
  final EntityRelationshipModel relationship;
  final BackendService backend;
  final Future<void> Function() onChanged;

  const _RelationshipSheet({
    required this.relationship,
    required this.backend,
    required this.onChanged,
  });

  @override
  State<_RelationshipSheet> createState() => _RelationshipSheetState();
}

class _RelationshipSheetState extends State<_RelationshipSheet> {
  bool _busy = false;
  String? _error;

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: EchoColors.card,
        title: const Text(
          'Delete this relationship?',
          style: TextStyle(fontSize: 16),
        ),
        content: const Text(
          'Only the connection is removed. Neither entity is deleted.',
          style: TextStyle(fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text(
              'Delete',
              style: TextStyle(color: EchoColors.danger),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.backend.deleteRelationship(widget.relationship.id);
      await widget.onChanged();
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'The relationship was not deleted.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rel = widget.relationship;
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          color: EchoColors.card,
          borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
        ),
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Relationship',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: EchoColors.ink,
              ),
            ),
            const SizedBox(height: 12),
            _SheetRow(label: 'Source', value: rel.fromName),
            _SheetRow(label: 'Type', value: rel.relationType),
            _SheetRow(label: 'Target', value: rel.toName),
            _SheetRow(label: 'Status', value: rel.status),
            _SheetRow(label: 'Certainty', value: rel.certainty),
            if (_error != null) ...[
              const SizedBox(height: 6),
              Text(
                _error!,
                style: const TextStyle(fontSize: 11, color: EchoColors.danger),
              ),
            ],
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _busy ? null : _delete,
              icon: const Icon(Icons.link_off, size: 16),
              label: const Text('Delete relationship'),
            ),
          ],
        ),
      ),
    );
  }
}

class _SheetRow extends StatelessWidget {
  final String label;
  final String value;

  const _SheetRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 78,
            child: Text(
              label,
              style: const TextStyle(fontSize: 11, color: EchoColors.muted),
            ),
          ),
          Expanded(
            child: Text(
              value.isEmpty ? '—' : value,
              style: const TextStyle(fontSize: 13, color: EchoColors.ink),
            ),
          ),
        ],
      ),
    );
  }
}

/// Draws a path respecting the certainty encoding (KG-06): solid for confirmed,
/// dashed for uncertain and dotted for conflicting. Line style — not colour —
/// carries the meaning, so it survives grayscale.
void drawPatternedPath(Canvas canvas, Path path, Paint paint, String pattern) {
  if (pattern == 'solid') {
    canvas.drawPath(path, paint);
    return;
  }
  final patternLengths = pattern == 'dotted'
      ? const [1.2, 3.6]
      : const [7.0, 4.5];
  final dashedPaint = Paint()
    ..color = paint.color
    ..strokeWidth = paint.strokeWidth
    ..style = PaintingStyle.stroke;
  for (final metric in path.computeMetrics()) {
    var distance = 0.0;
    var index = 0;
    while (distance < metric.length) {
      final length = patternLengths[index % patternLengths.length];
      final next = math.min(distance + length, metric.length);
      if (index.isEven) {
        canvas.drawPath(metric.extractPath(distance, next), dashedPaint);
      }
      distance = next;
      index++;
    }
  }
}

class _GraphEdgePainter extends CustomPainter {
  final Map<String, Offset> centers;
  final Offset origin;
  final List<GraphEdgeModel> edges;
  final String? selectedNodeId;
  final String? focusedEdgeId;

  _GraphEdgePainter({
    required this.centers,
    required this.origin,
    required this.edges,
    required this.selectedNodeId,
    required this.focusedEdgeId,
  });

  @override
  void paint(Canvas canvas, Size size) {
    var labelBudget = 14;
    for (final edge in edges) {
      final from = centers[edge.fromNode];
      final to = centers[edge.toNode];
      if (from == null || to == null) continue;

      final p1 = from - origin;
      final p2 = to - origin;
      final connected =
          edge.fromNode == selectedNodeId || edge.toNode == selectedNodeId;
      final focused = edge.id == focusedEdgeId;

      final pattern = switch (edge.certainty) {
        'uncertain' => 'dashed',
        'conflicting' => 'dotted',
        _ => 'solid',
      };
      final paint = Paint()
        ..color = focused
            ? EchoColors.forest
            : (connected ? const Color(0xFF3F5A48) : const Color(0xFFAAB8AC))
        ..strokeWidth = focused ? 2.8 : (connected ? 2.1 : 1.2)
        ..style = PaintingStyle.stroke;

      final path = Path()
        ..moveTo(p1.dx, p1.dy)
        ..lineTo(p2.dx, p2.dy);
      drawPatternedPath(canvas, path, paint, pattern);

      final showLabel =
          labelBudget > 0 && (focused || connected) && edge.type.isNotEmpty;
      if (!showLabel) continue;
      labelBudget--;

      final anchor = Offset((p1.dx + p2.dx) / 2, (p1.dy + p2.dy) / 2);
      final textSpan = TextSpan(
        text: edge.type,
        style: const TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w600,
          color: EchoColors.forest,
        ),
      );
      final painter = TextPainter(
        text: textSpan,
        textDirection: TextDirection.ltr,
      )..layout();
      final rect = Rect.fromCenter(
        center: anchor,
        width: painter.width + 10,
        height: painter.height + 6,
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(6)),
        Paint()..color = const Color(0xFFE5EDE6),
      );
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(6)),
        Paint()
          ..color = EchoColors.sage
          ..style = PaintingStyle.stroke
          ..strokeWidth = 0.8,
      );
      painter.paint(
        canvas,
        Offset(anchor.dx - painter.width / 2, anchor.dy - painter.height / 2),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _GraphEdgePainter oldDelegate) => true;
}
