import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';

/// Entity detail (KG-07): name, description, type, certainty and the related
/// relationships. Name/description are editable; deletion asks for
/// confirmation. Transcripts and debug data are never shown.
class EntityDetailSheet extends StatefulWidget {
  final EntityDetailModel detail;
  final BackendService backend;
  final Future<void> Function() onChanged;

  const EntityDetailSheet({
    super.key,
    required this.detail,
    required this.backend,
    required this.onChanged,
  });

  @override
  State<EntityDetailSheet> createState() => _EntityDetailSheetState();
}

class _EntityDetailSheetState extends State<EntityDetailSheet> {
  late EntityModel _entity;
  late List<EntityRelationshipModel> _relationships;
  late TextEditingController _nameController;
  late TextEditingController _descriptionController;

  bool _editing = false;
  bool _busy = false;
  String? _error;
  EntityRelationshipModel? _activeRelationship;

  @override
  void initState() {
    super.initState();
    _entity = widget.detail.entity;
    _relationships = widget.detail.relationships;
    _nameController = TextEditingController(text: _entity.name);
    _descriptionController = TextEditingController(
      text: _entity.description,
    );
  }

  @override
  void dispose() {
    _nameController.dispose();
    _descriptionController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final name = _nameController.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'An entity name cannot be empty.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final updated = await widget.backend.updateEntity(
        _entity.id,
        name: name,
        description: _descriptionController.text.trim(),
      );
      await widget.onChanged();
      if (!mounted) return;
      setState(() {
        _entity = updated;
        _editing = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'Changes could not be saved. ${_short(e)}');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final confirmed = await _confirm(
      title: 'Delete this entity?',
      body:
          'The entity and its relationships are removed from your graph. '
          'Other records stay untouched.',
    );
    if (!confirmed) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.backend.deleteEntity(_entity.id);
      await widget.onChanged();
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'The entity was not deleted. ${_short(e)}');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _deleteRelationship(EntityRelationshipModel rel) async {
    final confirmed = await _confirm(
      title: 'Delete this relationship?',
      body:
          'Only the connection is removed. Neither entity is deleted from '
          'your graph.',
    );
    if (!confirmed) return;

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.backend.deleteRelationship(rel.id);
      await widget.onChanged();
      if (!mounted) return;
      setState(() {
        _relationships = _relationships
            .where((item) => item.id != rel.id)
            .toList();
        _activeRelationship = null;
      });
    } catch (e) {
      if (mounted) {
        setState(
          () => _error = 'The relationship was not deleted. ${_short(e)}',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm({required String title, required String body}) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: EchoColors.card,
        title: Text(title, style: const TextStyle(fontSize: 16)),
        content: Text(body, style: const TextStyle(fontSize: 13)),
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
    return result ?? false;
  }

  String _short(Object error) {
    final text = error.toString().replaceFirst('Exception: ', '');
    return text.length > 120 ? '${text.substring(0, 120)}…' : text;
  }

  @override
  Widget build(BuildContext context) {
    final rel = _activeRelationship;
    return _SheetFrame(
      child: rel == null
          ? _buildEntityView()
          : _RelationshipView(
              relationship: rel,
              busy: _busy,
              onBack: () => setState(() => _activeRelationship = null),
              onDelete: () => _deleteRelationship(rel),
            ),
    );
  }

  Widget _buildEntityView() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        _SheetHandle(),
        Row(
          children: [
            Expanded(
              child: _editing
                  ? TextField(
                      controller: _nameController,
                      autofocus: true,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                      decoration: const InputDecoration(
                        labelText: 'Entity name',
                      ),
                    )
                  : Text(
                      _entity.name,
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: EchoColors.ink,
                      ),
                    ),
            ),
            IconButton(
              tooltip: 'Delete entity',
              onPressed: _busy ? null : _delete,
              icon: const Icon(
                Icons.delete_outline,
                color: EchoColors.danger,
                size: 20,
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            _Tag(text: _entity.entityType.replaceAll('_', ' ')),
            _Tag(text: _certaintyLabel(_entity.certainty)),
          ],
        ),
        const SizedBox(height: 12),
        if (_editing)
          TextField(
            controller: _descriptionController,
            minLines: 2,
            maxLines: 5,
            style: const TextStyle(fontSize: 13),
            decoration: const InputDecoration(labelText: 'Description'),
          )
        else
          Text(
            _entity.description.isEmpty
                ? 'No description captured.'
                : _entity.description,
            style: const TextStyle(
              fontSize: 13,
              height: 1.45,
              color: EchoColors.ink,
            ),
          ),
        if (_error != null) ...[
          const SizedBox(height: 10),
          Text(
            _error!,
            style: const TextStyle(fontSize: 11, color: EchoColors.danger),
          ),
        ],
        const SizedBox(height: 14),
        Row(
          children: [
            if (_editing) ...[
              TextButton(
                onPressed: _busy
                    ? null
                    : () {
                        setState(() {
                          _editing = false;
                          _nameController.text = _entity.name;
                          _descriptionController.text = _entity.description;
                        });
                      },
                child: const Text('Cancel'),
              ),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _busy ? null : _save,
                child: const Text('Save'),
              ),
            ] else
              OutlinedButton.icon(
                onPressed: () => setState(() => _editing = true),
                icon: const Icon(Icons.edit_outlined, size: 16),
                label: const Text('Edit'),
              ),
          ],
        ),
        const SizedBox(height: 12),
        const Divider(height: 1, color: EchoColors.border),
        const SizedBox(height: 10),
        Text(
          'RELATIONSHIPS · ${_relationships.length}',
          style: const TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w700,
            letterSpacing: 1.0,
            color: EchoColors.muted,
          ),
        ),
        const SizedBox(height: 6),
        if (_relationships.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 10),
            child: Text(
              'No connections yet.',
              style: TextStyle(fontSize: 12, color: EchoColors.muted),
            ),
          )
        else
          ..._relationships.map(
            (relationship) => ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text(
                '${relationship.fromName} → ${relationship.toName}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: EchoColors.ink),
              ),
              subtitle: Text(
                '${relationship.relationType} · ${_certaintyLabel(relationship.certainty)}',
                style: const TextStyle(fontSize: 10),
              ),
              trailing: const Icon(
                Icons.chevron_right,
                size: 18,
                color: EchoColors.muted,
              ),
              onTap: () =>
                  setState(() => _activeRelationship = relationship),
            ),
          ),
        const SizedBox(height: 8),
      ],
    );
  }
}

