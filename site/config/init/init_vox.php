<?php
/*
Prepares the database for the VOX mode without touching any other data, so it can
be run on an already installed baby monitor. It creates the vox_settings table if
it is missing, adds any settings that have been introduced since the table was
created, and leaves existing settings untouched.
*/
include_once(dirname(__DIR__) . '/error_config.php');
require_once(dirname(__DIR__) . '/env_config.php');
require_once(dirname(__DIR__) . '/config.php');
require_once(SRC_DIR . '/database.php');

$table_name = 'vox_settings';

$database_info = $_CONFIG['database'];
$account_info = $database_info['account'];
$db_name = $database_info['name'];

echo "Connecting to database $db_name with user " . $account_info['user'] . "\n";
$database = connectToDatabase($account_info['host'], $account_info['user'], $account_info['password'], $db_name);

if (count($argv) > 1 && $argv[1] == '--drop') {
  echo "Dropping table $table_name from database $db_name\n";
  dropTableIfExists($database, $table_name);
  closeConnection($database);
  exit(0);
}

$columns = readTableColumnsFromConfig($table_name);
$initial_values = readTableInitialValuesFromConfig($table_name);

$added_columns = array();

if (tableExists($database, $table_name)) {
  echo "Table $table_name already exists\n";
  $existing_columns = getTableColumnNames($database, $table_name);
  foreach ($columns as $column_name => $type) {
    if (!in_array($column_name, $existing_columns)) {
      echo "Adding missing setting $column_name to table $table_name\n";
      addTableColumn($database, $table_name, $column_name, $type);
      array_push($added_columns, $column_name);
    }
  }
} else {
  echo "Creating table $table_name in database $db_name\n";
  createTableIfMissing($database, $table_name, $columns);
}

if (!tableKeyExists($database, $table_name, 'id', 0)) {
  echo "Writing initial values to table $table_name\n";
  insertValuesIntoTable($database, $table_name, $initial_values);
} elseif (!empty($added_columns)) {
  echo "Writing initial values for the added settings\n";
  $values = array('id' => 0);
  foreach ($added_columns as $column_name) {
    $values[$column_name] = $initial_values[$column_name];
  }
  updateValuesInTable($database, $table_name, $values);
} else {
  echo "Existing VOX settings were left unchanged\n";
}

echo "Closing connection to database $db_name\n";
closeConnection($database);
