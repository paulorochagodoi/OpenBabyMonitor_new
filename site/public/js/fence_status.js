const FENCE_STATUS_ID = 'fence_status';
const FENCE_STATUS_BADGE_ID = 'fence_status_badge';
const FENCE_STATUS_TEXT_ID = 'fence_status_text';
const FENCE_STATUS_ICON_ID = 'fence_status_icon';

const FENCE_STATE_ICONS = { unknown: 'question-circle', awake: 'eye', asleep: 'moon-stars' };
const FENCE_STATE_CLASSES = { unknown: 'bg-secondary', awake: 'bg-success', asleep: 'bg-primary' };

const FENCE_ALERT_HEADERS = { motion: LANG['fence_motion_alert'], outside: LANG['fence_outside_alert'] };
const FENCE_ALERT_TEXTS = { motion: LANG['fence_motion_alert_text'], outside: LANG['fence_outside_alert_text'] };

var _FENCE_EVENT_SOURCE = null;
var _FENCE_BROWSER_NOTIFICATION = null;
var _FENCE_ALERT_MODAL_TRIGGER = {};

$(function () {
    if (!FENCE_AVAILABLE) {
        return;
    }

    connectModalToObject(_FENCE_ALERT_MODAL_TRIGGER, { icon: 'exclamation-circle', noHeaderHiding: true, noBodyHiding: true, dismiss: LANG['close'] });

    if (INITIAL_MODE == VIDEOSTREAM_MODE) {
        initializeFenceMonitoring();
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            removeFenceBrowserNotification();
        }
    });
});

function initializeFenceMonitoring() {
    if (!FENCE_AVAILABLE || _FENCE_EVENT_SOURCE) {
        return;
    }
    _FENCE_EVENT_SOURCE = new EventSource('fence.php');
    _FENCE_EVENT_SOURCE.addEventListener('fence_status', handleFenceStatusEvent);
    _FENCE_EVENT_SOURCE.onerror = handleFenceErrorEvent;
}

function deactivateFenceMonitoring() {
    removeFenceBrowserNotification();
    if (_FENCE_EVENT_SOURCE) {
        _FENCE_EVENT_SOURCE.close();
        _FENCE_EVENT_SOURCE = null;
    }
    $('#' + FENCE_STATUS_ID).hide();
}

function handleFenceStatusEvent(event) {
    const data = JSON.parse(event.data);
    updateFenceBadge(data);

    const alert = data['alert'];
    if (alert && (alert in FENCE_ALERT_HEADERS)) {
        announceFenceAlert(alert);
    }
}

function updateFenceBadge(data) {
    const state = data['st'];
    const badge = $('#' + FENCE_STATUS_BADGE_ID);

    Object.values(FENCE_STATE_CLASSES).forEach(className => { badge.removeClass(className); });
    badge.addClass(FENCE_STATE_CLASSES[state] ? FENCE_STATE_CLASSES[state] : FENCE_STATE_CLASSES.unknown);

    const icon = FENCE_STATE_ICONS[state] ? FENCE_STATE_ICONS[state] : FENCE_STATE_ICONS.unknown;
    $('#' + FENCE_STATUS_ICON_ID).attr('href', 'media/bootstrap-icons.svg#' + icon);

    const key = 'fence_state_' + state;
    $('#' + FENCE_STATUS_TEXT_ID).text((key in LANG) ? LANG[key] : state);

    $('#' + FENCE_STATUS_ID).show();
}

function announceFenceAlert(alert) {
    if (browserNotificationsAllowed()) {
        removeFenceBrowserNotification();
        _FENCE_BROWSER_NOTIFICATION = createBrowserNotification(FENCE_ALERT_HEADERS[alert], FENCE_ALERT_TEXTS[alert], 'fence');
    } else {
        playNotificationSound();
    }

    if (document.visibilityState !== 'visible') {
        return;
    }
    _FENCE_ALERT_MODAL_TRIGGER.triggerModal(function () {
        setModalHeaderHTML(FENCE_ALERT_HEADERS[alert]);
        setModalBodyHTML('<p>' + FENCE_ALERT_TEXTS[alert] + '</p>');
    });
}

function removeFenceBrowserNotification() {
    if (_FENCE_BROWSER_NOTIFICATION) {
        removeBrowserNotification(_FENCE_BROWSER_NOTIFICATION);
        _FENCE_BROWSER_NOTIFICATION = null;
    }
}

function handleFenceErrorEvent(event) {
    switch (event.target.readyState) {
        case EventSource.CONNECTING:
            break
        case EventSource.CLOSED:
            _FENCE_EVENT_SOURCE = null;
            break
        default:
            triggerErrorEvent(new Error('SSE stream failed: ' + event.data));
            _FENCE_EVENT_SOURCE.close();
            _FENCE_EVENT_SOURCE = null;
    }
}
