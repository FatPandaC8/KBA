import 'dart:async';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';

import 'package:mobile/core/theme/echo_colors.dart';

/// Plays either a local file or authenticated server bytes.
///
/// Server audio is fetched through the owner-scoped API on demand; no public
/// URL is ever constructed (VR-02).
class AudioPlayerWidget extends StatefulWidget {
  final String? audioPath;
  final int? durationMs;
  final Future<Uint8List> Function()? remoteAudioLoader;

  const AudioPlayerWidget({
    super.key,
    this.audioPath,
    this.durationMs,
    this.remoteAudioLoader,
  }) : assert(
         audioPath != null || remoteAudioLoader != null,
         'Provide audioPath or remoteAudioLoader',
       );

  @override
  State<AudioPlayerWidget> createState() => _AudioPlayerWidgetState();
}

class _AudioPlayerWidgetState extends State<AudioPlayerWidget> {
  final AudioPlayer _player = AudioPlayer();
  bool _isPlaying = false;
  bool _isLoading = false;
  String? _error;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  StreamSubscription? _posSub;
  StreamSubscription? _durSub;
  StreamSubscription? _stateSub;

  @override
  void initState() {
    super.initState();
    if (widget.durationMs != null && widget.durationMs! > 0) {
      _duration = Duration(milliseconds: widget.durationMs!);
    }

    _posSub = _player.onPositionChanged.listen((p) {
      if (mounted) setState(() => _position = p);
    });
    _durSub = _player.onDurationChanged.listen((d) {
      if (mounted) setState(() => _duration = d);
    });
    _stateSub = _player.onPlayerStateChanged.listen((state) {
      if (mounted) setState(() => _isPlaying = state == PlayerState.playing);
    });
  }

  @override
  void dispose() {
    _posSub?.cancel();
    _durSub?.cancel();
    _stateSub?.cancel();
    _player.dispose();
    super.dispose();
  }

  Future<void> _togglePlay() async {
    if (_isPlaying) {
      await _player.pause();
      return;
    }

    setState(() {
      _error = null;
      _isLoading = true;
    });
    try {
      final path = widget.audioPath;
      if (path != null && path.isNotEmpty) {
        await _player.play(DeviceFileSource(path));
      } else {
        final bytes = await widget.remoteAudioLoader!();
        await _player.play(BytesSource(bytes));
      }
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'Audio could not be played.');
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  String _formatTime(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    final progress = _duration.inMilliseconds > 0
        ? (_position.inMilliseconds / _duration.inMilliseconds).clamp(0.0, 1.0)
        : 0.0;

    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: EchoColors.border),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: const BoxDecoration(
                  color: EchoColors.forest,
                  shape: BoxShape.circle,
                ),
                child: IconButton(
                  icon: _isLoading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            color: Colors.white,
                            strokeWidth: 2,
                          ),
                        )
                      : Icon(
                          _isPlaying ? Icons.pause : Icons.play_arrow,
                          color: Colors.white,
                          size: 20,
                        ),
                  padding: EdgeInsets.zero,
                  onPressed: _isLoading ? null : _togglePlay,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(3),
                      child: LinearProgressIndicator(
                        value: progress,
                        minHeight: 4,
                        backgroundColor: const Color(0xFFE1E3DF),
                        valueColor: const AlwaysStoppedAnimation<Color>(
                          EchoColors.sage,
                        ),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '${_formatTime(_position)} / ${_formatTime(_duration)}',
                          style: const TextStyle(
                            fontSize: 10,
                            color: EchoColors.muted,
                          ),
                        ),
                        const Text(
                          'Original audio',
                          style: TextStyle(
                            fontSize: 9,
                            color: EchoColors.muted,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (_error != null) ...[
            const SizedBox(height: 6),
            Text(
              _error!,
              style: const TextStyle(fontSize: 10, color: EchoColors.danger),
            ),
          ],
        ],
      ),
    );
  }
}
