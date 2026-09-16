package org.openbabymonitor.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Everything the app remembers between runs.
 *
 * The token is as good as the monitor password, so it is kept in encrypted
 * preferences rather than plain ones, and the app opts out of cloud backup so
 * it never leaves the phone.
 */
class Prefs private constructor(private val store: SharedPreferences) {

    companion object {
        private const val FILE = "babymonitor"

        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_TOKEN = "token"
        private const val KEY_PIN = "pin"
        private const val KEY_MONITORING = "monitoring"
        private const val KEY_LAST_SEEN = "last_seen"
        private const val ENABLED_PREFIX = "alert_"

        fun of(context: Context): Prefs {
            val key = MasterKey.Builder(context.applicationContext)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            val store = EncryptedSharedPreferences.create(
                context.applicationContext,
                FILE,
                key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
            return Prefs(store)
        }
    }

    var host: String
        get() = store.getString(KEY_HOST, "") ?: ""
        set(value) = store.edit().putString(KEY_HOST, value.trim()).apply()

    var port: Int
        get() = store.getInt(KEY_PORT, 443)
        set(value) = store.edit().putInt(KEY_PORT, value).apply()

    var token: String
        get() = store.getString(KEY_TOKEN, "") ?: ""
        set(value) = store.edit().putString(KEY_TOKEN, value).apply()

    /** SHA-256 of the certificate this phone was paired with. */
    var pin: String
        get() = store.getString(KEY_PIN, "") ?: ""
        set(value) = store.edit().putString(KEY_PIN, value).apply()

    var monitoring: Boolean
        get() = store.getBoolean(KEY_MONITORING, true)
        set(value) = store.edit().putBoolean(KEY_MONITORING, value).apply()

    /**
     * The time of the newest event the phone has already been told about, so a
     * reconnection does not replay the night.
     */
    var lastSeen: Double
        get() = java.lang.Double.longBitsToDouble(store.getLong(KEY_LAST_SEEN, 0L))
        set(value) = store.edit()
            .putLong(KEY_LAST_SEEN, java.lang.Double.doubleToRawLongBits(value)).apply()

    fun isPaired(): Boolean = host.isNotEmpty() && token.isNotEmpty() && pin.isNotEmpty()

    fun alertsFor(type: String): Boolean =
        store.getBoolean(ENABLED_PREFIX + type, EventTypes.alertsByDefault(type))

    fun setAlertsFor(type: String, enabled: Boolean) =
        store.edit().putBoolean(ENABLED_PREFIX + type, enabled).apply()

    /** Forgets the pairing completely, which is what "unpair" has to mean. */
    fun clear() = store.edit().clear().apply()

    fun baseUrl(): String = "https://$host:$port"
}
