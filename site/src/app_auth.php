<?php
/*
Authentication for the Android app.

The web application signs in with a password and keeps a PHP session, which is
right for a browser but wrong for an app that has to stay connected for a whole
night. The app instead exchanges the password once for a long lived token, and
sends that token with every request afterwards.

Only a hash of the token is stored, so a copy of the database does not hand
anyone access to the monitor, and each phone gets its own row so a single lost
phone can be revoked without touching the others.
*/
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(__DIR__ . '/database.php');

define('APP_TOKENS_TABLE', 'app_tokens');

// Tokens carry 256 bits of randomness, so they are hashed with a plain fast
// hash. A slow password hash exists to make guessing a low entropy secret
// expensive, and there is nothing here to guess.
define('APP_TOKEN_BYTES', 32);

// A failed sign in attempt costs this much delay, and after too many failures
// within the window no attempt is accepted at all
define('APP_LOGIN_FAILURE_DELAY', 1); // [s]
define('APP_LOGIN_MAX_FAILURES', 5);
define('APP_LOGIN_FAILURE_WINDOW', 900); // [s]

function appTokensAreAvailable($database) {
  return tableExists($database, APP_TOKENS_TABLE);
}

function hashAppToken($token) {
  return hash('sha256', $token);
}

/*
Creates a token for a phone and returns it. This is the only time the token
exists in readable form, so the caller has to pass it on to the phone right away.
*/
function createAppToken($database, $device) {
  $token = bin2hex(random_bytes(APP_TOKEN_BYTES));
  $hash = hashAppToken($token);
  $device = mb_substr($device, 0, 64);
  $now = microtime(true);

  // The device name is whatever the phone calls itself, so it goes in as a
  // parameter rather than through the shared insert helper, which builds its
  // statement by interpolating the values
  $statement = $database->prepare('INSERT INTO `' . APP_TOKENS_TABLE
    . '` (`token_hash`, `device`, `created`, `last_seen`) VALUES (?, ?, ?, ?);');
  if (!$statement) {
    bm_error('Could not prepare the token insertion: ' . $database->error);
  }
  $statement->bind_param('ssdd', $hash, $device, $now, $now);
  if (!$statement->execute()) {
    bm_error('Could not store the token: ' . $database->error);
  }
  $statement->close();

  return $token;
}

/*
Reads the token the app sent. The Authorization header is dropped by some Apache
configurations before PHP ever sees it, so a header of our own is the one that is
relied on and Authorization is only a fallback.
*/
function readAppTokenFromRequest() {
  if (isset($_SERVER['HTTP_X_BM_TOKEN'])) {
    return trim($_SERVER['HTTP_X_BM_TOKEN']);
  }
  $headers = array();
  if (function_exists('apache_request_headers')) {
    $headers = apache_request_headers();
  } elseif (function_exists('getallheaders')) {
    $headers = getallheaders();
  }
  foreach ($headers as $name => $value) {
    if (strcasecmp($name, 'X-BM-Token') === 0) {
      return trim($value);
    }
    if (strcasecmp($name, 'Authorization') === 0 && stripos($value, 'Bearer ') === 0) {
      return trim(substr($value, 7));
    }
  }
  if (isset($_SERVER['HTTP_AUTHORIZATION']) && stripos($_SERVER['HTTP_AUTHORIZATION'], 'Bearer ') === 0) {
    return trim(substr($_SERVER['HTTP_AUTHORIZATION'], 7));
  }
  return null;
}

/*
Returns the row of the phone the request came from, or false. The lookup is done
on the hash rather than by comparing every row, and hash_equals is still used so
that a timing difference cannot leak which hashes exist.
*/
function findAppToken($database, $token) {
  if (!$token || !ctype_xdigit($token) || strlen($token) !== APP_TOKEN_BYTES * 2) {
    return false;
  }
  $statement = $database->prepare(
    'SELECT `id`, `token_hash`, `device` FROM `' . APP_TOKENS_TABLE . '` WHERE `token_hash` = ? LIMIT 1;');
  if (!$statement) {
    bm_error('Could not prepare the token lookup: ' . $database->error);
  }
  $hash = hashAppToken($token);
  $statement->bind_param('s', $hash);
  if (!$statement->execute()) {
    bm_error('Could not look up the token: ' . $database->error);
  }
  $row = $statement->get_result()->fetch_assoc();
  $statement->close();

  if ($row === null || !hash_equals($row['token_hash'], $hash)) {
    return false;
  }
  return $row;
}

