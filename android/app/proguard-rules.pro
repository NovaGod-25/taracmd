# The JS bridge is reached by name from the page, so its methods cannot be
# renamed or stripped however unused they look from Kotlin.
-keepclassmembers class com.taracmd.app.MainActivity$Host {
    @android.webkit.JavascriptInterface <methods>;
}
