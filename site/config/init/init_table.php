<?php
/*
Prepares one table from the configuration file without touching any other data,
so it can be run on an already installed baby monitor.

It creates the table if it is missing, adds columns that have been introduced
since the table was created, and leaves values that are already stored alone.
Tables that define their own id column, like the event log, are treated as
tables of many rows and are left empty; the rest are settings tables and get
their initial values written when they are created.

Usage: init_table.php <table name> [--drop]
*/
include_once(dirname(__DIR__) . '/error_config.php');
require_once(dirname(__DIR__) . '/env_config.php');
require_once(dirname(__DIR__) . '/config.php');
require_once(SRC_DIR . '/database.php');

if (count($argv) < 2) {
  bm_error('The table name must be passed as the first command line argument');
}

$table_name = $argv[1];
$should_drop = (count($argv) > 2 && $argv[2] == '--drop');

global $_CONFIG;
if (!array_key_exists($table_name, $_CONFIG)) {
  bm_error("There is no definition of the table $table_name in the configuration file");
}

$database_info = $_CONFIG['database'];
$account_info = $database_info['account'];
$db_name = $database_info['name'];

echo "Connecting to database $db_name with user " . $account_info['user'] . "\n";
$database = connectToDatabase($account_info['host'], $account_info['user'], $account_info['password'], $db_name);

if ($should_drop) {
  echo "Dropping table $table_name from database $db_name\n";
  dropTableIfExists($database, $table_name);
  closeConnection($database);
  exit(0);
}

// A table that brings its own id holds many rows and has no initial values
$has_own_id = array_key_exists('id', $_CONFIG[$table_name]);
$columns = readTableColumnsFromConfig($table_name, !$has_own_id);
$initial_values = $has_own_id ? null : readTableInitialValuesFromConfig($table_name);

$added_columns = array();

if (tableExists($database, $table_name)) {
  echo "Table $table_name already exists\n";
  $existing_columns = getTableColumnNames($database, $table_name);
  foreach ($columns as $column_name => $type) {
    if (!in_array($column_name, $existing_columns)) {
      echo "Adding missing column $column_name to table $table_name\n";
      addTableColumn($database, $table_name, $column_name, $type);
      array_push($added_columns, $column_name);
    }
  }
} else {
  echo "Creating table $table_name in database $db_name\n";
  createTableIfMissing($database, $table_name, $columns);
}

if ($initial_values !== null) {
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
    echo "Existing values in $table_name were left unchanged\n";
  }
}

echo "Closing connection to database $db_name\n";
closeConnection($database);
