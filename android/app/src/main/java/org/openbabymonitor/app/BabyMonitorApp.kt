package org.openbabymonitor.app

import android.app.Application

class BabyMonitorApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }
}
