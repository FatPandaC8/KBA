import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';
import 'package:mobile/services/settings_service.dart';

import 'package:mobile/ui/widgets/echo_app_bar.dart';

class SettingsScreen extends StatefulWidget {
  final SettingsService settingsService;
  final VoidCallback onBack;

  const SettingsScreen({
    super.key,
    required this.settingsService,
    required this.onBack,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late TextEditingController _apiKeyController;
  late TextEditingController _baseUrlController;
  late TextEditingController _modelController;
  late bool _keepAudio;
  late bool _wifiOnly;

  @override
  void initState() {
    super.initState();
    _apiKeyController = TextEditingController(
      text: widget.settingsService.apiKey,
    );
    _baseUrlController = TextEditingController(
      text: widget.settingsService.baseUrl,
    );
    _modelController = TextEditingController(
      text: widget.settingsService.model,
    );
    _keepAudio = widget.settingsService.keepAudio;
    _wifiOnly = widget.settingsService.wifiOnly;
  }

  @override
  void dispose() {
    _apiKeyController.dispose();
    _baseUrlController.dispose();
    _modelController.dispose();
    super.dispose();
  }

  void _saveSettings() {
    widget.settingsService.apiKey = _apiKeyController.text.trim();
    widget.settingsService.baseUrl = _baseUrlController.text.trim();
    widget.settingsService.model = _modelController.text.trim();
    widget.settingsService.keepAudio = _keepAudio;
    widget.settingsService.wifiOnly = _wifiOnly;

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Settings saved successfully!')),
    );
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

              // AI Configuration section
              const Text(
                'AI CONFIGURATION (OPTIONAL)',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                  color: EchoColors.muted,
                ),
              ),
              const SizedBox(height: 10),
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: EchoColors.border),
                ),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'API Key',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _apiKeyController,
                      obscureText: true,
                      decoration: InputDecoration(
                        hintText: 'sk-... (leave empty for local-only)',
                        hintStyle: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFF9A9D97),
                        ),
                        filled: true,
                        fillColor: EchoColors.surface,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: const BorderSide(
                            color: EchoColors.border,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      'Base URL',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _baseUrlController,
                      decoration: InputDecoration(
                        hintText: 'https://api.openai.com/v1',
                        filled: true,
                        fillColor: EchoColors.surface,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: const BorderSide(
                            color: EchoColors.border,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 14),
                    const Text(
                      'Model',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextField(
                      controller: _modelController,
                      decoration: InputDecoration(
                        hintText: 'gpt-4o-mini',
                        filled: true,
                        fillColor: EchoColors.surface,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10),
                          borderSide: const BorderSide(
                            color: EchoColors.border,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: EchoColors.forest,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          elevation: 0,
                        ),
                        onPressed: _saveSettings,
                        child: const Text(
                          'Save AI Credentials',
                          style: TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 24),

              // Audio & Network Preferences
              const Text(
                'PREFERENCES',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.2,
                  color: EchoColors.muted,
                ),
              ),
              const SizedBox(height: 10),
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: EchoColors.border),
                ),
                child: Column(
                  children: [
                    SwitchListTile(
                      activeThumbColor: EchoColors.forest,
                      title: const Text(
                        'Keep original audio',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: const Text(
                        'Always preserve source recordings locally',
                        style: TextStyle(fontSize: 11, color: EchoColors.muted),
                      ),
                      value: _keepAudio,
                      onChanged: (val) {
                        setState(() => _keepAudio = val);
                        widget.settingsService.keepAudio = val;
                      },
                    ),
                    const Divider(height: 1, color: EchoColors.border),
                    SwitchListTile(
                      activeThumbColor: EchoColors.forest,
                      title: const Text(
                        'Process on Wi-Fi only',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: const Text(
                        'Reduce mobile data usage',
                        style: TextStyle(fontSize: 11, color: EchoColors.muted),
                      ),
                      value: _wifiOnly,
                      onChanged: (val) {
                        setState(() => _wifiOnly = val);
                        widget.settingsService.wifiOnly = val;
                      },
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 24),

              // Privacy card matching Figma
              const Text(
                'PRIVACY',
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
                child: const Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Your data stays yours',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    SizedBox(height: 6),
                    Text(
                      'Echo stores your original recordings and notes directly on your device. Original audio and text are never modified during AI organization.',
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
