<?php
require_once(__DIR__ . '/path_config.php');
require_once(SRC_DIR . '/session.php');
require_once(__DIR__ . '/error_config.php');
require_once(__DIR__ . '/env_config.php');
require_once(__DIR__ . '/config.php');
require_once(__DIR__ . '/network_config.php');
require_once(__DIR__ . '/database_config.php');
require_once(__DIR__ . '/control_config.php');
require_once(__DIR__ . '/monitoring_config.php');
require_once(SRC_DIR . '/security.php');
require_once(SRC_DIR . '/database.php');
require_once(SRC_DIR . '/mode.php');
require_once(SRC_DIR . '/control.php');
require_once(SRC_DIR . '/network.php');
require_once(__DIR__ . '/language_config.php');

switch (basename($_SERVER['SCRIPT_NAME'])) {
  case 'main.php':
    define('LOCATION', 'main');
    break;
  case 'listen_settings.php':
    define('LOCATION', 'listen_settings');
    break;
  case 'vox_settings.php':
    define('LOCATION', 'vox_settings');
    break;
  case 'recording_settings.php':
    define('LOCATION', 'recording_settings');
    break;
  case 'fence_settings.php':
    define('LOCATION', 'fence_settings');
    break;
  case 'timeline.php':
    define('LOCATION', 'timeline');
    break;
  case 'audiostream_settings.php':
    define('LOCATION', 'audiostream_settings');
    break;
  case 'videostream_settings.php':
    define('LOCATION', 'videostream_settings');
    break;
  case 'network_settings.php':
    define('LOCATION', 'network_settings');
    break;
  case 'system_settings.php':
    define('LOCATION', 'system_settings');
    break;
  case 'server_status.php':
    define('LOCATION', 'server_status');
    break;
  case 'debugging.php':
    define('LOCATION', 'debugging');
    break;
  case 'documentation.php':
    define('LOCATION', 'documentation');
    break;
  default:
    define('LOCATION', 'login');
    break;
}

define('MIC_CONNECTED', microphoneIsConnected());
if (!MIC_CONNECTED && LOCATION != 'login') {
  logout('index.php');
}

define('USES_CAMERA', cameraIsConnected());

// The VOX mode is only offered once it has been installed with install_vox.sh
define('VOX_AVAILABLE', array_key_exists('vox', MODE_VALUES) && tableExists($_DATABASE, 'vox_settings'));

// The timeline needs somewhere to read events from, which both the recording and
// the fence install
define('EVENTS_AVAILABLE', array_key_exists('events', $_CONFIG) && tableExists($_DATABASE, 'events'));

// The recording is only offered once it has been installed with
// install_recording.sh
define('RECORDING_AVAILABLE', array_key_exists('recording_settings', $_CONFIG)
  && tableExists($_DATABASE, 'recording_settings'));

// The fence needs a camera to watch, and install_fence.sh to have been run
define('FENCE_AVAILABLE', USES_CAMERA && array_key_exists('fence_settings', $_CONFIG)
  && tableExists($_DATABASE, 'fence_settings'));

if (isset($_COOKIE['color_scheme'])) {
  define('COLOR_SCHEME', $_COOKIE['color_scheme']);
} else {
  define('COLOR_SCHEME', 'light');
}
