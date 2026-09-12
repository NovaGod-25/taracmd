package com.taracmd.app

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.os.Build
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewFeature
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

/**
 * The WebView shell. The page itself is the whole app; this class exists to do
 * the five things a page cannot: serve itself over a real origin, hand the
 * hardware back button to the page, open outbound links in a real browser, put
 * one saved PDF on disk, and say when the app has been left.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var loader: WebViewAssetLoader
    private var downloadWatcher: BroadcastReceiver? = null
    private lateinit var pickShelf: ActivityResultLauncher<Uri?>
    private lateinit var pickDocs: ActivityResultLauncher<Array<String>>

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

        /** Where the shelf folder is remembered. The folder itself is not ours. */
        private const val PREFS = "taracmd"
        private const val SHELF_URI = "shelfUri"

        /**
         * The page's progress, written into the shelf folder so an uninstall
         * cannot take it. Kept off the shelf's own list: it is the app's file,
         * not one of the owner's documents.
         */
        private const val BACKUP_NAME = "TaraCmd progress.json"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        /* Both of these must be registered before the activity is STARTED,
           which is why they sit at the top of onCreate rather than next to the
           bridge methods that use them. */
        pickShelf = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri != null) {
                runCatching {
                    contentResolver.takePersistableUriPermission(
                        uri,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION or
                            Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                    )
                    prefs().edit().putString(SHELF_URI, uri.toString()).apply()
                }
            }
            // "picked" tells the page to look for a backup in the folder --
            // after a reinstall, this is the moment the old progress is found
            notifyShelf("picked")
        }
        pickDocs = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
            uris.forEach { copyToShelf(it) }
            notifyShelf()
        }

        loader = WebViewAssetLoader.Builder()
            .setDomain(APP_HOST)
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web = WebView(this)
        setContentView(web)

        /*
         * Keep the page out from under the status and navigation bars.
         *
         * targetSdk 35 means Android 15 draws this activity edge to edge
         * whether it asks to or not, so the WebView starts at pixel zero and
         * the page's own top bar ends up underneath the clock and the battery.
         * The page cannot fix that alone: env(safe-area-inset-*) reads zero
         * here, because as far as the WebView is concerned it has the whole
         * window.
         *
         * Padding the WebView by the system-bar insets is what actually
         * moves it, and it handles the gesture bar at the bottom in the same
         * pass. The window background is @color/paper and follows the theme,
         * so the strip behind the status bar matches the page rather than
         * flashing white.
         */
        /*
         * The listener on its own was not enough, and the page still came up
         * under the clock: AppCompat's decor consumes the top inset before it
         * reaches a child in some configurations, so the WebView is handed a
         * zero. From Android 15 the window is edge to edge whatever the app
         * asks for, so a zero top inset there is always wrong -- read the
         * window's own insets instead. Below 15 a zero is taken at its word,
         * because there the decor really may have fitted the content already
         * and padding again would leave a gap under the status bar.
         */
        fun padToInsets(dispatched: WindowInsetsCompat?) {
            val want = WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
            var bars = dispatched?.getInsets(want)
            if ((bars == null || bars.top == 0) && Build.VERSION.SDK_INT >= 35) {
                bars = ViewCompat.getRootWindowInsets(web)?.getInsets(want)
            }
            bars?.let { web.setPadding(it.left, it.top, it.right, it.bottom) }
        }
        ViewCompat.setOnApplyWindowInsetsListener(web) { _, insets ->
            padToInsets(insets)
            insets
        }
        // and once after the first layout, for the case where no dispatch arrives
        web.post { padToInsets(null) }

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

    /**
     * Every way of leaving the app arrives here — Home, Recents, a call, the
     * screen locking, another app taking focus. The page decides what that
     * means; this only has to report it, and report it for all of them.
     */
    override fun onPause() {
        super.onPause()
        web.evaluateJavascript("window.taracmdInterrupted && window.taracmdInterrupted()", null)
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

    /* ---- the shelf -------------------------------------------------------
     *
     * Documents the owner puts here have to outlive the app, and that single
     * requirement rules out everything the app owns: filesDir and
     * getExternalFilesDir() are both wiped by an uninstall, and so is anything
     * this app writes through MediaStore once its ownership is gone.
     *
     * So the app does not choose where they go. The owner picks a folder —
     * Documents, or wherever — and Android hands over a persistable grant to
     * it. The files are then ordinary files in ordinary storage: visible in
     * the phone's own Files app, editable by anything else, and untouched by
     * uninstalling TaraCmd.
     *
     * The grant does not survive an uninstall, which is Android's design and
     * not something to work around: MANAGE_EXTERNAL_STORAGE would, and it is
     * a Play-restricted permission that would be wildly disproportionate for
     * a shelf. Pointing at the same folder again after a reinstall costs one
     * tap and brings the whole shelf back. The page says so.
     */
    private fun prefs(): SharedPreferences =
        getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** The shelf, or null if none is picked or the grant has lapsed. */
    private fun shelf(): DocumentFile? {
        val raw = prefs().getString(SHELF_URI, null) ?: return null
        val uri = runCatching { Uri.parse(raw) }.getOrNull() ?: return null
        // A remembered string is not a permission. After an uninstall, or if
        // the user revokes it in Settings, the row is gone and reading through
        // it would throw — so ask, rather than assume.
        val held = contentResolver.persistedUriPermissions.any {
            it.uri == uri && it.isReadPermission && it.isWritePermission
        }
        if (!held) return null
        return runCatching { DocumentFile.fromTreeUri(this, uri) }
            .getOrNull()?.takeIf { it.isDirectory }
    }

    private fun notifyShelf(why: String = "") {
        runOnUiThread {
            web.evaluateJavascript("window.taracmdDocs && window.taracmdDocs('$why')", null)
        }
    }

    /**
     * Where the folder picker opens: the folder already in use if there is
     * one, otherwise the phone's own Documents -- which is where the shelf
     * belongs, and where a reinstalled app finds the one it had before.
     */
    private fun pickerStart(): Uri? = runCatching {
        prefs().getString(SHELF_URI, null)?.let { raw ->
            val tree = Uri.parse(raw)
            DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        } ?: DocumentsContract.buildDocumentUri(
            "com.android.externalstorage.documents", "primary:Documents"
        )
    }.getOrNull()

    private fun displayName(uri: Uri): String? =
        runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
        }.getOrNull()

    /** Copy one picked document onto the shelf, without overwriting a namesake. */
    private fun copyToShelf(src: Uri) {
        val dir = shelf() ?: return
        val name = displayName(src) ?: "document"
        val mime = contentResolver.getType(src) ?: "application/octet-stream"
        runCatching {
            var target = name
            var n = 2
            while (dir.findFile(target) != null) {
                val dot = name.lastIndexOf('.')
                target = if (dot > 0) name.substring(0, dot) + " (" + n + ")" + name.substring(dot)
                         else name + " (" + n + ")"
                n++
            }
            val out = dir.createFile(mime, target) ?: return
            contentResolver.openInputStream(src)?.use { input ->
                contentResolver.openOutputStream(out.uri)?.use { output -> input.copyTo(output) }
            }
        }
    }

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

        /**
         * Hold the screen awake for a focus run, and let it sleep afterwards.
         *
         * This is the whole of the native side of Focus now. An earlier
         * version called startLockTask() to pin the screen, and that was the
         * wrong idea: Android always leaves a way out of ordinary pinning, and
         * a study tool that fights the device is solving the wrong problem
         * anyway. Keeping the screen on is help rather than control — the
         * phone going dark mid-run and taking the run with it would be the
         * app's fault, not the user's.
         */
        @JavascriptInterface
        fun focusAwake(on: Boolean) {
            runOnUiThread {
                if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }

        /**
         * What is actually installed, so the app can say so.
         *
         * versionName is decided by Gradle at APK build time and follows the
         * CI run number, so the page cannot know it — build.py runs long
         * before the APK exists. Hence a bridge function rather than a token.
         */
        @JavascriptInterface
        fun appVersion(): String =
            runCatching {
                packageManager.getPackageInfo(packageName, 0).versionName ?: ""
            }.getOrDefault("")

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

        /** The shelf folder's name, or null while none is picked. */
        @JavascriptInterface
        fun docsFolder(): String? = shelf()?.name

        /** Choose (or change) the folder the shelf lives in. */
        @JavascriptInterface
        fun docsPick() {
            runOnUiThread { runCatching { pickShelf.launch(pickerStart()) } }
        }

        /** Add documents to it. Any type — this is the owner's own shelf. */
        @JavascriptInterface
        fun docsAdd() {
            runOnUiThread { runCatching { pickDocs.launch(arrayOf("*/*")) } }
        }

        /** What is on the shelf, newest first. */
        @JavascriptInterface
        fun docsList(): String {
            val dir = shelf() ?: return "[]"
            val out = JSONArray()
            runCatching {
                dir.listFiles()
                    .filter { it.isFile && it.name != BACKUP_NAME }
                    .sortedByDescending { it.lastModified() }
                    .forEach { f ->
                        out.put(JSONObject().apply {
                            put("id", f.uri.toString())
                            put("name", f.name ?: "document")
                            put("size", f.length())
                            put("mime", f.type ?: "")
                            put("on", f.lastModified())
                        })
                    }
            }
            return out.toString()
        }

        /** Hand one to whatever the phone uses to read it. */
        @JavascriptInterface
        fun docsOpen(id: String) {
            val uri = runCatching { Uri.parse(id) }.getOrNull() ?: return
            val mime = contentResolver.getType(uri) ?: "*/*"
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, mime)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            // A phone with nothing that opens this type is a normal phone, not
            // a crash.
            runCatching { startActivity(intent) }
        }

        /**
         * Delete one — the file, not a listing of it. The shelf IS the folder,
         * so there is no copy to remove instead, and the page asks first.
         */
        @JavascriptInterface
        fun docsRemove(id: String): Boolean {
            val uri = runCatching { Uri.parse(id) }.getOrNull() ?: return false
            return runCatching { DocumentsContract.deleteDocument(contentResolver, uri) }
                .getOrDefault(false)
        }

        /**
         * Write the page's progress into the shelf folder, replacing the last
         * copy. "wt" truncates: a plain "w" leaves the tail of a longer old
         * file behind on some Android versions, and that is a corrupt backup.
         */
        @JavascriptInterface
        fun docsBackupWrite(json: String): Boolean {
            val dir = shelf() ?: return false
            return runCatching {
                val f = dir.findFile(BACKUP_NAME)
                    ?: dir.createFile("application/octet-stream", BACKUP_NAME)
                    ?: return false
                contentResolver.openOutputStream(f.uri, "wt")?.use {
                    it.write(json.toByteArray(Charsets.UTF_8))
                } ?: return false
                true
            }.getOrDefault(false)
        }

        /** The backup in the shelf folder, or null if there is none. */
        @JavascriptInterface
        fun docsBackupRead(): String? {
            val f = shelf()?.findFile(BACKUP_NAME) ?: return null
            return runCatching {
                contentResolver.openInputStream(f.uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
            }.getOrNull()
        }
    }
}
