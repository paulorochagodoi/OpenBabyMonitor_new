package org.openbabymonitor.app

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * The part that has to keep working while the phone is in a pocket.
 *
 * It holds one request open against the device at a time. The device answers as
 * soon as something happens, so an alert arrives about as fast as the detection
 * itself, and in between there is nothing going over the network at all.
 *
 * Everything here runs on the home network. If the phone leaves it, the service
 * keeps trying and says so in its notification rather than pretending to watch.
 */
class MonitorService : Service() {

    enum class Connection { CONNECTING, WATCHING, OFFLINE, UNPAIRED, CERTIFICATE_CHANGED }

    data class State(
        val connection: Connection = Connection.CONNECTING,
        val mode: String = "",
        val lastEventTime: Double = 0.0,
        val detail: String = ""
    )

    companion object {
        private const val ACTION_STOP = "org.openbabymonitor.app.STOP"

        /** Backoff between reconnection attempts, in milliseconds. */
        private const val RETRY_MIN = 2_000L
        private const val RETRY_MAX = 60_000L

        private val _state = MutableStateFlow(State())
        val state: StateFlow<State> = _state

        fun start(context: Context) {
            val intent = Intent(context, MonitorService::class.java)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, MonitorService::class.java).setAction(ACTION_STOP)
            )
        }
    }

    private val job = SupervisorJob()
    private val scope = CoroutineScope(Dispatchers.IO + job)
    private var loop: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        startInForeground()
        acquireWakeLock()

        if (loop?.isActive != true) {
            loop = scope.launch { watch() }
        }

        // The whole point is to be running when something happens, so the system
        // is asked to bring it back if it has to kill it
        return START_STICKY
    }

    override fun onDestroy() {
        releaseWakeLock()
        scope.cancel()
        super.onDestroy()
    }

    private fun startInForeground() {
        val notification = Notifications.serviceNotification(this, getString(R.string.state_connecting))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                Notifications.SERVICE_NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(Notifications.SERVICE_NOTIFICATION_ID, notification)
        }
    }

    /**
     * A baby monitor that goes quiet because the phone fell asleep is worse than
     * useless, so the CPU is kept available while watching. The phone is
     * expected to be charging overnight; the service is easy to switch off when
     * it is not.
     */
    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val power = getSystemService(PowerManager::class.java) ?: return
        wakeLock = power.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK, "OpenBabyMonitor:watching"
        ).apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private suspend fun watch() {
        val prefs = Prefs.of(this)
        val api = MonitorApi(prefs)
        var retry = RETRY_MIN

        while (scope.isActive) {
            if (!prefs.isPaired()) {
                publish(State(Connection.UNPAIRED, detail = getString(R.string.state_unpaired)))
                stopSelf()
                return
            }

            try {
                val status = api.poll(prefs.lastSeen, wait = true)
                retry = RETRY_MIN

                val newest = handleEvents(prefs, status)
                prefs.lastSeen = newest

                publish(
                    State(
                        connection = Connection.WATCHING,
                        mode = status.mode,
                        lastEventTime = newest,
                        detail = describeMode(status.mode)
                    )
                )
            } catch (exception: MonitorApi.ApiException) {
                when (exception.failure) {
                    MonitorApi.Failure.UNAUTHORIZED -> {
                        // The token was revoked from the web interface, or the
                        // device was reinstalled. Watching again needs a person,
                        // so it must not come back by itself after a reboot.
                        prefs.monitoring = false
                        publish(State(Connection.UNPAIRED, detail = getString(R.string.state_unpaired)))
                        stopSelf()
                        return
                    }

                    MonitorApi.Failure.CERTIFICATE -> {
                        // Either the certificate was replaced on the device or
                        // something else is answering. Both need a person to look.
                        prefs.monitoring = false
                        publish(
                            State(
                                Connection.CERTIFICATE_CHANGED,
                                detail = getString(R.string.state_certificate_changed)
                            )
                        )
                        stopSelf()
                        return
                    }

                    else -> {
                        publish(
                            State(
                                connection = Connection.OFFLINE,
                                detail = getString(R.string.state_offline)
                            )
                        )
                        delay(retry)
                        retry = (retry * 2).coerceAtMost(RETRY_MAX)
                    }
                }
            } catch (exception: Exception) {
                publish(State(Connection.OFFLINE, detail = getString(R.string.state_offline)))
                delay(retry)
                retry = (retry * 2).coerceAtMost(RETRY_MAX)
            }
        }
    }

    /**
     * Shows the events the user asked to be told about and returns the time to
     * ask from next. Events that are switched off still move that time forward,
     * so switching one on does not produce a burst of old notifications.
     */
    private fun handleEvents(prefs: Prefs, status: MonitorApi.Status): Double {
        var newest = maxOf(prefs.lastSeen, status.now)
        for (event in status.events) {
            if (event.time > newest) {
                newest = event.time
            }
            if (prefs.alertsFor(event.type)) {
                Notifications.showEvent(this, event)
            }
        }
        return newest
    }

    private fun describeMode(mode: String): String {
        val label = when (mode) {
            "standby" -> R.string.mode_standby
            "listen" -> R.string.mode_listen
            "audiostream" -> R.string.mode_audiostream
            "videostream" -> R.string.mode_videostream
            "vox" -> R.string.mode_vox
            else -> R.string.mode_unknown
        }
        return getString(R.string.state_watching, getString(label))
    }

    private fun publish(state: State) {
        _state.value = state
        Notifications.updateServiceNotification(this, state.detail)
    }
}
