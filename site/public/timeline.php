<?php
require_once(dirname(__DIR__) . '/config/site_config.php');
redirectIfLoggedOut('index.php');
require_once(SRC_DIR . '/events.php');
require_once(SRC_DIR . '/recordings.php');

if (!EVENTS_AVAILABLE) {
  redirectTo('main.php');
}

$mode = readCurrentMode($_DATABASE);
?>

<link href="css/fill.css" rel="stylesheet">

<!DOCTYPE html>
<html class="fillview">

<head>
  <?php require_once(TEMPLATES_DIR . '/head_common.php'); ?>

  <style>
    .timeline-track {
      position: relative;
      height: 4.5rem;
      border: 1px solid rgba(128, 128, 128, 0.5);
      border-radius: 0.25rem;
      overflow: hidden;
      cursor: crosshair;
    }

    .timeline-coverage {
      position: absolute;
      top: 0;
      height: 100%;
      background-color: rgba(128, 128, 128, 0.22);
    }

    .timeline-event {
      position: absolute;
      top: 0.4rem;
      bottom: 0.4rem;
      width: 3px;
      margin-left: -1px;
      border-radius: 2px;
      cursor: pointer;
    }

    .timeline-event:hover {
      width: 5px;
      margin-left: -2px;
    }

    .timeline-cursor {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      margin-left: -1px;
      background-color: currentColor;
      display: none;
    }

    .event-crying {
      background-color: #dc3545;
    }

    .event-babbling {
      background-color: #198754;
    }

    .event-sound {
      background-color: #ffc107;
    }

    .event-transmission {
      background-color: #0d6efd;
    }

    .event-motion {
      background-color: #fd7e14;
    }

    .event-outside {
      background-color: #d63384;
    }

    .event-asleep {
      background-color: #6f42c1;
    }

    .event-awake {
      background-color: #20c997;
    }

    .event-rec_stopped {
      background-color: #6c757d;
    }

    .event-legend-swatch {
      display: inline-block;
      width: 0.8rem;
      height: 0.8rem;
      border-radius: 2px;
      margin-right: 0.35rem;
    }
  </style>
</head>

