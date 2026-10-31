import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

class EchoBottomNav extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const EchoBottomNav({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    // Grow the bar slightly with the system font scale instead of letting
    // labels overflow the fixed template height.
    final textScale = MediaQuery.textScalerOf(context)
        .scale(1.0)
        .clamp(0.8, 1.4);
    final barHeight = 72.0 + (textScale - 1.0) * 26.0;
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return MediaQuery.withClampedTextScaling(
      maxScaleFactor: 1.3,
      child: Container(
        height: barHeight + bottomPadding,
        padding: EdgeInsets.fromLTRB(20, 8, 20, bottomPadding + 6),
        decoration: const BoxDecoration(
          color: EchoColors.surface,
          border: Border(top: BorderSide(color: EchoColors.border)),
        ),
        child: Row(
          children: [
            Expanded(
              child: _buildNavItem(0, 'Record', Icons.mic_none, Icons.mic),
            ),
            Expanded(
              child: _buildNavItem(1, 'Graph', Icons.hub_outlined, Icons.hub),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildNavItem(
    int index,
    String label,
    IconData icon,
    IconData activeIcon,
  ) {
    final active = currentIndex == index;
    return Semantics(
      button: true,
      selected: active,
      label: label,
      excludeSemantics: true,
      child: GestureDetector(
        onTap: () => onTap(index),
        behavior: HitTestBehavior.opaque,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              height: 36,
              width: 60,
              decoration: BoxDecoration(
                color: active ? EchoColors.sageSoft : Colors.transparent,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Icon(
                active ? activeIcon : icon,
                color: active ? EchoColors.forest : EchoColors.muted,
                size: 22,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                color: active ? EchoColors.forest : EchoColors.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