/// Relationship detail (KG-08): source, type, target and status. Deleting the
/// connection never deletes either entity.
class _RelationshipView extends StatelessWidget {
  final EntityRelationshipModel relationship;
  final bool busy;
  final VoidCallback onBack;
  final VoidCallback onDelete;

  const _RelationshipView({
    required this.relationship,
    required this.busy,
    required this.onBack,
    required this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        _SheetHandle(),
        Row(
          children: [
            IconButton(
              tooltip: 'Back to entity',
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back, size: 18),
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
            ),
            const SizedBox(width: 10),
            const Expanded(
              child: Text(
                'Relationship',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: EchoColors.ink,
                ),
              ),
            ),
            IconButton(
              tooltip: 'Delete relationship',
              onPressed: busy ? null : onDelete,
              icon: const Icon(
                Icons.delete_outline,
                color: EchoColors.danger,
                size: 20,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        _DetailRow(label: 'Source', value: relationship.fromName),
        _DetailRow(label: 'Type', value: relationship.relationType),
        _DetailRow(label: 'Target', value: relationship.toName),
        _DetailRow(label: 'Status', value: relationship.status),
        _DetailRow(
          label: 'Certainty',
          value: _certaintyLabel(relationship.certainty),
        ),
        const SizedBox(height: 14),
        OutlinedButton.icon(
          onPressed: busy ? null : onDelete,
          icon: const Icon(Icons.link_off, size: 16),
          label: const Text('Delete relationship'),
        ),
        const SizedBox(height: 8),
      ],
    );
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

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

class _SheetFrame extends StatelessWidget {
  final Widget child;

  const _SheetFrame({required this.child});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * 0.78,
        ),
        decoration: const BoxDecoration(
          color: EchoColors.card,
          borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
        ),
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
        child: SingleChildScrollView(child: child),
      ),
    );
  }
}

class _SheetHandle extends StatelessWidget {
  const _SheetHandle();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 40,
        height: 4,
        margin: const EdgeInsets.only(bottom: 14),
        decoration: BoxDecoration(
          color: EchoColors.border,
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  final String text;

  const _Tag({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: EchoColors.sageSoft,
        borderRadius: BorderRadius.circular(7),
      ),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: EchoColors.forest,
        ),
      ),
    );
  }
}

String _certaintyLabel(String certainty) {
  switch (certainty) {
    case 'uncertain':
      return 'Uncertain';
    case 'conflicting':
      return 'Conflicting';
    default:
      return 'Confirmed';
  }
}
