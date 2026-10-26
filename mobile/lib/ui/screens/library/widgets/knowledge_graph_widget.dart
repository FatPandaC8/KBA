import 'package:flutter/material.dart';
import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'graph_layout_engine.dart';

class KnowledgeGraphWidget extends StatefulWidget {
  final NoteProvider noteProvider;
  final Function(String noteId) onOpenDetail;
  final String searchQuery;

  const KnowledgeGraphWidget({
    super.key,
    required this.noteProvider,
    required this.onOpenDetail,
    this.searchQuery = '',
  });

  @override
  State<KnowledgeGraphWidget> createState() => _KnowledgeGraphWidgetState();
}

class _KnowledgeGraphWidgetState extends State<KnowledgeGraphWidget> {
  List<GraphEdgeModel> _relationships = [];
  bool _isLoading = false;
  String? _selectedNodeId;
  double _zoom = 1.0;
  Offset _panOffset = Offset.zero;

  @override
  void initState() {
    super.initState();
    widget.noteProvider.addListener(_onProviderChanged);
    _loadRelationships();
  }

  @override
  void didUpdateWidget(KnowledgeGraphWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.noteProvider != widget.noteProvider) {
      oldWidget.noteProvider.removeListener(_onProviderChanged);
      widget.noteProvider.addListener(_onProviderChanged);
      _loadRelationships();
    }
  }

  @override
  void dispose() {
    widget.noteProvider.removeListener(_onProviderChanged);
    super.dispose();
  }

  void _onProviderChanged() {
    _loadRelationships();
  }

  Future<void> _loadRelationships() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final rels = await widget.noteProvider.backendService.fetchAllRelationships();
      if (mounted) {
        setState(() {
          _relationships = rels;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          // Even if backend fails, local notes can still be viewed in graph
          _relationships = [];
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final allNotes = widget.noteProvider.notes;

    // Filter notes based on search query
    final query = widget.searchQuery.trim().toLowerCase();
    final visibleNotes = query.isEmpty
        ? allNotes
        : allNotes.where((n) {
            return n.title.toLowerCase().contains(query) ||
                n.originalContent.toLowerCase().contains(query) ||
                (n.summary?.toLowerCase().contains(query) ?? false);
          }).toList();

    if (_isLoading && allNotes.isEmpty) {
      return Container(
        height: 380,
        alignment: Alignment.center,
        child: const Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: EchoColors.forest),
            SizedBox(height: 14),
            Text(
              'Mapping your ideas…',
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
            ),
            SizedBox(height: 4),
            Text(
              'Building a focused view',
              style: TextStyle(color: EchoColors.muted, fontSize: 11),
            ),
          ],
        ),
      );
    }

    if (visibleNotes.isEmpty) {
      return Container(
        height: 360,
        alignment: Alignment.center,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 56,
              height: 56,
              decoration: const BoxDecoration(
                color: EchoColors.sageSoft,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.hub_outlined,
                color: EchoColors.forest,
                size: 28,
              ),
            ),
            const SizedBox(height: 14),
            Text(
              allNotes.isEmpty ? 'No captures yet' : 'No ideas match',
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
            ),
            const SizedBox(height: 6),
            Text(
              allNotes.isEmpty
                  ? 'Record voice thoughts or type captures to see them connect.'
                  : 'Adjust your search to see connected ideas.',
              style: const TextStyle(color: EchoColors.muted, fontSize: 12),
            ),
          ],
        ),
      );
    }

    // Convert visible notes to GraphNodeModels
    final graphNodes = visibleNotes.map((note) {
      return GraphNodeModel(
        id: note.id,
        title: note.title,
        kind: note.audioPath != null ? 'capture' : 'idea',
        x: 0,
        y: 0,
      );
    }).toList();

    // Map relationships where both endpoints exist
    final visibleNoteIds = visibleNotes.map((n) => n.id).toSet();
    final visibleEdges = _relationships.where((e) {
      return visibleNoteIds.contains(e.fromNode) && visibleNoteIds.contains(e.toNode);
    }).toList();

    // Run deterministic layout engine
    final positionedMap = DeterministicGraphLayout.computeLayout(
      nodes: graphNodes,
      edges: visibleEdges,
    );

    // Selected node handling: default to first if none or selected removed
    final selectedId = (_selectedNodeId != null && visibleNoteIds.contains(_selectedNodeId))
        ? _selectedNodeId!
        : visibleNotes.first.id;

    final selectedNote = visibleNotes.firstWhere(
      (n) => n.id == selectedId,
      orElse: () => visibleNotes.first,
    );

    // Identify direct neighbor IDs of selected node
    final neighborIds = <String>{};
    for (final edge in visibleEdges) {
      if (edge.fromNode == selectedId) neighborIds.add(edge.toNode);
      if (edge.toNode == selectedId) neighborIds.add(edge.fromNode);
    }

    return Column(
      children: [
        // Graph Legend and Meta
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          child: Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  color: EchoColors.forest,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 5),
              const Text(
                'Voice',
                style: TextStyle(fontSize: 10, color: EchoColors.muted),
              ),
              const SizedBox(width: 14),
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                  border: Border.all(color: EchoColors.sage, width: 1.5),
                ),
              ),
              const SizedBox(width: 5),
              const Text(
                'Text',
                style: TextStyle(fontSize: 10, color: EchoColors.muted),
              ),
              const SizedBox(width: 14),
              Container(
                width: 14,
                height: 2,
                color: const Color(0xFF6B8A7A),
              ),
              const SizedBox(width: 5),
              Text(
                '${visibleEdges.length} connections',
                style: const TextStyle(fontSize: 10, color: EchoColors.muted),
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(
                  Icons.refresh,
                  size: 18,
                  color: EchoColors.muted,
                ),
                onPressed: _loadRelationships,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
              ),
            ],
          ),
        ),

        // Interactive Canvas Container
        Container(
          height: 490,
          width: double.infinity,
          decoration: BoxDecoration(
            color: const Color(0xFFF1F3EE),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: EchoColors.border),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            children: [
              // Draggable / Zoomable Canvas Area
              GestureDetector(
                onPanUpdate: (details) {
                  setState(() {
                    _panOffset += details.delta;
                  });
                },
                child: Transform.translate(
                  offset: _panOffset,
                  child: Transform.scale(
                    scale: _zoom,
                    alignment: Alignment.center,
                    child: SizedBox(
                      width: 500,
                      height: 500,
                      child: Stack(
                        clipBehavior: Clip.none,
                        children: [
                          // Edge Lines
                          CustomPaint(
                            size: const Size(500, 500),
                            painter: _GraphEdgePainter(
                              positionedMap: positionedMap,
                              edges: visibleEdges,
                              selectedNodeId: selectedId,
                            ),
                          ),

                          // Node Buttons
                          ...visibleNotes.map((note) {
                            final posNode = positionedMap[note.id];
                            if (posNode == null) return const SizedBox.shrink();

                            final isSelected = note.id == selectedId;
                            final isNeighbor = neighborIds.contains(note.id);
                            final isCapture = note.audioPath != null;

                            final opacity = (_selectedNodeId == null || isSelected || isNeighbor)
                                ? 1.0
                                : 0.45;

                            return Positioned(
                              left: posNode.position.dx,
                              top: posNode.position.dy,
                              child: Opacity(
                                opacity: opacity,
                                child: GestureDetector(
                                  onTap: () {
                                    setState(() {
                                      _selectedNodeId = note.id;
                                    });
                                  },
                                  onDoubleTap: () {
                                    widget.onOpenDetail(note.id);
                                  },
                                  child: Container(
                                    width: posNode.width,
                                    height: posNode.height,
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 8,
                                      vertical: 6,
                                    ),
                                    decoration: BoxDecoration(
                                      color: isCapture
                                          ? EchoColors.forest
                                          : Colors.white,
                                      borderRadius: BorderRadius.circular(14),
                                      border: Border.all(
                                        color: isSelected
                                            ? EchoColors.forest
                                            : (isNeighbor ? const Color(0xFF6B8A7A) : EchoColors.sage),
                                        width: isSelected ? 2.5 : (isNeighbor ? 2.0 : 1.2),
                                      ),
                                      boxShadow: [
                                        BoxShadow(
                                          color: isSelected
                                              ? EchoColors.forest.withValues(alpha: 0.25)
                                              : const Color.fromRGBO(35, 42, 37, 0.06),
                                          blurRadius: isSelected ? 12 : 6,
                                          offset: const Offset(0, 3),
                                        ),
                                      ],
                                    ),
                                    alignment: Alignment.center,
                                    child: Text(
                                      note.title,
                                      textAlign: TextAlign.center,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 10,
                                        fontWeight: FontWeight.w700,
                                        color: isCapture
                                            ? Colors.white
                                            : EchoColors.forest,
                                        height: 1.2,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            );
                          }),
                        ],
                      ),
                    ),
                  ),
                ),
              ),

              // Zoom Controls
              Positioned(
                top: 10,
                right: 10,
                child: Container(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: EchoColors.border),
                  ),
                  child: Column(
                    children: [
                      IconButton(
                        icon: const Icon(
                          Icons.add,
                          size: 18,
                          color: EchoColors.forest,
                        ),
                        onPressed: () => setState(
                          () => _zoom = (_zoom + 0.15).clamp(0.6, 1.6),
                        ),
                        constraints: const BoxConstraints(
                          minWidth: 32,
                          minHeight: 32,
                        ),
                        padding: EdgeInsets.zero,
                      ),
                      const Divider(height: 1, color: EchoColors.border),
                      IconButton(
                        icon: const Icon(
                          Icons.remove,
                          size: 18,
                          color: EchoColors.forest,
                        ),
                        onPressed: () => setState(
                          () => _zoom = (_zoom - 0.15).clamp(0.6, 1.6),
                        ),
                        constraints: const BoxConstraints(
                          minWidth: 32,
                          minHeight: 32,
                        ),
                        padding: EdgeInsets.zero,
                      ),
                    ],
                  ),
                ),
              ),

              // Quick open selected node banner
              Positioned(
                bottom: 8,
                left: 12,
                right: 12,
                child: GestureDetector(
                  onTap: () => widget.onOpenDetail(selectedNote.id),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.94),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: EchoColors.border),
                      boxShadow: const [
                        BoxShadow(
                          color: Color.fromRGBO(35, 42, 37, 0.06),
                          blurRadius: 8,
                          offset: Offset(0, 2),
                        ),
                      ],
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                selectedNote.title,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: EchoColors.ink,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '${neighborIds.length} connected ideas · Tap to open',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: EchoColors.muted,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const Icon(
                          Icons.arrow_forward_ios,
                          size: 12,
                          color: EchoColors.forest,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _GraphEdgePainter extends CustomPainter {
  final Map<String, PositionedNode> positionedMap;
  final List<GraphEdgeModel> edges;
  final String selectedNodeId;

  _GraphEdgePainter({
    required this.positionedMap,
    required this.edges,
    required this.selectedNodeId,
  });

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      final from = positionedMap[edge.fromNode];
      final to = positionedMap[edge.toNode];
      if (from == null || to == null) continue;

      final isConnectedToSelected =
          edge.fromNode == selectedNodeId || edge.toNode == selectedNodeId;

      final paint = Paint()
        ..color = isConnectedToSelected
            ? const Color(0xFF285430)
            : const Color(0xFFB0BEB3)
        ..strokeWidth = isConnectedToSelected ? 2.5 : 1.4
        ..style = PaintingStyle.stroke;

      final p1 = from.center;
      final p2 = to.center;

      // Draw subtle cubic bezier curve to prevent edges overlapping straight lines
      final midX = (p1.dx + p2.dx) / 2;
      final midY = (p1.dy + p2.dy) / 2;
      final dx = p2.dx - p1.dx;
      final dy = p2.dy - p1.dy;
      final dist = (dx * dx + dy * dy);
      final offsetDist = dist > 400 ? 12.0 : 0.0;

      final controlPoint = Offset(midX - (dy / 25).clamp(-offsetDist, offsetDist), midY + (dx / 25).clamp(-offsetDist, offsetDist));
      final path = Path()
        ..moveTo(p1.dx, p1.dy)
        ..quadraticBezierTo(controlPoint.dx, controlPoint.dy, p2.dx, p2.dy);

      canvas.drawPath(path, paint);

      // Draw small relationship chip/indicator along selected edges
      if (isConnectedToSelected && edge.type.isNotEmpty) {
        final textSpan = TextSpan(
          text: edge.type,
          style: const TextStyle(
            color: Color(0xFF285430),
            fontSize: 9,
            fontWeight: FontWeight.w700,
          ),
        );
        final tp = TextPainter(
          text: textSpan,
          textDirection: TextDirection.ltr,
        )..layout();

        final badgeRect = RRect.fromRectAndRadius(
          Rect.fromCenter(
            center: controlPoint,
            width: tp.width + 10,
            height: tp.height + 6,
          ),
          const Radius.circular(6),
        );

        final badgePaint = Paint()..color = const Color(0xFFE5EDE6);
        final badgeBorder = Paint()
          ..color = const Color(0xFF94A897)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.0;

        canvas.drawRRect(badgeRect, badgePaint);
        canvas.drawRRect(badgeRect, badgeBorder);
        tp.paint(canvas, Offset(controlPoint.dx - tp.width / 2, controlPoint.dy - tp.height / 2));
      }
    }
  }

  @override
  bool shouldRepaint(covariant _GraphEdgePainter oldDelegate) => true;
}
