package org.openbabymonitor.app

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLHandshakeException

/**
 * Talking to the device.
 *
 * Every connection is pinned to the certificate the phone was paired with, so
 * there is no situation in which the app talks to something else, on any
 * network, silently or otherwise.
 */
class MonitorApi(private val prefs: Prefs) {

    enum class Failure {
        /** The device could not be reached at all. */
        UNREACHABLE,

        /** It answered, but with a certificate this phone was not paired with. */
        CERTIFICATE,

        /** The token was refused, so the phone has to be paired again. */
        UNAUTHORIZED,

        WRONG_PASSWORD,
        TOO_MANY_ATTEMPTS,
        NOT_INSTALLED,
        NEEDS_HTTPS,
        SERVER
    }

    class ApiException(val failure: Failure, message: String) : IOException(message)

    data class Event(val time: Double, val type: String, val value: Double?)

    data class Status(
        val now: Double,
        val mode: String,
        val events: List<Event>,
        val fence: JSONObject?
    )

    companion object {
        private const val CONNECT_TIMEOUT = 10_000

        /** Matches the budget app_poll.php waits for, with room for the answer. */
        private const val POLL_READ_TIMEOUT = 70_000
        private const val SHORT_READ_TIMEOUT = 15_000
    }

    /**
     * Exchanges the monitor password for a token. The certificate must already
     * have been shown to the user and accepted, and its fingerprint is passed in
     * so that this request is pinned like every other one.
     */
    @Throws(ApiException::class)
    fun pair(host: String, port: Int, password: String, deviceName: String, pin: String): String {
        val body = JSONObject()
            .put("password", password)
            .put("device", deviceName)
            .toString()

        val response = request(
            url = URL("https://$host:$port/app_login.php"),
            pin = pin,
            token = null,
            body = body,
            readTimeout = SHORT_READ_TIMEOUT
        )
        val token = response.optString("token")
        if (token.isEmpty()) {
            throw ApiException(Failure.SERVER, "The device did not return a token")
        }
        return token
    }

    /**
     * Asks for everything that happened after [since]. The request stays open on
     * the device until something happens or its budget runs out, so this blocks
     * for up to about a minute and must not be called from the main thread.
     */
    @Throws(ApiException::class)
    fun poll(since: Double, wait: Boolean): Status {
        val query = "?since=" + URLEncoder.encode(formatTime(since), "UTF-8") +
            "&wait=" + (if (wait) "1" else "0")
        val response = request(
            url = URL(prefs.baseUrl() + "/app_poll.php" + query),
            pin = prefs.pin,
            token = prefs.token,
            body = null,
            readTimeout = if (wait) POLL_READ_TIMEOUT else SHORT_READ_TIMEOUT
        )

        val events = mutableListOf<Event>()
        val array = response.optJSONArray("events")
        if (array != null) {
            for (i in 0 until array.length()) {
                val item = array.optJSONObject(i) ?: continue
                val type = item.optString("type")
                if (type.isEmpty()) continue
                events.add(
                    Event(
                        time = item.optDouble("time", 0.0),
                        type = type,
                        // An event without a measurement stores SQL NULL
                        value = if (item.isNull("value")) null else item.optDouble("value")
                    )
                )
            }
        }

        return Status(
            now = response.optDouble("now", 0.0),
            mode = response.optString("mode", "unknown"),
            events = events,
            fence = response.optJSONObject("fence")
        )
    }

    /** Full precision, because the device compares it against stored event times. */
    private fun formatTime(time: Double): String = String.format(java.util.Locale.ROOT, "%.6f", time)

    private fun request(
        url: URL,
        pin: String,
        token: String?,
        body: String?,
        readTimeout: Int
    ): JSONObject {
        if (pin.isEmpty()) {
            throw ApiException(Failure.CERTIFICATE, "No certificate has been pinned")
        }

        val connection: HttpsURLConnection
        try {
            connection = (url.openConnection() as HttpsURLConnection).apply {
                sslSocketFactory = PinnedTrust.socketFactoryFor(pin)
                hostnameVerifier = PinnedTrust.pinnedHostnameVerifier()
                connectTimeout = CONNECT_TIMEOUT
                this.readTimeout = readTimeout
                instanceFollowRedirects = false
                setRequestProperty("Accept", "application/json")
                if (token != null) {
                    setRequestProperty("X-BM-Token", token)
                }
                if (body != null) {
                    requestMethod = "POST"
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                }
            }
        } catch (exception: Exception) {
            throw ApiException(Failure.UNREACHABLE, exception.message ?: "Could not open the connection")
        }

        try {
            if (body != null) {
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }

            val status = connection.responseCode
            val text = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""

            if (status !in 200..299) {
                throw ApiException(failureFor(status, text), "The device answered with $status")
            }

            return try {
                JSONObject(text)
            } catch (exception: Exception) {
                throw ApiException(Failure.SERVER, "The device sent something that is not JSON")
            }
        } catch (exception: SSLHandshakeException) {
            // The pinned trust manager refuses the handshake, which is what a
            // changed or impersonated certificate looks like from here
            throw ApiException(
                Failure.CERTIFICATE,
                exception.message ?: "The certificate did not match the paired one"
            )
        } catch (exception: ApiException) {
            throw exception
        } catch (exception: Exception) {
            throw ApiException(Failure.UNREACHABLE, exception.message ?: "The device did not answer")
        } finally {
            connection.disconnect()
        }
    }

    private fun failureFor(status: Int, text: String): Failure {
        val error = try {
            JSONObject(text).optString("error")
        } catch (exception: Exception) {
            ""
        }
        return when {
            error == "wrong_password" -> Failure.WRONG_PASSWORD
            error == "too_many_attempts" -> Failure.TOO_MANY_ATTEMPTS
            error == "not_installed" -> Failure.NOT_INSTALLED
            error == "needs_https" -> Failure.NEEDS_HTTPS
            status == HttpURLConnection.HTTP_UNAUTHORIZED -> Failure.UNAUTHORIZED
            else -> Failure.SERVER
        }
    }
}
