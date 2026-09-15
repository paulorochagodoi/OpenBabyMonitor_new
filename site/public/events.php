<?php
/*
Hands the timeline the events that happened in a time interval, together with
the stretches of time the recordings cover.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(SRC_DIR . '/session.php');
require_once(dirname(__DIR__) . '/config/database_config.php');
require_once(dirname(__DIR__) . '/config/control_config.php');
require_once(SRC_DIR . '/events.php');
require_once(SRC_DIR . '/recordings.php');

abortIfSessionExpired();

define('DEFAULT_INTERVAL', 6 * 3600);

if (!eventsAreAvailable($_DATABASE)) {
  header('Content-Type: application/json');
  echo json_encode(array('available' => false, 'events' => array(), 'recordings' => array()));
  exit();
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['clear'])) {
  deleteAllEvents($_DATABASE);
  if ($_POST['clear'] === 'all') {
    deleteAllRecordings();
  }
  header('Content-Type: application/json');
  echo json_encode(array('cleared' => true));
  exit();
}

$now = microtime(true);
$to = isset($_GET['to']) ? floatval($_GET['to']) : $now;
$from = isset($_GET['from']) ? floatval($_GET['from']) : ($to - DEFAULT_INTERVAL);
$limit = isset($_GET['limit']) ? intval($_GET['limit']) : MAX_EVENTS_PER_REQUEST;

header('Content-Type: application/json');
echo json_encode(array(
  'available' => true,
  'now' => $now,
  'from' => $from,
  'to' => $to,
  'range' => readEventTimeRange($_DATABASE),
  'events' => readEventsInRange($_DATABASE, $from, $to, $limit),
  'recordings' => array_values(readAllRecordingCoverages()),
  'storage' => getRecordingDiskUsage()
));
