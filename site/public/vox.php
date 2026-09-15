<?php
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(SRC_DIR . '/sse.php');

sendSSEHeaders();

$inotify_instance = inotify_init();
if (!$inotify_instance) {
  sendSSEMessage('error', 'Could not initialize inotify');
  bm_error('Could not initialize inotify');
}
stream_set_blocking($inotify_instance, true);

$comm_dir = CONTROL_DIR . '/.comm';
$state_file = "$comm_dir/vox_state.json";
$level_file = "$comm_dir/vox_level.dat";

foreach (array($state_file, $level_file) as $file) {
  if (!file_exists($file)) {
    $msg = "VOX communication file does not exist: $file";
    sendSSEMessage('error', $msg);
    bm_error($msg);
  }
}

$state_descriptor = inotify_add_watch($inotify_instance, $state_file, IN_CLOSE_WRITE);
$level_descriptor = inotify_add_watch($inotify_instance, $level_file, IN_CLOSE_WRITE);

// Send the current state immediately, so a client connecting in the middle of a
// transmission does not have to wait for the next state change. The file is empty
// until the VOX mode has been run for the first time.
$initial_state = file_get_contents($state_file);
if (!empty($initial_state)) {
  sendSSEMessage('vox_state', $initial_state);
}

while (!connection_aborted()) {
  $events = inotify_read($inotify_instance);
  foreach ($events as $event) {
    if ($event['wd'] == $state_descriptor) {
      sendSSEMessage('vox_state', file_get_contents($state_file));
    } elseif ($event['wd'] == $level_descriptor) {
      sendSSEMessage('vox_level', file_get_contents($level_file));
    }
  }
}

fclose($inotify_instance);