<body class="fillview" style="overflow: hidden;">
  <div class="d-flex flex-column fillview">
    <header>
      <?php
      require_once(TEMPLATES_DIR . '/navbar.php');
      require_once(TEMPLATES_DIR . '/confirmation_modal.php');
      ?>
    </header>

    <div class="d-flex flex-column flex-grow-1 justify-content-start overflow-auto">
      <main id="main_container" class="container" style="display: none;">
        <h1 class="my-4"><?php echo LANG['timeline']; ?></h1>

        <div class="row align-items-center mb-3">
          <div class="col-auto">
            <div class="btn-group" role="group">
              <input type="radio" class="btn-check" name="timeline_span" id="timeline_span_1" value="3600" autocomplete="off">
              <label class="btn btn-outline-secondary" for="timeline_span_1"><?php echo LANG['last_hour']; ?></label>
              <input type="radio" class="btn-check" name="timeline_span" id="timeline_span_6" value="21600" autocomplete="off" checked>
              <label class="btn btn-outline-secondary" for="timeline_span_6"><?php echo LANG['last_6_hours']; ?></label>
              <input type="radio" class="btn-check" name="timeline_span" id="timeline_span_24" value="86400" autocomplete="off">
              <label class="btn btn-outline-secondary" for="timeline_span_24"><?php echo LANG['last_24_hours']; ?></label>
            </div>
          </div>
          <div class="col-auto">
            <button id="timeline_refresh_button" class="btn btn-outline-secondary" type="button">
              <svg class="bi" style="height: 1.1em; width: 1.1em;" fill="currentColor">
                <use href="media/bootstrap-icons.svg#arrow-clockwise" />
              </svg>
            </button>
          </div>
          <div class="col-auto form-check form-switch mb-0">
            <input id="timeline_autorefresh_switch" class="form-check-input" type="checkbox" role="button" checked>
            <label class="form-check-label" for="timeline_autorefresh_switch"><?php echo LANG['auto_refresh']; ?></label>
          </div>
        </div>

        <div id="timeline_track" class="timeline-track text-bm mb-1">
          <div id="timeline_cursor" class="timeline-cursor"></div>
        </div>
        <div class="d-flex justify-content-between text-bm mb-3" style="font-size: 0.8rem;">
          <span id="timeline_start_label"></span>
          <span id="timeline_end_label"></span>
        </div>

        <div id="timeline_legend" class="mb-4 text-bm" style="font-size: 0.85rem;"></div>

        <div class="row align-items-center mb-2">
          <div class="col-auto fw-bold text-bm"><?php echo LANG['playback']; ?></div>
          <div class="col-auto">
            <div class="btn-group btn-group-sm" role="group">
              <input type="radio" class="btn-check" name="recording_kind" id="recording_kind_video" value="video" autocomplete="off" disabled>
              <label class="btn btn-outline-secondary" for="recording_kind_video"><?php echo LANG['nav_video']; ?></label>
              <input type="radio" class="btn-check" name="recording_kind" id="recording_kind_audio" value="audio" autocomplete="off" disabled>
              <label class="btn btn-outline-secondary" for="recording_kind_audio"><?php echo LANG['nav_audio']; ?></label>
            </div>
          </div>
          <div class="col-auto text-bm" id="playback_position_label" style="font-size: 0.85rem;"></div>
        </div>

        <div class="row mb-4">
          <div class="col-12">
            <video id="timeline_player" class="w-100" style="max-width: 40rem; background-color: #000;" controls playsinline></video>
            <p id="timeline_player_message" class="mt-2 text-bm"><?php echo LANG['no_recording_yet']; ?></p>
          </div>
        </div>

        <h2 class="mb-3"><?php echo LANG['events']; ?></h2>
        <div class="table-responsive mb-4">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th scope="col"><?php echo LANG['event_time']; ?></th>
                <th scope="col"><?php echo LANG['event_type']; ?></th>
                <th scope="col"><?php echo LANG['event_value']; ?></th>
              </tr>
            </thead>
            <tbody id="event_table_body">
            </tbody>
          </table>
          <p id="no_events_message" class="text-bm" style="display: none;"><?php echo LANG['no_events']; ?></p>
        </div>

        <div class="mb-5">
          <button type="button" class="btn btn-warning" id="clear_events_button"><?php echo LANG['clear_events']; ?></button>
          <button type="button" class="btn btn-danger ms-2" id="clear_all_button"><?php echo LANG['clear_everything']; ?></button>
          <div id="storage_label" class="mt-3 text-bm" style="font-size: 0.85rem;"></div>
        </div>
      </main>
    </div>
  </div>
  <div style="position: relative; top: 100%; left: 0; width: 100%; height: 10vh; overflow: hidden;"></div>
</body>

<?php
require_once(TEMPLATES_DIR . '/bootstrap_js.php');
require_once(TEMPLATES_DIR . '/hls-js_js.php');
require_once(TEMPLATES_DIR . '/jquery_js.php');
require_once(TEMPLATES_DIR . '/js-cookie_js.php');
?>

<script src="js/confirmation_modal.js"></script>

<?php
require_once(TEMPLATES_DIR . '/notifications_js.php');
require_once(TEMPLATES_DIR . '/monitoring_js.php');
?>

<script>
  const USES_CAMERA = <?php echo USES_CAMERA ? 'true' : 'false'; ?>;
  const STANDBY_MODE = <?php echo MODE_VALUES['standby']; ?>;
  const SITE_MODE = null;
  const INITIAL_MODE = <?php echo $mode; ?>;
  const DETECT_FORM_CHANGES = false;
  const SETTINGS_FORM_ID = null;
</script>
<script src="js/style.js"></script>
<script src="js/jquery_utils.js"></script>
<script src="js/navbar.js"></script>
<script src="js/navbar_settings.js"></script>
<script src="js/timeline.js"></script>

</html>
