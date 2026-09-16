package org.openbabymonitor.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.ViewGroup
import android.widget.LinearLayout
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.materialswitch.MaterialSwitch
import org.openbabymonitor.app.databinding.ActivitySettingsBinding

/**
 * Which events are worth a notification, and what this phone is paired with.
 *
 * The fingerprint is shown here too, so it can be compared against the device at
 * any time, not only while pairing.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        title = getString(R.string.settings_title)

        prefs = Prefs.of(this)

        buildEventSwitches()
        showPairing()

        binding.batteryButton.setOnClickListener { openBatterySettings() }
        binding.unpairButton.setOnClickListener { confirmUnpair() }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    private fun buildEventSwitches() {
        for (descriptor in EventTypes.all) {
            val toggle = MaterialSwitch(this).apply {
                text = getString(descriptor.label)
                isChecked = prefs.alertsFor(descriptor.type)
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).also { it.topMargin = 8 }
                setOnCheckedChangeListener { _, checked ->
                    prefs.setAlertsFor(descriptor.type, checked)
                }
            }
            binding.eventSwitches.addView(toggle)
        }
    }

    private fun showPairing() {
        binding.pairingInfo.text = getString(
            R.string.settings_pairing_info,
            prefs.baseUrl(),
            PinnedTrust.formatForDisplay(prefs.pin)
        )
    }

    /**
     * Android stops background work aggressively by default, which for this app
     * means missing the alert it exists to deliver.
     */
    private fun openBatterySettings() {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (power.isIgnoringBatteryOptimizations(packageName)) {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            return
        }
        try {
            startActivity(
                Intent(
                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName")
                )
            )
        } catch (exception: Exception) {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun confirmUnpair() {
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.unpair_title)
            .setMessage(R.string.unpair_message)
            .setPositiveButton(R.string.unpair_confirm) { _, _ -> unpair() }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun unpair() {
        MonitorService.stop(this)
        prefs.clear()
        startActivity(
            Intent(this, SetupActivity::class.java)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        )
        finish()
    }
}
