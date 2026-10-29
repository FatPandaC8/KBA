import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

class AudioService {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  String? _currentRecordingPath;
  DateTime? _recordingStartTime;

  Future<bool> checkPermission() async {
    final status = await Permission.microphone.status;
    return status.isGranted;
  }

  Future<bool> requestPermission() async {
    final status = await Permission.microphone.request();
    return status.isGranted;
  }

  Future<void> startRecording() async {
    final hasPerm = await checkPermission();
    if (!hasPerm) {
      final granted = await requestPermission();
      if (!granted) {
        throw Exception('Microphone permission denied');
      }
    }

    final docsDir = await getApplicationDocumentsDirectory();
    final audioDir = Directory(p.join(docsDir.path, 'recordings'));
    if (!await audioDir.exists()) {
      await audioDir.create(recursive: true);
    }

    final filename = 'capture_${DateTime.now().millisecondsSinceEpoch}.m4a';
    final filePath = p.join(audioDir.path, filename);
    _currentRecordingPath = filePath;
    _recordingStartTime = DateTime.now();

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
        bitRate: 64000,
        sampleRate: 44100,
      ),
      path: filePath,
    );
  }

  Future<({String path, int durationMs})?> stopRecording() async {
    if (!await _recorder.isRecording()) return null;

    final path = await _recorder.stop();
    final durationMs = _recordingStartTime != null
        ? DateTime.now().difference(_recordingStartTime!).inMilliseconds
        : 0;

    _recordingStartTime = null;
    if (path != null && File(path).existsSync()) {
      return (path: path, durationMs: durationMs);
    }
    return null;
  }

  Future<void> cancelRecording() async {
    if (await _recorder.isRecording()) {
      await _recorder.stop();
    }
    if (_currentRecordingPath != null) {
      try {
        final f = File(_currentRecordingPath!);
        if (await f.exists()) await f.delete();
      } catch (_) {}
      _currentRecordingPath = null;
    }
    _recordingStartTime = null;
  }

  Future<bool> isRecording() => _recorder.isRecording();

  // Playback helpers
  AudioPlayer get player => _player;

  Future<void> play(String path) async {
    await _player.stop();
    await _player.play(DeviceFileSource(path));
  }

  /// Plays authenticated audio bytes fetched from the server (VR-02). Bytes
  /// are handed to the player directly, so no public URL or temp file leaks.
  Future<void> playBytes(Uint8List bytes) async {
    await _player.stop();
    await _player.play(BytesSource(bytes));
  }

  Future<void> pause() => _player.pause();
  Future<void> stop() => _player.stop();

  void dispose() {
    _recorder.dispose();
    _player.dispose();
  }
}
