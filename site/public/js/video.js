const MODE_CONTENT_VIDEO_ID = 'mode_content_video';
const VIDEO_STREAM_PARENT_ID = MODE_CONTENT_VIDEO_ID + '_box';
const VIDEO_STREAM_DIV_ID = 'video_stream';
const VIDEO_STREAM_ID = VIDEO_STREAM_DIV_ID + '_html5_api';
const VIDEO_STREAM_SRC = 'streaming/picam/index.m3u8';
const VIDEO_STREAM_TYPE = 'application/x-mpegURL';

var _AUDIO_CONTEXT;
var _VIDEO_HLS = null;

$(function () {
    if (INITIAL_MODE == VIDEOSTREAM_MODE) {
        enableVideoStreamPlayer();
    }
});

function createVideoElement() {
    var videoElement = $('<video></video>')
        .addClass('video-js vjs-default-skin vjs-big-play-centered vjs-fill')
        .prop({ id: VIDEO_STREAM_DIV_ID, controls: true })
        .hide();
    $('#' + VIDEO_STREAM_PARENT_ID).append(videoElement);
    videojs(videoElement.get(0), { autoplay: 'now', preload: 'metadata', responsive: true }, function () {
        if (Hls.isSupported()) {
            const hls = new Hls({ backBufferLength: 0 });
            _VIDEO_HLS = hls;
            hls.on(Hls.Events.MEDIA_ATTACHED, () => {
                hls.loadSource(VIDEO_STREAM_SRC);
            });
            hls.on(Hls.Events.ERROR, function (event, data) {
                if (!data.fatal) {
                    return;
                }
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        hls.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        hls.recoverMediaError();
                        break;
                    default:
                        hls.destroy();
                        _VIDEO_HLS = null;
                        triggerErrorEvent(new Error('Could not load the video stream'));
                }
            });
            hls.attachMedia($('#' + VIDEO_STREAM_ID).get(0));
        } else {
            this.src({ src: VIDEO_STREAM_SRC, type: VIDEO_STREAM_TYPE });
        }
        $('#' + VIDEO_STREAM_DIV_ID).show(); // New parent element of the video element created by video-js
        $('#' + VIDEO_STREAM_ID).show(); // The actual video element
    });
}

function enableVideoStreamPlayer() {
    createVideoElement();
    setupAudioFiltering();
}

function setupAudioFiltering() {
    _AUDIO_CONTEXT = new (window.AudioContext || window.webkitAudioContext)();
    var source = _AUDIO_CONTEXT.createMediaElementSource($('#' + VIDEO_STREAM_ID).get()[0]);
    var highpassFilter = _AUDIO_CONTEXT.createBiquadFilter();
    var lowpassFilter = _AUDIO_CONTEXT.createBiquadFilter();
    var gain = _AUDIO_CONTEXT.createGain();
    source.connect(highpassFilter);
    highpassFilter.connect(lowpassFilter);
    lowpassFilter.connect(gain);
    gain.connect(_AUDIO_CONTEXT.destination);

    setupBandpassFilters(highpassFilter, lowpassFilter);
    setupGain(gain);
}

function disableVideoStreamPlayer() {
    if (_VIDEO_HLS) {
        _VIDEO_HLS.destroy();
        _VIDEO_HLS = null;
    }
    var player = videojs.getPlayer(VIDEO_STREAM_ID);
    if (player && !player.isDisposed()) {
        _AUDIO_CONTEXT.close();
        player.dispose();
    }
}
