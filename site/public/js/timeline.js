const TIMELINE_TRACK_ID = 'timeline_track';
const TIMELINE_CURSOR_ID = 'timeline_cursor';
const TIMELINE_START_LABEL_ID = 'timeline_start_label';
const TIMELINE_END_LABEL_ID = 'timeline_end_label';
const TIMELINE_LEGEND_ID = 'timeline_legend';
const EVENT_TABLE_BODY_ID = 'event_table_body';
const NO_EVENTS_MESSAGE_ID = 'no_events_message';
const PLAYER_ID = 'timeline_player';
const PLAYER_MESSAGE_ID = 'timeline_player_message';
const PLAYBACK_POSITION_LABEL_ID = 'playback_position_label';
const STORAGE_LABEL_ID = 'storage_label';
const AUTOREFRESH_SWITCH_ID = 'timeline_autorefresh_switch';

const EVENT_TYPES = ['crying', 'babbling', 'sound', 'transmission', 'motion', 'outside', 'asleep', 'awake', 'rec_stopped'];

const REFRESH_INTERVAL = 15000; // [ms]

var _SPAN_SECONDS = 6 * 3600;
var _DATA = null;
var _HLS = null;
var _FRAGMENTS = [];
var _PENDING_SEEK = null;
var _CURRENT_KIND = null;
var _REFRESH_HANDLE = null;
var _CLEAR_EVENTS_MODAL_TRIGGER = {};
var _CLEAR_ALL_MODAL_TRIGGER = {};

