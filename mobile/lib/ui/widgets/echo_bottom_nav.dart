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
    return Container(
      decoration: const BoxDecoration(
        color: EchoColors.surface,
        border: Border(top: BorderSide(color: EchoColors.border, width: 1)),
      ),
      padding: EdgeInsets.only(
        top: 6,
        bottom: MediaQuery.of(context).padding.bottom + 6,
        left: 24,
        right: 24,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _buildNavItem(0, 'Home', Icons.home_outlined, Icons.home),
          _buildNavItem(1, 'Recall', Icons.search_outlined, Icons.search),
          _buildNavItem(
            2,
            'Library',
            Icons.library_books_outlined,
            Icons.library_books,
          ),
        ],
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
    return GestureDetector(
      onTap: () => onTap(index),
      behavior: HitTestBehavior.opaque,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            height: 32,
            width: 56,
            decoration: BoxDecoration(
              color: active ? EchoColors.sageSoft : Colors.transparent,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Icon(
              active ? activeIcon : icon,
              color: active ? EchoColors.forest : EchoColors.muted,
              size: 21,
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
    );
  }
}
