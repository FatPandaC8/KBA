// Driver for e2e perf runs (integration_test binding). The integration test
// reports FrameTiming summaries per run; the driver saves them to stdout and
// to a JSON file for the e2e perf report.
import 'dart:io';

import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver(
      writeResponseOnFailure: true,
      responseDataCallback: (data) async {
        if (data == null) return;
        final file = File('build/perf_report.json');
        await file.writeAsString(data.toString());
        stdout.writeln('PERF_REPORT_FILE ${file.absolute.path}');
      },
    );
