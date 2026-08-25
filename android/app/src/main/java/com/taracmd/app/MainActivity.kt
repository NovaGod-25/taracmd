package com.taracmd.app

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewFeature
import java.io.File

/**
 * The WebView shell. The page itself is the whole app; this class exists to do
 * the four things a page cannot: serve itself over a real origin, hand the
 * hardware back button to the page, open outbound links in a real browser, and
 * put one saved PDF on disk.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var loader: WebViewAssetLoader
    private var downloadWatcher: BroadcastReceiver? = null

    companion object {
        /**
         * Served over https, not file:///android_asset/.
         *
         * A file:// page gets an opaque origin, which makes localStorage
         * unreliable across WebView versions — and every revision tick the
         * user has ever made lives in localStorage. This host is the one
         * Google reserves for exactly this; it never resolves on the network.
         */
        private const val APP_HOST = "appassets.androidplatform.net"
        private const val APP_URL = "https://$APP_HOST/assets/index.html"

        /** Where a tapped Save lands, and the path prefix the page links to. */
        private const val SAVED_DIR = "saved"
        private const val SAVED_SCHEME = "saved"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        loader = WebViewAssetLoader.Builder()
            .setDomain(APP_HOST)
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this)
        setContentView(web)

        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true          // localStorage: the revision ticks
            allowFileAccess = false
            allowContentAccess = false
            mediaPlaybackRequiresUserGesture = true
        }

        // The page paints its own dark theme off prefers-color-scheme. Letting
        // WebView also invert it would double-darken. Replaces setForceDark,
        // deprecated since API 33.
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(web.settings, false)
        }

        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView,
                request: WebResourceRequest
            ): WebResourceResponse? = loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean = handleOutbound(request.url)
        }

        web.addJavascriptInterface(Host(), "AndroidHost")

        // Page owns the back button: sheet, then subject, then the Subjects
        // tab, and only then the OS.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("window.taracmdBack && window.taracmdBack()") { result ->
                    if (result != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })

        // Restore scroll position and history across a rotation or a
        // process death, rather than dumping the user back on the Subjects tab.
        if (savedInstanceState != null) {
            if (web.restoreState(savedInstanceState) == null) web.loadUrl(APP_URL)
        } else {
            web.loadUrl(APP_URL)
        }

        watchDownloads()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onDestroy() {
        downloadWatcher?.let { runCatching { unregisterReceiver(it) } }
        super.onDestroy()
    }

    /**
     * Anything that is not the app itself goes to a real browser or a real PDF
     * viewer. A device with neither must not take the app down with it, hence
     * the guard — an unhandled ActivityNotFoundException here is a crash.
     */
    private fun handleOutbound(url: Uri): Boolean {
        if (url.host == APP_HOST && url.scheme == "https") return false

        val intent = Intent(Intent.ACTION_VIEW).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        if (url.scheme == SAVED_SCHEME) {
            val f = File(savedDir(), url.schemeSpecificPart.trimStart('/'))
            if (!f.isFile) return true
            // A file:// Uri handed to another app throws FileUriExposedException
            // on API 24+, and minSdk here is 24. Has to be a content:// grant.
            val shared = FileProvider.getUriForFile(
                this, "$packageName.files", f
            )
            intent.setDataAndType(shared, "application/pdf")
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } else {
            intent.data = url
        }

        return try {
            startActivity(intent)
            true
        } catch (e: ActivityNotFoundException) {
            true    // swallowed on purpose: nothing to open it with, and no crash
        }
    }

    private fun savedDir(): File =
        File(getExternalFilesDir(null) ?: filesDir, SAVED_DIR).apply { mkdirs() }

    private fun fileNameFor(url: String): String =
        Uri.parse(url).lastPathSegment?.takeIf { it.endsWith(".pdf", true) }
            ?: (url.hashCode().toString().replace("-", "0") + ".pdf")

    /** Flip the row to "saved" once a download actually lands. */
    private fun watchDownloads() {
        val r = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                web.evaluateJavascript("window.taracmdSaved && window.taracmdSaved()", null)
            }
        }
        downloadWatcher = r
        val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        ContextCompat.registerReceiver(this, r, filter, ContextCompat.RECEIVER_EXPORTED)
    }

    /**
     * The bridge the page looks for. Absent on the web, where the browser's own
     * download handles it — the page checks for it before offering Save.
     *
     * One tap, one URL. There is no crawler here and there should not be: the
     * booklets belong to the institutes that published them.
     */
    private inner class Host {

        /** Non-null once this exact PDF is on disk, so the row can say "saved". */
        @JavascriptInterface
        fun savedPath(url: String): String? {
            val f = File(savedDir(), fileNameFor(url))
            return if (f.isFile) "$SAVED_SCHEME:${f.name}" else null
        }

        @JavascriptInterface
        fun saveCopy(url: String) {
            val name = fileNameFor(url)
            val req = DownloadManager.Request(Uri.parse(url))
                .setTitle(name)
                .setDescription("TaraCmd — toppers' copy")
                .setNotificationVisibility(
                    DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
                )
                .setAllowedOverRoaming(false)
                .setDestinationUri(Uri.fromFile(File(savedDir(), name)))

            runCatching {
                (getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            }
        }
    }
}
