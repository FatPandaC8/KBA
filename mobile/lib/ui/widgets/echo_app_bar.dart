import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class EchoAppBar extends StatelessWidget implements PreferredSizeWidget {
  final String title;
  final VoidCallback? onBack;
  final VoidCallback? onSettings;

  const EchoAppBar({
    super.key,
    required this.title,
    this.onBack,
    this.onSettings,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      color: EchoColors.surface,
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 6,
        left: 16,
        right: 16,
        bottom: 8,
      ),
      child: SizedBox(
        height: 52,
        child: Row(
          children: [
            // Left: Back button if present
            if (onBack != null)
              IconButton(
                tooltip: 'Back',
                icon: const Icon(
                  Icons.arrow_back_ios_new,
                  size: 20,
                  color: EchoColors.ink,
                ),
                onPressed: onBack,
                splashRadius: 20,
              )
            else
              const SizedBox(width: 24),

            // Middle: Title
            Expanded(
              child: Text(
                title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.15,
                  color: EchoColors.ink,
                ),
              ),
            ),

            // Right: Settings or spacer
            if (onSettings != null)
              IconButton(
                tooltip: 'Settings',
                icon: const Icon(
                  Icons.settings_outlined,
                  size: 22,
                  color: EchoColors.ink,
                ),
                onPressed: onSettings,
                splashRadius: 20,
              )
            else
              const SizedBox(width: 40),
          ],
        ),
      ),
    );
  }

  @override
  Size get preferredSize => const Size.fromHeight(68);
}
