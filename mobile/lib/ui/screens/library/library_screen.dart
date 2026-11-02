import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show setEquals;
import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/state/note_provider.dart';
import 'package:mobile/ui/widgets/echo_app_bar.dart';

import 'widgets/knowledge_graph_widget.dart';

/// Graph tab (KG-04..KG-08, SRCH-01..SRCH-03).
///
/// A single canvas with the user's entities and relationships plus semantic
/// search over the same graph. Tapping a search result focuses the node or edge
/// on the canvas and opens its detail panel. The tab never shows transcripts.
class LibraryScreen extends StatefulWidget {
  final NoteProvider noteProvider;

  const LibraryScreen({super.key, required this.noteProvider});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  final TextEditingController _searchController = TextEditingController();
  Timer? _debounce;

  GraphDataModel? _graph;
  bool _loading = true;
  String? _loadError;
  String? _graphErrorMessage;
  String? _graphErrorSubmessage;

  String _query = '';
  bool _searching = false;
  String? _searchError;
  GraphSearchResult? _result;

  GraphFocusRequest? _focus;
  int _focusSequence = 0;

  Set<String> _readySignature = {};
  Timer? _reloadTimer;
  bool _hasNewGraphData = false;

  // For incremental graph updates
  Map<String, Offset> _nodePositions = {};

