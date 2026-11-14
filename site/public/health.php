<?php
require_once(dirname(__DIR__) . '/src/session.php');
header('Content-Type: application/json');
header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
  http_response_code(405);
  header('Allow: GET');
  echo json_encode(array('ok' => false));
  exit();
}
$path = dirname(__DIR__, 2) . '/control/.comm/health.json';
$health = json_decode(@file_get_contents($path), true);
$valid = is_array($health) && isset($health['ts'], $health['ok'], $health['mode'], $health['interval_s'])
  && is_numeric($health['ts']) && is_numeric($health['interval_s']) && $health['interval_s'] > 0;
$stale = !$valid || time() - $health['ts'] > 3 * $health['interval_s'] || $health['ts'] > time();
if (!$valid) {
  $health = array('ok' => false, 'ts' => null, 'mode' => 'unknown');
}
$health['stale'] = $stale;
$health['ok'] = !$stale && $health['ok'];
if (!isLoggedIn()) {
  $health = array_intersect_key($health, array_flip(array('ok', 'ts', 'mode', 'stale')));
}
http_response_code($health['ok'] ? 200 : 503);
echo json_encode($health);
