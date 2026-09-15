<?php
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(dirname(__DIR__) . '/config/path_config.php');

define('RECORDING_KINDS', array('video', 'audio'));
// Where the recordings are reachable from the browser
define('RECORDING_URL_PREFIX', 'recordings');

function getRecordingDir() {
  $dir = getenv('BM_RECORDING_DIR');
  return $dir ? $dir : realpath(dirname(SITE_DIR)) . '/recordings';
}

function getRecordingPlaylistPath($kind) {
  return getRecordingDir() . "/$kind/index.m3u8";
}

function getRecordingPlaylistUrl($kind) {
  return RECORDING_URL_PREFIX . "/$kind/index.m3u8";
}

/*
Works out which stretch of time a recording covers, by following the wall clock
times the recorder wrote into the playlist. Returns null when there is nothing
recorded.
*/
function readRecordingCoverage($kind) {
  $playlist_path = getRecordingPlaylistPath($kind);
  if (!file_exists($playlist_path)) {
    return null;
  }

  $lines = file($playlist_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
  if ($lines === false) {
    return null;
  }

  $start = null;
  $cursor = null;
  $end = null;
  $segment_count = 0;

  foreach ($lines as $line) {
    if (strpos($line, '#EXT-X-PROGRAM-DATE-TIME:') === 0) {
      $timestamp = parsePlaylistDate(substr($line, strlen('#EXT-X-PROGRAM-DATE-TIME:')));
      if ($timestamp !== null) {
        $cursor = $timestamp;
        if ($start === null) {
          $start = $timestamp;
        }
      }
    } elseif (strpos($line, '#EXTINF:') === 0) {
      $duration = floatval(substr($line, strlen('#EXTINF:')));
      $segment_count += 1;
      if ($cursor !== null) {
        $cursor += $duration;
        $end = $cursor;
      }
    }
  }

  if ($start === null || $end === null) {
    return null;
  }

  return array(
    'kind' => $kind,
    'url' => getRecordingPlaylistUrl($kind),
    'start' => $start,
    'end' => $end,
    'segments' => $segment_count
  );
}

function parsePlaylistDate($text) {
  $text = trim($text);
  if ($text === '') {
    return null;
  }
  // The recorder writes ISO 8601 with milliseconds, which strtotime truncates
  // to whole seconds. That is precise enough for finding a moment again.
  $timestamp = strtotime($text);
  return ($timestamp === false) ? null : floatval($timestamp);
}

function readAllRecordingCoverages() {
  $coverages = array();
  foreach (RECORDING_KINDS as $kind) {
    $coverage = readRecordingCoverage($kind);
    if ($coverage !== null) {
      $coverages[$kind] = $coverage;
    }
  }
  return $coverages;
}

function getRecordingDiskUsage() {
  $dir = getRecordingDir();
  if (!is_dir($dir)) {
    return null;
  }
  $total = 0;
  foreach (RECORDING_KINDS as $kind) {
    foreach (glob("$dir/$kind/*.ts") as $path) {
      $size = filesize($path);
      if ($size !== false) {
        $total += $size;
      }
    }
  }
  $free = disk_free_space($dir);
  return array('used' => $total, 'free' => ($free === false) ? null : $free);
}

function deleteAllRecordings() {
  $dir = getRecordingDir();
  foreach (RECORDING_KINDS as $kind) {
    foreach (glob("$dir/$kind/*.ts") as $path) {
      @unlink($path);
    }
    @unlink("$dir/$kind/index.m3u8");
  }
}