  @override
  void initState() {
    super.initState();
    widget.noteProvider.addListener(_onProviderChanged);
    _readySignature = _currentReadySignature();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadGraph());
  }

  @override
  void didUpdateWidget(LibraryScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.noteProvider != widget.noteProvider) {
      oldWidget.noteProvider.removeListener(_onProviderChanged);
      widget.noteProvider.addListener(_onProviderChanged);
      _loadGraph();
    }
  }

  @override
  void dispose() {
    widget.noteProvider.removeListener(_onProviderChanged);
    _debounce?.cancel();
    _reloadTimer?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  Set<String> _currentReadySignature() {
    return widget.noteProvider.notes
        .where((note) => note.status.name == 'ready')
        .map((note) => note.id)
        .toSet();
  }

  void _onProviderChanged() {
    // Recording polls notify on every stage change; only a change in which
    // captures finished processing can change the graph.
    final signature = _currentReadySignature();
    if (setEquals(signature, _readySignature)) return;
    _readySignature = signature;
    if (_graph != null && mounted) setState(() => _hasNewGraphData = true);
  }

  Future<void> _loadGraph() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _loadError = null;
        _graphErrorMessage = null;
        _graphErrorSubmessage = null;
      });
    }
    try {
      final graph = await widget.noteProvider.backendService.fetchGraph();
      if (!mounted) return;
      _mergeGraphData(graph, isFullReload: true);
      // Connectivity returned: stop the background reload attempts.
      _reloadTimer?.cancel();
      _reloadTimer = null;
    } on FormatException catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _graphErrorMessage = 'Unable to load graph';
        _graphErrorSubmessage = 'The server returned an invalid response. Please retry when the server is reachable.';
      });
      _scheduleAutoReload();
    } on BackendException catch (e) {
      if (!mounted) return;
      // Bug #4: consent is required before the first graph load. A 403 with a
      // consent message opens the consent prompt; granting it reloads.
      if (e.statusCode == 403 &&
          e.message.toLowerCase().contains('consent')) {
        setState(() {
          _loading = false;
          _graphErrorMessage = 'Processing confirmation needed';
          _graphErrorSubmessage =
              'Echo needs your OK to build the knowledge graph. Confirm to continue.';
        });
        final granted = await _promptConsent();
        if (granted && mounted) {
          await _loadGraph();
        }
        return;
      }
      setState(() {
        _loading = false;
        _graphErrorMessage = 'Could not load graph';
        _graphErrorSubmessage = e.message;
      });
      _scheduleAutoReload();
    } catch (e) {
      if (!mounted) return;
      // Determine error type for user-friendly messaging
      final errorText = e.toString().toLowerCase();
      setState(() {
        _loading = false;
        _graphErrorMessage = 'Could not load graph';
        if (errorText.contains('socket') ||
            errorText.contains('timeout') ||
            errorText.contains('network') ||
            errorText.contains('unreachable') ||
            errorText.contains('connection')) {
          _graphErrorSubmessage =
              'No internet connection. Please check your connection and retry.';
        } else if (errorText.contains('401') || errorText.contains('403')) {
          _graphErrorSubmessage =
              'Authentication failed. Please sign in again and retry.';
        } else {
          _graphErrorSubmessage =
              'Server error. Please retry when the server is reachable.';
        }
      });
      _scheduleAutoReload();
    }
  }

  /// Merges new graph data with existing graph, preserving node positions for
  /// existing nodes and placing new nodes near their connected neighbors.
  void _mergeGraphData(GraphDataModel newGraph, {required bool isFullReload}) {
    final oldGraph = _graph;
    
    if (oldGraph == null || isFullReload) {
      // First load or explicit full reload: use server positions as base
      _nodePositions = {
        for (final node in newGraph.nodes) node.id: Offset(node.x, node.y),
      };
      setState(() {
        _graph = newGraph;
        _hasNewGraphData = false;
        _loading = false;
        _loadError = null;
        _graphErrorMessage = null;
        _graphErrorSubmessage = null;
      });
      return;
    }

    // Incremental merge: preserve existing node positions
    final oldNodeIds = oldGraph.nodes.map((n) => n.id).toSet();
    final newNodeIds = newGraph.nodes.map((n) => n.id).toSet();
    final addedNodeIds = newNodeIds.difference(oldNodeIds);
    final removedNodeIds = oldNodeIds.difference(newNodeIds);

    // Build adjacency for new nodes to find neighbors
    final adjacency = <String, Set<String>>{};
    for (final node in newGraph.nodes) {
      adjacency[node.id] = <String>{};
    }
    for (final edge in newGraph.edges) {
      if (adjacency.containsKey(edge.fromNode) && adjacency.containsKey(edge.toNode)) {
        adjacency[edge.fromNode]!.add(edge.toNode);
        adjacency[edge.toNode]!.add(edge.fromNode);
      }
    }

    // Preserve positions for existing nodes
    final mergedPositions = Map<String, Offset>.from(_nodePositions);
    
    // Remove positions for deleted nodes
    for (final id in removedNodeIds) {
      mergedPositions.remove(id);
    }

    // Place new nodes near their neighbors
    for (final node in newGraph.nodes) {
      if (addedNodeIds.contains(node.id)) {
        final neighbors = adjacency[node.id] ?? <String>{};
        final knownNeighbors = neighbors.where(mergedPositions.containsKey).toList();
        
        if (knownNeighbors.isNotEmpty) {
          // Average position of known neighbors
          double avgX = 0, avgY = 0;
          for (final nbrId in knownNeighbors) {
            final pos = mergedPositions[nbrId]!;
            avgX += pos.dx;
            avgY += pos.dy;
          }
          avgX /= knownNeighbors.length;
          avgY /= knownNeighbors.length;
          // Add small random offset to avoid exact overlap
          final angle = math.Random(node.id.hashCode).nextDouble() * 2 * math.pi;
          const radius = 80.0;
          mergedPositions[node.id] = Offset(
            avgX + radius * math.cos(angle),
            avgY + radius * math.sin(angle),
          );
        } else {
          // No known neighbors, use server position
          mergedPositions[node.id] = Offset(node.x, node.y);
        }
      }
    }

    // Create updated graph with merged positions
    final updatedNodes = newGraph.nodes.map((node) {
      final pos = mergedPositions[node.id];
      if (pos != null) {
        return GraphNodeModel(
          id: node.id,
          title: node.title,
          kind: node.kind,
          x: pos.dx,
          y: pos.dy,
          clusterId: node.clusterId,
          certainty: node.certainty,
          confidence: node.confidence,
          degree: node.degree,
          isSelf: node.isSelf,
        );
      }
      return node;
    }).toList();

    final updatedGraph = GraphDataModel(
      nodes: updatedNodes,
      edges: newGraph.edges,
      clusters: newGraph.clusters,
    );

    _nodePositions = mergedPositions;
    setState(() {
      _graph = updatedGraph;
      _hasNewGraphData = false;
    });
  }

  /// When the graph fails to load, poll the health endpoint in the background
  /// and auto-reload once connectivity returns. The manual Retry button keeps
  /// working at any time (NET-01).
  void _scheduleAutoReload() {
    if (_reloadTimer != null || _graphErrorMessage == null) return;
    _reloadTimer = Timer.periodic(const Duration(seconds: 5), (_) async {
      if (!mounted) {
        _reloadTimer?.cancel();
        _reloadTimer = null;
        return;
      }
      try {
        final healthy = await widget.noteProvider.backendService.checkHealth();
        if (!healthy) return;
      } catch (_) {
        return;
      }
      // Connectivity is back: reload and stop polling.
      _reloadTimer?.cancel();
      _reloadTimer = null;
      if (mounted) _loadGraph();
    });
  }

  /// Bug #4: the consent gate for the first graph request. Shows a visible
  /// consent prompt (provider/version detail from the server); confirming
  /// records consent via POST /api/consent and reloads the graph. Returning
  /// without confirming keeps the error card with its Retry button.
  Future<bool> _promptConsent() async {
    if (!mounted) return false;
    Map<String, dynamic>? status;
    try {
      status = await widget.noteProvider.backendService.getConsent();
    } catch (_) {}
    final granted = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        final version = (status?['version'] as String?) ?? '';
        return AlertDialog(
          title: const Text('AI processing consent'),
          content: Text(
            'Echo builds your knowledge graph by processing captured text on '
            'the configured server. Transcripts are never returned to the '
            'app.${version.isEmpty ? '' : '\n\nConsent version: $version'}',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Not now'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('Allow'),
            ),
          ],
        );
      },
    );
    if (granted != true) return false;
    if (!mounted) return false;
    final backend = widget.noteProvider.backendService;
    try {
      await backend.ensureConsent();
      return true;
    } catch (e) {
      if (!mounted) return false;
      final messenger = ScaffoldMessenger.of(context);
      messenger.showSnackBar(
        SnackBar(content: Text('Could not confirm processing setup: $e')),
      );
      return false;
    }
  }

  void _onQueryChanged(String value) {
    _debounce?.cancel();
    final query = value.trim();
    setState(() {
      _query = query;
      if (query.isEmpty) {
        _result = null;
        _searchError = null;
        _searching = false;
      }
    });
    if (query.isEmpty) return;
    _debounce = Timer(const Duration(milliseconds: 350), () {
      _runSearch(query);
    });
  }

  Future<void> _runSearch(String query) async {
    setState(() {
      _searching = true;
      _searchError = null;
    });
    try {
      final result = await widget.noteProvider.backendService.searchGraph(
        query,
      );
      if (!mounted || _query != query) return;
      setState(() {
        _result = result;
        _searching = false;
      });
    } catch (e) {
      if (!mounted || _query != query) return;
      setState(() {
        _searching = false;
        _searchError = 'Search is unavailable right now.';
      });
    }
  }

  Future<void> _focusEntity(String entityId) async {
    FocusScope.of(context).unfocus();
    if (_graph == null) await _loadGraph();
    if (!mounted) return;
    setState(() {
      _focusSequence++;
      _focus = GraphFocusRequest(entityId: entityId, sequence: _focusSequence);
    });
  }

  Future<void> _focusRelationship(String relationshipId) async {
    FocusScope.of(context).unfocus();
    if (_graph == null) await _loadGraph();
    if (!mounted) return;
    setState(() {
      _focusSequence++;
      _focus = GraphFocusRequest(
        relationshipId: relationshipId,
        sequence: _focusSequence,
      );
    });
  }

  String _nodeTitle(String id) {
    final nodes = _graph?.nodes ?? const <GraphNodeModel>[];
    for (final node in nodes) {
      if (node.id == id) return node.title;
    }
    return id;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: EchoAppBar(title: 'Graph'),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 4),
              const Text(
                'Your knowledge',
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  color: EchoColors.ink,
                  letterSpacing: -0.5,
                ),
              ),
              const SizedBox(height: 10),
              _searchField(),
              if (_hasNewGraphData)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: _loadGraph,
                    icon: const Icon(Icons.refresh, size: 16),
                    label: const Text('New data available'),
                  ),
                ),
              if (_query.isNotEmpty) ...[
                const SizedBox(height: 8),
                _searchResults(),
              ],
              const SizedBox(height: 10),
              Expanded(child: _graphBody()),
            ],
          ),
        ),
      ),
    );
  }

  Widget _searchField() {
    return Container(
      height: 46,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: EchoColors.border),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          const Icon(Icons.search, size: 19, color: EchoColors.muted),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _searchController,
              onChanged: _onQueryChanged,
              textInputAction: TextInputAction.search,
              onSubmitted: (value) {
                final query = value.trim();
                if (query.isEmpty) return;
                _debounce?.cancel();
                _runSearch(query);
              },
              style: const TextStyle(fontSize: 13, color: EchoColors.ink),
              decoration: const InputDecoration(
                hintText: 'Search entities and relationships',
                hintStyle: TextStyle(color: Color(0xFF9A9D97), fontSize: 13),
                border: InputBorder.none,
              ),
            ),
          ),
          if (_query.isNotEmpty)
            GestureDetector(
              onTap: () {
                _searchController.clear();
                _onQueryChanged('');
                FocusScope.of(context).unfocus();
              },
              child: const Icon(Icons.close, size: 18, color: EchoColors.muted),
            ),
        ],
      ),
    );
  }

  Widget _searchResults() {
    if (_searching) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            SizedBox(
              width: 13,
              height: 13,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: EchoColors.forest,
              ),
            ),
            SizedBox(width: 8),
            Text(
              'Searching your graph…',
              style: TextStyle(fontSize: 11, color: EchoColors.muted),
            ),
          ],
        ),
      );
    }

    if (_searchError != null) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: EchoColors.dangerSoft,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: EchoColors.danger),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline, size: 15, color: EchoColors.danger),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                _searchError!,
                style: const TextStyle(fontSize: 11, color: EchoColors.ink),
              ),
            ),
            TextButton(
              onPressed: () => _runSearch(_query),
              child: const Text(
                'Retry',
                style: TextStyle(fontSize: 11, color: EchoColors.forest),
              ),
            ),
          ],
        ),
      );
    }

    final result = _result;
    if (result == null) return const SizedBox.shrink();
    if (result.entities.isEmpty && result.relationships.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 6),
        child: Text(
          'No matching entities or relationships.',
          style: TextStyle(fontSize: 11, color: EchoColors.muted),
        ),
      );
    }

    return Container(
      constraints: const BoxConstraints(maxHeight: 210),
      child: Material(
        color: Colors.white,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: EchoColors.border),
        ),
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.symmetric(vertical: 4),
          children: [
            for (final scored in result.entities)
              ListTile(
                dense: true,
                visualDensity: VisualDensity.compact,
                leading: const Icon(
                  Icons.circle,
                  size: 8,
                  color: EchoColors.forest,
                ),
                title: Text(
                  scored.entity.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: EchoColors.ink,
                  ),
                ),
                subtitle: Text(
                  _entityContext(scored.entity),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 10),
                ),
                onTap: () => _focusEntity(scored.entity.id),
              ),
            for (final relationship in result.relationships)
              ListTile(
                dense: true,
                visualDensity: VisualDensity.compact,
                leading: const Icon(
                  Icons.link,
                  size: 14,
                  color: EchoColors.muted,
                ),
                title: Text(
                  '${_nodeTitle(relationship.fromId)} → ${_nodeTitle(relationship.toId)}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: EchoColors.ink,
                  ),
                ),
                subtitle: Text(
                  '${relationship.relationType} · ${relationship.status}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 10),
                ),
                onTap: () => _focusRelationship(relationship.id),
              ),
          ],
        ),
      ),
    );
  }

  String _entityContext(EntityModel entity) {
    final type = entity.entityType.replaceAll('_', ' ');
    final description = entity.description.trim();
    if (description.isEmpty) return type;
    return '$type · $description';
  }

  Widget _graphBody() {
    if (_loading && _graph == null) {
      return Container(
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: const Color(0xFFF1F3EE),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: EchoColors.border),
        ),
        child: const Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: EchoColors.forest),
            SizedBox(height: 12),
            Text(
              'Loading your graph…',
              style: TextStyle(fontSize: 12, color: EchoColors.muted),
            ),
          ],
        ),
      );
    }

    if (_loadError != null || _graphErrorMessage != null) {
      return Container(
        alignment: Alignment.center,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: EchoColors.dangerSoft,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: EchoColors.danger),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(
              Icons.cloud_off_outlined,
              color: EchoColors.danger,
              size: 26,
            ),
            const SizedBox(height: 10),
            Text(
              _graphErrorMessage ?? 'Could not load graph',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: EchoColors.ink,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 4),
            Text(
              _graphErrorSubmessage ??
                  'Please retry when the server is reachable',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 11, color: EchoColors.muted),
            ),
            const SizedBox(height: 8),
            TextButton(onPressed: _loadGraph, child: const Text('Retry')),
          ],
        ),
      );
    }

    return KnowledgeGraphWidget(
      graph: _graph ?? GraphDataModel(nodes: const [], edges: const [], clusters: const []),
      backend: widget.noteProvider.backendService,
      focus: _focus,
      selfNodeId: _selfNodeId,
      onGraphMutated: _loadGraph,
      presetPositions: _nodePositions.isNotEmpty ? _nodePositions : null,
    );
  }

  String? get _selfNodeId {
    for (final node in _graph?.nodes ?? const <GraphNodeModel>[]) {
      if (node.isSelf) return node.id;
    }
    return null;
  }
}
