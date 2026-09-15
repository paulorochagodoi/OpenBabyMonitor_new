const FENCE_CANVAS_ID = 'fence_canvas';
const FENCE_SNAPSHOT_ID = 'fence_snapshot';
const FENCE_EDITOR_ID = 'fence_editor';
const FENCE_STATUS_LABEL_ID = 'fence_status_label';
const FENCE_NO_STREAM_MESSAGE_ID = 'fence_no_stream_message';
const POLYGON_INPUT_ID = 'polygon';

// How close to a corner a click has to be to grab it instead of adding a new one
const GRAB_RADIUS = 14; // [px]
const HANDLE_RADIUS = 6; // [px]
const DEFAULT_FENCE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]];

var _POLYGON = [];
var _DRAGGED_POINT = null;
var _HAS_SNAPSHOT = false;

$(function () {
    _POLYGON = readPolygonFromInput();

    $('#' + FENCE_CANVAS_ID).on('pointerdown', handlePointerDown);
    $('#' + FENCE_CANVAS_ID).on('pointermove', handlePointerMove);
    $('#' + FENCE_CANVAS_ID).on('pointerup pointercancel pointerleave', handlePointerUp);

    $('#fence_undo_button').click(() => { _POLYGON.pop(); commit(); });
    $('#fence_clear_button').click(() => { _POLYGON = []; commit(); });
    $('#fence_default_button').click(() => { _POLYGON = DEFAULT_FENCE.map(point => point.slice()); commit(); });
    $('#fence_refresh_button').click(loadSnapshot);

    $(window).resize(resizeCanvas);

    loadSnapshot();
    resizeCanvas();
    draw();
});

function readPolygonFromInput() {
    const text = $('#' + POLYGON_INPUT_ID).val();
    if (!text) {
        return [];
    }
    try {
        const parsed = JSON.parse(text);
        if (!Array.isArray(parsed)) {
            return [];
        }
        return parsed
            .filter(point => Array.isArray(point) && point.length >= 2)
            .map(point => [clampFraction(point[0]), clampFraction(point[1])]);
    } catch (error) {
        return [];
    }
}

function clampFraction(value) {
    const number = parseFloat(value);
    if (isNaN(number)) {
        return 0;
    }
    return Math.min(1, Math.max(0, number));
}

function loadSnapshot() {
    const snapshot = $('#' + FENCE_SNAPSHOT_ID);
    setStatus(LANG['loading_snapshot']);

    fetch('snapshot.php?t=' + Date.now())
        .then(response => {
            if (response.status == 409) {
                throw new Error('no_stream');
            }
            if (!response.ok) {
                throw new Error('failed');
            }
            return response.blob();
        })
        .then(blob => {
            const url = URL.createObjectURL(blob);
            snapshot.one('load', function () {
                URL.revokeObjectURL(url);
                _HAS_SNAPSHOT = true;
                snapshot.show();
                $('#' + FENCE_NO_STREAM_MESSAGE_ID).hide();
                resizeCanvas();
                draw();
                setStatus('');
            });
            snapshot.attr('src', url);
        })
        .catch(error => {
            _HAS_SNAPSHOT = false;
            snapshot.hide();
            $('#' + FENCE_NO_STREAM_MESSAGE_ID).show();
            setStatus('');
            resizeCanvas();
            draw();
        });
}

/*
The canvas is kept exactly on top of the snapshot, so a point clicked on the
image lands where the fence monitor will look for it.
*/
function resizeCanvas() {
    const canvas = $('#' + FENCE_CANVAS_ID);
    const snapshot = $('#' + FENCE_SNAPSHOT_ID);
    const editor = $('#' + FENCE_EDITOR_ID);

    var width;
    var height;
    if (_HAS_SNAPSHOT && snapshot.width() > 0) {
        width = snapshot.width();
        height = snapshot.height();
    } else {
        // Without a snapshot the fence is drawn on an empty area of the same
        // shape as a widescreen camera image
        width = Math.min(editor.parent().width(), 640);
        height = Math.round(width * 9 / 16);
        editor.css({ width: width + 'px', height: height + 'px', backgroundColor: 'rgba(128, 128, 128, 0.2)' });
    }

    canvas.prop({ width: width, height: height }).css({ width: width + 'px', height: height + 'px' });
    draw();
}

