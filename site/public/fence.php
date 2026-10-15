<?php
/*
Streams what the fence monitor is seeing to the browser, so the video page can
show whether the child is moving or sleeping and raise an alert when something
crosses the fence.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(SRC_DIR . '/session.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(SRC_DIR . '/sse.php');

abortIfSessionExpired();
// Whether the child is moving or sleeping is nobody else's business, but this
// stream stays open for as long as the page does, and a request holding the
// session file locked would block every other request from the same browser
session_write_close();

sendSSEHeaders();

$status_file = CONTROL_DIR . '/.comm/fence.json';

if (!file_exists($status_file)) {
  $msg = "Fence status file does not exist: $status_file";
  sendSSEMessage('error', $msg);
  bm_error($msg);
}

$inotify_instance = inotify_init();
if (!$inotify_instance) {
  sendSSEMessage('error', 'Could not initialize inotify');
  bm_error('Could not initialize inotify');
}
stream_set_blocking($inotify_instance, false);

$status_descriptor = inotify_add_watch($inotify_instance, $status_file, IN_CLOSE_WRITE);

// The file is empty until the fence has run for the first time
$initial_status = file_get_contents($status_file);
if (!empty($initial_status)) {
  sendSSEMessage('fence_status', $initial_status);
}

// PHP only notices that the browser has gone away when it tries to write, so
// something is written regularly even when nothing happens, and the request
// ends after a while in any case. The browser reconnects by itself.
define('FENCE_KEEPALIVE_INTERVAL', 15); // [s]
define('FENCE_MAX_LIFETIME', 300); // [s]

@set_time_limit(FENCE_MAX_LIFETIME + 2 * FENCE_KEEPALIVE_INTERVAL);

$end_time = time() + FENCE_MAX_LIFETIME;
while (!connection_aborted() && time() < $end_time) {
  $read = array($inotify_instance);
  $write = null;
  $except = null;
  $timeout = max(0, min(FENCE_KEEPALIVE_INTERVAL, $end_time - time()));
  $n_ready = @stream_select($read, $write, $except, $timeout);
  if ($n_ready === false) {
    break;
  }
  if ($n_ready === 0) {
    echo ": ping\n\n";
    while (ob_get_level() > 0) {
      ob_end_flush();
    }
    flush();
    continue;
  }
  $events = inotify_read($inotify_instance);
  if ($events === false) {
    continue;
  }
  foreach ($events as $event) {
    if ($event['wd'] == $status_descriptor) {
      sendSSEMessage('fence_status', file_get_contents($status_file));
    }
  }
}

fclose($inotify_instance);
