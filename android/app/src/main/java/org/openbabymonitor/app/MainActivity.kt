package org.openbabymonitor.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.CookieManager
import android.webkit.SslErrorHandler
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import kotlinx.coroutines.launch
import org.openbabymonitor.app.databinding.ActivityMainBinding

/**
 * The monitor itself, shown in a web view, with a strip on top saying whether
 * the background watching is actually connected.
 *
 * The web view is held to the same pinned certificate as everything else. The
 * usual "continue anyway" that a self-signed certificate produces in a browser
 * is not offered here: either it is the paired device or the page does not load.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: Prefs

    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Snackbar.make(
                binding.root, R.string.notification_permission_message, Snackbar.LENGTH_LONG
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs.of(this)

        if (!prefs.isPaired()) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        setSupportActionBar(binding.toolbar)

        configureWebView()
        binding.webRetry.setOnClickListener { loadMonitor() }

        binding.monitoringSwitch.isChecked = prefs.monitoring
        binding.monitoringSwitch.setOnCheckedChangeListener { _, checked ->
            prefs.monitoring = checked
            if (checked) MonitorService.start(this) else MonitorService.stop(this)
        }

        askForNotificationPermission()
        observeService()
        loadMonitor()

        if (prefs.monitoring) {
            MonitorService.start(this)
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        R.id.action_settings -> {
            startActivity(Intent(this, SettingsActivity::class.java))
            true
        }

        R.id.action_reload -> {
            loadMonitor()
            true
        }

        else -> super.onOptionsItemSelected(item)
    }

    override fun onDestroy() {
        if (this::binding.isInitialized) {
            binding.web.destroy()
        }
        super.onDestroy()
    }

    private fun askForNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun configureWebView() {
        CookieManager.getInstance().setAcceptCookie(true)
        with(binding.web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            // The video and audio pages start playing on their own
            mediaPlaybackRequiresUserGesture = false
        }
        binding.web.webViewClient = PinnedWebViewClient()
    }

    /**
     * Opens the monitor through app_session.php, which trades the token for the
     * session cookie the site expects, so the password never has to be typed
     * into the page.
     */
    private fun loadMonitor() {
        binding.webError.visibility = View.GONE
        binding.web.visibility = View.VISIBLE
        binding.web.loadUrl(
            prefs.baseUrl() + "/app_session.php?target=main.php",
            mapOf("X-BM-Token" to prefs.token)
        )
    }

    private fun showWebError() {
        binding.web.visibility = View.GONE
        binding.webErrorText.setText(R.string.web_error)
        binding.webError.visibility = View.VISIBLE
    }

    private inner class PinnedWebViewClient : WebViewClient() {

        override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
            val certificate = error?.certificate?.x509Certificate
            val pin = prefs.pin
            if (certificate != null && pin.isNotEmpty() && PinnedTrust.matches(certificate, pin)) {
                // Self-signed, so Android objects; but it is the exact
                // certificate this phone was paired with
                handler?.proceed()
                return
            }
            handler?.cancel()
            binding.webErrorText.setText(R.string.error_certificate)
            binding.web.visibility = View.GONE
            binding.webError.visibility = View.VISIBLE
        }

        override fun onReceivedError(
            view: WebView?,
            request: WebResourceRequest?,
            error: WebResourceError?
        ) {
            if (request?.isForMainFrame == true) {
                showWebError()
            }
        }

        override fun onPageFinished(view: WebView?, url: String?) {
            CookieManager.getInstance().flush()
        }
    }

    private fun observeService() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                MonitorService.state.collect { state -> render(state) }
            }
        }
    }

    private fun render(state: MonitorService.State) {
        binding.statusText.text = if (state.detail.isNotEmpty()) {
            state.detail
        } else {
            getString(R.string.state_connecting)
        }

        val color = when (state.connection) {
            MonitorService.Connection.WATCHING -> Color.parseColor("#2E7D32")
            MonitorService.Connection.CONNECTING -> Color.parseColor("#F9A825")
            MonitorService.Connection.OFFLINE -> Color.parseColor("#F9A825")
            else -> Color.parseColor("#C62828")
        }
        (binding.statusDot.background as? GradientDrawable)?.setColor(color)

        if (state.connection == MonitorService.Connection.UNPAIRED) {
            binding.monitoringSwitch.isChecked = false
        }
    }
}