function touchAppToken($database, $id) {
  $statement = $database->prepare(
    'UPDATE `' . APP_TOKENS_TABLE . '` SET `last_seen` = ? WHERE `id` = ?;');
  if (!$statement) {
    return;
  }
  $now = microtime(true);
  $statement->bind_param('di', $now, $id);
  $statement->execute();
  $statement->close();
}

/*
Ends the request with 401 unless it carries a valid token. Every app endpoint
starts with this.
*/
function requireAppToken($database) {
  if (!appTokensAreAvailable($database)) {
    sendAppError(503, 'not_installed');
  }
  $row = findAppToken($database, readAppTokenFromRequest());
  if ($row === false) {
    sendAppError(401, 'unauthorized');
  }
  touchAppToken($database, $row['id']);
  return $row;
}

function readAppDevices($database) {
  $result = $database->query(
    'SELECT `id`, `device`, `created`, `last_seen` FROM `' . APP_TOKENS_TABLE . '` ORDER BY `created` ASC;');
  if (!$result) {
    bm_error('Could not read the paired devices: ' . $database->error);
  }
  return $result->fetch_all(MYSQLI_ASSOC);
}

function revokeAppToken($database, $id) {
  $statement = $database->prepare('DELETE FROM `' . APP_TOKENS_TABLE . '` WHERE `id` = ?;');
  if (!$statement) {
    bm_error('Could not prepare the revocation: ' . $database->error);
  }
  $id = intval($id);
  $statement->bind_param('i', $id);
  $statement->execute();
  $statement->close();
}

function revokeAllAppTokens($database) {
  if (!$database->query('DELETE FROM `' . APP_TOKENS_TABLE . '`;')) {
    bm_error('Could not revoke the paired devices: ' . $database->error);
  }
}

/*
Keeps someone who can reach the device from trying passwords at speed. The
attempts are kept in a file rather than the database so that a flood of them
cannot fill up a table.
*/
function getAppLoginAttemptsFile() {
  return dirname(__DIR__, 2) . '/control/.comm/app_login_attempts.json';
}

function readAppLoginFailures() {
  $path = getAppLoginAttemptsFile();
  if (!file_exists($path)) {
    return array();
  }
  $content = @file_get_contents($path);
  if ($content === false) {
    return array();
  }
  $failures = json_decode($content, true);
  if (!is_array($failures)) {
    return array();
  }
  $cutoff = microtime(true) - APP_LOGIN_FAILURE_WINDOW;
  return array_values(array_filter($failures, function ($time) use ($cutoff) {
    return is_numeric($time) && $time > $cutoff;
  }));
}

function appLoginIsBlocked() {
  return count(readAppLoginFailures()) >= APP_LOGIN_MAX_FAILURES;
}

function recordAppLoginFailure() {
  $failures = readAppLoginFailures();
  $failures[] = microtime(true);
  @file_put_contents(getAppLoginAttemptsFile(), json_encode($failures));
}

function clearAppLoginFailures() {
  @file_put_contents(getAppLoginAttemptsFile(), json_encode(array()));
}

function sendAppJSON($data, $status = 200) {
  http_response_code($status);
  header('Content-Type: application/json');
  header('Cache-Control: no-store');
  echo json_encode($data);
  exit();
}

function sendAppError($status, $error) {
  sendAppJSON(array('error' => $error), $status);
}

/*
The password may only cross an encrypted connection. The app pins the
certificate of the device, so it always has one.
*/
function requireEncryptedConnection() {
  $is_encrypted = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
    || (isset($_SERVER['SERVER_PORT']) && $_SERVER['SERVER_PORT'] == 443);
  if (!$is_encrypted) {
    sendAppError(403, 'needs_https');
  }
}
