import 'dart:async';

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

  @override
  void initState() {
    super.initState();
    widget.noteProvider.addListener(_onProviderChanged);
    _readySignature = _currentReadySignature();
    _loadGraph();
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
    _loadGraph();
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
      setState(() {
        _graph = graph;
        _loading = false;
        _loadError = null;
        _graphErrorMessage = null;
        _graphErrorSubmessage = null;
      });
      // Connectivity returned: stop the background reload attempts.
      _reloadTimer?.cancel();
      _reloadTimer = null;
    } on FormatException catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _graphErrorMessage = 'Unable to load graph';
        _graphErrorSubmessage =
            'The server returned an invalid response. Please retry when the server is reachable.';
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
      final result = await widget.noteProvider.backendService.searchGraph(query);
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

  void _focusEntity(String entityId) {
    FocusScope.of(context).unfocus();
    setState(() {
      _focusSequence++;
      _focus = GraphFocusRequest(
        entityId: entityId,
        sequence: _focusSequence,
      );
    });
  }

  void _focusRelationship(String relationshipId) {
    FocusScope.of(context).unfocus();
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
            const Icon(
              Icons.error_outline,
              size: 15,
              color: EchoColors.danger,
            ),
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

    if (_loadError != null) {
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
              _graphErrorSubmessage ?? 'Please retry when the server is reachable',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 11, color: EchoColors.muted),
            ),
            const SizedBox(height: 8),
            TextButton(
              onPressed: _loadGraph,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    return KnowledgeGraphWidget(
      graph: _graph ?? GraphDataModel(nodes: const [], edges: const [], clusters: const []),
      backend: widget.noteProvider.backendService,
      focus: _focus,
      onGraphMutated: _loadGraph,
    );
  }
}
