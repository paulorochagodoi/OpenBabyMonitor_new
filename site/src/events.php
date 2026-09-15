<?php
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(__DIR__ . '/database.php');

define('EVENTS_TABLE', 'events');

// The events the timeline knows how to show
define('EVENT_TYPES', array('crying', 'babbling', 'sound', 'transmission', 'motion', 'outside', 'asleep', 'awake', 'rec_stopped'));

define('MAX_EVENTS_PER_REQUEST', 2000);

function eventsAreAvailable($database) {
  return tableExists($database, EVENTS_TABLE);
}

/*
Reads the events that happened in a time interval, oldest first. The bounds are
converted to numbers before they reach the query, so they cannot carry anything
but a time.
*/
function readEventsInRange($database, $from, $to, $limit = MAX_EVENTS_PER_REQUEST) {
  $from = floatval($from);
  $to = floatval($to);
  $limit = max(1, min(MAX_EVENTS_PER_REQUEST, intval($limit)));

  $query = "SELECT `time`, `type`, `value` FROM `" . EVENTS_TABLE . "` WHERE `time` >= $from AND `time` <= $to ORDER BY `time` ASC LIMIT $limit;";
  $result = $database->query($query);
  if (!$result) {
    bm_error('Could not read the events: ' . $database->error);
  }
  return $result->fetch_all(MYSQLI_ASSOC);
}

function readLatestEvents($database, $limit = 50) {
  $limit = max(1, min(MAX_EVENTS_PER_REQUEST, intval($limit)));
  $query = "SELECT `time`, `type`, `value` FROM `" . EVENTS_TABLE . "` ORDER BY `time` DESC LIMIT $limit;";
  $result = $database->query($query);
  if (!$result) {
    bm_error('Could not read the latest events: ' . $database->error);
  }
  return array_reverse($result->fetch_all(MYSQLI_ASSOC));
}

function readEventTimeRange($database) {
  $query = "SELECT MIN(`time`) AS `first`, MAX(`time`) AS `last` FROM `" . EVENTS_TABLE . "`;";
  $result = $database->query($query);
  if (!$result) {
    bm_error('Could not read the event time range: ' . $database->error);
  }
  $row = $result->fetch_assoc();
  if ($row === null || $row['first'] === null) {
    return null;
  }
  return array('first' => floatval($row['first']), 'last' => floatval($row['last']));
}

function deleteAllEvents($database) {
  if (!$database->query("DELETE FROM `" . EVENTS_TABLE . "`;")) {
    bm_error('Could not delete the events: ' . $database->error);
  }
}
