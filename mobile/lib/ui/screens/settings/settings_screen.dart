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
  late bool _keepAudio;
  late bool _wifiOnly;
  late bool _evalConsent;

  @override
  void initState() {
    super.initState();
    _keepAudio = widget.settingsService.keepAudio;
    _wifiOnly = widget.settingsService.wifiOnly;
    _evalConsent = widget.settingsService.evalConsent;
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
              Material(
                color: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: const BorderSide(color: EchoColors.border),
                ),
                clipBehavior: Clip.antiAlias,
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
                    const Divider(height: 1, color: EchoColors.border),
                    SwitchListTile(
                      activeThumbColor: EchoColors.forest,
                      title: const Text(
                        'Evaluation dataset participation',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: const Text(
                        'Explicit opt-in: Allow server to retain audio recordings for offline pipeline quality evaluation. Disabled by default.',
                        style: TextStyle(fontSize: 11, color: EchoColors.muted),
                      ),
                      value: _evalConsent,
                      onChanged: (val) {
                        setState(() => _evalConsent = val);
                        widget.settingsService.evalConsent = val;
                      },
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 24),

              // Privacy card matching Figma
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
                      'Echo stores your source notes on-device and uses the server for transcription, structured knowledge extraction, and embedding-based semantic recall. Audio is not retained on the server unless you opt in to evaluation participation.',
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