function getCanvas() {
    return $('#' + FENCE_CANVAS_ID).get(0);
}

function getPointerPosition(pointerEvent) {
    const canvas = getCanvas();
    const rectangle = canvas.getBoundingClientRect();
    const originalEvent = pointerEvent.originalEvent ? pointerEvent.originalEvent : pointerEvent;
    return {
        x: originalEvent.clientX - rectangle.left,
        y: originalEvent.clientY - rectangle.top
    };
}

function findPointNear(position) {
    const canvas = getCanvas();
    for (var i = 0; i < _POLYGON.length; i++) {
        const x = _POLYGON[i][0] * canvas.width;
        const y = _POLYGON[i][1] * canvas.height;
        if (Math.hypot(x - position.x, y - position.y) <= GRAB_RADIUS) {
            return i;
        }
    }
    return null;
}

function handlePointerDown(pointerEvent) {
    pointerEvent.preventDefault();
    const canvas = getCanvas();
    const position = getPointerPosition(pointerEvent);
    const existingPoint = findPointNear(position);

    if (existingPoint !== null) {
        _DRAGGED_POINT = existingPoint;
    } else {
        _POLYGON.push([clampFraction(position.x / canvas.width), clampFraction(position.y / canvas.height)]);
        _DRAGGED_POINT = _POLYGON.length - 1;
    }
    commit();
}

function handlePointerMove(pointerEvent) {
    if (_DRAGGED_POINT === null) {
        return;
    }
    pointerEvent.preventDefault();
    const canvas = getCanvas();
    const position = getPointerPosition(pointerEvent);
    _POLYGON[_DRAGGED_POINT] = [
        clampFraction(position.x / canvas.width),
        clampFraction(position.y / canvas.height)
    ];
    commit();
}

function handlePointerUp() {
    _DRAGGED_POINT = null;
}

function commit() {
    $('#' + POLYGON_INPUT_ID).val(JSON.stringify(_POLYGON.map(point => [
        parseFloat(point[0].toFixed(4)),
        parseFloat(point[1].toFixed(4))
    ])));
    draw();
    updateStatus();
}

function updateStatus() {
    if (_POLYGON.length == 0) {
        setStatus(LANG['fence_covers_everything']);
    } else if (_POLYGON.length < 3) {
        setStatus(LANG['fence_needs_three_corners']);
    } else {
        setStatus(LANG['fence_corners'] + ': ' + _POLYGON.length);
    }
}

function setStatus(text) {
    $('#' + FENCE_STATUS_LABEL_ID).text(text);
}

function draw() {
    const canvas = getCanvas();
    const context = canvas.getContext('2d');
    context.clearRect(0, 0, canvas.width, canvas.height);

    if (_POLYGON.length == 0) {
        return;
    }

    const points = _POLYGON.map(point => [point[0] * canvas.width, point[1] * canvas.height]);

    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    for (var i = 1; i < points.length; i++) {
        context.lineTo(points[i][0], points[i][1]);
    }
    if (points.length >= 3) {
        context.closePath();
        context.fillStyle = 'rgba(13, 110, 253, 0.25)';
        context.fill();
    }
    context.strokeStyle = 'rgba(13, 110, 253, 0.95)';
    context.lineWidth = 2;
    context.stroke();

    points.forEach((point, index) => {
        context.beginPath();
        context.arc(point[0], point[1], HANDLE_RADIUS, 0, 2 * Math.PI);
        context.fillStyle = (index == _DRAGGED_POINT) ? '#ffc107' : '#ffffff';
        context.fill();
        context.strokeStyle = 'rgba(13, 110, 253, 0.95)';
        context.lineWidth = 2;
        context.stroke();
    });
}