$(function () {
    connectModalToObject(_CLEAR_EVENTS_MODAL_TRIGGER, { icon: 'exclamation-circle', header: LANG['sure_want_to_clear_events'], confirm: LANG['clear_events'], confirmClass: 'btn btn-warning', dismiss: LANG['cancel'], confirmOnclick: () => { hideModalWithoutDismissCallback(); clearHistory('events'); } });
    connectModalToObject(_CLEAR_ALL_MODAL_TRIGGER, { icon: 'exclamation-circle', header: LANG['sure_want_to_clear_everything'], confirm: LANG['clear_everything'], confirmClass: 'btn btn-danger', dismiss: LANG['cancel'], confirmOnclick: () => { hideModalWithoutDismissCallback(); clearHistory('all'); } });

    $('#clear_events_button').click(() => { _CLEAR_EVENTS_MODAL_TRIGGER.triggerModal(); });
    $('#clear_all_button').click(() => { _CLEAR_ALL_MODAL_TRIGGER.triggerModal(); });

    $('input[name="timeline_span"]').change(function () {
        _SPAN_SECONDS = parseInt(this.value);
        refresh();
    });

    $('input[name="recording_kind"]').change(function () {
        loadRecording(this.value);
    });

    $('#timeline_refresh_button').click(refresh);

    $('#' + AUTOREFRESH_SWITCH_ID).change(function () {
        if (this.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });

    $('#' + TIMELINE_TRACK_ID).click(function (clickEvent) {
        if ($(clickEvent.target).hasClass('timeline-event')) {
            return;
        }
        const fraction = (clickEvent.pageX - $(this).offset().left) / $(this).width();
        seekToTime(getFrom() + fraction * _SPAN_SECONDS);
    });

    $('#' + PLAYER_ID).get(0).addEventListener('timeupdate', updatePlaybackPosition);

    renderLegend();
    refresh();
    startAutoRefresh();

    $('#main_container').show();
});

function getFrom() {
    return _DATA ? _DATA.from : (Date.now() / 1000 - _SPAN_SECONDS);
}

function startAutoRefresh() {
    stopAutoRefresh();
    _REFRESH_HANDLE = setInterval(refresh, REFRESH_INTERVAL);
}

function stopAutoRefresh() {
    if (_REFRESH_HANDLE) {
        clearInterval(_REFRESH_HANDLE);
        _REFRESH_HANDLE = null;
    }
}

function refresh() {
    const to = Date.now() / 1000;
    const from = to - _SPAN_SECONDS;
    fetch('events.php?from=' + from.toFixed(3) + '&to=' + to.toFixed(3))
        .then(response => response.text())
        .then(responseText => {
            if (responseText.trim() == '-1') {
                logout();
                return;
            }
            _DATA = JSON.parse(responseText);
            renderTimeline();
            renderEventTable();
            renderStorage();
            updateRecordingButtons();
        })
        .catch(triggerErrorEvent);
}

function renderTimeline() {
    const track = $('#' + TIMELINE_TRACK_ID);
    track.find('.timeline-event, .timeline-coverage').remove();

    if (!_DATA || !_DATA.available) {
        return;
    }

    const from = _DATA.from;
    const span = _DATA.to - _DATA.from;

    (_DATA.recordings || []).forEach(coverage => {
        const startFraction = Math.max(0, (coverage.start - from) / span);
        const endFraction = Math.min(1, (coverage.end - from) / span);
        if (endFraction <= startFraction) {
            return;
        }
        $('<div></div>')
            .addClass('timeline-coverage')
            .attr('title', translateKind(coverage.kind))
            .css({ left: (100 * startFraction).toFixed(2) + '%', width: (100 * (endFraction - startFraction)).toFixed(2) + '%' })
            .appendTo(track);
    });

    (_DATA.events || []).forEach(event => {
        const time = parseFloat(event.time);
        const fraction = (time - from) / span;
        if (fraction < 0 || fraction > 1) {
            return;
        }
        $('<div></div>')
            .addClass('timeline-event event-' + event.type)
            .attr('title', formatTime(time) + ' – ' + translateEventType(event.type))
            .css('left', (100 * fraction).toFixed(3) + '%')
            .click(() => { seekToTime(time); })
            .appendTo(track);
    });

    $('#' + TIMELINE_START_LABEL_ID).text(formatTime(_DATA.from, true));
    $('#' + TIMELINE_END_LABEL_ID).text(formatTime(_DATA.to, true));
}

function renderEventTable() {
    const body = $('#' + EVENT_TABLE_BODY_ID);
    body.empty();

    const events = (_DATA && _DATA.events) ? _DATA.events.slice().reverse() : [];
    $('#' + NO_EVENTS_MESSAGE_ID).toggle(events.length == 0);

    events.forEach(event => {
        const time = parseFloat(event.time);
        const row = $('<tr></tr>').css('cursor', 'pointer').click(() => { seekToTime(time); });
        $('<td></td>').text(formatTime(time, true)).appendTo(row);
        const typeCell = $('<td></td>').appendTo(row);
        $('<span></span>').addClass('event-legend-swatch event-' + event.type).appendTo(typeCell);
        typeCell.append(document.createTextNode(translateEventType(event.type)));
        $('<td></td>').text(event.value === null ? '' : formatValue(event.type, event.value)).appendTo(row);
        body.append(row);
    });
}

function renderLegend() {
    const legend = $('#' + TIMELINE_LEGEND_ID);
    EVENT_TYPES.forEach(type => {
        const entry = $('<span></span>').addClass('me-3 text-nowrap');
        $('<span></span>').addClass('event-legend-swatch event-' + type).appendTo(entry);
        entry.append(document.createTextNode(translateEventType(type)));
        legend.append(entry);
    });
}

function renderStorage() {
    if (!_DATA || !_DATA.storage) {
        return;
    }
    const used = formatBytes(_DATA.storage.used);
    const free = _DATA.storage.free === null ? '?' : formatBytes(_DATA.storage.free);
    $('#' + STORAGE_LABEL_ID).text(LANG['recording_uses'] + ': ' + used + ' – ' + LANG['free_space'] + ': ' + free);
}

function updateRecordingButtons() {
    const available = {};
    (_DATA && _DATA.recordings ? _DATA.recordings : []).forEach(coverage => { available[coverage.kind] = coverage; });

    ['video', 'audio'].forEach(kind => {
        $('#recording_kind_' + kind).prop('disabled', !available[kind]);
    });

    if (_CURRENT_KIND && available[_CURRENT_KIND]) {
        return;
    }
    const firstAvailable = available['video'] ? 'video' : (available['audio'] ? 'audio' : null);
    if (firstAvailable) {
        $('#recording_kind_' + firstAvailable).prop('checked', true);
        loadRecording(firstAvailable);
    } else {
        $('#' + PLAYER_MESSAGE_ID).text(LANG['no_recording_yet']).show();
    }
}

function findCoverage(kind) {
    return (_DATA && _DATA.recordings ? _DATA.recordings : []).find(coverage => coverage.kind == kind);
}

function loadRecording(kind) {
    const coverage = findCoverage(kind);
    if (!coverage) {
        return;
    }
    if (_CURRENT_KIND == kind && _HLS) {
        return;
    }
    _CURRENT_KIND = kind;
    _FRAGMENTS = [];

    const player = $('#' + PLAYER_ID).get(0);

    if (_HLS) {
        _HLS.destroy();
        _HLS = null;
    }

    if (!Hls.isSupported()) {
        $('#' + PLAYER_MESSAGE_ID).text(LANG['playback_unsupported']).show();
        return;
    }

    _HLS = new Hls();
    _HLS.attachMedia(player);
    _HLS.on(Hls.Events.MEDIA_ATTACHED, () => { _HLS.loadSource(coverage.url); });
    _HLS.on(Hls.Events.LEVEL_LOADED, (event, data) => {
        _FRAGMENTS = data.details.fragments;
        $('#' + PLAYER_MESSAGE_ID).hide();
        if (_PENDING_SEEK !== null) {
            const target = _PENDING_SEEK;
            _PENDING_SEEK = null;
            seekToTime(target);
        }
    });
    _HLS.on(Hls.Events.ERROR, (event, data) => {
        if (data.fatal) {
            $('#' + PLAYER_MESSAGE_ID).text(LANG['playback_failed']).show();
            _HLS.destroy();
            _HLS = null;
        }
    });
}

/*
Moves the playback to an absolute moment in time, switching to the recording
that covers it when needed.
*/
function seekToTime(targetTime) {
    const videoCoverage = findCoverage('video');
    const audioCoverage = findCoverage('audio');
    const covers = coverage => coverage && targetTime >= coverage.start && targetTime <= coverage.end;

    var kind = null;
    if (covers(videoCoverage)) {
        kind = 'video';
    } else if (covers(audioCoverage)) {
        kind = 'audio';
    }

    if (kind === null) {
        $('#' + PLAYER_MESSAGE_ID).text(LANG['moment_not_recorded']).show();
        moveCursor(targetTime);
        return;
    }

    if (kind != _CURRENT_KIND) {
        $('#recording_kind_' + kind).prop('checked', true);
        _PENDING_SEEK = targetTime;
        loadRecording(kind);
        return;
    }

    if (!applySeek(targetTime)) {
        _PENDING_SEEK = targetTime;
    }
    moveCursor(targetTime);
}

function applySeek(targetTime) {
    const player = $('#' + PLAYER_ID).get(0);
    const targetMilliseconds = targetTime * 1000;

    for (var i = 0; i < _FRAGMENTS.length; i++) {
        const fragment = _FRAGMENTS[i];
        if (fragment.programDateTime == null) {
            continue;
        }
        const endMilliseconds = fragment.programDateTime + fragment.duration * 1000;
        if (targetMilliseconds >= fragment.programDateTime && targetMilliseconds <= endMilliseconds) {
            player.currentTime = fragment.start + (targetMilliseconds - fragment.programDateTime) / 1000;
            player.play().catch(() => { });
            return true;
        }
    }
    return false;
}

function updatePlaybackPosition() {
    const player = $('#' + PLAYER_ID).get(0);
    const time = getPlaybackTime(player.currentTime);
    if (time === null) {
        return;
    }
    $('#' + PLAYBACK_POSITION_LABEL_ID).text(formatTime(time, true));
    moveCursor(time);
}

function getPlaybackTime(position) {
    for (var i = 0; i < _FRAGMENTS.length; i++) {
        const fragment = _FRAGMENTS[i];
        if (fragment.programDateTime == null) {
            continue;
        }
        if (position >= fragment.start && position <= fragment.start + fragment.duration) {
            return (fragment.programDateTime + (position - fragment.start) * 1000) / 1000;
        }
    }
    return null;
}

function moveCursor(time) {
    if (!_DATA) {
        return;
    }
    const fraction = (time - _DATA.from) / (_DATA.to - _DATA.from);
    const cursor = $('#' + TIMELINE_CURSOR_ID);
    if (fraction < 0 || fraction > 1) {
        cursor.hide();
        return;
    }
    cursor.css('left', (100 * fraction).toFixed(3) + '%').show();
}

function clearHistory(what) {
    var data = new URLSearchParams();
    data.append('clear', what);
    fetch('events.php', { method: 'post', body: data })
        .then(response => response.text())
        .then(responseText => {
            if (responseText.trim() == '-1') {
                logout();
                return;
            }
            if (what == 'all') {
                _CURRENT_KIND = null;
                if (_HLS) {
                    _HLS.destroy();
                    _HLS = null;
                }
                _FRAGMENTS = [];
            }
            refresh();
        })
        .catch(triggerErrorEvent);
}

function translateEventType(type) {
    const key = 'event_' + type;
    return (key in LANG) ? LANG[key] : type;
}

function translateKind(kind) {
    return kind == 'video' ? LANG['nav_video'] : LANG['nav_audio'];
}

function formatValue(type, value) {
    const number = parseFloat(value);
    if (isNaN(number)) {
        return '';
    }
    if (type == 'motion' || type == 'outside') {
        return number.toFixed(1) + ' %';
    }
    return number.toFixed(1) + ' dB';
}

function formatTime(time, withDate) {
    const date = new Date(time * 1000);
    if (withDate && _SPAN_SECONDS > 6 * 3600) {
        return date.toLocaleString();
    }
    return date.toLocaleTimeString();
}

function formatBytes(bytes) {
    if (bytes === null || isNaN(bytes)) {
        return '?';
    }
    const megabytes = bytes / (1024 * 1024);
    if (megabytes >= 1024) {
        return (megabytes / 1024).toFixed(1) + ' GB';
    }
    return megabytes.toFixed(0) + ' MB';
}
