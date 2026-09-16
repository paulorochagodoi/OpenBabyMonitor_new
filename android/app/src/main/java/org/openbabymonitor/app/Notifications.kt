package org.openbabymonitor.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import java.text.DateFormat
import java.util.Date
import java.util.Locale

/**
 * Everything that shows up in the notification shade.
 *
 * Urgent events and quiet ones go to separate channels so that silencing "the
 * child fell asleep" in the system settings does not also silence "the child is
 * crying".
 */
object Notifications {

    const val CHANNEL_SERVICE = "monitor"
    const val CHANNEL_URGENT = "alerts_urgent"
    const val CHANNEL_INFO = "alerts_info"

    const val SERVICE_NOTIFICATION_ID = 1

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return

        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_SERVICE,
                context.getString(R.string.channel_service),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = context.getString(R.string.channel_service_description)
                setShowBadge(false)
            }
        )

        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_URGENT,
                context.getString(R.string.channel_urgent),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = context.getString(R.string.channel_urgent_description)
                enableVibration(true)
            }
        )

        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_INFO,
                context.getString(R.string.channel_info),
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = context.getString(R.string.channel_info_description)
            }
        )
    }

    private fun openAppIntent(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(
            context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    /** The notification the foreground service has to keep up while it runs. */
    fun serviceNotification(context: Context, state: String): Notification =
        NotificationCompat.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_monitor)
            .setContentTitle(context.getString(R.string.service_title))
            .setContentText(state)
            .setContentIntent(openAppIntent(context))
            .setOngoing(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    fun updateServiceNotification(context: Context, state: String) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return
        try {
            NotificationManagerCompat.from(context)
                .notify(SERVICE_NOTIFICATION_ID, serviceNotification(context, state))
        } catch (exception: SecurityException) {
            // The user revoked the notification permission while we were running
        }
    }

    /**
     * Shows one event. A second event of the same kind replaces the first
     * instead of stacking, so a long stretch of crying leaves one notification
     * showing the latest time rather than forty.
     */
    fun showEvent(context: Context, event: MonitorApi.Event) {
        val descriptor = EventTypes.of(event.type) ?: return
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return

        val time = DateFormat.getTimeInstance(DateFormat.MEDIUM)
            .format(Date((event.time * 1000).toLong()))
        val detail = if (event.value != null && descriptor.unit != null) {
            context.getString(
                R.string.event_detail_with_value,
                time,
                String.format(Locale.getDefault(), "%.1f", event.value),
                descriptor.unit
            )
        } else {
            context.getString(R.string.event_detail, time)
        }

        val notification = NotificationCompat.Builder(
            context,
            if (descriptor.urgent) CHANNEL_URGENT else CHANNEL_INFO
        )
            .setSmallIcon(R.drawable.ic_monitor)
            .setContentTitle(context.getString(descriptor.label))
            .setContentText(detail)
            .setContentIntent(openAppIntent(context))
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(
                if (descriptor.urgent) NotificationCompat.PRIORITY_HIGH
                else NotificationCompat.PRIORITY_DEFAULT
            )
            .build()

        try {
            NotificationManagerCompat.from(context).notify(event.type.hashCode(), notification)
        } catch (exception: SecurityException) {
            // Same as above: nothing to do but stay quiet
        }
    }
}
