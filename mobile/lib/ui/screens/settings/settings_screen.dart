import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/backend_service.dart';
import 'package:mobile/services/settings_service.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';

class SettingsScreen extends StatefulWidget {
  final SettingsService settingsService;
  final BackendService backendService;
  final VoidCallback onBack;

  const SettingsScreen({
    super.key,
    required this.settingsService,
    required this.backendService,
    required this.onBack,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _serverController;
  late final TextEditingController _tokenController;
  late bool _evalConsent;
  bool _obscureToken = true;
  bool _saving = false;
  String? _statusMessage;
  bool _statusOk = false;

  @override
  void initState() {
    super.initState();
    _serverController = TextEditingController(
      text: widget.settingsService.serverUrl,
    );
    _tokenController = TextEditingController(
      text: widget.settingsService.clientToken,
    );
    _evalConsent = widget.settingsService.evalConsent;
  }

  @override
  void dispose() {
    _serverController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  Future<bool> _saveConnection() async {
    final rawUrl = _serverController.text.trim();
    final uri = Uri.tryParse(rawUrl);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty) {
      setState(() {
        _statusOk = false;
        _statusMessage = 'Enter a valid URL starting with http:// or https://.';
      });
      return false;
    }

    setState(() {
      _saving = true;
      _statusMessage = null;
    });
    try {
      widget.settingsService.serverUrl = rawUrl.replaceAll(RegExp(r'/+$'), '');
      await widget.settingsService.setClientToken(_tokenController.text);
      if (!mounted) return false;
      setState(() {
        _statusOk = true;
        _statusMessage = 'Connection settings saved.';
      });
      return true;
    } catch (e) {
      if (!mounted) return false;
      setState(() {
        _statusOk = false;
        _statusMessage = 'Could not save settings securely: $e';
      });
      return false;
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _testConnection() async {
    final saved = await _saveConnection();
    if (!saved) return;
    setState(() {
      _saving = true;
      _statusMessage = 'Testing connection…';
    });
    final result = await widget.backendService.testConnection();
    if (!mounted) return;
    setState(() {
      _saving = false;
      _statusOk = result.ok;
      _statusMessage = result.message;
    });
  }

  Future<void> _setConsent(bool value) async {
    final previous = _evalConsent;
    setState(() => _evalConsent = value);
    widget.settingsService.evalConsent = value;
    try {
      await widget.backendService.updateConsent(value);
      if (!mounted) return;
      setState(() {
        _statusOk = true;
        _statusMessage = value ? 'Evaluation participation enabled.' : 'Consent withdrawn. Server-retained audio and evaluation data were purged.';
      });
    } catch (e) {
      widget.settingsService.evalConsent = previous;
      if (!mounted) return;
      setState(() {
        _evalConsent = previous;
        _statusOk = false;
        _statusMessage =
            'Consent update failed. The change was not applied: ${e.toString()}';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: EchoAppBar(title: 'Settings', onBack: widget.onBack),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Settings',
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w700,
                  color: EchoColors.ink,
                ),
              ),
              const SizedBox(height: 20),

              const Text(
                'SERVER CONNECTION',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                  color: EchoColors.muted,
                ),
              ),
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: EchoColors.border),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextField(
                      controller: _serverController,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: const InputDecoration(
                        labelText: 'Backend URL',
                        hintText: 'http://192.168.1.20:8000',
                        helperText:
                            'USB development: adb reverse tcp:8000 tcp:8000',
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: _tokenController,
                      obscureText: _obscureToken,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: InputDecoration(
                        labelText: 'Client access token',
                        helperText: 'Stored in Android encrypted storage, not plain preferences.',
                        suffixIcon: IconButton(
                          tooltip: _obscureToken ? 'Show token' : 'Hide token',
                          icon: Icon(
                            _obscureToken
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                          onPressed: () =>
                              setState(() => _obscureToken = !_obscureToken),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: _saving ? null : _saveConnection,
                            child: const Text('Save'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: ElevatedButton(
                            onPressed: _saving ? null : _testConnection,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: EchoColors.forest,
                              foregroundColor: Colors.white,
                            ),
                            child: const Text('Test connection'),
                          ),
                        ),
                      ],
                    ),
                    if (_statusMessage != null) ...[
                      const SizedBox(height: 10),
                      Text(
                        _statusMessage!,
                        style: TextStyle(
                          fontSize: 12,
                          height: 1.4,
                          color: _statusOk
                              ? EchoColors.forest
                              : EchoColors.danger,
                        ),
                      ),
                    ],
                  ],
                ),
              ),

              const SizedBox(height: 24),

              const Text(
                'PRIVACY & PROCESSING',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                  color: EchoColors.muted,
                ),
              ),
              const SizedBox(height: 10),
              Material(
                color: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: const BorderSide(color: EchoColors.border),
                ),
                clipBehavior: Clip.antiAlias,
                child: SwitchListTile(
                  activeThumbColor: EchoColors.forest,
                  title: const Text(
                    'Evaluation dataset participation',
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                  ),
                  subtitle: const Text(
                    'Allow the server to retain audio and evaluation data. '
                    'Turning this off purges retained audio and evaluation records. '
                    'Disabled by default.',
                    style: TextStyle(fontSize: 11, color: EchoColors.muted),
                  ),
                  value: _evalConsent,
                  onChanged: _setConsent,
                ),
              ),

              const SizedBox(height: 24),

              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: EchoColors.border),
                ),
                padding: const EdgeInsets.all(16),
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Transparent Processing',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 6),
                    Text(
                      'Echo stores your source notes on-device and sends audio '
                      'to your configured server for transcription, structured '
                      'extraction, and semantic recall. Audio is not retained '
                      'on the server unless evaluation participation is enabled.',
                      style: TextStyle(
                        fontSize: 11,
                        color: EchoColors.muted,
                        height: 1.5,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
