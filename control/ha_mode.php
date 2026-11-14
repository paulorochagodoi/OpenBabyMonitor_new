<?php
// Local CLI adapter: deliberately has no HTTP entry point or session bypass.
if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit(1);
}
require_once(dirname(__DIR__) . '/site/src/mode.php');
$names = array('standby', 'listen', 'audiostream', 'videostream', 'vox');
if ($argc === 1) {
    $value = readCurrentMode($_DATABASE);
    foreach ($names as $name) {
        if (MODE_VALUES[$name] == $value) {
            echo $name;
            exit(0);
        }
    }
    exit(1);
}
if ($argc !== 2 || !in_array($argv[1], $names, true)) {
    exit(1);
}
echo switchMode($_DATABASE, MODE_VALUES[$argv[1]]);
