const MODE_CONTENT_VOX_ID = 'mode_content_vox';
const VOX_ICON_USE_ID = 'vox_icon_use';
const VOX_STATE_TEXT_ID = 'vox_state_text';
const VOX_LEVEL_BAR_ID = 'vox_level_bar';
const VOX_LEVEL_VALUE_ID = 'vox_level_value';
const VOX_THRESHOLD_MARKER_ID = 'vox_threshold_marker';
const VOX_THRESHOLD_LABEL_ID = 'vox_threshold_label';
const VOX_LAST_ACTIVATION_ID = 'vox_last_activation';
const VOX_PLAYER_PARENT_ID = 'vox_player_box';

const VOX_STATE_CALIBRATING = 'calibrating';
const VOX_STATE_ARMED = 'armed';
const VOX_STATE_TRANSMITTING = 'transmitting';

const VOX_MIN_LEVEL = 0; // [dB over background]
const VOX_MAX_LEVEL = 50; // [dB over background]

const VOX_STATE_ICONS = {
    calibrating: 'hourglass-split',
    armed: 'broadcast',
    transmitting: 'broadcast-pin'
};
const VOX_STATE_TEXTS = {
    calibrating: LANG['vox_calibrating'],
    armed: LANG['vox_armed'],
    transmitting: LANG['vox_transmitting']
};

var _VOX_EVENT_SOURCE = null;
var _VOX_STATE = null;
var _VOX_PLAYER_ACTIVE = false;
var _VOX_BROWSER_NOTIFICATION = null;
var _VOX_NOTIFICATION_MODAL_TRIGGER = {};

$(function () {
    if (!VOX_AVAILABLE) {
        return;
    }

    connectModalToObject(_VOX_NOTIFICATION_MODAL_TRIGGER, { icon: 'exclamation-circle', noHeaderHiding: true, noBodyHiding: true, confirmOnclick: function () { hideModalWithoutDismissCallback(); startVoxPlayer(); }, confirm: LANG['play_audio'], dismiss: LANG['close'] });

    styleVoxMeter();

    if (INITIAL_MODE == VOX_MODE) {
        initializeVoxMode();
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            removeVoxBrowserNotification();
        }
    });
});

function initializeVoxMode() {
    subscribeToVoxMessages();
    // The connection checker is shared with the listen mode, which can never be
    // active at the same time as the VOX mode
    setupConnectionChecker();
}

function deactivateVoxMode() {
    removeVoxBrowserNotification();
    removeConnectionChecker();
    unsubscribeFromVoxMessages();
    stopVoxPlayer();
    _VOX_STATE = null;
}

function subscribeToVoxMessages() {
    if (_VOX_EVENT_SOURCE) {
        return;
    }
    _VOX_EVENT_SOURCE = new EventSource('vox.php');
    // Both events carry the full status of the device, the state event is just
    // sent immediately when something happens instead of at a fixed interval
    _VOX_EVENT_SOURCE.addEventListener('vox_state', handleVoxStatusEvent);
    _VOX_EVENT_SOURCE.addEventListener('vox_level', handleVoxStatusEvent);
    _VOX_EVENT_SOURCE.onerror = handleVoxErrorEvent;
}

function unsubscribeFromVoxMessages() {
    if (_VOX_EVENT_SOURCE) {
        _VOX_EVENT_SOURCE.close();
        _VOX_EVENT_SOURCE = null;
    }
}

function handleVoxStatusEvent(event) {
    const data = JSON.parse(event.data);
    const newState = data['st'];
    const stateChanged = newState != _VOX_STATE;
    _VOX_STATE = newState;

    updateVoxMeter(data);
    updateVoxStateDisplay(newState);

    if (newState == VOX_STATE_TRANSMITTING) {
        if (stateChanged) {
            $('#' + VOX_LAST_ACTIVATION_ID).html(new Date().toLocaleTimeString());
            if (parseInt(data['nt'])) {
                announceVoxActivation();
            }
        }
        if (SETTING_VOX_AUTOPLAY) {
            startVoxPlayer();
        }
    } else {
        stopVoxPlayer();
    }
}

function handleVoxErrorEvent(event) {
    switch (event.target.readyState) {
        case EventSource.CONNECTING:
            break
        case EventSource.CLOSED:
            _VOX_EVENT_SOURCE = null;
            break
        default:
            triggerErrorEvent(new Error('SSE stream failed: ' + event.data));
            _VOX_EVENT_SOURCE.close();
            _VOX_EVENT_SOURCE = null;
    }
}

function announceVoxActivation() {
    if (browserNotificationsAllowed()) {
        createVoxBrowserNotification();
    } else {
        playNotificationSound();
    }
    if (!SETTING_VOX_AUTOPLAY) {
        displayVoxNotificationModal();
    }
}

function createVoxBrowserNotification() {
    removeVoxBrowserNotification();
    _VOX_BROWSER_NOTIFICATION = createBrowserNotification(LANG['vox_activation_alert'], LANG['vox_activation_text'], 'vox');
}

function removeVoxBrowserNotification() {
    if (_VOX_BROWSER_NOTIFICATION) {
        removeBrowserNotification(_VOX_BROWSER_NOTIFICATION);
        _VOX_BROWSER_NOTIFICATION = null;
    }
}

function displayVoxNotificationModal() {
    _VOX_NOTIFICATION_MODAL_TRIGGER.triggerModal(function () {
        setModalHeaderHTML(LANG['vox_activation_alert']);
        setModalBodyHTML('<p>' + LANG['vox_activation_text'] + '</p>');
    })
}

function updateVoxStateDisplay(state) {
    const icon = VOX_STATE_ICONS[state];
    if (icon) {
        $('#' + VOX_ICON_USE_ID).attr('href', 'media/bootstrap-icons.svg#' + icon);
    }
    const text = VOX_STATE_TEXTS[state];
    $('#' + VOX_STATE_TEXT_ID).html(text ? text : LANG['vox_waiting_for_device']);
}

function updateVoxMeter(data) {
    const soundLevel = parseFloat(data['ct']);
    const threshold = parseFloat(data['th']);

    const bar = $('#' + VOX_LEVEL_BAR_ID);
    bar.css('width', (100 * levelToFraction(soundLevel)).toFixed(1) + '%');
    bar.toggleClass('bg-danger', soundLevel >= threshold);

    $('#' + VOX_LEVEL_VALUE_ID).html(soundLevel.toFixed(1) + ' dB');
    $('#' + VOX_THRESHOLD_MARKER_ID).css('left', (100 * levelToFraction(threshold)).toFixed(1) + '%');
    $('#' + VOX_THRESHOLD_LABEL_ID).html(LANG['vox_trigger_level'] + ': ' + threshold.toFixed(1) + ' dB');
}

function levelToFraction(level) {
    return Math.max(0, Math.min(1, (level - VOX_MIN_LEVEL) / (VOX_MAX_LEVEL - VOX_MIN_LEVEL)));
}

function styleVoxMeter() {
    $('#' + VOX_THRESHOLD_MARKER_ID).css('background-color', FOREGROUND_COLOR);
}

function startVoxPlayer() {
    if (_VOX_PLAYER_ACTIVE) {
        return;
    }
    enableAudioStreamPlayer({ parentId: VOX_PLAYER_PARENT_ID, withVisualization: false });
    _VOX_PLAYER_ACTIVE = true;
}

function stopVoxPlayer() {
    if (!_VOX_PLAYER_ACTIVE) {
        return;
    }
    disableAudioStreamPlayer();
    _VOX_PLAYER_ACTIVE = false;
}
