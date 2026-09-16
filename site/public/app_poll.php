<?php
/*
What the app listens to.

The phone keeps one request open here. If anything has happened since the time
it passed, the answer comes back immediately; otherwise the request waits until
something happens or the budget runs out, and the phone reconnects. That gives
alerts within a second of the event without the phone having to poll in a loop,
which is what would drain the battery.

Nothing is pushed through anyone else's server: the phone talks straight to the
device over the local network.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/database_config.php');
require_once(dirname(__DIR__) . '/config/control_config.php');
require_once(SRC_DIR . '/events.php');
require_once(SRC_DIR . '/app_auth.php');

// How long a request may wait for something to happen. Kept below a minute so
// that the phone notices a dead connection reasonably quickly, and so that no
// proxy or timeout in between decides to cut it first.
define('APP_POLL_TIMEOUT', 50.0); // [s]
define('APP_POLL_INTERVAL', 200000); // [microseconds]

define('APP_MAX_EVENTS', 100);

requireAppToken($_DATABASE);

// The waiting below has to be allowed to outlast the default execution limit
@set_time_limit(0);

$comm_dir = CONTROL_DIR . '/.comm';
$fence_file = $comm_dir . '/fence.json';

function readModeName($database) {
  $value = readValuesFromTable($database, 'modes', 'current', true);
  return array_key_exists($value, MODE_NAMES) ? MODE_NAMES[$value] : 'unknown';
}

function readFenceStatus($fence_file) {
  if (!file_exists($fence_file)) {
    return null;
  }
  $content = @file_get_contents($fence_file);
  if ($content === false || $content === '') {
    return null;
  }
  $status = json_decode($content, true);
  return is_array($status) ? $status : null;
}

/*
Strictly newer than what the phone already has. The bound is turned into a
number before it reaches the query, so it cannot carry anything but a time, and
using > rather than >= is what keeps an event from being delivered, and notified
about, twice.
*/
function readNewEvents($database, $since) {
  if (!eventsAreAvailable($database)) {
    return array();
  }
  $since = floatval($since);
  $limit = APP_MAX_EVENTS;
  $result = $database->query("SELECT `time`, `type`, `value` FROM `" . EVENTS_TABLE
    . "` WHERE `time` > $since ORDER BY `time` ASC LIMIT $limit;");
  if (!$result) {
    bm_error('Could not read the events for the app: ' . $database->error);
  }
  return $result->fetch_all(MYSQLI_ASSOC);
}

function respond($database, $fence_file, $now, $events) {
  sendAppJSON(array(
    'now' => $now,
    'mode' => readModeName($database),
    'events' => $events,
    'fence' => readFenceStatus($fence_file)
  ));
}

/*
Reads the time before the events, never after. The phone sends this value back
as the point to continue from, so an event stored between the two reads has to
land after it and be delivered next time, rather than before it and be lost.
*/
function respondWithEvents($database, $fence_file, $since) {
  $now = microtime(true);
  respond($database, $fence_file, $now, readNewEvents($database, $since));
}

$since = isset($_GET['since']) ? floatval($_GET['since']) : 0.0;
$should_wait = !isset($_GET['wait']) || $_GET['wait'] !== '0';

// A phone that has just been paired asks for nothing but the current state, and
// gets back the time to start watching from
if ($since <= 0.0) {
  respond($_DATABASE, $fence_file, microtime(true), array());
}

$now = microtime(true);
$events = readNewEvents($_DATABASE, $since);
if (!empty($events) || !$should_wait || !is_dir($comm_dir)) {
  respond($_DATABASE, $fence_file, $now, $events);
}

$inotify_instance = inotify_init();
if (!$inotify_instance) {
  // Without inotify the phone falls back to asking again in a moment
  respond($_DATABASE, $fence_file, $now, array());
}
stream_set_blocking($inotify_instance, false);

// Watching the directories rather than the files means a file that is replaced
// instead of rewritten does not silently stop waking us up
inotify_add_watch($inotify_instance, $comm_dir, IN_CLOSE_WRITE | IN_MOVED_TO);
$signal_dir = dirname(MODE_SIGNAL_FILE_STEM);
if (is_dir($signal_dir)) {
  inotify_add_watch($inotify_instance, $signal_dir, IN_ATTRIB | IN_CLOSE_WRITE);
}

$deadline = microtime(true) + APP_POLL_TIMEOUT;
while (microtime(true) < $deadline) {
  if (inotify_read($inotify_instance) !== false) {
    break;
  }
  usleep(APP_POLL_INTERVAL);
}

fclose($inotify_instance);

respondWithEvents($_DATABASE, $fence_file, $since);
