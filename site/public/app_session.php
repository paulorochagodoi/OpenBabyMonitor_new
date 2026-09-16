<?php
/*
Lets the app open the web interface without asking for the password again.

The app holds a token, not a password, so it cannot fill in the sign in form.
Instead it loads this page with its token in a header, and gets back the same
session cookie the form would have given it, along with a redirect to wherever
it wanted to go.

A token is therefore worth as much as the password for as long as it is valid,
which is the point of being able to revoke one phone at a time.
*/
require_once(dirname(__DIR__) . '/config/path_config.php');
require_once(SRC_DIR . '/session.php');
require_once(dirname(__DIR__) . '/config/error_config.php');
require_once(dirname(__DIR__) . '/config/env_config.php');
require_once(dirname(__DIR__) . '/config/database_config.php');
require_once(SRC_DIR . '/app_auth.php');

requireEncryptedConnection();
requireAppToken($_DATABASE);

$_SESSION['login'] = true;

// Only somewhere inside the site itself, so a token cannot be used to bounce a
// signed in browser off to another address
$target = isset($_GET['target']) ? $_GET['target'] : 'main.php';
if (!preg_match('/^[A-Za-z0-9_]+\.php(\?[A-Za-z0-9_=&%.\-]*)?$/', $target)) {
  $target = 'main.php';
}

redirectTo($target);
