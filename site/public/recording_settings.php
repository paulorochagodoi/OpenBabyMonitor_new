<?php
require_once(dirname(__DIR__) . '/config/site_config.php');
redirectIfLoggedOut('index.php');
require_once(SRC_DIR . '/settings.php');
require_once(SRC_DIR . '/recordings.php');

if (!RECORDING_AVAILABLE) {
  redirectTo('main.php');
}

$mode = readCurrentMode($_DATABASE);

$setting_type = 'recording';
$table_name = $setting_type . '_settings';
if (isset($_POST['submit'])) {
  $settings_edited = true;
  unset($_POST['submit']);
  updateValuesInTable($_DATABASE, $table_name, withPrimaryKey(convertSettingValues($setting_type, $_POST)));
  $values = readValuesFromTable($_DATABASE, $table_name, readTableColumnNamesFromConfig($table_name));
} elseif (isset($_POST['reset'])) {
  $settings_edited = true;
  $values = readTableInitialValuesFromConfig($table_name);
  updateValuesInTable($_DATABASE, $table_name, $values);
} else {
  $settings_edited = false;
  $values = readValuesFromTable($_DATABASE, $table_name, readTableColumnNamesFromConfig($table_name));
}
$grouped_values = groupSettingValues($setting_type, $values);

$storage = getRecordingDiskUsage();

require_once(TEMPLATES_DIR . '/settings.php');
?>

<link href="css/fill.css" rel="stylesheet">

<!DOCTYPE html>
<html class="fillview">

<head>
  <?php require_once(TEMPLATES_DIR . '/head_common.php'); ?>
</head>

<body class="fillview" style="overflow: hidden;">
  <div class="d-flex flex-column fillview">
    <header>
      <?php
      require_once(TEMPLATES_DIR . '/navbar.php');
      require_once(TEMPLATES_DIR . '/confirmation_modal.php');
      ?>
    </header>

    <div class="d-flex flex-column flex-grow-1 justify-content-center overflow-auto">
      <main id="main_container" class="fillview" style="display: none;">
        <div class="container">
          <h1 class="my-4"><?php echo LANG['recording_settings']; ?></h1>
          <p class="mb-2" style="max-width: 44rem;"><?php echo LANG['recording_settings_description']; ?></p>
          <p class="mb-4" style="max-width: 44rem;"><em><?php echo LANG['recording_card_warning']; ?></em></p>

          <?php if ($storage !== null) { ?>
            <p class="mb-4" style="font-size: 0.9rem;">
              <?php echo LANG['recording_uses']; ?>: <?php echo round($storage['used'] / (1024 * 1024)); ?> MB
              <?php if ($storage['free'] !== null) { ?>
                &ndash; <?php echo LANG['free_space']; ?>: <?php echo round($storage['free'] / (1024 * 1024)); ?> MB
              <?php } ?>
            </p>
          <?php } ?>

          <form id="recording_settings_form" action="" method="post">
            <div class="row">
              <?php $input_scripts = generateInputs($setting_type, $grouped_values, [], []); ?>
            </div>
            <div class="my-4">
              <button type="submit" name="submit" class="btn btn-primary"><?php echo LANG['submit']; ?></button>
              <button type="submit" name="reset" style="display: none;" id="reset_submit_button" disabled></button><input type="button" class="btn btn-warning ms-2" id="reset_button" value="<?php echo LANG['reset']; ?>" />
            </div>
          </form>
        </div>
      </main>
    </div>
  </div>
  <div style="position: relative; top: 100%; left: 0; width: 100%; height: 10vh; overflow: hidden;"></div>
</body>

<?php
require_once(TEMPLATES_DIR . '/bootstrap_js.php');
require_once(TEMPLATES_DIR . '/jquery_js.php');
require_once(TEMPLATES_DIR . '/js-cookie_js.php');
?>

<script src="js/confirmation_modal.js"></script>

<?php
require_once(TEMPLATES_DIR . '/notifications_js.php');
require_once(TEMPLATES_DIR . '/monitoring_js.php');
?>

<script>
  const SETTINGS_FORM_ID = 'recording_settings_form';
  const SETTINGS_EDITED = <?php echo $settings_edited ? 'true' : 'false'; ?>;
  const USES_CAMERA = <?php echo USES_CAMERA ? 'true' : 'false'; ?>;
  const STANDBY_MODE = <?php echo MODE_VALUES['standby']; ?>;
  // The settings are read when a mode starts, so whatever is running has to be
  // restarted for a change to take effect
  const SITE_MODE = <?php echo $mode; ?>;
  const INITIAL_MODE = <?php echo $mode; ?>;
  const DETECT_FORM_CHANGES = true;
</script>
<script src="js/style.js"></script>
<script src="js/jquery_utils.js"></script>
<script src="js/settings.js"></script>
<script src="js/navbar.js"></script>
<script src="js/navbar_settings.js"></script>
<script>
  <?php generateBehavior($setting_type); ?>
</script>
<?php if ($input_scripts != null) { ?>
  <script>
    <?php foreach ($input_scripts as $script) {
      echo $script . "\n";
    } ?>
  </script>
<?php } ?>
<script>
  $(function() {
    captureElementState(SETTINGS_FORM_ID);
  });
</script>

</html>
