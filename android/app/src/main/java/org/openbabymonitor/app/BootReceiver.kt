package org.openbabymonitor.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Starts watching again after the phone reboots, but only if it was watching
 * when the phone went down. A baby monitor that quietly stops because of a
 * restart in the middle of the night is the failure worth guarding against.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = Prefs.of(context)
        if (prefs.isPaired() && prefs.monitoring) {
            MonitorService.start(context)
        }
    }
}
