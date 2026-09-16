package org.openbabymonitor.app

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.openbabymonitor.app.databinding.ActivitySetupBinding
import java.security.cert.X509Certificate

/**
 * Pairing the phone with the device.
 *
 * This screen exists for one reason that cannot be automated away: the first
 * connection has nothing to verify the device against, so the fingerprint of its
 * certificate is put in front of the user to compare with the one the device
 * printed during installation. Everything after that is pinned to it.
 */
class SetupActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySetupBinding
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySetupBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = Prefs.of(this)
        binding.deviceName.setText(Build.MODEL ?: "Android")
        if (prefs.host.isNotEmpty()) {
            binding.host.setText(prefs.host)
            binding.port.setText(prefs.port.toString())
        }

        binding.pairButton.setOnClickListener { startPairing() }
    }

    private fun startPairing() {
        val host = binding.host.text?.toString()?.trim().orEmpty()
        val port = binding.port.text?.toString()?.trim()?.toIntOrNull() ?: 443
        val password = binding.password.text?.toString().orEmpty()

        if (host.isEmpty()) {
            showMessage(getString(R.string.setup_needs_host))
            return
        }
        if (password.isEmpty()) {
            showMessage(getString(R.string.setup_needs_password))
            return
        }

        setBusy(true)
        lifecycleScope.launch {
            val certificate = try {
                withContext(Dispatchers.IO) { PinnedTrust.probeCertificate(host, port) }
            } catch (exception: Exception) {
                setBusy(false)
                showMessage(getString(R.string.error_unreachable))
                return@launch
            }
            setBusy(false)
            confirmCertificate(certificate) { pin ->
                completePairing(host, port, password, pin)
            }
        }
    }

    private fun confirmCertificate(certificate: X509Certificate, onAccepted: (String) -> Unit) {
        val fingerprint = PinnedTrust.fingerprintOf(certificate)
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.fingerprint_title)
            .setMessage(
                getString(
                    R.string.fingerprint_message,
                    PinnedTrust.formatForDisplay(fingerprint)
                )
            )
            .setPositiveButton(R.string.fingerprint_accept) { _, _ -> onAccepted(fingerprint) }
            .setNegativeButton(R.string.fingerprint_reject, null)
            .setCancelable(false)
            .show()
    }

    private fun completePairing(host: String, port: Int, password: String, pin: String) {
        setBusy(true)
        lifecycleScope.launch {
            val deviceName = binding.deviceName.text?.toString()?.trim().orEmpty()
                .ifEmpty { Build.MODEL ?: "Android" }

            val token = try {
                withContext(Dispatchers.IO) {
                    MonitorApi(prefs).pair(host, port, password, deviceName, pin)
                }
            } catch (exception: MonitorApi.ApiException) {
                setBusy(false)
                showMessage(getString(messageFor(exception.failure)))
                return@launch
            } catch (exception: Exception) {
                setBusy(false)
                showMessage(getString(R.string.error_unreachable))
                return@launch
            }

            prefs.host = host
            prefs.port = port
            prefs.pin = pin
            prefs.token = token
            prefs.monitoring = true
            // Nothing that happened before pairing is worth a notification
            prefs.lastSeen = System.currentTimeMillis() / 1000.0

            setBusy(false)
            startActivity(
                Intent(this@SetupActivity, MainActivity::class.java)
                    .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            )
            finish()
        }
    }

    private fun messageFor(failure: MonitorApi.Failure): Int = when (failure) {
        MonitorApi.Failure.WRONG_PASSWORD -> R.string.error_wrong_password
        MonitorApi.Failure.TOO_MANY_ATTEMPTS -> R.string.error_too_many
        MonitorApi.Failure.NOT_INSTALLED -> R.string.error_not_installed
        MonitorApi.Failure.NEEDS_HTTPS -> R.string.error_needs_https
        MonitorApi.Failure.CERTIFICATE -> R.string.error_certificate
        MonitorApi.Failure.UNREACHABLE -> R.string.error_unreachable
        else -> R.string.error_server
    }

    private fun setBusy(busy: Boolean) {
        binding.progress.visibility = if (busy) View.VISIBLE else View.GONE
        binding.pairButton.isEnabled = !busy
    }

    private fun showMessage(text: String) {
        binding.message.text = text
        binding.message.visibility = View.VISIBLE
    }
}
