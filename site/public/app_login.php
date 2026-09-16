<?php
/*
Pairs a phone with the device.

The app sends the monitor password once, over a connection whose certificate it
has pinned, and gets back a token it keeps from then on. The password is never
stored on the phone.

This is deliberately not part of the browser session: the app has to stay
connected all night, and a PHP session that expires after twenty minutes is the
wrong tool for that.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/database_config.php');
require_once(SRC_DIR . '/security.php');
require_once(SRC_DIR . '/app_auth.php');

requireEncryptedConnection();

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
  sendAppError(405, 'method_not_allowed');
}

if (!appTokensAreAvailable($_DATABASE)) {
  sendAppError(503, 'not_installed');
}

$request = $_POST;
if (empty($request)) {
  $body = file_get_contents('php://input');
  $decoded = json_decode($body, true);
  if (is_array($decoded)) {
    $request = $decoded;
  }
}

$password = isset($request['password']) ? $request['password'] : '';
$device = isset($request['device']) ? trim($request['device']) : '';
if ($device === '') {
  $device = 'Android';
}

if (appLoginIsBlocked()) {
  sendAppError(429, 'too_many_attempts');
}

if (!password_verify($password, readHashedPassword($_DATABASE))) {
  recordAppLoginFailure();
  sleep(APP_LOGIN_FAILURE_DELAY);
  sendAppError(401, 'wrong_password');
}

clearAppLoginFailures();

sendAppJSON(array(
  'token' => createAppToken($_DATABASE, $device),
  'device' => $device
));
