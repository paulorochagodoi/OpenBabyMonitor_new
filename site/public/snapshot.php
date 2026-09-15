<?php
/*
Grabs a single frame from the live video stream, which is what the fence is
drawn on top of. The frame is cached for a moment so that reloading the editor
does not start a new decode every time.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(SRC_DIR . '/session.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/error_config.php');

abortIfSessionExpired();

define('SNAPSHOT_MAX_AGE', 3); // [s]

$stream_file = getenv('BM_PICAM_STREAM_FILE');
$snapshot_path = CONTROL_DIR . '/.comm/snapshot.jpg';

if (!$stream_file || !file_exists($stream_file)) {
  // Nothing to take a picture of until the video mode is running
  http_response_code(409);
  header('Content-Type: text/plain');
  echo 'no_stream';
  exit();
}

clearstatcache(true, $snapshot_path);
$is_stale = !file_exists($snapshot_path) || (time() - filemtime($snapshot_path)) > SNAPSHOT_MAX_AGE;

if ($is_stale) {
  $command = 'ffmpeg -y -hide_banner -loglevel error -live_start_index -1 -allowed_extensions ALL'
    . ' -i ' . escapeshellarg($stream_file)
    . ' -frames:v 1 -q:v 5 ' . escapeshellarg($snapshot_path) . ' 2>&1';
  $output = null;
  $result_code = null;
  exec($command, $output, $result_code);
  if ($result_code != 0 || !file_exists($snapshot_path)) {
    bm_warning("Could not take a snapshot of the stream:\n" . join("\n", $output));
    http_response_code(500);
    header('Content-Type: text/plain');
    echo 'snapshot_failed';
    exit();
  }
}

header('Content-Type: image/jpeg');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Content-Length: ' . filesize($snapshot_path));
readfile($snapshot_path);
